"""Consult note return and loop-closure verification: gating, SoD, OCC, cycles."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    consult_note_payload, loop_closure_payload,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_completed_referral,
    create_pending_verification_referral, submit_consult_note, verify_loop,
    set_clock, get_referral, get_appointment,
    make_auditor_headers, make_coordinator_headers,
    assert_consult_note, assert_loop_closure,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _bootstrap():
    set_clock("2026-08-01T00:00:00Z")
    plan = create_plan()
    specialist = create_specialist()
    create_participation(specialist["id"], plan["id"])
    provider = create_provider()
    patient = create_patient(plan["id"])
    return plan, specialist, provider, patient


class TestClosureRequiresConsultNote:
    def test_verify_rejected_while_visit_completed(self, api):
        """PRD §3.7: "requires the referral to actually sit in
        `PENDING_VERIFICATION`, else `ERR_INVALID_STATE`."
        PRD §3.7: "Submitting the note advances the referral from `VISIT_COMPLETED`
        to `PENDING_VERIFICATION` and increments the referral's `version`."
        PRD §2.7: "Sixth, the optimistic-concurrency check on
        `expected_referral_version` where the endpoint requires it (priority 6,
        `ERR_STALE_VERSION`) — this check runs after existence and before any state
        or business rule".

        Design: Difficulty/cross_entity_state_dependency/closure_requires_consult_note
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_completed_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z", coordinator_user_id="coord-1",
        )
        assert referral["status"] == "VISIT_COMPLETED"
        res = api.create_loop_closure(
            referral["id"],
            loop_closure_payload(referral["version"], "VERIFIED_CLOSED",
                                 verification_note="premature"),
            make_auditor_headers("audit-1"),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_consult_note_unlocks_verification(self, api):
        """PRD §3.7: "Submitting the note advances the referral from
        `VISIT_COMPLETED` to `PENDING_VERIFICATION` and increments the referral's
        `version`."
        PRD §3.7: "On `VERIFIED_CLOSED` the referral reaches its terminal `CLOSED`
        state; on `REOPENED` it drops back to `VISIT_COMPLETED`, awaiting another
        note and another verification pass. Either outcome increments the referral's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/closure_requires_consult_note
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_completed_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z", coordinator_user_id="coord-1",
        )
        note = submit_consult_note(appointment["id"], specialist["id"],
                                   findings_summary="Stable angina")
        pending = get_referral(referral["id"])
        assert pending["status"] == "PENDING_VERIFICATION"

        closure = verify_loop(pending, outcome="VERIFIED_CLOSED",
                              verification_note="Loop verified",
                              auditor_user_id="audit-1")
        assert_loop_closure(closure)
        assert closure["outcome"] == "VERIFIED_CLOSED"
        assert get_referral(referral["id"])["status"] == "CLOSED"


class TestReopenCycle:
    def test_closure_reopen_cycle_with_amended_note(self, api):
        """PRD §3.7: "on `REOPENED` it drops back to `VISIT_COMPLETED`, awaiting
        another note and another verification pass."
        PRD §3.7: "The note's `note_sequence` is assigned as 1 plus the count of
        prior consult notes on the same referral, so the first note on a referral is
        sequence 1".

        Design: Corner/state_machines/closure_reopen_cycle_with_amended_note
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment, note1 = create_pending_verification_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z", coordinator_user_id="coord-1",
            note_summary="v1",
        )
        assert note1["note_sequence"] == 1

        reopened = verify_loop(referral, outcome="REOPENED",
                               verification_note="Note incomplete",
                               auditor_user_id="audit-1")
        assert reopened["outcome"] == "REOPENED"
        assert get_referral(referral["id"])["status"] == "VISIT_COMPLETED"

        note2 = submit_consult_note(appointment["id"], specialist["id"],
                                    findings_summary="v2 amended",
                                    follow_up_recommended=True)
        assert note2["note_sequence"] == 2, "Amended note is sequence 2 on the same referral"
        assert get_referral(referral["id"])["status"] == "PENDING_VERIFICATION"

        current = get_referral(referral["id"])
        verify_loop(current, outcome="VERIFIED_CLOSED",
                    verification_note="Now complete", auditor_user_id="audit-1")
        assert get_referral(referral["id"])["status"] == "CLOSED"


