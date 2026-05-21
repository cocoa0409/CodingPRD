"""TNC decision branch + sweep-driven default close.

Covers PRD §3.5 (TNC contest, no_contest, deadline), §2.11 (sweep),
PRD §3.7 (onboarding_status derivation across the cycle).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_audit_action_absent,
    assert_audit_action_present,
    assert_audit_order,
    deliver_result,
    get_employee,
    get_everify_case,
    list_audit_events,
    make_employee_headers,
    run_sweep,
    setup_employee_with_tnc_case,
    submit_tnc_decision,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# TNC CONTEST — PRD §3.5
# ===========================================================================
class TestTncContest:

    def test_contest_loops_tnc_back_to_pending(self, api):
        """PRD §3.5: "A `decision` of `CONTEST` records
        `tnc_employee_decision` as `CONTEST`, transitions the case
        from `TNC` back to `PENDING`, appends an `AuditEvent` with
        action `TNC_CONTESTED`, and moves `onboarding_status` back to
        `EVERIFY_PENDING` so the upstream agency can re-evaluate."

        Claim: contest cycles TNC -> PENDING and writes
        tnc_employee_decision=CONTEST.
        """
        emp, form, case = setup_employee_with_tnc_case(
            tnc_kind="SSA",
            tnc_opened_at="2026-06-15T09:00:00.000Z",
        )
        # Within the contest window.
        advance_clock_to("2026-06-16T10:00:00.000Z")
        resp = api.submit_tnc_decision(
            case["id"], {"decision": "CONTEST"},
            make_employee_headers(emp["id"]),
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["case_status"] == "PENDING"
        assert updated["tnc_employee_decision"] == "CONTEST"
        re_emp = get_employee(emp["id"])
        assert re_emp["onboarding_status"] == "EVERIFY_PENDING", (
            "PRD §3.7: non-closed PENDING case → EVERIFY_PENDING"
        )
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "TNC_CONTESTED")

    def test_contest_after_deadline_returns_err_tnc_deadline_passed(
            self, api):
        """PRD §3.5: "The case must be in state `TNC` and the current
        time must be on or before `tnc_contest_deadline`; a request
        after the deadline is rejected with `ERR_TNC_DEADLINE_PASSED`."."""
        emp, form, case = setup_employee_with_tnc_case(
            tnc_kind="SSA",
            tnc_opened_at="2026-06-15T09:00:00.000Z",
        )
        # tnc_contest_deadline = 2026-06-30T23:59:59.999Z. Advance past.
        advance_clock_to("2026-07-01T00:00:00.001Z")
        resp = api.submit_tnc_decision(
            case["id"], {"decision": "CONTEST"},
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, "ERR_TNC_DEADLINE_PASSED")


# ===========================================================================
# TNC NO_CONTEST — PRD §3.5
# ===========================================================================
class TestTncNoContest:

    def test_no_contest_closes_case_and_terminates_employee(self, api):
        """PRD §3.5: "A `decision` of `NO_CONTEST` records
        `tnc_employee_decision` as `NO_CONTEST`, sets
        `final_disposition` to `NOT_AUTHORIZED`, transitions the case
        to `CLOSED_NOT_AUTHORIZED`, appends an `AuditEvent` of action
        `CASE_CLOSED` with `disposition` `NOT_AUTHORIZED`, moves
        `onboarding_status` to `NOT_AUTHORIZED`, and cascades into the
        employee-termination subroutine (`is_terminated` becomes true
        and an additional `AuditEvent` with action `TERMINATE` is
        appended)."."""
        emp, form, case = setup_employee_with_tnc_case(
            tnc_kind="SSA",
            tnc_opened_at="2026-06-15T09:00:00.000Z",
        )
        advance_clock_to("2026-06-16T10:00:00.000Z")
        resp = api.submit_tnc_decision(
            case["id"], {"decision": "NO_CONTEST"},
            make_employee_headers(emp["id"]),
        )
        closed = validate_success(resp, expected_status=200)
        assert closed["case_status"] == "CLOSED_NOT_AUTHORIZED"
        assert closed["tnc_employee_decision"] == "NO_CONTEST"
        assert closed["final_disposition"] == "NOT_AUTHORIZED"
        re_emp = get_employee(emp["id"])
        assert re_emp["is_terminated"] is True
        assert re_emp["onboarding_status"] == "TERMINATED"
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "CASE_CLOSED")
        assert_audit_action_present(events, "TERMINATE")


# ===========================================================================
# Sweep default close — PRD §3.5, §2.11
# ===========================================================================
class TestSweepDefaultClose:

    def test_sweep_closes_tnc_case_after_deadline(self, api):
        """PRD §3.5: "If a case in state `TNC` is left untouched until
        after `tnc_contest_deadline`, the next sweep closes it
        automatically. The sweep transitions the case from `TNC` to
        `CLOSED_NOT_AUTHORIZED` (precondition: `case_status` is `TNC`
        and `tnc_employee_decision` is still null), sets
        `final_disposition` to `NOT_AUTHORIZED`, appends an `AuditEvent`
        with action `TNC_DEADLINE_LAPSED` followed by an `AuditEvent`
        with action `CASE_CLOSED` and `disposition` `NOT_AUTHORIZED`,
        moves `onboarding_status` to `NOT_AUTHORIZED`, and cascades
        into the employee-termination subroutine described above
        (`is_terminated` becomes true with its own `AuditEvent` of
        action `TERMINATE`)"."""
        emp, form, case = setup_employee_with_tnc_case(
            tnc_kind="SSA",
            tnc_opened_at="2026-06-15T09:00:00.000Z",
        )
        # Past tnc_contest_deadline (2026-06-30T23:59:59.999Z).
        advance_clock_to("2026-07-01T00:00:01.000Z")
        run_sweep()
        # Re-read case + employee.
        re_case = get_everify_case(case["id"])
        assert re_case["case_status"] == "CLOSED_NOT_AUTHORIZED"
        assert re_case["final_disposition"] == "NOT_AUTHORIZED"
        # PRD §3.5: tnc_employee_decision remains null in the sweep
        # path (no employee action was taken).
        assert re_case["tnc_employee_decision"] is None, (
            f"Sweep-default close must leave tnc_employee_decision=null, "
            f"got {re_case['tnc_employee_decision']!r}"
        )
        re_emp = get_employee(emp["id"])
        assert re_emp["is_terminated"] is True
        assert re_emp["onboarding_status"] == "TERMINATED"
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "TNC_DEADLINE_LAPSED")
        assert_audit_action_present(events, "CASE_CLOSED")
        assert_audit_action_present(events, "TERMINATE")
        # Ordering: TNC_DEADLINE_LAPSED <= CASE_CLOSED <= TERMINATE.
        assert_audit_order(events, "TNC_DEADLINE_LAPSED", "CASE_CLOSED")
        assert_audit_order(events, "CASE_CLOSED", "TERMINATE")
