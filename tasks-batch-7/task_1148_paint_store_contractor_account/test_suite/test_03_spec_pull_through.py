"""Spec pull-through: ordered-basis vs delivered-basis divergence (PRD §3.5)
and bulletin-driven spec cascade assertions."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_spec_line,
    create_publish_bulletin,
    create_spec_sheet_with_line,
    get_first_spec_line,
    place_and_pay_order,
    schedule_delivery,
    dispatch_delivery,
    deliver_delivery,
    set_logical_clock,
    setup_account_job_product,
    setup_approved_spec_with_line,
    submit_spec_sheet,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
WRITER = TEST_USERS["spec_writer_headers"]


def _setup_divergence_scenario(api):
    """APPROVED sheet specifying 10 units; a 6-unit order paid but never
    delivered, and a 4-unit order paid and fully delivered."""
    account, _, job, product = setup_account_job_product(
        company_name="Pull Co", credit_limit_cents=100_000_000,
        jurisdiction_code="OR-OPEN", jurisdiction_name="Oregon Open",
        job_name="Tower", sku="P-PT-1", product_name="Spec Flat",
        list_price_cents=100_000)
    sheet, line = setup_approved_spec_with_line(
        product["id"], project_code="PRJ-PT", specified_qty=10)
    order1 = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 6,
          "spec_line_id": line["id"]}],
        headers=ASSOCIATE)
    order2 = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 4,
          "spec_line_id": line["id"]}],
        headers=ASSOCIATE)
    delivery2 = schedule_delivery(order2["id"], job["id"],
                                  window_start="2026-06-10T09:00:00Z",
                                  window_end="2026-06-10T10:00:00Z")
    dispatch_delivery(delivery2["id"])
    return sheet, line, order1, order2, delivery2


def test_pull_through_ordered_basis_counts_paid_orders(api):
    """PRD §3.5: "Each spec line tracks two computed counters: `ordered_qty`,
    the sum of `quantity` minus `returned_quantity` over order lines
    referencing it whose order's `payment_status` is `PAID` or
    `PARTIALLY_REFUNDED`, and `delivered_qty`, the same sum over order lines
    whose order's `fulfillment_status` is `DELIVERED`. Each sheet reports two
    percentages, each computed over its current lines and each zero when the
    sheet has no lines: `pull_through_ordered_pct` takes, per line, the
    smaller of `ordered_qty` and `specified_qty`, sums those capped values,
    divides by the sum of `specified_qty`, multiplies by 100, and rounds half
    up to 2 decimal places; `pull_through_delivered_pct` has exactly the same
    shape with `delivered_qty` in place of `ordered_qty`. The ordered basis
    reports commitments made; the delivered basis reports final fulfillment,
    and for identical order data the two variants diverge whenever a paid
    order has not yet been delivered."

    Two paid orders of 6 + 4 units against a 10-unit line give ordered_qty
    10 and an ordered basis of 100.0 even before any delivery lands.

    Design: Difficulty/dual_variant_calc/pull_through_ordered_vs_delivered_divergence
    """
    sheet, line, _, _, delivery2 = _setup_divergence_scenario(api)
    deliver_delivery(delivery2["id"])
    line_after = validate_success(api.get_spec_line(line["id"], WRITER))
    assert_spec_line(line_after)
    assert line_after["ordered_qty"] == 10, (
        f"both paid orders count toward the ordered basis (6 + 4), "
        f"got {line_after['ordered_qty']}")
    sheet_after = validate_success(api.get_spec_sheet(sheet["id"], WRITER))
    assert sheet_after["pull_through_ordered_pct"] == pytest.approx(100.0, abs=0.001), (
        f"min(6,10) + min(4,10) over 10 = 100.0, "
        f"got {sheet_after['pull_through_ordered_pct']}")


def test_pull_through_delivered_basis_counts_only_delivered(api):
    """PRD §3.5: "The ordered basis reports commitments made; the delivered
    basis reports final fulfillment, and for identical order data the two
    variants diverge whenever a paid order has not yet been delivered. Both
    are recomputed whenever a contributing event lands: an order payment, a
    return, a delivery completion, or a spec-line replacement touching a
    referenced line."

    With the 6-unit order paid but never delivered and the 4-unit order
    delivered, delivered_qty is 4 and the delivered basis is 40.0 — diverging
    from the 100.0 ordered basis.

    Design: Difficulty/dual_variant_calc/pull_through_ordered_vs_delivered_divergence
    """
    sheet, line, _, _, delivery2 = _setup_divergence_scenario(api)
    deliver_delivery(delivery2["id"])
    line_after = validate_success(api.get_spec_line(line["id"], WRITER))
    assert line_after["delivered_qty"] == 4, (
        f"only the delivered order counts toward the delivered basis, "
        f"got {line_after['delivered_qty']}")
    sheet_after = validate_success(api.get_spec_sheet(sheet["id"], WRITER))
    assert sheet_after["pull_through_delivered_pct"] == pytest.approx(40.0, abs=0.001), (
        f"min(4,10) over 10 = 40.0, got {sheet_after['pull_through_delivered_pct']}")
    assert sheet_after["pull_through_delivered_pct"] != \
        sheet_after["pull_through_ordered_pct"], (
            "the two variants must diverge while a paid order is not yet delivered")
