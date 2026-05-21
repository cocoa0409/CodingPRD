"""Finalization, workweek lock, and audit invariants.

Covers PRD §3.6 (Finalization / Lock), §3.8 (Audit Trail), §2.7
(Recompute cascade), §2.10 (concurrency serialization on lock).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    api_client,
    approve_time_edit,
    assert_audit_action_present,
    clock_set,
    finalize_shift,
    get_shift,
    get_workweek,
    list_audit,
    make_payroll_admin_headers,
    make_supervisor_headers,
    PAYROLL_ADMIN_SECONDARY_ID,
    PAYROLL_ADMIN_SHARED_ID,
    setup_closed_shift,
    setup_finalized_shift,
    setup_finalized_week,
    setup_locked_workweek,
    setup_pending_time_edit,
    setup_revert_ready_finalized_shift,
    setup_week_with_shifts,
    submit_time_edit,
    SUPERVISOR_SHARED_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    validate_error,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# Finalize — PRD §3.6
# ===========================================================================
class TestFinalize:

    def test_finalize_closed_shift_transitions_to_finalized(self, api):
        """PRD §3.6: "Finalization is a payroll-administrator operation
        that takes a shift in state `CLOSED` and transitions it to
        `FINALIZED`."
        """
        closed = setup_closed_shift()
        resp = api.finalize_shift(
            closed["shift"]["id"], TEST_USERS["payroll_admin_headers"],
        )
        finalized = validate_success(resp, expected_status=200)
        assert finalized["state"] == "FINALIZED"

    def test_finalize_already_finalized_rejected(self, api):
        """PRD §3.6: "Finalize is permitted only when the shift is in
        `CLOSED`".

        Claim: finalize on a FINALIZED shift → ERR_SHIFT_INVALID_STATE.
        """
        state = setup_finalized_shift()
        resp = api.finalize_shift(
            state["shift"]["id"], TEST_USERS["payroll_admin_headers"],
        )
        validate_error(resp, "ERR_SHIFT_INVALID_STATE")

    def test_finalize_with_pending_time_edit_rejected(self, api):
        """PRD §3.6: "a `PENDING` edit on the shift causes finalize to
        reject with `ERR_TIME_EDIT_NOT_PENDING`."

        Per scaffold_difficulty_design.cross_entity_state_dependency.
        shift_finalize_blocked_by_pending_timeedit, the loop's
        observable surface is also valid as ERR_SHIFT_INVALID_STATE
        (Shift is now DISPUTED). PRD §2.9 places state-shift check
        (priority 6) above time-edit-state (priority 7), so
        ERR_SHIFT_INVALID_STATE is the higher-priority error. Either
        is faithful to PRD prose for this combination.
        """
        state = setup_pending_time_edit()
        resp = api.finalize_shift(
            state["shift"]["id"], TEST_USERS["payroll_admin_headers"],
        )
        body = resp.json()
        assert resp.status_code == 409
        assert body["data"]["error_id"] in (
            "ERR_SHIFT_INVALID_STATE",
            "ERR_TIME_EDIT_NOT_PENDING",
        ), (
            f"expected ERR_SHIFT_INVALID_STATE or "
            f"ERR_TIME_EDIT_NOT_PENDING, got {body['data']['error_id']!r}"
        )


# ===========================================================================
# Lock workweek — PRD §3.6
# ===========================================================================
class TestLock:

    def test_lock_posted_workweek_succeeds(self, api):
        """PRD §3.6: "A payroll administrator locks a workweek when its
        `payroll_status` is `POSTED` and no `PENDING` time edits exist
        on any constituent shift; the transition `POSTED → LOCKED`
        freezes the workweek".
        """
        state = setup_finalized_week(
            daily_hours=[8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        resp = api.lock_workweek(
            state["workweek"]["id"], TEST_USERS["payroll_admin_headers"],
        )
        locked = validate_success(resp, expected_status=200)
        assert locked["payroll_status"] == "LOCKED"

    def test_locked_workweek_blocks_approve(self, api):
        """PRD §3.6: "Once locked, further time-edit approvals on the
        workweek's shifts are rejected with `ERR_WORKWEEK_LOCKED`".

        Per scaffold_difficulty_design.cross_entity_state_dependency.
        timeedit_approve_blocked_by_locked_workweek.
        """
        # Setup: POSTED workweek; submit TimeEdit BEFORE locking (since
        # PRD §3.6 says lock requires no PENDING edits — but a TimeEdit
        # submitted on a FINALIZED shift before lock keeps the shift
        # FINALIZED until approve. Wait — PRD §3.5: "Submitting a time
        # edit against a FINALIZED shift does not change the shift's
        # state at submission time". So submit, then lock, then approve.
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
        proposed = add_minutes(state["shift"]["scheduled_end"], -10)
        edit = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            proposed,
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        # Lock the workweek now (PRD §3.6: lock requires no PENDING edits.
        # But for this race we deliberately have a pending edit; the
        # PRD also says §2.10 covers the concurrency outcome. We'll
        # exercise the simpler chain: lock requires no PENDING edits,
        # so reject the PENDING first, then lock, then probe approve).
        api.reject_time_edit(
            edit["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SHARED_ID),
        )
        lock_resp = api.lock_workweek(
            state["workweek"]["id"], TEST_USERS["payroll_admin_headers"],
        )
        validate_success(lock_resp, expected_status=200)
        # Now submit a fresh edit and attempt approve — approve must
        # reject under the LOCKED workweek.
        edit2 = submit_time_edit(
            state["shift"]["id"],
            state["out_punch"]["id"],
            add_minutes(state["shift"]["scheduled_end"], -5),
            reason_code="CLERICAL",
            requester_headers=make_supervisor_headers(SUPERVISOR_SHARED_ID),
        )
        # The submit may itself error under PRD §3.6 lockdown — but the
        # PRD's §3.5 narrative does not state the submit step is blocked
        # by lock. We probe the approve step which is the rule under
        # test.
        resp = api.approve_time_edit(
            edit2["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        validate_error(resp, "ERR_WORKWEEK_LOCKED")

    def test_locked_workweek_blocks_revert(self, api):
        """PRD §3.6: "Once locked, ... revert is likewise rejected"
        (with `ERR_WORKWEEK_LOCKED`).

        Claim: approve a TimeEdit on a FINALIZED shift, lock the
        workweek (which would unlock POSTED→OPEN due to approve? PRD
        §3.5 says approve on FINALIZED flips FINALIZED→CLOSED and
        POSTED→OPEN). Re-finalize, re-lock, then attempt revert →
        ERR_WORKWEEK_LOCKED.
        """
        state = setup_revert_ready_finalized_shift(
            overrun_minutes=65,
            base_hourly_rate_cents=2000,
        )
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
        # Approve flipped shift back to CLOSED and workweek to OPEN.
        # Re-finalize.
        finalize_shift(state["shift"]["id"])
        # Lock.
        ww = get_workweek(state["workweek"]["id"])
        api.lock_workweek(ww["id"], TEST_USERS["payroll_admin_headers"])
        # Revert the (APPROVED) TimeEdit.
        resp = api.revert_time_edit(
            edit["id"],
            make_payroll_admin_headers(PAYROLL_ADMIN_SECONDARY_ID),
        )
        validate_error(resp, "ERR_WORKWEEK_LOCKED")


# ===========================================================================
# Audit on finalize — PRD §3.6 / §3.8
# ===========================================================================
class TestAuditOnFinalize:

    def test_finalize_appends_audit_entry(self, api):
        """PRD §3.6: "On finalize ... an audit row is appended with
        `action` value `SHIFT_FINALIZED`".
        """
        closed = setup_closed_shift()
        finalize_shift(closed["shift"]["id"])
        entries = list_audit(
            subject_entity="Shift", subject_id=closed["shift"]["id"],
        )
        assert_audit_action_present(
            entries, "SHIFT_FINALIZED",
            subject_id=closed["shift"]["id"],
        )

    def test_lock_appends_workweek_locked_audit(self, api):
        """PRD §3.6: "the transition `POSTED → LOCKED` ... appends an
        audit row with `action` value `WORKWEEK_LOCKED`."
        """
        state = setup_locked_workweek(
            daily_hours=[8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        entries = list_audit(
            subject_entity="Workweek", subject_id=state["workweek"]["id"],
        )
        assert_audit_action_present(
            entries, "WORKWEEK_LOCKED",
            subject_id=state["workweek"]["id"],
        )
