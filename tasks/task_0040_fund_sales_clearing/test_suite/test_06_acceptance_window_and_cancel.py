"""PRD §3.3: 15:00 UTC acceptance-window cutoff for trade_date assignment,
and the cancel-window rule that mirrors it.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    build_user_headers,
    create_on_shelf_fund,
    create_kyc_approved_investor,
    create_subscribe_order_payload,
    get_order_fresh,
    make_investor_headers,
    setup_basic_investor_and_fund,
    submit_subscribe_order,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


# =====================================================================
# Acceptance window (PRD §3.3)
# =====================================================================
class TestAcceptanceWindow:
    def test_pre_cutoff_trade_date_is_today(self, api):
        """PRD §3.3: "If `submitted_at` is strictly before that cutoff
        instant, `trade_date` is the calendar date of `submitted_at`."

        Claim: an order submitted at 14:59 UTC has trade_date == that
        same calendar date.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-08-10T14:59:00.000Z")
        order = submit_subscribe_order(investor, fund, 1_000)
        assert order["trade_date"].startswith("2026-08-10"), (
            f"Expected trade_date to start with 2026-08-10, got "
            f"{order['trade_date']!r}"
        )

    def test_at_cutoff_trade_date_shifts_next_day(self, api):
        """PRD §3.3: "If `submitted_at` is at or after the cutoff (the
        boundary at exactly 15:00 inclusive shifts to next day),
        `trade_date` is the calendar date of `submitted_at` plus one
        calendar day."

        Claim: an order submitted at exactly 15:00 UTC shifts trade_date
        to the next calendar day.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-08-12T15:00:00.000Z")
        order = submit_subscribe_order(investor, fund, 1_000)
        assert order["trade_date"].startswith("2026-08-13"), (
            f"Expected trade_date to start with 2026-08-13, got "
            f"{order['trade_date']!r}"
        )

    def test_post_cutoff_trade_date_shifts_next_day(self, api):
        """PRD §3.3: "If `submitted_at` is at or after the cutoff (the
        boundary at exactly 15:00 inclusive shifts to next day),
        `trade_date` is the calendar date of `submitted_at` plus one
        calendar day."

        Claim: an order submitted at 15:30 UTC has trade_date == the
        next calendar day.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-08-15T15:30:00.000Z")
        order = submit_subscribe_order(investor, fund, 1_000)
        assert order["trade_date"].startswith("2026-08-16"), (
            f"Expected trade_date to start with 2026-08-16, got "
            f"{order['trade_date']!r}"
        )


# =====================================================================
# Cancel-window (PRD §3.3 / §2.10 priority 13)
# =====================================================================
class TestCancelWindow:
    def test_cancel_before_cutoff_succeeds(self, api):
        """PRD §3.3: "An `Investor` may cancel an `ACCEPTED` order -- but
        only if the server clock is strictly before the order's
        `trade_date` combined with 15:00 UTC."

        Claim: a cancel issued at 14:59 UTC of trade_date succeeds and
        the order transitions ACCEPTED -> CANCELLED.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-09-01T10:00:00.000Z")
        order = submit_subscribe_order(investor, fund, 1_000)
        # trade_date should be 2026-09-01 (pre-cutoff submit)
        advance_clock_to("2026-09-01T14:59:00.000Z")
        res = api.cancel_order(
            order["id"], make_investor_headers(investor["id"])
        )
        cancelled = validate_success(res)
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_at_cutoff_rejected(self, api):
        """PRD §3.3: "if the server clock is strictly before the order's
        `trade_date` combined with 15:00 UTC, otherwise
        `ERR_CANCEL_WINDOW_CLOSED`."

        Claim: at exactly 15:00 UTC of the trade_date the cancel window
        is closed; cancel yields ERR_CANCEL_WINDOW_CLOSED.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-09-05T10:00:00.000Z")
        order = submit_subscribe_order(investor, fund, 1_000)
        advance_clock_to("2026-09-05T15:00:00.000Z")
        res = api.cancel_order(
            order["id"], make_investor_headers(investor["id"])
        )
        validate_error(res, "ERR_CANCEL_WINDOW_CLOSED")

    def test_cancel_after_cutoff_rejected(self, api):
        """PRD §3.3: "if the server clock is strictly before the order's
        `trade_date` combined with 15:00 UTC, otherwise
        `ERR_CANCEL_WINDOW_CLOSED`."

        Claim: well after the cutoff, cancel yields
        ERR_CANCEL_WINDOW_CLOSED.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-09-10T10:00:00.000Z")
        order = submit_subscribe_order(investor, fund, 1_000)
        advance_clock_to("2026-09-10T16:30:00.000Z")
        res = api.cancel_order(
            order["id"], make_investor_headers(investor["id"])
        )
        validate_error(res, "ERR_CANCEL_WINDOW_CLOSED")

    def test_cancel_by_non_owner_rejected(self, api):
        """PRD §3.3: "Cancel by anyone other than the investor who owns
        the order is rejected (the `X-User-ID` must equal
        `Order.investor_id`)."

        Claim: cancel issued by a different Investor.id is rejected.
        Because the X-User-ID does not match the Order.investor_id,
        the implementation may surface the violation either as
        ERR_FORBIDDEN (per §2.1 ownership semantics) or as
        ERR_NOT_FOUND (the resource is not visible to the caller).
        Either is faithful PRD reading; both are accepted.
        """
        owner, fund = setup_basic_investor_and_fund()
        intruder = create_kyc_approved_investor()
        advance_clock_to("2026-09-15T10:00:00.000Z")
        order = submit_subscribe_order(owner, fund, 1_000)
        res = api.cancel_order(
            order["id"], make_investor_headers(intruder["id"])
        )
        # PRD does not commit to a single error_id for this case; both
        # ERR_FORBIDDEN and ERR_NOT_FOUND are PRD-faithful readings of
        # the §2.1 ownership rule.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, ["ERR_FORBIDDEN", "ERR_NOT_FOUND"])
