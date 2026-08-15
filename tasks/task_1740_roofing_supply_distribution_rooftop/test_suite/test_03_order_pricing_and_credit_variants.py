"""Order pricing (tier discount, surge premium, delivery fee) and the two
credit-availability readings (PRD §2.8, §3.4)."""
from test_helpers import (
    TEST_USERS,
    assert_order,
    confirm_order,
    convert_to_order,
    create_quoted_takeoff,
    make_account,
    make_branch,
    make_job,
    make_lot,
    make_product,
    request_and_grant_allocation,
    schedule_delivery,
    setup_active_surge_event,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _order_with_delivery(*, branch_code, sku, price, bps=3.0, squares=20.0,
                         valley=0, tier="STANDARD", credit_limit=10_000_000,
                         on_hand=500, equipment="ROOFTOP_CONVEYOR",
                         slot_date="2026-08-10"):
    """QUOTED order with a delivery already scheduled (fee accrued), ready
    for confirmation."""
    branch = make_branch(branch_code)
    product = make_product(sku, price=price, bps=bps)
    make_lot(branch["id"], product["id"], on_hand=on_hand)
    account = make_account(credit_limit=credit_limit, tier=tier)
    job = make_job(account["id"])
    takeoff = create_quoted_takeoff(job["id"], product["id"], squares,
                                    0, valley)
    order = convert_to_order(takeoff["id"], branch["id"], account["id"])
    _slot, delivery = schedule_delivery(order["id"], branch["id"],
                                        slot_date=slot_date,
                                        equipment_type=equipment)
    return {"branch": branch, "product": product, "account": account,
            "job": job, "takeoff": takeoff, "order": order,
            "delivery": delivery}


class TestOrderPricingNormalVsSurgeVariant:
    def test_normal_mode_pricing_has_zero_surge_premium(self, api):
        """PRD §3.4: "fourth, `surge_premium_cents` is the subtotal times the
        active event's `surge_multiplier_pct` percent, again rounded half up,
        when the branch is in `SURGE` mode, and zero in `NORMAL` mode; and
        finally `total_cents` recomputes."
        PRD §3.4: "the resulting `total_cents`, which is the subtotal minus
        the discount plus the delivery fee plus the surge premium."

        60 bundles * 3500 = 210000 subtotal; VOLUME below the 250000 floor ->
        5% = 10500; rooftop fee 22500 + (60-40)*350 = 29500;
        total = 210000 - 10500 + 0 + 29500 = 229000.

        Design: Difficulty/dual_variant_calc/order_pricing_normal_vs_surge_variant
        """
        ctx = _order_with_delivery(branch_code="BR-N1", sku="SH-N1",
                                   price=3500, squares=20.0, valley=40,
                                   tier="VOLUME")
        confirmed = confirm_order(ctx["order"]["id"], ctx["account"]["id"])
        assert_order(confirmed)
        assert confirmed["subtotal_cents"] == 210000
        assert confirmed["discount_cents"] == 10500
        assert confirmed["surge_premium_cents"] == 0
        assert confirmed["delivery_fee_cents"] == 29500
        assert confirmed["total_cents"] == 229000

    def test_surge_mode_pricing_adds_multiplier_premium(self, api):
        """PRD §3.4: "When the branch's `surge_mode` is `SURGE`, the order
        auto-links to the branch's single active storm surge event —
        `storm_surge_event_id` is set — and each line's quantity must not
        exceed the contractor's unconsumed granted allocation for that product
        under that event, or confirmation fails with
        `ERR_SURGE_ALLOCATION_EXCEEDED`."
        PRD §3.4: "fourth, `surge_premium_cents` is the subtotal times the
        active event's `surge_multiplier_pct` percent, again rounded half up,
        when the branch is in `SURGE` mode, and zero in `NORMAL` mode; and
        finally `total_cents` recomputes."

        Same order shape as the normal-mode arm, but under an ACTIVE event at
        15%: surge premium = 210000 * 15% = 31500;
        total = 210000 - 10500 + 31500 + 29500 = 260500.

        Design: Difficulty/dual_variant_calc/order_pricing_normal_vs_surge_variant
        """
        ctx = _order_with_delivery(branch_code="BR-N2", sku="SH-N2",
                                   price=3500, squares=20.0, valley=40,
                                   tier="VOLUME")
        event = setup_active_surge_event(ctx["branch"]["id"],
                                         event_name="Hail-N2",
                                         surge_multiplier_pct=15,
                                         allocation_pool_bundles=5000)
        request_and_grant_allocation(event["id"], ctx["account"]["id"],
                                     ctx["product"]["id"], 100)
        confirmed = confirm_order(ctx["order"]["id"], ctx["account"]["id"])
        assert confirmed["subtotal_cents"] == 210000
        assert confirmed["discount_cents"] == 10500
        assert confirmed["surge_premium_cents"] == 31500
        assert confirmed["delivery_fee_cents"] == 29500
        assert confirmed["total_cents"] == 260500
        assert confirmed["storm_surge_event_id"] == event["id"]


class TestCreditAvailableVariants:
    def _confirmed_hold_scenario(self):
        branch = make_branch("BR-C1")
        product = make_product("SH-C1", price=2000, color_code="BLK")
        make_lot(branch["id"], product["id"], on_hand=500, lot_code="LOT-C")
        account = make_account(credit_limit=500_000, name="Roofer Two")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"], 20.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])
        confirm_order(order["id"], account["id"])
        return account

    def test_statement_read_excludes_pending_delivery_hold(self, api):
        """PRD §2.8: "The account statement read is the post-delivery
        position: it reports `open_balance_cents`,
        `pending_delivery_hold_cents`, and `lien_hold_cents` as they stand,
        but computes its `credit_available_cents` under the invoiced-only
        variant, leaving the pending delivery hold out of the subtraction."

        60 bundles * 2000 = 120000 confirmed but not invoiced:
        statement reports the 120000 hold yet shows 500000 available.

        Design: Difficulty/dual_variant_calc/credit_available_with_vs_without_pending_holds
        """
        account = self._confirmed_hold_scenario()
        stmt = validate_success(
            api.get_account_statement(account["id"], CREDIT))
        assert stmt["pending_delivery_hold_cents"] == 120000
        assert stmt["open_balance_cents"] == 0
        assert stmt["credit_available_cents"] == 500000

    def test_account_read_includes_pending_delivery_hold(self, api):
        """PRD §2.8: "The read-only `credit_available_cents` is the credit
        limit minus the open balance, minus the pending delivery hold, minus
        the lien hold."
        PRD §2.8: "At order confirmation time the evaluation is conservative
        and includes the pending delivery hold, so committed-but-uninvoiced
        work consumes buying power."

        The same account reads 500000 - 120000 = 380000 on the conservative
        entity reading while the statement reads 500000.

        Design: Difficulty/dual_variant_calc/credit_available_with_vs_without_pending_holds
        """
        account = self._confirmed_hold_scenario()
        stmt = validate_success(
            api.get_account_statement(account["id"], CREDIT))
        entity = validate_success(
            api.get_contractor_account(account["id"], CREDIT))
        assert entity["credit_available_cents"] == 380000
        assert stmt["credit_available_cents"] == 500000
        assert entity["credit_available_cents"] < stmt["credit_available_cents"]


class TestTierThresholdAndSurgeInteraction:
    def test_volume_eight_percent_at_threshold_with_surge(self, api):
        """PRD §3.4: "Pricing then evaluates in a pinned order, because the
        discount tier keys on the pre-discount subtotal: first `subtotal_cents`
        is the sum over lines of each `extended_price_cents`; second, the
        account's `pricing_tier` selects a discount percent — `STANDARD` pays
        full price, `PREFERRED` takes five percent, and `VOLUME` takes eight
        percent, except that `VOLUME` earns its eight percent only when the
        pre-discount subtotal reaches 250,000 cents ($2,500.00), falling back
        to the five percent `PREFERRED` rate below that floor; third,
        `discount_cents` is the subtotal times the selected percent, rounded
        half up to whole cents; fourth, `surge_premium_cents` is the subtotal
        times the active event's `surge_multiplier_pct` percent, again rounded
        half up, when the branch is in `SURGE` mode, and zero in `NORMAL`
        mode; and finally `total_cents` recomputes."

        60 bundles * 5000 = 300000 >= 250000 -> 8% = 24000; surge 15% ->
        45000; rooftop fee 60 bundles -> 29500;
        total = 300000 - 24000 + 45000 + 29500 = 350500.

        Design: Difficulty/combinatorial_formula/order_pricing_tier_threshold_and_surge_interaction
        """
        ctx = _order_with_delivery(branch_code="BR-P1", sku="SH-P1",
                                   price=5000, squares=20.0, tier="VOLUME",
                                   credit_limit=100_000_000, on_hand=1000,
                                   slot_date="2026-08-11")
        event = setup_active_surge_event(ctx["branch"]["id"],
                                         event_name="Hail-P1",
                                         surge_multiplier_pct=15,
                                         allocation_pool_bundles=5000)
        request_and_grant_allocation(event["id"], ctx["account"]["id"],
                                     ctx["product"]["id"], 100)
        confirmed = confirm_order(ctx["order"]["id"], ctx["account"]["id"])
        assert confirmed["subtotal_cents"] == 300000
        assert confirmed["discount_cents"] == 24000
        assert confirmed["surge_premium_cents"] == 45000
        assert confirmed["delivery_fee_cents"] == 29500
        assert confirmed["total_cents"] == 350500

    def test_volume_falls_back_to_five_percent_below_floor(self, api):
        """PRD §3.4: "second, the account's `pricing_tier` selects a discount
        percent — `STANDARD` pays full price, `PREFERRED` takes five percent,
        and `VOLUME` takes eight percent, except that `VOLUME` earns its eight
        percent only when the pre-discount subtotal reaches 250,000 cents
        ($2,500.00), falling back to the five percent `PREFERRED` rate below
        that floor; third, `discount_cents` is the subtotal times the selected
        percent, rounded half up to whole cents; fourth, `surge_premium_cents`
        is the subtotal times the active event's `surge_multiplier_pct`
        percent, again rounded half up, when the branch is in `SURGE` mode,
        and zero in `NORMAL` mode; and finally `total_cents` recomputes."

        60 bundles * 3500 = 210000 < 250000 -> 5% = 10500; no delivery, no
        surge: total = 210000 - 10500 = 199500.

        Design: Difficulty/combinatorial_formula/order_pricing_tier_threshold_and_surge_interaction
        """
        branch = make_branch("BR-P2")
        product = make_product("SH-P2", price=3500)
        make_lot(branch["id"], product["id"], on_hand=500)
        account = make_account(credit_limit=100_000_000, tier="VOLUME")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"], 20.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])
        confirmed = confirm_order(order["id"], account["id"])
        assert confirmed["subtotal_cents"] == 210000
        assert confirmed["discount_cents"] == 10500
        assert confirmed["surge_premium_cents"] == 0
        assert confirmed["total_cents"] == 199500


class TestRateThresholdFallback:
    def test_volume_fallback_discount_with_ground_delivery_fee(self, api):
        """PRD §3.4: "second, the account's `pricing_tier` selects a discount
        percent — `STANDARD` pays full price, `PREFERRED` takes five percent,
        and `VOLUME` takes eight percent, except that `VOLUME` earns its eight
        percent only when the pre-discount subtotal reaches 250,000 cents
        ($2,500.00), falling back to the five percent `PREFERRED` rate below
        that floor; third, `discount_cents` is the subtotal times the selected
        percent, rounded half up to whole cents; fourth, `surge_premium_cents`
        is the subtotal times the active event's `surge_multiplier_pct`
        percent, again rounded half up, when the branch is in `SURGE` mode,
        and zero in `NORMAL` mode; and finally `total_cents` recomputes."
        PRD §3.5: "A weight surcharge applies only above the heavy-load line
        of forty bundles: the surcharge is the excess over forty bundles times
        350 cents per bundle, the boundary is strict, and a delivery of
        exactly forty bundles pays no surcharge at all."

        60 bundles * 3500 = 210000 < 250000 -> discount 5% = 10500; ground
        fee 8500 + (60-40)*350 = 15500; total = 210000 - 10500 + 15500 =
        215000.

        Design: Corner/cross_cutting_layers/rate_threshold_volume_fallback_below_min_subtotal
        """
        ctx = _order_with_delivery(branch_code="BR-CC4", sku="SH-CC4",
                                   price=3500, squares=20.0, tier="VOLUME",
                                   credit_limit=100_000_000,
                                   equipment="GROUND", slot_date="2026-08-16")
        confirmed = confirm_order(ctx["order"]["id"], ctx["account"]["id"])
        assert confirmed["discount_cents"] == 10500
        assert confirmed["delivery_fee_cents"] == 15500
        assert confirmed["total_cents"] == 215000


class TestImmediateConsistency:
    def test_confirm_response_carries_computed_pricing(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.4: "The line's `unit_price_cents` is locked from the product's
        `base_price_per_bundle_cents` at that moment, and its
        `extended_price_cents` becomes the quantity times that locked price."

        15 bundles * 2000 = 30000 subtotal, no delivery, no surge: the confirm
        response itself carries status CONFIRMED, subtotal 30000, total 30000.

        Design: Corner/consistency_model/immediate_visibility_of_confirm_side_effects
        """
        branch = make_branch("BR-CM1")
        product = make_product("SH-CM1", price=2000)
        make_lot(branch["id"], product["id"], on_hand=100,
                 lot_code="LOT-CM1")
        account = make_account(name="CM1 Co")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"], 5.0, 0, 0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])
        confirmed = confirm_order(order["id"], account["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["subtotal_cents"] == 30000
        assert confirmed["total_cents"] == 30000
