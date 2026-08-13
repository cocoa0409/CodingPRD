"""Subprocessor disclosures, vendor offboarding, attestations, and the
append-only reassessment schedule (PRD §3.9, §2.4)."""
import pytest

from test_helpers import (
    ANALYST,
    APPROVER,
    ApiErrorId,
    assert_instant_equal,
    assert_schedule_event,
    create_acceptance_payload,
    create_alert,
    create_and_submit_response,
    create_exception_payload,
    create_published_template,
    get_success_data,
    issue_cycle,
    list_schedule_events,
    make_vendor_contact_headers,
    open_cycle,
    register_vendor,
    review_artifact_clean,
    score_cycle,
    setup_active_policy,
    setup_approved_vendor,
    setup_disclosure_under_review,
    setup_offboarding_vendor,
    submit_attestation_payload,
    upload_evidence,
    validate_error,
    validate_success,
    yes_answers,
)


def _suspended_vendor_with_disclosure(api):
    """Vendor driven ONBOARDING -> (cycle REJECTED) -> SUSPENDED while a
    subprocessor disclosure sits UNDER_REVIEW."""
    setup_active_policy()
    template = create_published_template()
    vendor, contact = register_vendor()
    ch = make_vendor_contact_headers(contact["id"])
    disclosure = setup_disclosure_under_review(vendor["id"], ch)
    cycle = open_cycle(vendor["id"], template["id"])
    cycle = issue_cycle(vendor["id"], cycle["id"])
    create_and_submit_response(vendor["id"], cycle["id"], ch, yes_answers(template))
    score_cycle(vendor["id"], cycle["id"])
    artifact = upload_evidence(vendor["id"], cycle["id"], ch, kind="OTHER", issued_by="Self")
    review_artifact_clean(vendor["id"], cycle["id"], artifact["id"])
    exception = get_success_data(
        api.create_exception(
            vendor["id"], cycle["id"],
            create_exception_payload(severity="CRITICAL", description="fatal gap",
                                     evidence_artifact_id=artifact["id"]),
            ANALYST,
        )
    )
    get_success_data(api.complete_evidence_review(vendor["id"], cycle["id"], ANALYST))
    acceptance = get_success_data(
        api.create_risk_acceptance(
            vendor["id"], cycle["id"], create_acceptance_payload([exception["id"]]), ANALYST
        )
    )
    get_success_data(api.reject_risk_acceptance(vendor["id"], cycle["id"], acceptance["id"], APPROVER))
    get_success_data(
        api.mark_false_positive(
            vendor["id"], cycle["id"], exception["id"],
            {"closure_reason": "re-classified as not applicable"}, ANALYST,
        )
    )
    get_success_data(api.resolve_remediation(vendor["id"], cycle["id"], ANALYST))
    get_success_data(api.reject_cycle(vendor["id"], cycle["id"], APPROVER))
    vendor = get_success_data(api.get_vendor(vendor["id"], ANALYST))
    return vendor, disclosure


