"""Loyalty accrual, tier progression, and depth-3 delivery cascade."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order, deliver,
    TEST_USERS, make_customer_headers, make_delivery_driver_headers,
)


# -----------------------------------------------------------------------------
# Difficulty Rule 1: Dual-variant calculations — loyalty provisional vs final
# -----------------------------------------------------------------------------

class TestLoyaltyProvisionalAndFinalVariants:

    def _customer_bumped_to_silver(self, email: str) -> tuple:
        """Deliver a 50000-cent seed order at BRONZE tier → lifetime=500 → SILVER."""
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email=email, delivery_zone="ZONE_A")
        driver = create_driver(name=f"drv-{email}")
        # 50000 subtotal / 100 * BRONZE(1.0) = 500 → exactly SILVER threshold.
        seed = create_plant(
            name=f"seed-{email}", light_tag="BRIGHT_INDIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=50000, warranty_days=30,
        )
        intake_stock_unit(seed["id"], acquisition_date="2026-03-20T00:00:00Z")
        target_plant = create_plant(
            name=f"target-{email}", light_tag="BRIGHT_INDIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=5000, warranty_days=30,
        )
        intake_stock_unit(target_plant["id"], acquisition_date="2026-03-26T00:00:00Z")
        seed_order = create_order(customer["id"], [(seed["id"], 1)])
        pay_order(seed_order["id"], customer["id"])
        seed_delivery = dispatch_order(
            seed_order["id"], driver["id"], "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z"
        )
        deliver(seed_delivery["id"], driver["id"])
        return customer, driver, target_plant

    def test_second_order_stamps_provisional_at_silver(self, api):
        """PRD §3.4: "The provisional variant runs at checkout: base_points is
        the order's subtotal_cents divided by 100 and floored to an integer; the
        tier multiplier is 1.0 for BRONZE, 1.5 for SILVER, 2.0 for GOLD, and 3.0
        for PLATINUM, read from Customer.loyalty_tier as observed at checkout;
        the awarded points value is the product of base_points and the tier
        multiplier, floored after multiplication. The result is stamped to
        Order.points_provisional and appended as an ACCRUAL_PROVISIONAL row
        with delta_points equal to the awarded amount."

        Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_after_tier_flip
        """
        customer, driver, target_plant = self._customer_bumped_to_silver("alice1@example.com")
        trigger = create_order(customer["id"], [(target_plant["id"], 1)])
        # 5000 / 100 = 50 base_points; SILVER multiplier 1.5 → floor(50 * 1.5) = 75
        assert trigger["points_provisional"] == 75

    def test_ledger_records_accrual_provisional_row_at_checkout(self, api):
        """PRD §3.4: "the awarded points value is the product of base_points and
        the tier multiplier, floored after multiplication. The result is stamped
        to Order.points_provisional and appended as an ACCRUAL_PROVISIONAL row
        with delta_points equal to the awarded amount."

        Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_after_tier_flip
        """
        customer, driver, target_plant = self._customer_bumped_to_silver("alice2@example.com")
        trigger = create_order(customer["id"], [(target_plant["id"], 1)])
        # Customer is SILVER at trigger checkout → provisional = floor(5000/100*1.5) = 75.
        assert trigger["points_provisional"] == 75
        # The provisional ledger row lives on the order-scoped ledger endpoint.
        from test_helpers import validate_paginated
        r = api.get_order_loyalty_ledger(trigger["id"], make_customer_headers(customer["id"]))
        rows, meta = validate_paginated(r)
        provisional_rows = [row for row in rows if row.get("reason") == "ACCRUAL_PROVISIONAL"]
        assert len(provisional_rows) == 1
        assert provisional_rows[0]["delta_points"] == 75


# -----------------------------------------------------------------------------
# Difficulty Rule 4: Transitive cascade depth-3 on delivery
# -----------------------------------------------------------------------------

class TestDeliveryDeliverCascadeDepth3:

    def _setup_at_lifetime_450(self, email: str):
        """Deliver a 45000-cent order at BRONZE → lifetime=450 (just below SILVER).
        Returns (customer, driver, target_plant, target_stock)."""
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email=email, delivery_zone="ZONE_A")
        driver = create_driver(name=f"driver-{email}")
        seed_plant = create_plant(
            name=f"seed-{email}", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=45000, warranty_days=30,
        )
        intake_stock_unit(seed_plant["id"], acquisition_date="2026-03-25T00:00:00Z")
        seed_order = create_order(customer["id"], [(seed_plant["id"], 1)])
        pay_order(seed_order["id"], customer["id"])
        seed_delivery = dispatch_order(
            seed_order["id"], driver["id"], "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z"
        )
        deliver(seed_delivery["id"], driver["id"])
        # lifetime = 45000/100*1.0 = 450 → still BRONZE.
        target_plant = create_plant(
            name=f"target-{email}", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=5000, warranty_days=30,
        )
        target_stock = intake_stock_unit(target_plant["id"], acquisition_date="2026-03-26T00:00:00Z")
        return customer, driver, target_plant, target_stock

    def test_deliver_cascades_order_and_stock_unit(self, api):
        """PRD §3.3: "On success the delivery flips to DELIVERED, the parent order
        flips its fulfillment dimension from DISPATCHED to DELIVERED (so the
        order pair becomes DELIVERED+PAID), each OrderLine.stock_unit_id flips
        from RESERVED to SOLD".

        Design: Difficulty/transitive_cascade/delivery_deliver_cascade_depth_3_order_stock_customer
        """
        customer, driver, target_plant, target_stock = self._setup_at_lifetime_450("greta1@example.com")
        target_order = create_order(customer["id"], [(target_plant["id"], 1)])
        pay_order(target_order["id"], customer["id"])
        target_delivery = dispatch_order(
            target_order["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T11:00:00Z"
        )
        deliver(target_delivery["id"], driver["id"])

        # depth 2: Order.fulfillment_status → DELIVERED
        order_after = get_success_data(api.get_order(target_order["id"], make_customer_headers(customer["id"])))
        assert order_after["fulfillment_status"] == "DELIVERED"
        # depth 3: StockUnit.sale_status → SOLD
        stock_after = get_success_data(api.get_stock_unit(target_stock["id"], TEST_USERS["manager_headers"]))
        assert stock_after["sale_status"] == "SOLD"

    def test_deliver_cascades_customer_lifetime_to_500_and_flips_silver(self, api):
        """PRD §3.4: "loyalty_tier_evaluation reruns after every ledger append
        whose reason is an accrual. The tier moves to PLATINUM when
        lifetime_points_earned is at least 10000; otherwise to GOLD when
        lifetime_points_earned is at least 2000; otherwise to SILVER when
        lifetime_points_earned is at least 500; otherwise remains BRONZE. The
        comparisons are non-strict: exactly 500 lifetime points crosses to
        SILVER, exactly 2000 to GOLD, and exactly 10000 to PLATINUM."

        Design: Difficulty/transitive_cascade/delivery_deliver_cascade_depth_3_order_stock_customer
        """
        customer, driver, target_plant, target_stock = self._setup_at_lifetime_450("greta2@example.com")
        target_order = create_order(customer["id"], [(target_plant["id"], 1)])
        pay_order(target_order["id"], customer["id"])
        target_delivery = dispatch_order(
            target_order["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T11:00:00Z"
        )
        deliver(target_delivery["id"], driver["id"])

        customer_after = get_success_data(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
        assert customer_after["lifetime_points_earned"] == 500
        assert customer_after["loyalty_tier"] == "SILVER"


# -----------------------------------------------------------------------------
# Difficulty Rule 9: Compensating-action invariants — cancel preserves ledger sum
# -----------------------------------------------------------------------------

class TestOrderCancelCompensatingReversal:

    def test_cancel_paid_order_appends_reversal_zeroing_points_balance(self, api):
        """PRD §3.4: "A REVERSAL row is appended in two situations. The first is
        order cancellation, which appends a REVERSAL with delta_points equal to
        the negation of Order.points_provisional (preserving the customer's
        total-ledger invariant)."
        PRD §3.4: "Customer.points_balance is the sum of delta_points across
        every ledger row for that customer".

        Design: Difficulty/compensating_invariant/order_cancel_preserves_customer_points_balance_invariant
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="vera1@example.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Basil", light_tag="DIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=8000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        assert order["points_provisional"] == 80, "8000/100 * BRONZE(1.0) = 80"
        pay_after = get_success_data(api.pay_order(order["id"], make_customer_headers(customer["id"])))
        # Cancel with fresh version.
        r = api.cancel_order(
            order["id"],
            {"expected_order_version": pay_after["version"]},
            make_customer_headers(customer["id"]),
        )
        validate_success(r)
        customer_after = get_success_data(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
        assert customer_after["points_balance"] == 0

    def test_cancel_paid_order_credits_full_total_to_wallet(self, api):
        """PRD §3.2: "In both paths, if payment_status was PAID at the time of
        cancel, the payment dimension flips to REFUNDED and
        Customer.wallet_credit_cents is increased by Order.total_cents."

        Design: Difficulty/compensating_invariant/order_cancel_preserves_customer_points_balance_invariant
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="vera2@example.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Basil2", light_tag="DIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=8000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        total_at_create = order["total_cents"]
        # subtotal=8000, no redemption, tax=round_half_up(8000*0.0875)=700
        # fee = base 500 + ZONE_A 0 = 500 → clamp 800; total = 8000+700+800 = 9500
        assert total_at_create == 9500
        pay_after = get_success_data(api.pay_order(order["id"], make_customer_headers(customer["id"])))
        validate_success(api.cancel_order(
            order["id"],
            {"expected_order_version": pay_after["version"]},
            make_customer_headers(customer["id"]),
        ))
        customer_after = get_success_data(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
        assert customer_after["wallet_credit_cents"] == 9500
