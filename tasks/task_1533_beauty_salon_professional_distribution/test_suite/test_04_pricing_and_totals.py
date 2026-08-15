"""Pricing engine branches and pinned order-total evaluation (PRD §3.4-§3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_salon,
    create_draft_order,
    get_order,
    list_order_line_items,
    make_brand,
    make_product,
    make_salon_buyer_headers,
    setup_salon_with_credit_points,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _gold_salon_with_products(product_specs):
    """GOLD-tier salon plus one brand and the requested products.
    product_specs: list of dicts accepted by make_product."""
    salon, consultant = create_active_salon(tier="GOLD")
    brand = make_brand()
    products = [make_product(brand["id"], **spec) for spec in product_specs]
    return salon, products


class TestLinePricingBranches:
    def test_gold_backbar_and_retail_branch_prices(self, api):
        """PRD §3.4: "First the tier discount — 0 percent for `SILVER`,
        10 percent for `GOLD`, 15 percent for `PLATINUM` — is applied to the
        base price and the result rounded half-up to integer cents."
        PRD §3.4: "Then, if the line's `variant_type` is `BACKBAR`, the
        backbar discount of 20 percent is applied to the already-rounded
        tier-adjusted value and rounded half-up again."

        Design: Difficulty/combinatorial_formula/line_pricing_tier_variant_lifecycle_branches
        """
        salon, products = _gold_salon_with_products([
            {"variant_type": "BACKBAR", "base_price_cents": 20000,
             "weight_grams": 1000},
            {"variant_type": "RETAIL", "base_price_cents": 20000,
             "weight_grams": 300},
        ])
        order = create_draft_order(salon["id"], [
            {"product_id": products[0]["id"], "quantity": 1},
            {"product_id": products[1]["id"], "quantity": 1},
        ])
        items = {it["product_id"]: it for it in list_order_line_items(order["id"])}
        assert items[products[0]["id"]]["unit_price_cents"] == 14400, (
            "BACKBAR GOLD: round(round(20000*0.9)*0.8) == 14400")
        assert items[products[1]["id"]]["unit_price_cents"] == 18000, (
            "RETAIL GOLD: round(20000*0.9) == 18000")

    def test_liquidation_branch_replaces_tier_and_backbar(self, api):
        """PRD §3.4: "When the product is in `LIQUIDATION`, the discount is a
        flat ladder off base price, and tier and backbar discounts do not
        apply at all."
        PRD §3.4: "Fewer than 14 days elapsed: 20 percent off."

        Design: Difficulty/combinatorial_formula/line_pricing_tier_variant_lifecycle_branches
        """
        salon, products = _gold_salon_with_products([
            {"variant_type": "BACKBAR", "base_price_cents": 20000,
             "weight_grams": 1000},
            {"variant_type": "RETAIL", "base_price_cents": 20000,
             "weight_grams": 300},
            {"variant_type": "RETAIL", "base_price_cents": 20000,
             "weight_grams": 300},
        ])
        liquidation_product = products[2]
        validate_success(api.transition_product_lifecycle(
            liquidation_product["id"], {"target_status": "DISCONTINUED"}, ADMIN), 200)
        validate_success(api.transition_product_lifecycle(
            liquidation_product["id"], {"target_status": "LIQUIDATION"}, ADMIN), 200)

        order = create_draft_order(salon["id"], [
            {"product_id": products[0]["id"], "quantity": 1},
            {"product_id": products[1]["id"], "quantity": 1},
        ])
        # OCC-guarded add of the liquidation line.
        validate_success(api.add_order_item(
            order["id"],
            {"product_id": liquidation_product["id"], "quantity": 1,
             "expected_order_version": order["version"]},
            make_salon_buyer_headers(salon["id"])), 201)

        items = {it["product_id"]: it for it in list_order_line_items(order["id"])}
        assert items[liquidation_product["id"]]["unit_price_cents"] == 16000, (
            "LIQUIDATION week 0: round_half_up(20000 * (1 - 0.20)) == 16000")
        refreshed = get_order(order["id"])
        assert refreshed["merchandise_total_cents"] == 48400, (
            "14400 + 18000 + 16000 == 48400")


class TestPinnedRoundingOrder:
    def test_unit_price_rounded_before_quantity_multiplication(self, api):
        """PRD §3.6: "Second, each line's `line_total_cents` is the unit price
        multiplied by the quantity as an exact integer; the alternative
        ordering (multiplying base by quantity before discounting and rounding
        once) yields different cents and is wrong."

        Design: Difficulty/combinatorial_formula/order_total_round_per_unit_then_multiply
        """
        salon, products = _gold_salon_with_products([
            {"variant_type": "RETAIL", "base_price_cents": 3333,
             "weight_grams": 100},
        ])
        order = create_draft_order(
            salon["id"], [{"product_id": products[0]["id"], "quantity": 3}])
        items = list_order_line_items(order["id"])
        assert len(items) == 1
        assert items[0]["unit_price_cents"] == 3000, (
            "round_half_up(3333 * 0.9) == 3000 (not computed on 9999)")
        assert items[0]["line_total_cents"] == 9000, (
            "3000 * 3 == 9000; the wrong order would give round(9999*0.9) == 8999")

    def test_merchandise_total_sums_rounded_line_totals(self, api):
        """PRD §3.6: "Third, `merchandise_total_cents` is the sum of
        `line_total_cents` over all items, with promotional lines contributing
        zero."

        Design: Difficulty/combinatorial_formula/order_total_round_per_unit_then_multiply
        """
        salon, products = _gold_salon_with_products([
            {"variant_type": "RETAIL", "base_price_cents": 3333,
             "weight_grams": 100},
        ])
        order = create_draft_order(
            salon["id"], [{"product_id": products[0]["id"], "quantity": 3}])
        refreshed = get_order(order["id"])
        assert refreshed["merchandise_total_cents"] == 9000
        assert refreshed["credit_applied_cents"] == 0
        assert refreshed["net_merch_cents"] == 9000


class TestCreditCapAndNetAccrualOrder:
    def _setup_salon_with_1000_points(self):
        salon, consultant, _ = setup_salon_with_credit_points(1000)
        assert salon["education_credit_points"] == 1000
        return salon

    def test_credit_redemption_exactly_at_cap_allowed(self, api):
        """PRD §3.5: "The cap is inclusive: a request landing exactly at the
        cap is allowed."

        Design: Difficulty/combinatorial_formula/credit_cap_net_accrual_evaluation_order
        """
        salon = self._setup_salon_with_1000_points()
        brand = make_brand()
        mask = make_product(brand["id"], base_price_cents=20000,
                            weight_grams=200)
        order = create_draft_order(
            salon["id"], [{"product_id": mask["id"], "quantity": 6}])
        assert order["merchandise_total_cents"] == 120000

        redeemed = validate_success(api.redeem_credits(
            order["id"], {"points": 600},
            make_salon_buyer_headers(salon["id"])), 200)
        assert redeemed["credit_applied_cents"] == 60000, (
            "600 points x 100 cents lands exactly on floor(120000 * 0.5)")
        assert redeemed["net_merch_cents"] == 60000

    def test_provisional_accrual_computed_on_net_after_credit(self, api):
        """PRD §3.9: "Note that the accrual base is `net_merch_cents`, the
        after-credit figure, not the gross merchandise total."
        PRD §3.9: "At order submit, a `PROVISIONAL_ACCRUAL` entry posts: the
        point value is the floor of `net_merch_cents` divided by 1000,
        multiplied by the tier multiplier — 1 for `SILVER`, 2 for `GOLD`, 3
        for `PLATINUM` — using the salon's tier at submit time."

        Design: Difficulty/combinatorial_formula/credit_cap_net_accrual_evaluation_order
        """
        salon = self._setup_salon_with_1000_points()
        brand = make_brand()
        mask = make_product(brand["id"], base_price_cents=20000,
                            weight_grams=200)
        order = create_draft_order(
            salon["id"], [{"product_id": mask["id"], "quantity": 6}])
        validate_success(api.redeem_credits(
            order["id"], {"points": 600},
            make_salon_buyer_headers(salon["id"])), 200)

        submitted = validate_success(api.submit_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)
        assert submitted["fulfillment_status"] == "SUBMITTED"
        assert submitted["credit_applied_cents"] == 60000
        assert submitted["net_merch_cents"] == 60000

        entries = validate_success(api.list_order_credit_entries(
            order["id"], ADMIN), 200)
        provisional = [e for e in entries
                       if e["entry_type"] == "PROVISIONAL_ACCRUAL"]
        assert len(provisional) == 1
        assert provisional[0]["points"] == 60, (
            "floor(60000/1000) * SILVER 1 == 60, computed on net not gross")

        salon_after = validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200)
        assert salon_after["education_credit_points"] == 460, (
            "1000 - 600 (redemption) + 60 (provisional) == 460")
