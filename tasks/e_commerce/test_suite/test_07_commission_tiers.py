"""
Test 07 -- Commission Tiers
============================
Validates tiered (marginal) commission calculation including within-tier,
cross-tier boundary, exact boundary, GMV accumulation, and precision.

Tiers:
    0 - 10,000   @ 8%
    10,000 - 50,000  @ 5%
    50,000+      @ 3%
"""

import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_cost_precision, assert_version_incremented,
    assert_order, assert_product, assert_order_invariants, assert_inventory_consistency,
    assert_shop_invariants,
    NON_EXISTENT_UUID, TEST_USERS, COMMISSION_TIERS, RESERVATION_TIMEOUT_MINUTES,
    create_order_payload, create_product_payload, create_refund_payload,
    create_and_approve_shop, create_and_list_product,
    setup_basic_order_scenario, place_and_pay_order, place_pay_and_deliver_order,
    create_paid_order, setup_shop_at_gmv, setup_shop_near_tier_boundary,
    setup_completed_order_for_refund, setup_partial_refund_scenario,
    get_shop_after, get_order_items,
)

# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_expected_commission(gmv_before: float, order_amount: float) -> float:
    """Compute expected marginal commission given current GMV and order amount.

    Uses COMMISSION_TIERS to calculate the tiered rate, splitting the order
    amount across boundaries as needed.
    """
    remaining = order_amount
    commission = 0.0
    current_gmv = gmv_before

    for tier in COMMISSION_TIERS:
        if remaining <= 0:
            break
        if current_gmv >= tier["upper"]:
            continue
        # Amount that fits in this tier
        tier_room = tier["upper"] - current_gmv
        taxable = min(remaining, tier_room)
        commission += taxable * tier["rate"]
        current_gmv += taxable
        remaining -= taxable

    return round(commission, 2)


def _deliver_and_get_order(shop_id, product_id, quantity=1):
    """Place, pay, deliver a single-product order and return the completed order."""
    items = [{"product_id": product_id, "quantity": quantity}]
    return place_pay_and_deliver_order(shop_id, items)


# ===========================================================================
# TestCommissionTiers
# ===========================================================================


