"""Matter close-out battery, reopen window, and phase-budget void guards."""
from test_helpers import (
    ApiErrorId,
    add_approved_entry,
    advance_and_close_books,
    api_client,
    make_billing_partner_headers,
    make_managing_partner_headers,
    run_true_up,
    setup_active_matter,
    setup_collar_matter_year_ended,
    setup_matter_with_accrual_report,
    validate_error,
    validate_success,
)


class TestMatterCloseBattery:

    def test_close_blocked_by_open_wip(self):
        """PRD section 3.9: "First, no time entry may remain in `DRAFT`,
        `SUBMITTED`, or `APPROVED`, else the close is rejected with
        `ERR_MATTER_HAS_OPEN_WIP`."

        Design: Corner/state_machines/matter_close_blocked_by_open_wip
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                           ctx["partner"]["id"], 50000, ctx["partner"]["id"])

        resp = api_client.close_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MATTER_HAS_OPEN_WIP)

    def test_close_blocked_by_outstanding_accrual(self):
        """PRD section 3.9: "Fifth, when the client mandates accrual
        reporting, the matter's latest accrual report must be `SUBMITTED` or
        `ACKNOWLEDGED`, else `ERR_MATTER_ACCRUAL_OUTSTANDING`."

        Design: Corner/errors/error_accrual_outstanding_on_matter_close
        """
        # Accrual-reporting client; one period advanced so a DRAFT report
        # exists but is never submitted.
        ctx = setup_matter_with_accrual_report()
        assert ctx["report"]["status"] == "DRAFT"

        resp = api_client.close_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MATTER_ACCRUAL_OUTSTANDING)

    def test_close_blocked_by_unsettled_collar_true_up(self):
        """PRD section 3.9: "Fourth, when the matter's arrangement is a
        `COLLAR` whose fiscal year has ended, its true-up must be `SETTLED`
        or `WAIVED`, else `ERR_MATTER_COLLAR_UNSETTLED`."

        Design: Difficulty/cross_entity_state_dependency/matter_close_depends_on_collar_true_up_state
        """
        ctx = setup_collar_matter_year_ended()
        true_up = run_true_up(ctx["firm"]["id"], ctx["matter"]["id"],
                              ctx["partner"]["id"])
        assert true_up["status"] == "COMPUTED"

        resp = api_client.close_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MATTER_COLLAR_UNSETTLED)


class TestMatterReopen:

    def test_reopen_after_window_closed(self):
        """PRD section 3.9: "A closed matter can be brought back — by a
        `ManagingPartner` only — within a bounded reopen window: the closure
        must fall within `closed_through_period_index` plus two periods.
        Outside that window the attempt is rejected with
        `ERR_REOPEN_WINDOW_CLOSED`."

        Design: Corner/errors/error_reopen_window_closed
        """
        ctx = setup_active_matter()
        closed = validate_success(api_client.close_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"])), 200)
        assert closed["status"] == "CLOSED"

        # Close the books four periods past the closure, beyond the
        # closed_through_period_index + 2 reopen window.
        advance_and_close_books(ctx["firm"]["id"], cycles=4)

        resp = api_client.reopen_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_managing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED)

    def test_billing_partner_cannot_reopen(self):
        """PRD section 2.1: "A request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD section 3.9: "A closed matter can be brought back — by a
        `ManagingPartner` only — within a bounded reopen window: the closure
        must fall within `closed_through_period_index` plus two periods."

        Design: Corner/rbac/managing_partner_exclusive_reopen
        """
        ctx = setup_active_matter()
        validate_success(api_client.close_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"])), 200)

        resp = api_client.reopen_matter(
            ctx["firm"]["id"], ctx["matter"]["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestPhaseBudgetVoid:

    def test_void_blocked_by_actuals(self):
        """PRD section 3.3: "An `ACTIVE` phase budget may be voided only by
        a `BillingPartner`, and only when two guards pass, evaluated in
        order: its `actual_to_date_cents` must be zero, or the void is
        rejected with `ERR_PHASE_HAS_ACTUALS`; and no budget amendment in
        `DRAFT` or `PENDING_REVIEW` may reference it, or the void is
        rejected with `ERR_PHASE_HAS_PENDING_AMENDMENT`."

        Design: Corner/state_machines/phase_budget_void_blocked_by_actuals
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        phase = ctx["phases"]["L110"]
        add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                           ctx["partner"]["id"], 50000, ctx["partner"]["id"])

        resp = api_client.void_phase_budget(
            ctx["firm"]["id"], phase["id"],
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PHASE_HAS_ACTUALS)
