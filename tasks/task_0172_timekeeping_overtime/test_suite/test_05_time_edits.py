"""Time edits — submit, approve, reject, revert, idempotency.

Covers PRD §3.5 (Time Edits and Disputes), §2.10 (idempotency),
§2.1 (segregation of duties on approval).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    add_minutes,
    approve_time_edit,
    assert_time_edit,
    clock_advance,
    clock_set,
    create_time_edit_payload,
    finalize_shift,
    get_shift,
    list_audit,
    make_employee_headers,
    make_payroll_admin_headers,
    make_supervisor_headers,
    PAYROLL_ADMIN_SHARED_ID,
    PAYROLL_ADMIN_SECONDARY_ID,
    setup_closed_shift,
    setup_finalized_shift,
    setup_pending_time_edit,
    setup_revert_ready_finalized_shift,
    submit_time_edit,
    SUPERVISOR_SHARED_ID,
    SUPERVISOR_SECONDARY_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# TimeEdit submission — PRD §3.5
# ===========================================================================
class TestSubmit:

    def test_submit_time_edit_transitions_closed_to_disputed(self, api):
        """PRD §3.5: "submitting one against a `CLOSED` shift likewise
        transitions it to `DISPUTED`, holding it back from being
        finalized."
        """
        state = setup_pending_time_edit()
        assert state["shift"]["state"] == "DISPUTED"
        assert state["time_edit"]["state"] == "PENDING"

    def test_submit_time_edit_proposed_outside_window_rejected(self, api):
        """PRD §3.5: "The `proposed_punched_at` must lie within the
        window from 4 hours before the shift's `scheduled_start` to 6
        hours after the shift's `scheduled_end`; anything outside is
        rejected with `ERR_TIME_EDIT_OUT_OF_RANGE`."

        Claim: proposed = scheduled_end + 6h + 1s → rejected.
        """
        closed = setup_closed_shift()
        proposed = add_hours(closed["shift"]["scheduled_end"], 6)
        # +1 second past the window endpoint.
        from test_helpers import add_seconds
        proposed_plus_1s = add_seconds(proposed, 1)
        resp = api.create_time_edit(
            create_time_edit_payload(
                shift_id=closed["shift"]["id"],
                target_punch_id=closed["out_punch"]["id"],
                proposed_punched_at=proposed_plus_1s,
            ),
            TEST_USERS["supervisor_headers"],
        )
        validate_error(resp, "ERR_TIME_EDIT_OUT_OF_RANGE")

    def test_submit_time_edit_proposed_before_4h_window_rejected(self, api):
        """PRD §3.5: window starts "4 hours before the shift's
        `scheduled_start`"; proposed < that is rejected with
        ERR_TIME_EDIT_OUT_OF_RANGE.
        """
        closed = setup_closed_shift()
        proposed = add_hours(closed["shift"]["scheduled_start"], -4)
        from test_helpers import add_seconds
        proposed_minus_1s = add_seconds(proposed, -1)
        resp = api.create_time_edit(
            create_time_edit_payload(
                shift_id=closed["shift"]["id"],
                target_punch_id=closed["out_punch"]["id"],
                proposed_punched_at=proposed_minus_1s,
            ),
            TEST_USERS["supervisor_headers"],
        )
        validate_error(resp, "ERR_TIME_EDIT_OUT_OF_RANGE")


# ===========================================================================
# Idempotency — PRD §2.10, §3.5
# ===========================================================================
class TestIdempotency:

    def test_idempotent_replay_returns_same_row(self, api):
        """PRD §3.5: "A second submission carrying the same key and a
        byte-identical input payload returns the originally created row
        — the operation is treated as a retry and produces the same 201
        with the same id."
        """
        closed = setup_closed_shift()
        proposed = add_minutes(closed["shift"]["scheduled_end"], -10)
        key = unique_idempotency_key("idemp")
        payload = create_time_edit_payload(
            shift_id=closed["shift"]["id"],
            target_punch_id=closed["out_punch"]["id"],
            proposed_punched_at=proposed,
            reason_code="CLERICAL",
            idempotency_key=key,
        )
        resp1 = api.create_time_edit(
            payload, TEST_USERS["supervisor_headers"],
        )
        first = validate_success(resp1, expected_status=201)
        # Re-issue with byte-identical payload.
        resp2 = api.create_time_edit(
            payload, TEST_USERS["supervisor_headers"],
        )
        second = validate_success(resp2, expected_status=201)
        assert first["id"] == second["id"], (
            "PRD §3.5: idempotent replay returns the original row"
        )

    def test_conflicting_payload_with_same_key_rejected(self, api):
        """PRD §3.5: "A second submission carrying the same key but any
        difference in `target_punch_id`, `proposed_punched_at`, or
        `reason_code` is rejected with `ERR_DUPLICATE_IDEMPOTENCY_KEY`
        because the key is being reused with a conflicting intent."
        """
        closed = setup_closed_shift()
        proposed = add_minutes(closed["shift"]["scheduled_end"], -10)
        key = unique_idempotency_key("idemp")
        first = api.create_time_edit(
            create_time_edit_payload(
                shift_id=closed["shift"]["id"],
                target_punch_id=closed["out_punch"]["id"],
                proposed_punched_at=proposed,
                reason_code="CLERICAL",
                idempotency_key=key,
            ),
            TEST_USERS["supervisor_headers"],
        )
        validate_success(first, expected_status=201)
        # Same key but different proposed_punched_at.
        resp = api.create_time_edit(
            create_time_edit_payload(
                shift_id=closed["shift"]["id"],
                target_punch_id=closed["out_punch"]["id"],
                proposed_punched_at=add_minutes(proposed, -5),
                reason_code="CLERICAL",
                idempotency_key=key,
            ),
            TEST_USERS["supervisor_headers"],
        )
        validate_error(resp, "ERR_DUPLICATE_IDEMPOTENCY_KEY")


# ===========================================================================
# Approve — PRD §3.5, §2.1 (segregation of duties)
# ===========================================================================
class TestApprove:

    def test_approve_transitions_pending_to_approved(self, api):
        """PRD §3.5: "Approving by posting to the time-edit approval
        action transitions the edit `PENDING → APPROVED`".
        """
        state = setup_pending_time_edit(
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        # Approver must differ from requester per segregation rule.
        approved = approve_time_edit(
            state["time_edit"]["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        assert approved["state"] == "APPROVED"
        assert approved["applied_at"] is not None
        assert approved["approved_by_user_id"] == PAYROLL_ADMIN_SHARED_ID

    def test_approve_same_user_as_requester_rejected(self, api):
        """PRD §3.5: "the approver's `X-User-ID` does not equal
        `requested_by_user_id` (segregation of duties — same person
        rejects with `ERR_SEGREGATION_OF_DUTIES`)".

        Claim: requester and approver share the same X-User-ID →
        ERR_SEGREGATION_OF_DUTIES.
        """
        # Use the same Supervisor for both submit and approve.
        common = make_supervisor_headers(SUPERVISOR_SHARED_ID)
        state = setup_pending_time_edit(requester_headers=common)
        resp = api.approve_time_edit(
            state["time_edit"]["id"], common,
        )
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES")

    def test_approve_fraud_correction_by_supervisor_rejected(self, api):
        """PRD §3.5: "if the `reason_code` is `FRAUD_CORRECTION` the
        approver's role is `PayrollAdmin` (a supervisor approving a
        fraud-correction edit is rejected with
        `ERR_FRAUD_REQUIRES_ADMIN`)".
        """
        state = setup_pending_time_edit(
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
            reason_code="FRAUD_CORRECTION",
        )
        resp = api.approve_time_edit(
            state["time_edit"]["id"],
            make_supervisor_headers(SUPERVISOR_SECONDARY_ID),
        )
        validate_error(resp, "ERR_FRAUD_REQUIRES_ADMIN")

    def test_approve_fraud_correction_by_payroll_admin_succeeds(self, api):
        """PRD §3.5: by exclusion, a PayrollAdmin approving a
        FRAUD_CORRECTION edit succeeds; the FRAUD-REQUIRES-ADMIN rule
        names PayrollAdmin as the only valid approver role.
        """
        state = setup_pending_time_edit(
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
            reason_code="FRAUD_CORRECTION",
        )
        approved = approve_time_edit(
            state["time_edit"]["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        assert approved["state"] == "APPROVED"

    def test_approve_already_approved_rejects_err_time_edit_not_pending(
        self, api,
    ):
        """PRD §3.5: "Approve, reject, and revert called against a
        time edit whose state is not the required pre-transition state
        are rejected with `ERR_TIME_EDIT_NOT_PENDING`".
        """
        state = setup_pending_time_edit(
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            state["time_edit"]["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        # Re-approve.
        resp = api.approve_time_edit(
            state["time_edit"]["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        validate_error(resp, "ERR_TIME_EDIT_NOT_PENDING")


# ===========================================================================
# Reject — PRD §3.5
# ===========================================================================
class TestReject:

    def test_reject_transitions_pending_to_rejected(self, api):
        """PRD §3.5: "Rejecting by posting to the time-edit reject
        action transitions the edit `PENDING → REJECTED`".
        """
        state = setup_pending_time_edit(
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        resp = api.reject_time_edit(
            state["time_edit"]["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SHARED_ID),
        )
        rejected = validate_success(resp, expected_status=200)
        assert rejected["state"] == "REJECTED"

    def test_reject_same_user_as_requester_rejected_segregation(self, api):
        """PRD §3.5: "the segregation-of-duties rule still applies on
        the reject path — the approver's `X-User-ID` must not equal
        `requested_by_user_id`."
        """
        common = make_supervisor_headers(SUPERVISOR_SHARED_ID)
        state = setup_pending_time_edit(requester_headers=common)
        resp = api.reject_time_edit(state["time_edit"]["id"], common)
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES")


# ===========================================================================
# Revert — PRD §3.5
# ===========================================================================
class TestRevert:

    def test_revert_transitions_approved_to_reverted(self, api):
        """PRD §3.5: "Reverting an already-approved time edit ...
        transitions the edit `APPROVED → REVERTED`."
        """
        state = setup_revert_ready_finalized_shift()
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        resp = api.revert_time_edit(
            edit["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        reverted = validate_success(resp, expected_status=200)
        assert reverted["state"] == "REVERTED"

    def test_revert_pending_time_edit_rejected(self, api):
        """PRD §3.5: "Approve, reject, and revert called against a
        time edit whose state is not the required pre-transition state
        are rejected with `ERR_TIME_EDIT_NOT_PENDING`".

        Claim: revert on PENDING → ERR_TIME_EDIT_NOT_PENDING.
        """
        state = setup_pending_time_edit()
        resp = api.revert_time_edit(
            state["time_edit"]["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SHARED_ID),
        )
        validate_error(resp, "ERR_TIME_EDIT_NOT_PENDING")


# ===========================================================================
# Audit chain on TimeEdit transitions — PRD §3.8
# ===========================================================================
class TestAuditOnTimeEdit:

    def test_approved_then_reverted_appears_in_audit(self, api):
        """PRD §3.5: "An audit row is appended with `action` value
        `TIME_EDIT_APPROVED`" and "An audit row is appended with
        `action` value `TIME_EDIT_REVERTED`".
        """
        state = setup_revert_ready_finalized_shift()
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        approve_time_edit(
            edit["id"],
            approver_headers=make_payroll_admin_headers(
                PAYROLL_ADMIN_SHARED_ID,
            ),
        )
        api.revert_time_edit(
            edit["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        entries = list_audit(
            subject_entity="TimeEdit", subject_id=edit["id"],
        )
        actions = [e["action"] for e in entries]
        assert "TIME_EDIT_APPROVED" in actions, (
            f"expected TIME_EDIT_APPROVED in audit; got {actions}"
        )
        assert "TIME_EDIT_REVERTED" in actions, (
            f"expected TIME_EDIT_REVERTED in audit; got {actions}"
        )
