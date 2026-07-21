"""Submit-time validations: empty-order boundary, raw-milk safety over wholesale fiscal floor,
and the standalone wholesale minimum-order floor."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    set_clock, create_customer, create_wholesale_customer, create_product, create_cave,
    receive_lot, create_order, add_weight_line, allocate_line,
    setup_allocated_wholesale_order, make_wholesale_customer_headers, TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
CS = TEST_USERS["counter_staff_headers"]


# ─── boundary_precision_check / submit_empty_order_zero_lines ──────────────
class TestSubmitEmptyOrder:
    def test_empty_order_rejected(self, api):
        """PRD §3.5: "first, the order must have at least one line — an empty order is rejected
        with `ERR_EMPTY_ORDER`."

        Design: Difficulty/boundary_precision_check/submit_empty_order_zero_lines
        """
        customer = create_customer()
        order = create_order(customer["id"], "RETAIL")
        res = api.submit_order(order["id"], CS)
        validate_error(res, "ERR_EMPTY_ORDER")

    def test_order_stays_draft_after_rejection(self, api):
        """PRD §3.5: "**Submitting** a `DRAFT` order (by `CounterStaff`, or by a
        `WholesaleCustomer` for its own order) runs a battery of checks in a fixed priority
        order and, on success, moves the order `DRAFT → SUBMITTED` and recomputes its totals."

        Design: Difficulty/boundary_precision_check/submit_empty_order_zero_lines
        """
        customer = create_customer()
        order = create_order(customer["id"], "RETAIL")
        api.submit_order(order["id"], CS)
        reread = get_success_data(api.get_order(order["id"], CS))
        assert reread["fulfillment_status"] == "DRAFT"


# ─── priority_pair_validation_conflict / submit_rawmilk_safety_beats_wholesale_min ──
class TestRawMilkSafetyBeatsWholesaleMin:
    def _build_dual_failure_order(self, api):
        set_clock("2026-07-01T00:00:00Z")
        customer = create_wholesale_customer(name="Bistro Y", region_code="CA")
        wc = make_wholesale_customer_headers(customer["id"])
        product = create_product(name="Raw Sheep", milk_type="SHEEP", pasteurized=False,
                                 price_per_kg_cents=8000, min_aging_days=30, target_aging_days=60)
        cave = create_cave(name="Cave 10")
        lot = receive_lot(product["id"], cave["id"], 1000)
        set_clock("2026-08-10T00:00:00Z")   # +40 days: >= min 30 (READY) but < 60 legal
        api.rotate_cave(cave["id"], SM)
        order = create_order(customer["id"], "WHOLESALE", headers=wc)
        line = add_weight_line(order["id"], product["id"], 500)   # subtotal 4000 < 10000
        allocate_line(line["id"], lot["id"])
        return order

    def test_safety_error_wins_over_fiscal_error(self, api):
        """PRD §3.5: "Then the raw-milk safety check runs: no allocated lot of an unpasteurized
        product may have `aging_days` below the legal minimum of 60 days
        (`RAW_MILK_MIN_LEGAL_AGING_DAYS`); a violation is rejected with `ERR_RAW_MILK_AGING`."

        Design: Difficulty/priority_pair_validation_conflict/submit_rawmilk_safety_beats_wholesale_min
        """
        order = self._build_dual_failure_order(api)
        res = api.submit_order(order["id"], CS)
        validate_error(res, "ERR_RAW_MILK_AGING")

    def test_order_stays_draft_on_safety_rejection(self, api):
        """PRD §3.5: "Then the raw-milk safety check runs: no allocated lot of an unpasteurized
        product may have `aging_days` below the legal minimum of 60 days
        (`RAW_MILK_MIN_LEGAL_AGING_DAYS`); a violation is rejected with `ERR_RAW_MILK_AGING`."
        PRD §3.5: "Finally, for a wholesale order, the fiscal floor is enforced: the order's
        `subtotal_cents` must be at least the wholesale minimum of 10000 cents (one hundred
        dollars); a shortfall is rejected with `ERR_WHOLESALE_MIN_ORDER`."

        Design: Difficulty/priority_pair_validation_conflict/submit_rawmilk_safety_beats_wholesale_min
        """
        order = self._build_dual_failure_order(api)
        api.submit_order(order["id"], CS)
        reread = get_success_data(api.get_order(order["id"], CS))
        assert reread["fulfillment_status"] == "DRAFT"


# ─── Corner: validations / corner_submit_wholesale_below_min_standalone ────
def test_submit_wholesale_below_minimum(api):
    """PRD §3.5: "Finally, for a wholesale order, the fiscal floor is enforced: the order's
    `subtotal_cents` must be at least the wholesale minimum of 10000 cents (one hundred
    dollars); a shortfall is rejected with `ERR_WHOLESALE_MIN_ORDER`."

    Design: Corner/validations/corner_submit_wholesale_below_min_standalone
    """
    sc = setup_allocated_wholesale_order(price_per_kg_cents=3000, requested_weight_g=500,
                                         received_weight_g=1000)   # subtotal 1500 < 10000
    res = api.submit_order(sc["order"]["id"], CS)
    validate_error(res, "ERR_WHOLESALE_MIN_ORDER")
