"""Billing transactions: overpayment guard, the past-due sweep boundary, and
the two-condition work-order close."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_estimated,
    close_work_order,
    parse_ts,
    record_payment,
    set_clock,
    setup_issued_standard_result,
    setup_noncompliant_work_order,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["audit_manager_headers"]


class TestRecordPayment:
    def test_record_payment_overpayment_rejected(self, api):
        """PRD: "Recording a payment (against an invoice) or a credit
        application (against a return premium) supplies `amount_cents`; the
        amount must not exceed the remaining balance — `amount_cents` minus
        `paid_cents` — or the recording is rejected with `ERR_OVERPAYMENT`
        (HTTP 422)."
        PRD: "Each accepted recording adds to `paid_cents`, and when the
        cumulative figure reaches the full amount an invoice becomes `PAID`
        and a credit becomes `APPLIED`; both are terminal, as is `CANCELLED`."

        Design: Corner/validations/record_payment_overpayment_rejected
        """
        ctx = setup_issued_standard_result(policy_number="WC-V7")
        billing = ctx["billing"]
        assert billing["amount_cents"] == 554400

        too_much = api.record_payment(billing["id"], {"amount_cents": 554401},
                                      ctx["billing_clerk"])
        validate_error(too_much, ApiErrorId.ERR_OVERPAYMENT)

        settled = record_payment(ctx, 554400)
        assert settled["status"] == "APPLIED"
        assert settled["paid_cents"] == 554400


class TestPastDueSweep:
    def test_billing_past_due_boundary_is_strict(self, api):
        """PRD: "Second, every billing transaction still `ISSUED` whose
        `due_at` is strictly before the new clock moves to `PAST_DUE`."
        PRD: "All three sweeps use strict-greater comparisons at their
        boundaries."
        PRD: "with `amount_cents` equal to the absolute adjustment,
        `paid_cents` zero, `issued_at` at the clock, `due_at` thirty days
        after `issued_at`, and status `ISSUED`."

        Design: Corner/calculations/billing_past_due_boundary
        """
        ctx = setup_noncompliant_work_order(policy_number="WC-K6")
        approve_estimated(ctx, approver="mgr-2")
        billing = ctx["billing"]
        assert billing["type"] == "ADDITIONAL_PREMIUM_INVOICE"
        assert billing["amount_cents"] == 500000
        assert parse_ts(billing["due_at"]) == parse_ts("2026-09-16T00:00:00Z"), (
            "issued at 2026-08-17 plus thirty days")

        set_clock("2026-09-16T00:00:00Z")
        at_due = validate_success(
            api.get_billing_transaction(billing["id"], MANAGER))
        assert at_due["status"] == "ISSUED", (
            "At clock == due_at exactly the transaction must stay ISSUED")

        set_clock("2026-09-16T00:00:01Z")
        past_due = validate_success(
            api.get_billing_transaction(billing["id"], MANAGER))
        assert past_due["status"] == "PAST_DUE", (
            "One second past due_at the transaction must flip to PAST_DUE")


class TestWorkOrderClose:
    def test_close_rejected_while_billing_unsettled(self, api):
        """PRD: "A billed audit is closed by an `AuditManager` once two
        conditions hold: every billing transaction of the work order's result
        stands `PAID` or `APPLIED` (or no billing exists because the
        adjustment was zero), and the logical clock has passed strictly beyond
        `issued_at` plus thirty days, so the dispute window has elapsed.
        Either failure is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/close_requires_billing_settled_and_window_elapsed
        """
        ctx = setup_issued_standard_result(policy_number="WC-1500")
        set_clock("2026-09-15T00:00:00Z")  # dispute window elapsed (09-14)
        assert ctx["billing"]["status"] == "ISSUED"

        resp = api.close_work_order(ctx["work_order"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_close_succeeds_after_settlement_and_window(self, api):
        """PRD: "A billed audit is closed by an `AuditManager` once two
        conditions hold: every billing transaction of the work order's result
        stands `PAID` or `APPLIED` (or no billing exists because the
        adjustment was zero), and the logical clock has passed strictly beyond
        `issued_at` plus thirty days, so the dispute window has elapsed."
        PRD: "Closing moves the work order to `CLOSED` and increments its
        `version`; when no other work order of the same policy remains in a
        non-terminal state, the policy itself moves `AUDIT_PENDING →
        AUDIT_FINALIZED` with a `Policy.version` increment."

        Design: Difficulty/cross_entity_state_dependency/close_requires_billing_settled_and_window_elapsed
        """
        ctx = setup_issued_standard_result(policy_number="WC-1500")
        set_clock("2026-09-15T00:00:00Z")
        blocked = api.close_work_order(ctx["work_order"]["id"], MANAGER)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        settled = record_payment(ctx, 554400)
        assert settled["status"] == "APPLIED"

        closed = close_work_order(ctx)
        assert closed["status"] == "CLOSED"

        policy = validate_success(api.get_policy(ctx["policy"]["id"], MANAGER))
        assert policy["status"] == "AUDIT_FINALIZED", (
            "With no other non-terminal work order the policy bubbles up")

    def test_closed_work_order_rejects_further_actions(self, api):
        """PRD: "A work order's full state alphabet is `SELECTED`,
        `RECORDS_REQUESTED`, `APPOINTMENT_SCHEDULED`, `FIELD_WORK_DONE`,
        `RESULT_DRAFTED`, `BILLED`, `DISPUTED`, `NONCOMPLIANT_PENDING`,
        `ESTIMATED_BILLED`, and the three terminal states `CLOSED`,
        `SUPERSEDED_BY_REAUDIT`, and `CANCELLED`."
        PRD: "7. **State legality** — the target resource is in a from-state
        its state machine permits for the attempted transition, and terminal
        states reject everything; failure yields `ERR_INVALID_STATE_TRANSITION`
        (409)."

        Design: Corner/state_machines/closed_work_order_rejects_further_actions
        """
        ctx = setup_issued_standard_result(policy_number="WC-S3",
                                           experience_mod_factor=1.00)
        record_payment(ctx, ctx["billing"]["amount_cents"])
        set_clock("2026-09-15T00:00:00Z")
        close_work_order(ctx)
        assert ctx["work_order"]["status"] == "CLOSED"

        resp = api.mark_noncompliant(ctx["work_order"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