class TestSubprocessorPostureGate:
    def test_approval_blocked_when_vendor_suspended(self, api):
        """PRD §3.9: "approval requires the vendor's posture to be `APPROVED`,
        `CONDITIONAL`, or `ASSESSING` and moves the disclosure to `APPROVED`,
        recording `decided_by`; a vendor in `SUSPENDED`, `OFFBOARDING`, or another
        non-permitting posture sees the approval rejected with
        `ERR_VENDOR_POSTURE_BLOCKS`."
        PRD §3.7: "Rejecting the cycle instead moves it to `REJECTED`, drops the
        vendor's posture to `SUSPENDED`, clears `active_cycle_id`, and increments
        the vendor's `version`."

        Design: Difficulty/cross_entity_state_dependency/subprocessor_approval_gated_by_vendor_posture
        """
        vendor, disclosure = _suspended_vendor_with_disclosure(api)
        assert vendor["posture"] == "SUSPENDED"
        res = api.approve_subprocessor(vendor["id"], disclosure["id"], APPROVER)
        validate_error(res, ApiErrorId.ERR_VENDOR_POSTURE_BLOCKS)
        disclosures = get_success_data(api.list_subprocessors(vendor["id"], ANALYST))
        current = next(d for d in disclosures if d["id"] == disclosure["id"])
        assert current["status"] == "UNDER_REVIEW"

    def test_approval_succeeds_while_vendor_assessing(self, api):
        """PRD §3.9: "approval requires the vendor's posture to be `APPROVED`,
        `CONDITIONAL`, or `ASSESSING` and moves the disclosure to `APPROVED`,
        recording `decided_by`".

        Design: Difficulty/cross_entity_state_dependency/subprocessor_approval_gated_by_vendor_posture
        """
        setup_active_policy()
        template = create_published_template()
        vendor, contact = register_vendor()
        ch = make_vendor_contact_headers(contact["id"])
        disclosure = setup_disclosure_under_review(vendor["id"], ch)
        cycle = open_cycle(vendor["id"], template["id"])
        issue_cycle(vendor["id"], cycle["id"])
        vendor = get_success_data(api.get_vendor(vendor["id"], ANALYST))
        assert vendor["posture"] == "ASSESSING"
        approved = validate_success(
            api.approve_subprocessor(vendor["id"], disclosure["id"], APPROVER), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by"] == APPROVER["X-User-ID"]


class TestOffboardingAttestations:
    def test_reject_creates_fresh_requested_and_extends_deadline(self, api):
        """PRD §3.9: "Rejection moves the attestation `SUBMITTED → REJECTED` and
        triggers the compensation loop: a fresh `OffboardingAttestation` in
        `REQUESTED` is created for the vendor, the `offboarding_deadline` extends
        by 30 days, and a `ReassessmentSchedule` event of kind `OFFBOARDING_SLIP`
        records the old deadline as `previous_due` and the extended deadline as
        `new_due` with its `reason_ref` pointing at the rejected attestation".
        PRD §3.9: "Offboarding moves the vendor's posture to `OFFBOARDING`, creates
        an **OffboardingAttestation** in `REQUESTED`, and sets the vendor's
        `offboarding_deadline` to the current clock plus 90 days, incrementing the
        vendor's `version`."

        Deadline 2026-08-01 + 90 days = 2026-10-30; extended -> 2026-11-29.

        Design: Corner/state_machines/offboarding_attestation_reject_creates_fresh_requested
        """
        ctx = setup_offboarding_vendor()
        vendor_id = ctx["vendor"]["id"]
        ch = make_vendor_contact_headers(ctx["contact"]["id"])
        vendor = get_success_data(api.get_vendor(vendor_id, ANALYST))
        assert_instant_equal(vendor["offboarding_deadline"], "2026-10-30T00:00:00Z")
        submitted = validate_success(
            api.submit_attestation(vendor_id, ctx["attestation"]["id"], submit_attestation_payload(), ch),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        rejected = validate_success(
            api.reject_attestation(vendor_id, ctx["attestation"]["id"], ANALYST), 200
        )
        assert rejected["status"] == "REJECTED"
        attestations = get_success_data(api.list_attestations(vendor_id, ANALYST))
        fresh = [a for a in attestations if a["status"] == "REQUESTED"]
        assert len(fresh) == 1, "Compensation loop must create exactly one fresh REQUESTED attestation"
        assert fresh[0]["id"] != ctx["attestation"]["id"]
        vendor = get_success_data(api.get_vendor(vendor_id, ANALYST))
        assert_instant_equal(vendor["offboarding_deadline"], "2026-11-29T00:00:00Z")

    def test_submit_with_both_flags_false_rejected(self, api):
        """PRD §3.9: "At least one of the two assertions must be true; a submission
        asserting neither is rejected with `ERR_ATTESTATION_INCOMPLETE` (HTTP 422)".

        Design: Corner/validations/attestation_submit_both_flags_false_rejected
        """
        ctx = setup_offboarding_vendor()
        ch = make_vendor_contact_headers(ctx["contact"]["id"])
        res = api.submit_attestation(
            ctx["vendor"]["id"], ctx["attestation"]["id"],
            {"data_returned": False, "data_destroyed": False, "attested_by": "Vendor CTO"},
            ch,
        )
        validate_error(res, ApiErrorId.ERR_ATTESTATION_INCOMPLETE)

    def test_verify_blocked_by_open_alert(self, api):
        """PRD §3.9: "Verification is blocked while any assessment cycle for the
        vendor sits in a non-terminal state or any monitoring alert remains `OPEN`
        or `ACKNOWLEDGED` — rejected with `ERR_OFFBOARDING_BLOCKED` (HTTP 422)".

        Design: Corner/validations/attestation_verify_blocked_by_open_alert
        """
        setup_active_policy()
        vendor, contact = register_vendor()
        create_alert(vendor["id"], signal="SCAN_FINDING", severity="LOW")  # stays OPEN
        vendor = get_success_data(api.offboard_vendor(vendor["id"], ANALYST))
        attestations = get_success_data(api.list_attestations(vendor["id"], ANALYST))
        attestation = attestations[0]
        ch = make_vendor_contact_headers(contact["id"])
        validate_success(
            api.submit_attestation(vendor["id"], attestation["id"], submit_attestation_payload(), ch), 200
        )
        res = api.verify_attestation(vendor["id"], attestation["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_OFFBOARDING_BLOCKED)


class TestReassessmentScheduleLog:
    def test_schedule_events_are_append_only_without_version(self, api):
        """PRD §2.4: "Two resources are exceptions to this rule: a
        `ReassessmentSchedule` event and a `VendorContact` carry only `id` and
        `created_at`. Both `updated_at` and `version` are absent on those two
        resources — they are append-only records and are never mutated after
        creation."
        PRD §3.5: "A clean approval moves the vendor's posture to `APPROVED`, sets
        `next_reassessment_due` to the current clock plus the active policy's
        cadence months for the vendor's `current_tier`, appends a
        `ReassessmentSchedule` event of kind `TIER_CADENCE`, clears
        `active_cycle_id`, and increments the vendor's `version`."

        Design: Corner/entities/reassessment_schedule_immutable_event_log
        """
        ctx = setup_approved_vendor()
        events = list_schedule_events(ctx["vendor"]["id"])
        assert len(events) >= 1, "Approval must journal at least one schedule event"
        assert any(e["kind"] == "TIER_CADENCE" for e in events)
        for event in events:
            assert_schedule_event(event)
