"""Cross-entity state dependencies: disclosure review needs an ACTIVE NDA;
employee activation needs a signed current-policy acknowledgment; evidence
release is blocked by an active preservation notice (PRD §3.5, §3.3, §3.8)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_nda_payload,
    create_registered_asset,
    create_employee_record,
    create_active_employee,
    create_submitted_disclosure,
    create_forensic_review_payload,
    create_evidence_item_payload,
    create_preservation_notice_payload,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_senior_counsel_headers,
    get_pending_ack_id,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


def _setup_submitted_disclosure_with_sent_nda(api):
    """REGISTERED asset; NDA in SENT (not yet executed); submitted disclosure."""
    cp = create_counterparty(legal_name="Kappa Print", counterparty_type="VENDOR")
    resp = api.create_nda(
        create_nda_payload(
            cp["id"], template_version="t9", governing_law="OR",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
            survival_months=6, classification_ceiling="CONFIDENTIAL",
        ), IP
    )
    nda = validate_success(resp, expected_status=201)
    validate_success(api.transition_nda(nda["id"], {"to_status": "SENT"}, IP))
    asset = create_registered_asset(
        title="Packaging dieline", description="box spec",
        classification="CONFIDENTIAL", owner_department="MKT",
        exposure_estimate_cents=40000,
    )
    emp = create_employee_record(
        full_name="Quinn Brand", email="quinn@x.com", department="MKT",
        role_title="Designer", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_submitted_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Packaging print", marking_protocol="STAMPED_CONFIDENTIAL",
        planned_disclosure_date="2026-07-01T00:00:00Z",
    )
    return cp, nda, asset, emp, disc


class TestDisclosureReviewRequiresActiveNda:
    def test_under_review_rejected_while_nda_only_sent(self, api):
        """PRD §3.5: "Counsel moves a submission into review — `SUBMITTED →
        UNDER_REVIEW` — only while the referenced NDA is `ACTIVE`, otherwise
        `ERR_NDA_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/disclosure_review_requires_active_nda
        """
        _cp, _nda, _asset, _emp, disc = _setup_submitted_disclosure_with_sent_nda(api)
        resp = api.transition_disclosure(disc["id"], {"to_status": "UNDER_REVIEW"}, IP)
        validate_error(resp, ApiErrorId.ERR_NDA_NOT_ACTIVE)

    def test_under_review_succeeds_after_nda_active_and_pin_frozen(self, api):
        """PRD §3.5: "Submission pins the world: `pinned_asset_version` captures
        the asset's current `version`, `pinned_nda_version` captures the NDA's
        current `version`, and `risk_score_provisional` is computed for the
        requester's own visibility."

        Design: Difficulty/cross_entity_state_dependency/disclosure_review_requires_active_nda
        """
        cp, nda, _asset, _emp, disc = _setup_submitted_disclosure_with_sent_nda(api)
        pinned_at_submit = validate_success(api.get_disclosure(disc["id"], IP))["pinned_nda_version"]
        validate_success(api.transition_nda(
            nda["id"], {"to_status": "EXECUTED"}, make_counterparty_rep_headers(cp["id"])
        ))
        validate_success(api.transition_nda(nda["id"], {"to_status": "ACTIVE"}, IP))
        data = validate_success(api.transition_disclosure(disc["id"], {"to_status": "UNDER_REVIEW"}, IP))
        assert data["status"] == "UNDER_REVIEW"
        assert data["pinned_nda_version"] == pinned_at_submit == 2, \
            "pin frozen at SUBMITTED (NDA version 2 after SENT); later transitions do not rewrite it"


class TestEmployeeActivationRequiresSignedCurrentAck:
    def test_activation_rejected_while_ack_pending(self, api):
        """PRD §3.3: "Activation of the employee — `PREBOARDING → ACTIVE` —
        requires a `SIGNED` acknowledgment on the current policy version to
        exist, otherwise `ERR_ACK_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/employee_activation_requires_signed_current_ack
        """
        emp = create_employee_record(
            full_name="Rita Newbie", email="rita@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.transition_employee(emp["id"], {"to_status": "ACTIVE"}, HR)
        validate_error(resp, ApiErrorId.ERR_ACK_REQUIRED)

    def test_activation_succeeds_after_signing(self, api):
        """PRD §3.3: "Signing belongs to the employee themself — `X-User-ID`
        must equal the acknowledgment's `employee_id`, otherwise
        `ERR_OWNERSHIP_REQUIRED` — and only an acknowledgment whose
        `policy_version` still matches the program's current version can be
        signed, otherwise `ERR_POLICY_VERSION_STALE`; signing stamps `signed_at`
        and moves the row to `SIGNED`."

        Design: Difficulty/cross_entity_state_dependency/employee_activation_requires_signed_current_ack
        """
        emp = create_employee_record(
            full_name="Rita Newbie", email="rita@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        ack_id = get_pending_ack_id(emp["id"])
        ack = validate_success(
            api.sign_acknowledgment(ack_id, make_employee_headers(emp["id"]))
        )
        assert ack["status"] == "SIGNED" and ack["policy_version"] == "v1"
        data = validate_success(api.transition_employee(emp["id"], {"to_status": "ACTIVE"}, HR))
        assert data["status"] == "ACTIVE"


def _setup_sealed_evidence_under_active_notice(api):
    """Forensic review (POLICY trigger) in IMAGING with one SEALED evidence
    item; ACTIVE preservation notice covering the review."""
    emp = create_active_employee(
        complete_training=False,
        full_name="Sam Watched", email="sam@x.com", department="ENG",
        role_title="SDE2", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    resp = api.create_forensic_review(
        create_forensic_review_payload(emp["id"], trigger_reason="POLICY"), IP
    )
    review = validate_success(resp, expected_status=201)
    validate_success(api.transition_forensic_review(review["id"], {"to_status": "IMAGING"}, SEC))
    resp = api.create_evidence_item(
        create_evidence_item_payload(review["id"], source="ACCESS_LOG",
                                     sha256="c" * 64, byte_size=2048), SEC
    )
    ev = validate_success(resp, expected_status=201)
    validate_success(api.transition_evidence_item(ev["id"], {"to_status": "SEALED"}, SEC))
    resp = api.create_preservation_notice(
        create_preservation_notice_payload(legal_matter_ref="M-2026-001",
                                           review_ids=[review["id"]]), IP
    )
    notice = validate_success(resp, expected_status=201)
    validate_success(api.transition_preservation_notice(notice["id"], {"to_status": "ISSUED"}, IP))
    validate_success(api.transition_preservation_notice(notice["id"], {"to_status": "ACTIVE"}, IP))
    return emp, review, ev, notice


class TestEvidenceReleaseBlockedByActivePreservation:
    def test_release_rejected_while_notice_active(self, api):
        """PRD §3.8: "Evidence release is narrower: an item whose `review_id` is
        listed in a notice in `ISSUED` or `ACTIVE` cannot be released, likewise
        `ERR_PRESERVATION_HOLD_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/evidence_release_blocked_by_active_preservation
        """
        _emp, _review, ev, _notice = _setup_sealed_evidence_under_active_notice(api)
        resp = api.transition_evidence_item(ev["id"], {"to_status": "RELEASED"}, IP)
        validate_error(resp, ApiErrorId.ERR_PRESERVATION_HOLD_ACTIVE)

    def test_release_succeeds_after_notice_released(self, api):
        """PRD §3.8: "Release of the notice itself — `ACTIVE → RELEASED` — is a
        `SeniorCounsel` step forbidden while any demand letter in `LITIGATION`
        references a review in the notice's `review_ids`, otherwise
        `ERR_INVALID_STATE`. `RELEASED` is terminal."
        PRD §3.8: "Release — `SEALED → RELEASED` — is counsel's step and
        carries the preservation blocks described above."

        Design: Difficulty/cross_entity_state_dependency/evidence_release_blocked_by_active_preservation
        """
        _emp, _review, ev, notice = _setup_sealed_evidence_under_active_notice(api)
        notice_now = validate_success(api.transition_preservation_notice(
            notice["id"], {"to_status": "RELEASED"}, make_senior_counsel_headers("senior_1")
        ))
        assert notice_now["status"] == "RELEASED"
        data = validate_success(api.transition_evidence_item(ev["id"], {"to_status": "RELEASED"}, IP))
        assert data["status"] == "RELEASED"
