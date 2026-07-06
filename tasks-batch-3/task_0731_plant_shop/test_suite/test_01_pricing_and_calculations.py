"""Pricing, order totals, delivery fee, and stock-selector correctness."""
import pytest

from test_helpers import (
    api_client, ApiErrorId,
    validate_success, validate_error, get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order, deliver,
    TEST_USERS, make_customer_headers,
)


# -----------------------------------------------------------------------------
# Difficulty Rule 2: Combinatorial formulas across different modes
# -----------------------------------------------------------------------------

class TestDeliveryFeeCombinatorial:
    """delivery_fee_calculation: base + zone + heavy(conditional) + gift, clamped."""

    def test_delivery_fee_zone_b_heavy_gift_small_cart_sums_to_1400(self, api):
        """PRD §3.3: "A heavy surcharge of 400 cents is added when at least one order
        line's plant has weight_class HEAVY, but the surcharge is waived (set to
        zero) either when the order's delivery_zone is ZONE_A or when the order's
        subtotal is at least 10000 cents; the surcharge applies only when a heavy
        line is present AND the zone is not ZONE_A AND the subtotal is strictly
        less than 10000 cents."
        PRD §3.3: "A gift surcharge of 200 cents is added when Order.gift_flag is
        true."

        Design: Difficulty/combinatorial_formula/delivery_fee_zone_heavy_gift_conditional_branch
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="carol@example.com", delivery_zone="ZONE_B")
        plant = create_plant(
            name="BigFiddleLeaf", light_tag="BRIGHT_INDIRECT", care_tag="MODERATE",
            weight_class="HEAVY", unit_price_cents=5000, warranty_days=60,
        )
        intake_stock_unit(plant["id"])
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "delivery_zone": "ZONE_B",
                "gift_flag": True,
                "lines": [{"plant_id": plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        order = validate_success(resp, expected_status=201)
        # base 500 + ZONE_B 300 + heavy 400 (heavy + non-A + subtotal<10000) + gift 200 = 1400
        assert order["delivery_fee_cents"] == 1400

    def test_delivery_fee_zone_b_heavy_gift_small_cart_records_subtotal_5000(self, api):
        """PRD §3.2: "The line's line_subtotal_cents is the line's qty multiplied by
        its unit_price_cents — an exact integer product with no per-line rounding."
        PRD §3.2: "the server stamps Order.subtotal_cents as the exact integer sum
        of all OrderLine.line_subtotal_cents".

        Design: Difficulty/combinatorial_formula/delivery_fee_zone_heavy_gift_conditional_branch
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="carol2@example.com", delivery_zone="ZONE_B")
        plant = create_plant(
            name="BigFiddleLeaf2", light_tag="BRIGHT_INDIRECT", care_tag="MODERATE",
            weight_class="HEAVY", unit_price_cents=5000, warranty_days=60,
        )
        intake_stock_unit(plant["id"])
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "delivery_zone": "ZONE_B",
                "gift_flag": True,
                "lines": [{"plant_id": plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert order["subtotal_cents"] == 5000


class TestOrderTotalRoundingOrder:
    """order_total_computation: pinned four-step order matters when redemption
    interacts with tax rounding."""

    def _customer_with_seed_delivered_order(self, email: str, driver_name: str, target_plant_name: str):
        """Register a customer, deliver a 30000-cent seed order to bootstrap 300 points
        (BRONZE lifetime). Returns (customer, target_plant)."""
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email=email, delivery_zone="ZONE_B")
        driver = create_driver(name=driver_name)
        seed_plant = create_plant(
            name=f"SeedFern-{email}", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=30000, warranty_days=30,
        )
        intake_stock_unit(seed_plant["id"])
        target_plant = create_plant(
            name=target_plant_name, light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=5000, warranty_days=30,
        )
        intake_stock_unit(target_plant["id"])
        seed = create_order(customer["id"], [(seed_plant["id"], 1)], delivery_zone="ZONE_B")
        pay_order(seed["id"], customer["id"])
        seed_delivery = dispatch_order(
            seed["id"], driver["id"], "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z"
        )
        deliver(seed_delivery["id"], driver["id"])
        return customer, target_plant

    def test_order_total_uses_pre_tax_redemption_step_order(self, api):
        """PRD §3.3: "Step two subtracts Order.applied_redemption_cents from that
        subtotal (loyalty redemption is applied before tax, as a pre-tax
        discount). Step three multiplies the discounted amount by the tax rate
        of 0.0875 and rounds the product half-up to the nearest integer cent —
        this is the single rounding step in the entire pipeline. Step four adds
        Order.delivery_fee_cents to the discounted amount and the rounded tax to
        yield Order.total_cents."

        Design: Difficulty/combinatorial_formula/order_total_rounding_order_pre_tax_redemption
        """
        customer, target_plant = self._customer_with_seed_delivered_order(
            email="dan1@example.com", driver_name="Farah1", target_plant_name="Snake1",
        )
        # subtotal=5000, redemption=300, ZONE_B, LIGHT.
        # after_redemption = 4700; tax = round_half_up(4700*0.0875)=411.25 → 411
        # delivery_fee: base(500)+ZONE_B(300)=800 → clamp-min 800
        # total = 4700 + 411 + 800 = 5911
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "delivery_zone": "ZONE_B",
                "gift_flag": False,
                "applied_redemption_cents": 300,
                "lines": [{"plant_id": target_plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert order["total_cents"] == 5911

    def test_order_total_with_redemption_records_subtotal_and_fee(self, api):
        """PRD §3.3: "Step one sums all OrderLine.line_subtotal_cents as an exact
        integer to yield the order's subtotal_cents."
        PRD §3.3: "the final delivery_fee_cents is that raw amount clamped into
        the closed range from 800 cents to 3000 cents (so any raw sum below 800
        is lifted to 800 and any raw sum above 3000 is lowered to 3000)."

        Design: Difficulty/combinatorial_formula/order_total_rounding_order_pre_tax_redemption
        """
        customer, target_plant = self._customer_with_seed_delivered_order(
            email="dan2@example.com", driver_name="Farah2", target_plant_name="Snake2",
        )
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "delivery_zone": "ZONE_B",
                "gift_flag": False,
                "applied_redemption_cents": 300,
                "lines": [{"plant_id": target_plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert order["subtotal_cents"] == 5000
        assert order["delivery_fee_cents"] == 800
        assert order["applied_redemption_cents"] == 300


# -----------------------------------------------------------------------------
# Corner: Calculations (order_total no-drift, stock selector ranking)
# -----------------------------------------------------------------------------

class TestOrderTotalCornerNoTaxDrift:

    def test_order_total_no_redemption_no_drift(self, api):
        """PRD §3.3: "Step three multiplies the discounted amount by the tax rate
        of 0.0875 and rounds the product half-up to the nearest integer cent —
        this is the single rounding step in the entire pipeline."
        PRD §3.3: "the final delivery_fee_cents is that raw amount clamped into
        the closed range from 800 cents to 3000 cents (so any raw sum below 800
        is lifted to 800 and any raw sum above 3000 is lowered to 3000)."

        Design: Corner/calculations/order_total_computation_zero_redemption_no_tax_drift
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c4@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Eight", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=8000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "delivery_zone": "ZONE_A",
                "lines": [{"plant_id": plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        order = validate_success(resp, expected_status=201)
        # subtotal=8000, after_redemption=8000, tax=round_half_up(8000*0.0875)=700
        # delivery_fee = base(500)+ZONE_A(0)=500 → min-clamp to 800
        # total = 8000 + 700 + 800 = 9500
        assert order["subtotal_cents"] == 8000
        assert order["delivery_fee_cents"] == 800
        assert order["total_cents"] == 9500


class TestSubscriptionStockSelectorRanking:

    def test_selector_picks_earlier_acquisition_date_regardless_of_insertion_order(self, api):
        """PRD §3.6: "Candidates are ranked by oldest acquisition_date ascending,
        with ties broken by oldest StockUnit.created_at ascending; the id UUID
        is never used for ordering. The oldest candidate is selected."

        Design: Corner/calculations/subscription_stock_selector_ranks_oldest_acquisition_date
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c5@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="MatchA", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=2500, warranty_days=30,
        )
        # Insert later-acquired unit first, then earlier-acquired unit.
        later = intake_stock_unit(plant["id"], acquisition_date="2026-03-30T00:00:00Z")
        earlier = intake_stock_unit(plant["id"], acquisition_date="2026-03-15T00:00:00Z")

        resp = api.create_subscription(
            {
                "customer_id": customer["id"],
                "plan_tier": "STARTER",
                "care_tag_preference": "EASY",
                "light_tag_preference": "LOW",
            },
            make_customer_headers(customer["id"]),
        )
        validate_success(resp, expected_status=201)

        # Advance past next_fulfillment_at (30 days from 2026-04-01 = 2026-05-01).
        set_clock("2026-05-05T00:00:00Z")
        r = api.scheduler_fulfill_subscriptions(TEST_USERS["manager_headers"])
        summary = validate_success(r)
        assert summary["fulfilled_count"] == 1

        earlier_su = get_success_data(api.get_stock_unit(earlier["id"], TEST_USERS["manager_headers"]))
        later_su = get_success_data(api.get_stock_unit(later["id"], TEST_USERS["manager_headers"]))
        assert earlier_su["sale_status"] == "RESERVED", "older acquisition_date must be selected first"
        assert later_su["sale_status"] == "FOR_SALE"