class TestSegregationOfDuties:
    def test_scheduler_cannot_verify_own_closure(self, api):
        """PRD §3.7: "Verification belongs to an independent `ComplianceAuditor`, and
        it is the system's segregation-of-duties keystone: the auditor's `X-User-ID`
        must differ from the `scheduled_by_user_id` of the referral's latest
        `COMPLETED` appointment — the person who scheduled the visit may not verify
        its closure, and a match fails with `ERR_SOD_CONFLICT` (HTTP 403)."

        Design: Corner/rbac/sod_scheduler_cannot_verify_own_closure_rejected
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment, note = create_pending_verification_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z", coordinator_user_id="coord-1",
        )
        # The appointment was scheduled by coordinator user coord-1; the same opaque
        # id presenting the ComplianceAuditor role must be denied.
        res = api.create_loop_closure(
            referral["id"],
            loop_closure_payload(referral["version"], "VERIFIED_CLOSED",
                                 verification_note="self-verify attempt"),
            make_auditor_headers("coord-1"),
        )
        validate_error(res, ApiErrorId.ERR_SOD_CONFLICT, expected_status=403)

        closure = verify_loop(referral, outcome="VERIFIED_CLOSED",
                              verification_note="independent verify",
                              auditor_user_id="audit-1")
        assert closure["outcome"] == "VERIFIED_CLOSED"
        assert get_referral(referral["id"])["status"] == "CLOSED"


class TestOccOnLoopClosure:
    def test_stale_version_on_loop_closure_rejected(self, api):
        """PRD §2.5: "Verifying or reopening loop closure on a referral carries the
        same requirement: the request must carry `expected_referral_version` matching
        the referral's current `version`, because the clinical state under review may
        have changed since the auditor's read, and a mismatch is likewise rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "Submitting the note advances the referral from `VISIT_COMPLETED`
        to `PENDING_VERIFICATION` and increments the referral's `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_loop_closure_rejected
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_completed_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z", coordinator_user_id="coord-1",
        )
        stale_version = referral["version"]  # captured before the note
        submit_consult_note(appointment["id"], specialist["id"])  # version + 1

        res = api.create_loop_closure(
            referral["id"],
            loop_closure_payload(stale_version, "VERIFIED_CLOSED",
                                 verification_note="stale view"),
            make_auditor_headers("audit-1"),
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_referral(referral["id"])["status"] == "PENDING_VERIFICATION"


class TestConsultNoteImmutability:
    def test_consult_note_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "Three resource kinds are exceptions: `ConsultNote`,
        `LoopClosure`, and `LeakageRecord` carry only `id` and `created_at` — both
        `updated_at` and `version` are absent on those three, and nothing about them
        is ever mutated after creation."
        PRD §3.7: "The note's `note_sequence` is assigned as 1 plus the count of
        prior consult notes on the same referral, so the first note on a referral is
        sequence 1; ... and `returned_within_sla` is computed by comparing the note's
        `created_at` against the appointment's `completed_at` plus a 14-day return
        window — at or before that deadline counts as within SLA."

        Design: Corner/entities/consult_note_immutability
        """
        plan, specialist, provider, patient = _bootstrap()
        referral, appointment = create_completed_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z",
        )
        note = submit_consult_note(appointment["id"], specialist["id"])
        assert_consult_note(note)  # asserts absence of version/updated_at
        assert "version" not in note
        assert "updated_at" not in note
        assert note["note_sequence"] == 1
        assert note["returned_within_sla"] is True, (
            "Same-day return is within the 14-day window"
        )
