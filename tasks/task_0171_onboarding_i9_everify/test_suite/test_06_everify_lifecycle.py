"""E-Verify case lifecycle: submission, idempotency, result branching,
close.

Covers PRD §3.5 (submission, branching outcomes, idempotency) and §3.6
(closure). The TNC contest path is in test_07_tnc_decision.py.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_audit_action_absent,
    assert_audit_action_present,
    assert_everify_case,
    close_case,
    create_employee,
    deliver_result,
    get_employee,
    list_audit_events,
    setup_employee_with_employment_authorized_case,
    setup_employee_with_fnc_case,
    setup_employee_with_pending_case,
    setup_employee_with_section2_done,
    setup_employee_with_single_open_case,
    submit_everify_case,
    submit_everify_payload,
    TEST_USERS,
    EMPLOYER_REP_SHARED_ID,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submission — PRD §3.5
# ===========================================================================
class TestSubmission:

    def test_submit_case_transitions_to_pending(self, api,
                                                employer_rep_headers):
        """PRD §3.5: "The case is created in state `DRAFT` and
        immediately transitions to `PENDING`."

        Claim: a fresh submission returns case_status=PENDING.
        """
        emp, form, _doc = setup_employee_with_section2_done(
            clock_iso="2026-06-02T08:00:00.000Z",
        )
        resp = api.submit_everify_case(
            emp["id"],
            submit_everify_payload(i9_form_id=form["id"]),
            employer_rep_headers,
        )
        case = validate_success(resp, expected_status=201)
        assert_everify_case(case)
        assert case["case_status"] == "PENDING"
        assert case["i9_form_id"] == form["id"]
        assert case["submitted_at"] is not None
        # PRD §3.5: AuditEvent EVERIFY_SUBMIT.
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "EVERIFY_SUBMIT")

    def test_idempotent_replay_returns_same_case(self, api,
                                                 employer_rep_headers):
        """PRD §3.5: "the `idempotency_key` must be unique across this
        employee's cases — a retry with the same key returns the
        existing case as a 200 OK rather than creating a duplicate"."""
        emp, form, _doc = setup_employee_with_section2_done(
            clock_iso="2026-06-02T08:00:00.000Z",
        )
        # First submit.
        payload = submit_everify_payload(
            i9_form_id=form["id"], idempotency_key="key-replay-1",
        )
        first = validate_success(
            api.submit_everify_case(emp["id"], payload, employer_rep_headers),
            expected_status=201,
        )
        # Replay with the same key.
        resp = api.submit_everify_case(emp["id"], payload, employer_rep_headers)
        assert resp.status_code == 200, (
            f"PRD §3.5: idempotent replay returns 200 (got {resp.status_code})"
        )
        body = resp.json()
        replayed = body.get("data", {})
        assert replayed.get("id") == first["id"], (
            "Replay must return the SAME case row id"
        )

    def test_second_open_case_with_different_key_returns_err_case_already_open(
            self, api, employer_rep_headers):
        """PRD §3.5: "there must be no prior non-closed `EVerifyCase`
        for this employee, otherwise `ERR_CASE_ALREADY_OPEN`"."""
        ctx = setup_employee_with_single_open_case()
        emp = ctx["employee"]
        form = ctx["form"]
        resp = api.submit_everify_case(
            emp["id"],
            submit_everify_payload(
                i9_form_id=form["id"], idempotency_key="key-second",
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_CASE_ALREADY_OPEN")


# ===========================================================================
# Result delivery branches — PRD §3.5
# ===========================================================================
class TestResultDelivery:

    def test_result_employment_authorized_transitions_to_employment_authorized(
            self, api, system_headers):
        """PRD §3.5: "From `PENDING`, the case transitions to
        `EMPLOYMENT_AUTHORIZED` on result `EMPLOYMENT_AUTHORIZED`"."""
        emp, form, case = setup_employee_with_pending_case(
            clock_iso="2026-06-02T08:00:00.000Z",
        )
        resp = api.deliver_everify_result(
            case["id"],
            {"result": "EMPLOYMENT_AUTHORIZED"},
            system_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["case_status"] == "EMPLOYMENT_AUTHORIZED"
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "CASE_AUTHORIZED")

    def test_result_tnc_stamps_tnc_opened_at_and_computes_deadline(
            self, api, system_headers):
        """PRD §3.5: "The `TNC` transition stamps `tnc_opened_at` with
        the current time, records the `tnc_kind` from the payload,
        computes `tnc_contest_deadline` as 10 federal working days
        after `tnc_opened_at`"."""
        emp, form, case = setup_employee_with_pending_case(
            clock_iso="2026-06-02T08:00:00.000Z",
        )
        advance_clock_to("2026-06-15T09:00:00.000Z")
        resp = api.deliver_everify_result(
            case["id"], {"result": "TNC", "tnc_kind": "SSA"},
            system_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["case_status"] == "TNC"
        assert updated["tnc_kind"] == "SSA"
        assert updated["tnc_opened_at"] == "2026-06-15T09:00:00.000Z"
        # PRD §3.5: 10 federal working days after 2026-06-15
        # (skipping Juneteenth 2026-06-19) = 2026-06-30T23:59:59.999Z.
        assert updated["tnc_contest_deadline"] == "2026-06-30T23:59:59.999Z"

    def test_result_fnc_transitions_to_fnc_and_records_audit(self,
                                                             api,
                                                             system_headers):
        """PRD §3.5: "The `FNC` transition appends an `AuditEvent` with
        action `FNC_RECEIVED`"."""
        emp, form, case = setup_employee_with_pending_case(
            clock_iso="2026-06-02T08:00:00.000Z",
        )
        resp = api.deliver_everify_result(
            case["id"], {"result": "FNC"}, system_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["case_status"] == "FNC"
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "FNC_RECEIVED")


# ===========================================================================
# Close — PRD §3.6
# ===========================================================================
class TestCaseClose:

    def test_close_employment_authorized_case_moves_to_closed_authorized(
            self, api, employer_rep_headers):
        """PRD §3.6: "From `EMPLOYMENT_AUTHORIZED` the case transitions
        to `CLOSED_AUTHORIZED`: `final_disposition` is set to
        `AUTHORIZED`, an `AuditEvent` with action `CASE_CLOSED` and
        `disposition` `AUTHORIZED` is appended, and `onboarding_status`
        moves to `AUTHORIZED`"."""
        emp, form, case = setup_employee_with_employment_authorized_case()
        resp = api.close_everify_case(case["id"], None, employer_rep_headers)
        closed = validate_success(resp, expected_status=200)
        assert closed["case_status"] == "CLOSED_AUTHORIZED"
        assert closed["final_disposition"] == "AUTHORIZED"
        # Employee.onboarding_status flips to AUTHORIZED.
        re_emp = get_employee(emp["id"])
        assert re_emp["onboarding_status"] == "AUTHORIZED"
        assert re_emp["is_terminated"] is False, (
            "PRD §3.6: AUTHORIZED close does NOT terminate the employee"
        )

    def test_close_fnc_case_moves_to_closed_not_authorized_and_terminates(
            self, api, employer_rep_headers):
        """PRD §3.6: "From `FNC` the case transitions to
        `CLOSED_NOT_AUTHORIZED`: `final_disposition` is set to
        `NOT_AUTHORIZED`, an `AuditEvent` with action `CASE_CLOSED` and
        `disposition` `NOT_AUTHORIZED` is appended, `onboarding_status`
        moves to `NOT_AUTHORIZED`, and the employee-termination
        subroutine cascades (`is_terminated` becomes true with an
        `AuditEvent` of action `TERMINATE`)"."""
        emp, form, case = setup_employee_with_fnc_case()
        resp = api.close_everify_case(case["id"], None, employer_rep_headers)
        closed = validate_success(resp, expected_status=200)
        assert closed["case_status"] == "CLOSED_NOT_AUTHORIZED"
        assert closed["final_disposition"] == "NOT_AUTHORIZED"
        # Cascade: employee terminated.
        re_emp = get_employee(emp["id"])
        assert re_emp["is_terminated"] is True
        assert re_emp["onboarding_status"] == "TERMINATED", (
            "PRD §3.7: is_terminated=true → onboarding_status=TERMINATED"
        )
        events = list_audit_events(emp["id"])
        assert_audit_action_present(events, "CASE_CLOSED")
        assert_audit_action_present(events, "TERMINATE")

    def test_close_pending_case_returns_err_invalid_state(self, api,
                                                          employer_rep_headers):
        """PRD §3.6: "Closure from any other state is rejected as an
        invalid state transition"."""
        emp, form, case = setup_employee_with_pending_case(
            clock_iso="2026-06-02T08:00:00.000Z",
        )
        resp = api.close_everify_case(case["id"], None, employer_rep_headers)
        validate_error(resp, "ERR_INVALID_STATE")