class TestCommissionTiers:
    """Boundary-focused tests for marginal commission tier calculation."""

    # ---- Within single tier ------------------------------------------------

    def test_tier1_gmv_zero_order_1000(self):
        """Shop at GMV=0, order $1000 -> commission = $1000 * 0.08 = $80.00."""
        shop, product = setup_shop_at_gmv(0, product_price=1000.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        expected = _compute_expected_commission(0, 1000.00)
        assert expected == 80.00

        assert order["commission_amount"] == pytest.approx(80.00, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    def test_tier2_gmv_15000_order_1000(self):
        """Shop at GMV=15000, order $1000 -> commission = $1000 * 0.05 = $50.00."""
        shop, product = setup_shop_at_gmv(15000, product_price=1000.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        expected = _compute_expected_commission(15000, 1000.00)
        assert expected == 50.00

        assert order["commission_amount"] == pytest.approx(50.00, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    def test_tier3_gmv_60000_order_1000(self):
        """Shop at GMV=60000, order $1000 -> commission = $1000 * 0.03 = $30.00."""
        shop, product = setup_shop_at_gmv(60000, product_price=1000.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        expected = _compute_expected_commission(60000, 1000.00)
        assert expected == 30.00

        assert order["commission_amount"] == pytest.approx(30.00, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    # ---- Cross-tier boundary (the hard tests) ------------------------------

    def test_cross_tier1_tier2_gmv_9500_order_1000(self):
        """Shop at GMV=$9500, order $1000:
        $500 at 8% = $40.00, $500 at 5% = $25.00, total = $65.00.
        """
        shop, product = setup_shop_at_gmv(9500, product_price=500.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=2)
        # order total_amount = 2 * 500 = 1000
        expected = _compute_expected_commission(9500, 1000.00)
        assert expected == 65.00

        assert order["commission_amount"] == pytest.approx(65.00, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    def test_cross_tier2_tier3_gmv_49000_order_2000(self):
        """Shop at GMV=$49000, order $2000:
        $1000 at 5% = $50.00, $1000 at 3% = $30.00, total = $80.00.
        """
        shop, product = setup_shop_at_gmv(49000, product_price=2000.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        expected = _compute_expected_commission(49000, 2000.00)
        assert expected == 80.00

        assert order["commission_amount"] == pytest.approx(80.00, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    # ---- Exact boundary ----------------------------------------------------

    def test_exact_boundary_gmv_10000_order_100(self):
        """Shop at GMV exactly $10000, order $100 -> all at 5% -> $5.00."""
        shop, product = setup_shop_at_gmv(10000, product_price=100.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        expected = _compute_expected_commission(10000, 100.00)
        assert expected == 5.00

        assert order["commission_amount"] == pytest.approx(5.00, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    def test_one_cent_below_boundary_gmv_9999_order_2(self):
        """Shop at GMV=$9999, order $2:
        $1 at 8% ($0.08) + $1 at 5% ($0.05) = $0.13.
        """
        shop, product = setup_shop_at_gmv(9999, product_price=1.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=2)
        expected = _compute_expected_commission(9999, 2.00)
        assert expected == 0.13

        assert order["commission_amount"] == pytest.approx(0.13, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    def test_exact_boundary_gmv_50000_order_100(self):
        """Shop at GMV exactly $50000, order $100 -> all at 3% -> $3.00."""
        shop, product = setup_shop_at_gmv(50000, product_price=100.00)

        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        expected = _compute_expected_commission(50000, 100.00)
        assert expected == 3.00

        assert order["commission_amount"] == pytest.approx(3.00, abs=0.01)
        assert_cost_precision(order["commission_amount"])

    # ---- GMV accumulation --------------------------------------------------

    def test_gmv_accumulates_across_orders(self):
        """First order pushes GMV from 0 to X; second order calculated at X's position."""
        shop, product = setup_shop_at_gmv(0, product_price=5000.00)
        shop_id = shop["id"]
        product_id = product["id"]

        # First order: $5000 at 8% = $400
        order1 = _deliver_and_get_order(shop_id, product_id, quantity=1)
        assert order1["commission_amount"] == pytest.approx(400.00, abs=0.01)

        shop_after_1 = get_shop_after(shop_id)
        assert shop_after_1["monthly_gmv"] == pytest.approx(5000.00, abs=0.01)

        # Second order: $5000, GMV goes from 5000 to 10000, all at 8% = $400
        order2 = _deliver_and_get_order(shop_id, product_id, quantity=1)
        assert order2["commission_amount"] == pytest.approx(400.00, abs=0.01)

        shop_after_2 = get_shop_after(shop_id)
        assert shop_after_2["monthly_gmv"] == pytest.approx(10000.00, abs=0.01)

    def test_gmv_accumulates_crossing_tier(self):
        """Orders accumulate GMV across a tier boundary."""
        shop, product = setup_shop_at_gmv(0, product_price=8000.00)
        shop_id = shop["id"]
        product_id = product["id"]

        # First order: $8000 at 8% = $640
        order1 = _deliver_and_get_order(shop_id, product_id, quantity=1)
        assert order1["commission_amount"] == pytest.approx(640.00, abs=0.01)

        # Second order: $8000, GMV from 8000 to 16000
        # $2000 at 8% = $160, $6000 at 5% = $300, total = $460
        order2 = _deliver_and_get_order(shop_id, product_id, quantity=1)
        expected = _compute_expected_commission(8000, 8000.00)
        assert expected == 460.00
        assert order2["commission_amount"] == pytest.approx(460.00, abs=0.01)

        shop_after = get_shop_after(shop_id)
        assert shop_after["monthly_gmv"] == pytest.approx(16000.00, abs=0.01)
        assert_shop_invariants(shop_after)

    def test_monthly_gmv_updated_after_delivery(self):
        """shop.monthly_gmv is updated after each delivery."""
        shop, product = setup_shop_at_gmv(0, product_price=100.00)

        shop_before = get_shop_after(shop["id"])
        initial_gmv = shop_before["monthly_gmv"]

        _deliver_and_get_order(shop["id"], product["id"], quantity=1)

        shop_after = get_shop_after(shop["id"])
        assert shop_after["monthly_gmv"] == pytest.approx(initial_gmv + 100.00, abs=0.01)
        assert_shop_invariants(shop_after)

    # ---- Commission precision ----------------------------------------------

    def test_commission_precision_tier1(self):
        """All commission values have at most 2 decimal places (tier 1)."""
        shop, product = setup_shop_at_gmv(0, product_price=33.33)
        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        assert_cost_precision(order["commission_amount"])

    def test_commission_precision_cross_tier(self):
        """Commission precision maintained across tier boundaries."""
        shop, product = setup_shop_at_gmv(9999, product_price=3.00)
        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        assert_cost_precision(order["commission_amount"])

    def test_commission_precision_tier3(self):
        """All commission values have at most 2 decimal places (tier 3)."""
        shop, product = setup_shop_at_gmv(55000, product_price=77.77)
        order = _deliver_and_get_order(shop["id"], product["id"], quantity=1)
        assert_cost_precision(order["commission_amount"])
