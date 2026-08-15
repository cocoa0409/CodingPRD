"""Freshness aging, finished goods, fulfillment order reservation errors."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_order_line,
    create_counterparty,
    create_customer,
    create_fulfillment_order,
    set_clock,
    setup_packed_batch,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["trader_headers"]
PLANNER = TEST_USERS["fulfillment_planner_headers"]


class TestFreshnessBoundary:
    def test_freshness_at_sellable_until_is_still_fresh(self, api):
        """PRD §3.9: "Freshness decays lazily, per §2.11: when the current
        server time is strictly greater than `sellable_until`, the lot's
        `lot_status` flips from `FRESH` to `STALE` at the moment it is
        read or allocated against — at exactly `sellable_until` the lot
        is still `FRESH`."
        PRD §3.9: "The lot's `sellable_until` is computed as the batch's
        `roast_completed_at` plus the product's `freshness_days` days —
        each day exactly 86,400 seconds"

        Design: Corner/calculations/freshness_at_sellable_until_is_still_fresh
        """
        # Setup clock at 2026-08-01T00:00:00Z; roast completes then; 30 days
        # freshness => sellable_until = 2026-08-31T00:00:00Z.
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_packed_batch(
            supplier_ref="SUP-FR", product_sku="P-FR",
            scheduled_green_lbs=100, actual_roasted_lbs=84, packed_lbs=84,
            freshness_days=30,
        )
        fg = ctx["fg_lot"]
        # Roast completed at 2026-08-01T00:00:00Z; +30 days = 2026-08-31T00:00:00Z
        assert fg["sellable_until"] == "2026-08-31T00:00:00Z"
        # Advance clock to exactly sellable_until; lot is still FRESH.
        set_clock("2026-08-31T00:00:00Z")
        fetched = validate_success(
            api.get_finished_goods_lot(fg["id"], PLANNER))
        assert fetched["lot_status"] == "FRESH", (
            "at exactly sellable_until the lot is still FRESH"
        )


class TestFulfillmentReservation:
    def test_stale_goods_rejected_on_reserve(self, api):
        """PRD §3.9: "Its validations run in order: first freshness —
        every referenced lot must be `FRESH` at reservation time, since
        `STALE` or `RECALLED` lots cannot be allocated, otherwise
        `ERR_STALE_GOODS`"
        PRD §2.11: "Advancing the logical clock therefore triggers
        re-evaluation on the next read of any finished goods lot."

        Design: Corner/validations/stale_goods_rejected_on_reserve
        """
        set_clock("2026-08-01T00:00:00Z")
        # Pack a 84-lb lot with freshness_days = 1 => sellable_until 2026-08-02
        ctx = setup_packed_batch(
            supplier_ref="SUP-SG", product_sku="P-SG",
            scheduled_green_lbs=100, actual_roasted_lbs=84, packed_lbs=84,
            freshness_days=1,
        )
        fg = ctx["fg_lot"]
        # Advance the clock past sellable_until
        set_clock("2026-08-03T00:00:00Z")
        customer = create_customer(ref="CUST-SG",
                                    legal_name="StaleGoods Customer")
        order = create_fulfillment_order(
            customer["id"], channel="WHOLESALE",
            requested_ship_date="2026-08-04T00:00:00Z",
        )
        add_order_line(order["id"], fg["id"], 10)
        # Reserve should fail: the lot has staled.
        resp = api.reserve_fulfillment_order(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_GOODS)

    def test_insufficient_finished_goods_rejected(self, api):
        """PRD §3.9: "then sufficiency — each line's `allocated_lbs` must
        not exceed its lot's `available_lbs` at that moment, otherwise
        `ERR_INSUFFICIENT_FINISHED_GOODS`."

        Design: Corner/validations/insufficient_finished_goods_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_packed_batch(
            supplier_ref="SUP-IFG", product_sku="P-IFG",
            scheduled_green_lbs=60, actual_roasted_lbs=50, packed_lbs=50,
        )
        fg = ctx["fg_lot"]
        customer = create_customer(ref="CUST-IFG", legal_name="IFG Cust")
        order = create_fulfillment_order(
            customer["id"], channel="WHOLESALE",
            requested_ship_date="2026-08-05T00:00:00Z",
        )
        # 100 > available 50
        add_order_line(order["id"], fg["id"], 100)
        resp = api.reserve_fulfillment_order(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FINISHED_GOODS)
