"""PRD §3.6: Dividend lifecycle -- announce, ex-dividend snapshot,
payment (CASH/REINVEST), cancellation, and the cross-entity gating on
NAV-published-for-ex-dividend-date.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    create_dividend_plan_payload,
    create_kyc_approved_investor,
    create_on_shelf_fund,
    fee_tier,
    get_fund_fresh,
    holding_period_tier,
    make_investor_headers,
    publish_nav_payload,
    set_distribution_option_payload,
    setup_fund_with_outstanding_shares,
    setup_investor_with_confirmed_subscribe,
    submit_subscribe_order,
    subscribe_confirm,
    validate_error,
    validate_success,
)


# =====================================================================
# Date-ordering validation (PRD §3.6 / §2.10 priority 15)
# =====================================================================
class TestDividendDates:
    def test_record_before_announcement_rejected(self, api):
        """PRD §3.6: "The four dates must satisfy `record_date >=
        announcement_date`, ... any deviation yields
        `ERR_DIVIDEND_DATE_INVALID`."

        Claim: record_date earlier than announcement_date triggers
        ERR_DIVIDEND_DATE_INVALID.
        """
        fund = create_on_shelf_fund()
        res = api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2027-04-10",
                record_date="2027-04-05",  # before announcement
                ex_dividend_date="2027-04-06",
                payment_date="2027-04-15",
            ),
            TEST_USERS["product_operator_headers"],
        )
        validate_error(res, "ERR_DIVIDEND_DATE_INVALID")

    def test_ex_dividend_not_record_plus_one_rejected(self, api):
        """PRD §3.6: "`ex_dividend_date == record_date + 1` calendar
        day".

        Claim: ex_dividend_date != record_date + 1 (here record+2)
        triggers ERR_DIVIDEND_DATE_INVALID.

        # difficulty: resource_temporal_overlap/dividend_plan_dates_must_be_buffered
        """
        fund = create_on_shelf_fund()
        res = api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2027-04-01",
                record_date="2027-04-10",
                ex_dividend_date="2027-04-12",  # off by one
                payment_date="2027-04-15",
            ),
            TEST_USERS["product_operator_headers"],
        )
        validate_error(res, "ERR_DIVIDEND_DATE_INVALID")

    def test_payment_before_ex_dividend_rejected(self, api):
        """PRD §3.6: "`payment_date >= ex_dividend_date`".

        Claim: payment_date strictly before ex_dividend_date triggers
        ERR_DIVIDEND_DATE_INVALID.
        """
        fund = create_on_shelf_fund()
        res = api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2027-04-01",
                record_date="2027-04-10",
                ex_dividend_date="2027-04-11",
                payment_date="2027-04-09",  # before ex_dividend
            ),
            TEST_USERS["product_operator_headers"],
        )
        validate_error(res, "ERR_DIVIDEND_DATE_INVALID")

    def test_correctly_ordered_dates_succeed(self, api):
        """PRD §3.6: "The four dates must satisfy `record_date >=
        announcement_date`, `ex_dividend_date == record_date + 1`
        calendar day, and `payment_date >= ex_dividend_date`."

        Claim: a plan with all four dates correctly ordered is created
        successfully in ANNOUNCED status.

        # difficulty: resource_temporal_overlap/dividend_plan_dates_must_be_buffered
        """
        fund = create_on_shelf_fund()
        res = api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2027-05-01",
                record_date="2027-05-10",
                ex_dividend_date="2027-05-11",
                payment_date="2027-05-15",
            ),
            TEST_USERS["product_operator_headers"],
        )
        plan = validate_success(res, expected_status=201)
        assert plan["status"] == "ANNOUNCED"


# =====================================================================
# Cancel dividend plan (PRD §3.6)
# =====================================================================
class TestCancelDividendPlan:
    def test_cancel_before_ex_dividend_succeeds(self, api):
        """PRD §3.6: "A `ComplianceReviewer` may cancel a plan that is
        still in `ANNOUNCED` status as long as the server clock is
        strictly before `ex_dividend_date`; the plan transitions
        `ANNOUNCED → CANCELLED`."

        Claim: cancel before ex_dividend_date transitions the plan to
        CANCELLED.
        """
        fund = create_on_shelf_fund()
        advance_clock_to("2027-06-01T10:00:00.000Z")
        plan = validate_success(api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2027-06-01",
                record_date="2027-06-15",
                ex_dividend_date="2027-06-16",
                payment_date="2027-06-20",
            ),
            TEST_USERS["product_operator_headers"],
        ), expected_status=201)
        # Clock still before ex_dividend_date.
        res = api.cancel_dividend_plan(
            plan["id"], TEST_USERS["compliance_reviewer_headers"]
        )
        cancelled = validate_success(res)
        assert cancelled["status"] == "CANCELLED"


# =====================================================================
# Mark ex-dividend snapshots eligible holdings (PRD §3.6)
# =====================================================================
class TestMarkExDividend:
    def test_mark_ex_dividend_transitions_to_ex_dividend(self, api):
        """PRD §3.6: "When the server clock has reached or passed the
        date portion of `ex_dividend_date` and the fund's status is
        `ON_SHELF`, marking ex-dividend transitions the plan
        `ANNOUNCED → EX_DIVIDEND`."

        Claim: at or after ex_dividend_date, mark-ex-dividend produces
        EX_DIVIDEND status.
        """
        # Investor with confirmed holdings to make the snapshot non-empty.
        investor, fund, order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2027-07-01T10:00:00.000Z",
        )
        advance_clock_to("2027-07-05T10:00:00.000Z")
        plan = validate_success(api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2027-07-05",
                record_date="2027-07-10",
                ex_dividend_date="2027-07-11",
                payment_date="2027-07-15",
            ),
            TEST_USERS["product_operator_headers"],
        ), expected_status=201)
        advance_clock_to("2027-07-11T01:00:00.000Z")
        res = api.mark_ex_dividend(
            plan["id"], TEST_USERS["nav_operator_headers"]
        )
        ex_div = validate_success(res)
        assert ex_div["status"] == "EX_DIVIDEND"


# =====================================================================
# Execute payment requires NAV PUBLISHED for ex_dividend_date (PRD §3.6)
# =====================================================================
class TestExecutePaymentNavGate:
    def test_payment_without_nav_published_rejected(self, api):
        """PRD §3.6: "Once payment_date has been reached on the server
        clock and the NAV snapshot for the plan's `ex_dividend_date` is
        `PUBLISHED`, a `NavOperator` executes payment."

        Claim: when no NavSnapshot for ex_dividend_date is in PUBLISHED
        state, execute-payment is rejected with ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/dividend_payment_requires_nav_published_for_ex_div_date
        """
        investor, fund, order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2027-08-01T10:00:00.000Z",
        )
        advance_clock_to("2027-08-05T10:00:00.000Z")
        plan = validate_success(api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2027-08-05",
                record_date="2027-08-10",
                ex_dividend_date="2027-08-11",
                payment_date="2027-08-15",
                dividend_per_share_micros=10_000,
                tax_rate_bps_domestic=0,
                tax_rate_bps_foreign=0,
            ),
            TEST_USERS["product_operator_headers"],
        ), expected_status=201)
        advance_clock_to("2027-08-11T01:00:00.000Z")
        validate_success(api.mark_ex_dividend(
            plan["id"], TEST_USERS["nav_operator_headers"]
        ))
        # Clock past payment_date but NO NAV publish for 2027-08-11.
        advance_clock_to("2027-08-16T01:00:00.000Z")
        res = api.execute_dividend_payment(
            plan["id"], TEST_USERS["nav_operator_headers"]
        )
        validate_error(res, "ERR_INVALID_STATE")
