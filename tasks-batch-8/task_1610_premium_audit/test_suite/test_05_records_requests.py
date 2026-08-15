"""Records requests: due-date computation, the overdue sweep boundary,
terminal-state rules, duplicate-type rejection, and the non-compliance basis."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_records_request,
    parse_ts,
    receive_request,
    set_clock,
    setup_selected_work_order,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["audit_manager_headers"]


class TestRecordsRequestLifecycle:
    def test_records_request_due_at_computed_from_clock(self, api):
        """PRD: "A new request is born `OPEN`, stamped `requested_at` with the
        logical clock, with `due_at` fixed at fifteen days after
        `requested_at`"
        PRD: "Before any client call, the clock reads exactly
        `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock
        time."

        Design: Corner/entities/records_request_due_at_computed
        """
        ctx = setup_selected_work_order(policy_number="WC-C3",
                                        with_auditor=False, assign=False,
                                        request_types=())

        req = add_records_request(ctx, "PAYROLL_SUMMARY")

        assert parse_ts(req["requested_at"]) == parse_ts(
            "2026-08-01T00:00:00Z"), "requested_at must be the default clock"
        assert parse_ts(req["due_at"]) == parse_ts("2026-08-16T00:00:00Z"), (
            f"due_at must be requested_at + 15 days, got {req['due_at']}")
        assert parse_ts(req["due_at"]) - parse_ts(req["requested_at"]) == \
            timedelta(days=15)

    def test_records_request_overdue_boundary_is_strict(self, api):
        """PRD: "First, every records request still `OPEN` whose `due_at` is
        strictly before the new clock moves to `OVERDUE`; a request whose
        `due_at` equals the clock exactly remains `OPEN`."
        PRD: "All three sweeps use strict-greater comparisons at their
        boundaries."

        Design: Corner/state_machines/records_request_overdue_boundary
        """
        ctx = setup_selected_work_order(policy_number="WC-S1",
                                        with_auditor=False, assign=False)
        req = ctx["requests"][0]

        set_clock("2026-08-16T00:00:00Z")
        at_due = validate_success(api.get_records_request(req["id"], MANAGER))
        assert at_due["status"] == "OPEN", (
            "At clock == due_at exactly the request must stay OPEN")

        set_clock("2026-08-16T00:00:01Z")
        past_due = validate_success(api.get_records_request(req["id"], MANAGER))
        assert past_due["status"] == "OVERDUE", (
            "One second past due_at the request must flip to OVERDUE")

    def test_receive_twice_rejected(self, api):
        """PRD: "Receipt is recorded by the assigned auditor — a caller who is
        not the work order's assigned auditor is rejected with
        `ERR_FORBIDDEN_SCOPE` — moving the request from `OPEN` or `OVERDUE` to
        `RECEIVED` and stamping `received_at` with the clock; late receipt
        from `OVERDUE` is explicitly permitted."
        PRD: "Both `RECEIVED` and `WAIVED` are terminal."
        PRD: "7. **State legality** — the target resource is in a from-state
        its state machine permits for the attempted transition, and terminal
        states reject everything; failure yields `ERR_INVALID_STATE_TRANSITION`
        (409)."

        Design: Corner/state_machines/receive_twice_rejected
        """
        ctx = setup_selected_work_order(policy_number="WC-S5")
        req = ctx["requests"][0]
        receive_request(ctx, req)

        resp = api.receive_records_request(req["id"], ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_duplicate_records_request_type_rejected(self, api):
        """PRD: "at most one non-terminal request (`OPEN` or `OVERDUE`) of
        each type may exist per work order; a repeat is rejected with
        `ERR_DUPLICATE_RECORDS_REQUEST`."
        PRD: "An `AuditManager` may instead waive a request from `OPEN` or
        `OVERDUE`, moving it to `WAIVED`. Both `RECEIVED` and `WAIVED` are
        terminal."

        Design: Corner/validations/duplicate_records_request_type_rejected
        """
        ctx = setup_selected_work_order(policy_number="WC-V6",
                                        estimated_annual_premium_cents=2000000,
                                        minimum_premium_cents=100000)
        first = ctx["requests"][0]
        assert first["request_type"] == "PAYROLL_SUMMARY"

        dup = api.create_records_request(ctx["work_order"]["id"],
                                         {"request_type": "PAYROLL_SUMMARY"},
                                         MANAGER)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_RECORDS_REQUEST)

        waived = validate_success(
            api.waive_records_request(first["id"], MANAGER), 200)
        assert waived["status"] == "WAIVED"

        replacement = api.create_records_request(
            ctx["work_order"]["id"], {"request_type": "PAYROLL_SUMMARY"},
            MANAGER)
        req2 = validate_success(replacement, 201)
        assert req2["status"] == "OPEN"
        assert req2["request_type"] == "PAYROLL_SUMMARY"


class TestNonComplianceBasis:
    def test_mark_noncompliant_without_overdue_basis(self, api):
        """PRD: "An `AuditManager` may flag non-compliance while the work
        order is `RECORDS_REQUESTED` or `APPOINTMENT_SCHEDULED`, but only when
        at least one of its records requests stands `OVERDUE`; without that
        basis the flag is rejected with `ERR_NO_NONCOMPLIANCE_BASIS`."

        Design: Corner/validations/mark_noncompliant_without_overdue_basis
        """
        ctx = setup_selected_work_order(policy_number="WC-V1",
                                        estimated_annual_premium_cents=2000000,
                                        minimum_premium_cents=100000,
                                        with_auditor=False, assign=False)

        resp = api.mark_noncompliant(ctx["work_order"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_NO_NONCOMPLIANCE_BASIS)

        wo_after = validate_success(
            api.get_work_order(ctx["work_order"]["id"], MANAGER))
        assert wo_after["status"] == "RECORDS_REQUESTED"
