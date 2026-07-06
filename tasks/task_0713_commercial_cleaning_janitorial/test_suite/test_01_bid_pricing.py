"""Bid-estimate pricing: labor loading variants, burden build-up, proposal pricing.

Anchor figures for the STANDARD area set (two MEDIUM 10000@5/wk + one HEAVY
4000@5/wk), base_wage 1800, margin 0.20:
  ESTIMATE monthly_labor_hours = 187.66 ; LOADED = 187.62
  LOADED: labor_cost 432276, supply_cost 42000, total_cost 554042, base_bid 692553
  Proposal monthly_price = 671776 (3% volume discount on 692553).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_bid_estimate_payload, create_proposal_payload,
    setup_priced_bid, setup_draft_proposal, create_account, create_rfp,
    add_service_areas, STANDARD_AREAS, SINGLE_LIGHT_AREA,
    TEST_USERS,
)

_BID = TEST_USERS["bid_estimator_headers"]
_SALES = TEST_USERS["sales_rep_headers"]


class TestLaborLoadingVariants:
    """Difficulty rule: dual_variant_calc / load_estimate_round_then_sum_vs_sum_then_round."""

    def test_estimate_round_then_sum_monthly_hours(self, api):
        """PRD §3.4: "Under the ESTIMATE method (round-then-sum), each area's weekly
        hours is rounded to two decimal places first, and those rounded per-area
        values are summed to give the weekly total."
        PRD §3.4: "In both methods the weekly total is multiplied by 4.33 weeks per
        month and the product is rounded half up to two decimal places to give
        monthly_labor_hours."

        Design: Difficulty/dual_variant_calc/load_estimate_round_then_sum_vs_sum_then_round
        """
        acct = create_account(legal_name="Acme Towers")
        rfp = create_rfp(acct["id"], estimated_total_sqft=24000)
        add_service_areas(acct["id"], rfp["id"], STANDARD_AREAS)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"],
            create_bid_estimate_payload(loading_method="ESTIMATE"), _BID), 201)
        priced = validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        assert priced["monthly_labor_hours"] == 187.66

    def test_loaded_sum_then_round_diverges_from_estimate(self, api):
        """PRD §3.4: "Under the LOADED method (sum-then-round), the raw unrounded
        per-area weekly hours are summed first and the single weekly total is then
        rounded once to two decimal places."
        PRD §3.4: "The two methods can differ in the trailing cents of every
        downstream figure, so the method on the estimate must be honored exactly."

        Design: Difficulty/dual_variant_calc/load_estimate_round_then_sum_vs_sum_then_round
        """
        acct = create_account(legal_name="Acme Towers 2")
        rfp = create_rfp(acct["id"], estimated_total_sqft=24000)
        add_service_areas(acct["id"], rfp["id"], STANDARD_AREAS)
        est = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"],
            create_bid_estimate_payload(loading_method="ESTIMATE"), _BID), 201)
        loaded = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"],
            create_bid_estimate_payload(loading_method="LOADED"), _BID), 201)
        est_p = validate_success(api.price_bid_estimate(acct["id"], rfp["id"], est["id"], _BID), 200)
        loaded_p = validate_success(api.price_bid_estimate(acct["id"], rfp["id"], loaded["id"], _BID), 200)
        assert loaded_p["monthly_labor_hours"] == 187.62
        assert est_p["monthly_labor_hours"] != loaded_p["monthly_labor_hours"]


class TestBurdenBuildUp:
    """Difficulty rule: combinatorial_formula / burden_tier_selection_three_inputs_nonlinear."""

    def test_loaded_burden_tier_buildup_figures(self, api):
        """PRD §3.4: "otherwise if they are at most 320, the burden is 1.28; otherwise
        the burden is 1.35."
        PRD §3.4: "The labor_cost_cents is then monthly_labor_hours multiplied by that
        loaded wage, rounded half up."
        PRD §3.4: "The total_cost_cents is the direct cost plus the overhead. Finally
        the base_bid_cents is the total cost divided by the quantity one minus
        target_margin_pct, rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/burden_tier_selection_three_inputs_nonlinear
        """
        _, _, bid = setup_priced_bid(areas=STANDARD_AREAS, loading_method="LOADED",
                                     base_wage_cents=1800, target_margin_pct=0.20,
                                     legal_name="Burden Co")
        assert bid["monthly_labor_hours"] == 187.62
        assert bid["labor_cost_cents"] == 432276
        assert bid["supply_cost_cents"] == 42000
        assert bid["total_cost_cents"] == 554042
        assert bid["base_bid_cents"] == 692553

    def test_supply_cost_per_soil_rate(self, api):
        """PRD §3.4: "where LIGHT is 1.0 cent per square foot, MEDIUM is 1.5, and HEAVY
        is 3.0; that sum is rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/burden_tier_selection_three_inputs_nonlinear
        """
        _, _, bid = setup_priced_bid(areas=STANDARD_AREAS, loading_method="LOADED",
                                     legal_name="Supply Co")
        # 10000*1.5 + 10000*1.5 + 4000*3.0 = 42000 cents
        assert bid["supply_cost_cents"] == 42000


class TestProposalPricing:
    """Difficulty rule: combinatorial_formula / proposal_discount_keyed_on_bid_tier_circular_order."""

    def test_discount_keyed_on_base_bid_tier(self, api):
        """PRD §3.5: "The discount is 0.00 when base_bid_cents is below 500000 cents,
        0.03 when it is at least 500000 but below 800000 cents, and 0.05 when it is at
        least 800000 cents."
        PRD §3.5: "The monthly_price_cents is the base bid multiplied by the quantity
        one minus the discount percentage, rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/proposal_discount_keyed_on_bid_tier_circular_order
        """
        acct, rfp, bid, prop = setup_draft_proposal(areas=STANDARD_AREAS,
                                                    loading_method="LOADED",
                                                    legal_name="Disc Co")
        # base_bid 692553 is in [500000, 800000) -> 3% discount
        # round_half_up(692553 * 0.97) = 671776
        assert prop["monthly_price_cents"] == 671776

    def test_no_discount_below_first_break(self, api):
        """PRD §3.5: "The discount is 0.00 when base_bid_cents is below 500000 cents".
        PRD §3.5: "The monthly_price_cents is the base bid multiplied by the quantity
        one minus the discount percentage, rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/proposal_discount_keyed_on_bid_tier_circular_order
        """
        # A single small LIGHT area yields a base_bid well below 500000, so no discount
        # applies and monthly_price_cents equals base_bid_cents exactly.
        acct, rfp, bid, prop = setup_draft_proposal(areas=SINGLE_LIGHT_AREA,
                                                    loading_method="LOADED",
                                                    legal_name="NoDisc Co")
        assert bid["base_bid_cents"] < 500000
        assert prop["monthly_price_cents"] == bid["base_bid_cents"]


class TestPricingCornerClaims:
    """Corner section: calculations / consistency_model."""

    def test_supply_cost_correct_result(self, api):
        """PRD §3.4: "The supply_cost_cents is the sum over every service area of its
        sqft multiplied by the supply rate in cents per square foot for that area's
        soil level, where LIGHT is 1.0 cent per square foot, MEDIUM is 1.5, and HEAVY
        is 3.0; that sum is rounded half up to a whole cent."

        Design: Corner/calculations/supply_cost_per_soil_rate_correct
        """
        _, _, bid = setup_priced_bid(areas=STANDARD_AREAS, loading_method="LOADED",
                                     legal_name="Sup Co")
        assert bid["supply_cost_cents"] == 42000

    def test_price_recompute_idempotent_on_priced(self, api):
        """PRD §3.4: "Re-running pricing on an already-PRICED estimate recomputes the
        figures and leaves the status PRICED (the recompute is idempotent in state)."

        Design: Corner/calculations/bid_price_idempotent_recompute_on_priced
        """
        acct, rfp, bid = setup_priced_bid(areas=STANDARD_AREAS, loading_method="LOADED",
                                          legal_name="Idem Co")
        again = validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        assert again["status"] == "PRICED"
        assert again["base_bid_cents"] == 692553

    def test_priced_fields_immediately_visible_in_response(self, api):
        """PRD §3.4: "Pricing a bid estimate is a BidEstimator action that moves it from
        DRAFT to PRICED and computes every monetary field."
        PRD §3.4: "The total_cost_cents is the direct cost plus the overhead."

        Design: Corner/consistency_model/immediate_visibility_of_priced_fields
        """
        acct = create_account(legal_name="Imm Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=24000)
        add_service_areas(acct["id"], rfp["id"], STANDARD_AREAS)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(loading_method="LOADED"), _BID), 201)
        priced = validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        assert priced["total_cost_cents"] == 554042

    def test_default_loading_method_is_estimate(self, api):
        """PRD §3.3: "The loading_method must be either ESTIMATE or LOADED
        (ERR_INVALID_ENUM) and defaults to ESTIMATE when omitted; it picks the
        rounding order for the labor-loading variant."

        Design: Corner/entities/loading_method_default_estimate_applied
        """
        acct = create_account(legal_name="Def Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=24000)
        add_service_areas(acct["id"], rfp["id"], STANDARD_AREAS)
        # Omit loading_method entirely so the server default (ESTIMATE) applies.
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"],
            {"base_wage_cents": 1800, "target_margin_pct": 0.20}, _BID), 201)
        priced = validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        assert priced["loading_method"] == "ESTIMATE"
        assert priced["monthly_labor_hours"] == 187.66

    def test_price_empty_service_area_set_rejected(self, api):
        """PRD §3.4: "Pricing must be run against an RFP that has at least one service
        area; a price run with zero service areas on the RFP is rejected with
        ERR_SERVICE_AREA_REQUIRED."

        Design: Difficulty/boundary_precision_check/bid_price_with_empty_service_area_set_rejected
        """
        acct = create_account(legal_name="Empty Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=1000)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(loading_method="LOADED"), _BID), 201)
        res = api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID)
        validate_error(res, "ERR_SERVICE_AREA_REQUIRED")
        bid_after = validate_success(api.get_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        assert bid_after["status"] == "DRAFT"

    def test_price_zero_areas_second_assertion_status_draft(self, api):
        """PRD §3.4: "a price run with zero service areas on the RFP is rejected with
        ERR_SERVICE_AREA_REQUIRED."
        PRD §3.3: "The new BidEstimate records its rfp_id and is created in status DRAFT".

        Design: Difficulty/boundary_precision_check/bid_price_with_empty_service_area_set_rejected
        """
        acct = create_account(legal_name="Empty Co 2")
        rfp = create_rfp(acct["id"], estimated_total_sqft=1000)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(loading_method="LOADED"), _BID), 201)
        validate_error(api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID),
                       "ERR_SERVICE_AREA_REQUIRED")
        bid_after = validate_success(api.get_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        assert bid_after["status"] == "DRAFT"
