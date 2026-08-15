"""Settlement and the alpha price adjustment: branches, floor, clamp,
provisional-vs-final divergence, final-test gate, and the shortfall cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_lab_test_payload, setup_delivered_allocation, setup_settled_allocation,
    setup_two_consecutive_shortfall_years, settle_allocation, TEST_USERS,
)

CM = TEST_USERS["contract_manager_headers"]
FM = TEST_USERS["farm_manager_headers"]
LT = TEST_USERS["lab_technician_headers"]

PREMIUM_PRICING = {
    "annual_volume_lbs": 736,
    "base_price_cents_per_lb": 500,
    "alpha_floor_pct": 12.0,
    "alpha_premium_cents_per_point": 40,
    "alpha_discount_cents_per_point": 60,
}


class TestPremiumBranch:
    def _setup_blend_1275_delivery(self, api):
        """Pellet lot qty 736 at blend 12.75 (dried 500 @ FINAL 12.0 plus dried
        300 @ FINAL 14.0), delivered against a 736-lb contract."""
        return setup_delivered_allocation(
            sources=[
                {"wet_lbs": 1875, "dried_lbs": 500, "final_alpha": 12.0},
                {"wet_lbs": 1125, "dried_lbs": 300, "final_alpha": 14.0},
            ],
            contract_overrides=dict(PREMIUM_PRICING))

    def test_settle_premium_branch(self, api, contract_manager_headers):
        """PRD §3.5: "When the delivered alpha is at or above the floor, the unit
        price is the `base_price_cents_per_lb` plus the gap times
        `alpha_premium_cents_per_point`." PRD §3.6: settlement "sets
        `settlement_total_cents` to the `delivered_lbs` times the
        `unit_price_cents`." 500 + (12.75 - 12.0) x 40 = 530; 736 x 530 = 390080.

        Design: Difficulty/combinatorial_formula/alpha_price_branch_and_floor
        """
        ctx = self._setup_blend_1275_delivery(api)
        settled = settle_allocation(ctx["allocation"]["id"])
        assert settled["status"] == "SETTLED"
        assert settled["delivered_lbs"] == 736
        assert settled["unit_price_cents"] == 530
        assert settled["settlement_total_cents"] == 390080
        assert settled["delivery_shortfall_lbs"] == 0

    def test_full_delivery_resets_shortfall_counter(self, api, contract_manager_headers):
        """PRD §3.6: "if the allocation's `shortfall_lbs` plus its
        `delivery_shortfall_lbs` exceeds zero, the contract's
        `consecutive_shortfall_years` increments by 1; otherwise the counter
        resets to 0."

        Design: Difficulty/combinatorial_formula/alpha_price_branch_and_floor
        """
        ctx = self._setup_blend_1275_delivery(api)
        settle_allocation(ctx["allocation"]["id"])
        contract = validate_success(
            api.get_contract(ctx["contract"]["id"], contract_manager_headers), 200)
        assert contract["status"] == "ACTIVE"
        assert contract["consecutive_shortfall_years"] == 0


class TestExactFloorBoundary:
    def _setup_blend_1200(self, api):
        """Pellet lot qty 736 at blend 12.00 == floor 12.0, delivered."""
        return setup_delivered_allocation(
            sources=[{"wet_lbs": 3000, "dried_lbs": 800, "final_alpha": 12.0}],
            contract_overrides=dict(PREMIUM_PRICING))

    def test_settle_at_floor_pays_base(self, api):
        """PRD §3.5: "When the alpha equals the floor exactly, the unit price
        equals the base price: no premium, no discount." 736 x 500 = 368000.

        Design: Difficulty/boundary_precision_check/alpha_exactly_at_floor_pays_base
        """
        ctx = self._setup_blend_1200(api)
        settled = settle_allocation(ctx["allocation"]["id"])
        assert settled["unit_price_cents"] == 500
        assert settled["settlement_total_cents"] == 368000

    def test_deliver_estimate_at_floor_is_base(self, api):
        """PRD §3.6: "`estimated_unit_price_cents` is the alpha price adjustment
        of §3.5 run as the provisional variant over that delivered alpha". At
        alpha == floor the provisional variant also lands on the base price.

        Design: Difficulty/boundary_precision_check/alpha_exactly_at_floor_pays_base
        """
        ctx = self._setup_blend_1200(api)
        allocation = ctx["allocation"]
        assert allocation["delivered_alpha_pct"] == 12.0
        assert allocation["estimated_unit_price_cents"] == 500


class TestDiscountBranchAndClamp:
    def test_discount_branch_result(self, api):
        """PRD §3.5: "When the delivered alpha is below the floor, the unit price
        is the base minus the shortfall times
        `alpha_discount_cents_per_point`". 500 - (12.0 - 11.0) x 60 = 440;
        736 x 440 = 323840.

        Design: Corner/calculations/alpha_discount_branch_result
        """
        ctx = setup_settled_allocation(
            sources=[{"wet_lbs": 3000, "dried_lbs": 800, "final_alpha": 11.0}],
            contract_overrides=dict(PREMIUM_PRICING))
        settled = ctx["allocation"]
        assert settled["unit_price_cents"] == 440
        assert settled["settlement_total_cents"] == 323840

    def test_min_price_floor_clamps_discount(self, api):
        """PRD §3.5: "but never less than 100 cents per pound — that floor clamps
        the discount." Raw 500 - (12.0 - 5.0) x 60 = 80 clamps to 100;
        736 x 100 = 73600.

        Design: Corner/calculations/min_price_floor_applied
        """
        ctx = setup_settled_allocation(
            sources=[{"wet_lbs": 3000, "dried_lbs": 800, "final_alpha": 5.0}],
            contract_overrides=dict(PREMIUM_PRICING))
        settled = ctx["allocation"]
        assert settled["unit_price_cents"] == 100
        assert settled["settlement_total_cents"] == 73600


class TestProvisionalVsFinalVariants:
    def _setup_pending_final_delivery(self, api):
        """Pellet lot qty 736 blending source A (PROVISIONAL 13.0, no FINAL) and
        source B (FINAL 14.0); delivered against a 736-lb contract."""
        return setup_delivered_allocation(
            sources=[
                {"wet_lbs": 1875, "dried_lbs": 500, "provisional_alpha": 13.0},
                {"wet_lbs": 1125, "dried_lbs": 300, "provisional_alpha": 14.0,
                 "final_alpha": 14.0},
            ],
            contract_overrides=dict(PREMIUM_PRICING))

    def test_deliver_computes_provisional_estimate(self, api):
        """PRD §3.6: "Two computed fields land at delivery: `delivered_alpha_pct`
        is the qty-weighted blend of the delivered lots' `blended_alpha_pct`,
        rounded half-up to 2 decimal places, and `estimated_unit_price_cents` is
        the alpha price adjustment of §3.5 run as the provisional variant over
        that delivered alpha — provisional because a pending final test can still
        move it through the regrade cascade." Blend 13.38 over floor 12.0:
        500 + 1.38 x 40 = 555.2 -> 555.

        Design: Difficulty/dual_variant_calc/allocation_price_provisional_vs_final
        """
        ctx = self._setup_pending_final_delivery(api)
        allocation = ctx["allocation"]
        assert allocation["status"] == "DELIVERED"
        assert allocation["delivered_lbs"] == 736
        assert allocation["delivered_alpha_pct"] == 13.38
        assert allocation["estimated_unit_price_cents"] == 555
        assert allocation["unit_price_cents"] is None, (
            "the final variant arrives only at settle")

    def test_variants_diverge_once_final_posts(self, api, contract_manager_headers):
        """PRD §3.6: "the formula is identical, but the alpha inputs are now
        purely final, so the result diverges from the estimate whenever a final
        differed from its provisional". The delivered-but-unsettled allocation
        reprices 555 -> 530 when source A's FINAL posts 12.0 against its
        PROVISIONAL 13.0 (blend 13.38 -> 12.75).

        Design: Difficulty/dual_variant_calc/allocation_price_provisional_vs_final
        """
        ctx = self._setup_pending_final_delivery(api)
        est_before = ctx["allocation"]["estimated_unit_price_cents"]
        assert est_before == 555
        lot_a = ctx["lots"][0]
        validate_success(api.create_lab_test(
            create_lab_test_payload(lot_a["id"], "FINAL", 12.0), LT), 201)
        after = validate_success(
            api.get_allocation(ctx["allocation"]["id"], contract_manager_headers), 200)
        assert after["delivered_alpha_pct"] == 12.75
        assert after["estimated_unit_price_cents"] == 530
        assert after["estimated_unit_price_cents"] != est_before, (
            "identical delivery data, different variant inputs, different price")


class TestFinalTestGateAtSettle:
    def test_settle_without_source_final_rejected(self, api, contract_manager_headers):
        """PRD §3.6: "Moving from `DELIVERED` to `SETTLED` requires that every
        source harvest lot of every delivered pellet lot has its `alpha_pct_final`
        posted, otherwise `ERR_FINAL_TEST_REQUIRED`."

        Design: Corner/validations/final_test_required_at_settle
        """
        ctx = setup_delivered_allocation(
            sources=[{"wet_lbs": 3000, "dried_lbs": 800, "provisional_alpha": 12.0}],
            contract_overrides=dict(PREMIUM_PRICING))
        res = api.settle_allocation(ctx["allocation"]["id"], contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_FINAL_TEST_REQUIRED)
        after = validate_success(
            api.get_allocation(ctx["allocation"]["id"], contract_manager_headers), 200)
        assert after["status"] == "DELIVERED"


class TestShortfallCascade:
    def test_first_shortfall_year_increments_without_default(
            self, api, contract_manager_headers):
        """PRD §3.6: "if the allocation's `shortfall_lbs` plus its
        `delivery_shortfall_lbs` exceeds zero, the contract's
        `consecutive_shortfall_years` increments by 1; otherwise the counter
        resets to 0." 920 lbs delivered against 2000 contracted: shortfall 1080,
        delivery shortfall 0, counter to 1. Settlement total is 920 x 500 =
        460000 at alpha 12.0 == floor 12.0.

        Design: Difficulty/transitive_cascade/shortfall_settle_defaults_contract
        """
        ids = setup_two_consecutive_shortfall_years()
        settled = settle_allocation(ids["a_first"])
        assert settled["settlement_total_cents"] == 460000
        assert settled["delivery_shortfall_lbs"] == 0
        contract = validate_success(
            api.get_contract(ids["c_id"], contract_manager_headers), 200)
        assert contract["status"] == "ACTIVE"
        assert contract["consecutive_shortfall_years"] == 1

    def test_second_consecutive_shortfall_defaults_contract(
            self, api, contract_manager_headers):
        """PRD §3.6: "When the counter reaches 2, the contract auto-transitions
        from `ACTIVE` to `DEFAULTED`: every allocation of that contract in
        `PROJECTED` or `CONFIRMED` moves to `CANCELLED`, and each such confirmed
        allocation's reserved pellet lots return from `RESERVED` to
        `AVAILABLE`."

        Design: Difficulty/transitive_cascade/shortfall_settle_defaults_contract
        """
        ids = setup_two_consecutive_shortfall_years()
        settle_allocation(ids["a_first"])
        settled_second = settle_allocation(ids["a_second"])
        assert settled_second["settlement_total_cents"] == 460000
        contract = validate_success(
            api.get_contract(ids["c_id"], contract_manager_headers), 200)
        assert contract["status"] == "DEFAULTED"
        assert contract["consecutive_shortfall_years"] == 2
        leftover = validate_success(
            api.get_allocation(ids["a_final"], contract_manager_headers), 200)
        assert leftover["status"] == "CANCELLED", (
            "the default cascade reaches the non-terminal final-year allocation")
