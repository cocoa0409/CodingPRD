"""Every side effect of a variance hold is readable in the same synchronous breath."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_division_order_revenue_conserved,
    assert_money,
)
from test_helpers.test_users import ADMIN_HEADERS


def test_the_reported_line_carries_its_own_variance_and_suspends_the_order(api):
    """106.47 paid against 115.52 expected is a 9.05 variance and a suspended order.

    PRD: "The order itself moves `EXECUTED → SUSPENDED` and its
    `cumulative_variance_amount` becomes its previous value plus the line's
    `variance_amount`, rounded to cents — a running sum over the order's held lines."

    Design: Corner/consistency model/variance_hold_and_its_suspense_are_visible_in_the_same_response
    """
    world = fx.executed_division_order_ready(api)

    detail = fx.report_revenue(api, world["order"]["id"])

    assert detail["check_status"] == "VARIANCE_HELD"
    assert_money(detail["net_amount"], "106.47", "net_amount")
    assert_money(detail["expected_net_amount"], "115.52", "expected_net_amount")
    assert_money(detail["variance_amount"], "9.05", "variance_amount")

    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "SUSPENDED"
    assert_money(order["cumulative_variance_amount"], "9.05", "cumulative_variance_amount")
    assert_money(order["paid_net_total"], "0.00", "paid_net_total")


def test_the_suspense_the_owner_and_the_money_identity_are_all_current(api):
    """One ACCRUING account of 106.47 is already listed and already in suspense_total.

    PRD: "That figure is not client-supplied: it is always the sum of `accrued_amount`
    across the owner's suspense accounts whose `suspense_status` is `ACCRUING`, carried
    to 2 decimal places."

    PRD: "This identity is asserted after every revenue check detail is reported and
    after every suspense release."

    Design: Corner/consistency model/variance_hold_and_its_suspense_are_visible_in_the_same_response
    """
    world = fx.executed_division_order_ready(api)
    detail = fx.report_revenue(api, world["order"]["id"])

    accounts = fx.list_suspense_for_order(api, world["order"]["id"])

    assert len(accounts) == 1
    account = accounts[0]
    assert account["suspense_status"] == "ACCRUING"
    assert account["suspense_reason"] == "DECIMAL_VARIANCE"
    assert account["held_detail_count"] == 1
    assert account["first_suspended_month"] == "2026-06"
    assert_money(account["accrued_amount"], "106.47", "accrued_amount")

    owner = validate_success(api.get_royalty_owner(world["owner"]["id"], ADMIN_HEADERS), 200)
    assert_money(owner["suspense_total"], "106.47", "suspense_total")

    details, _meta = validate_paginated(
        api.list_revenue_check_details(world["order"]["id"], ADMIN_HEADERS)
    )
    assert [item["id"] for item in details] == [detail["id"]]
    assert_division_order_revenue_conserved(
        fx.read_division_order(api, world["order"]["id"]), details, accounts
    )
