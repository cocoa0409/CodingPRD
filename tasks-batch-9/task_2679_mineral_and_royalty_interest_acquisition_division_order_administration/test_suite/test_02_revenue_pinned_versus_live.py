"""One revenue line, three computations: reported, pinned-settlement and live audit."""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_acreage,
    assert_decimal_interest,
    assert_money,
    assert_rate,
)

PUGH_UNIT = {"pugh_clause_active": True, "pugh_deadline": "2026-12-31"}


def _pugh_released_executed_order(api):
    world = fx.executed_division_order_ready(api, unit_overrides=dict(PUGH_UNIT))
    fx.set_clock(api, "2027-01-01T00:00:00Z")
    world["allocation"] = fx.pugh_release(api, world["allocation"]["id"])
    return world


def test_revenue_line_settlement_variant_uses_the_pinned_decimal(api):
    """The settlement variant is built from the pinned decimal, not the live one.

    PRD: "This variant deliberately ignores every allocation, pooling and pugh
    change that occurred after the order was executed, because that is exactly
    what pinning a decimal means."

    Design: Difficulty/dual_variant_calc/revenue_check_pinned_decimal_versus_live_allocation_decimal
    """
    world = _pugh_released_executed_order(api)

    detail = fx.report_revenue(
        api,
        world["order"]["id"],
        production_month="2026-06",
        product_code="OIL",
        gross_volume=1000.0000,
        gross_value=62000.00,
        operator_decimal_used=0.00180000,
    )

    assert_rate(detail["severance_tax_rate"], "0.046000", "severance_tax_rate")
    assert_money(detail["reported_gross_royalty"], "111.60", "reported_gross_royalty")
    assert_money(detail["net_amount"], "106.47", "net_amount")
    assert_money(detail["expected_gross_royalty"], "121.09", "expected_gross_royalty")
    assert_money(detail["expected_net_amount"], "115.52", "expected_net_amount")
    assert_money(detail["variance_amount"], "9.05", "variance_amount")


def test_revenue_line_audit_variant_uses_the_live_pugh_shrunk_acreage(api):
    """The audit variant re-derives the decimal against the shrunken allocation.

    PRD: "After a pugh release the live decimal is strictly smaller than the
    pinned decimal, so `audit_gross_royalty` and `expected_gross_royalty` diverge
    for byte-identical inputs — and that divergence is the firm's signal that the
    order needs correcting."

    Design: Difficulty/dual_variant_calc/revenue_check_pinned_decimal_versus_live_allocation_decimal
    """
    world = _pugh_released_executed_order(api)
    assert_acreage(world["allocation"]["allocated_acres"], "213.3333", "allocated_acres")

    detail = fx.report_revenue(
        api,
        world["order"]["id"],
        gross_value=62000.00,
        operator_decimal_used=0.00180000,
    )

    assert_decimal_interest(detail["audit_decimal"], "0.00130208", "audit_decimal")
    assert_money(detail["audit_gross_royalty"], "80.73", "audit_gross_royalty")
    assert_money(detail["audit_variance_amount"], "-29.45", "audit_variance_amount")


def test_variance_holds_the_line_and_leaves_the_pinned_decimal_alone(api):
    """The held line suspends the order while the pinned decimal stays frozen.

    PRD: "The order itself moves `EXECUTED → SUSPENDED` and its
    `cumulative_variance_amount` becomes its previous value plus the line's
    `variance_amount`, rounded to cents — a running sum over the order's held
    lines."

    Design: Difficulty/dual_variant_calc/revenue_check_pinned_decimal_versus_live_allocation_decimal
    """
    world = _pugh_released_executed_order(api)

    detail = fx.report_revenue(
        api,
        world["order"]["id"],
        gross_value=62000.00,
        operator_decimal_used=0.00180000,
    )
    assert detail["check_status"] == "VARIANCE_HELD"

    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "SUSPENDED"
    assert_decimal_interest(order["pinned_decimal"], "0.00195313", "pinned_decimal")
    assert_money(order["cumulative_variance_amount"], "9.05", "cumulative_variance_amount")
