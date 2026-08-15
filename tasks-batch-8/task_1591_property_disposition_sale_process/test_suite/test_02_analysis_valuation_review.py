"""Hold/sell valuation, recommendation band, segregated review loop, listing
analysis gates, and OCC on superseding analysis creates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    alpha_asset_payload,
    create_analysis,
    create_analysis_payload,
    create_asset,
    decide_analysis,
    gamma_asset_payload,
    get_asset,
    make_analyst_headers,
    make_ic_headers,
    submit_analysis,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]
ANALYST = TEST_USERS["analyst_headers"]
IC = TEST_USERS["ic_headers"]


class TestValuationVariants:
    def test_hold_sell_dcf_variant_literal(self, api):
        """PRD: "`hold_value_direct_cap_cents` is the asset's `noi_cents` scaled
        by ten thousand and divided by `cap_rate_bps`, rounded half up to whole
        cents."
        PRD: "`hold_value_dcf_cents` is then the sum of each hold year's NOI
        discounted back at the rate implied by `discount_rate_bps` for that
        number of years, plus the terminal value discounted for the full
        horizon, with a single round-half-up applied at the very end."
        PRD: "`hold_value_cents` is whichever variant `selected_method` names"
        PRD: "the recommendation is `SELL` when one hundred times
        `sell_net_cents` is greater than or equal to one hundred five times
        `hold_value_cents`"

        Design: Corner/calculations/hold_sell_dcf_variant_literal
        """
        asset = create_asset(alpha_asset_payload())
        analysis = create_analysis(asset["id"], selected_method="DCF")

        assert analysis["hold_value_direct_cap_cents"] == 4_545_454_545
        assert analysis["hold_value_dcf_cents"] == 4_472_790_059
        assert analysis["hold_value_cents"] == 4_472_790_059, \
            "DCF variant selected"
        assert analysis["sell_net_cents"] == 5_000_000_000
        assert analysis["value_gap_cents"] == 527_209_941
        assert analysis["recommendation"] == "SELL"

    def test_recommendation_hysteresis_band_boundaries(self, api):
        """PRD: "The `recommendation` applies a hysteresis band using integer
        cross-multiplication with inclusive boundaries: the recommendation is
        `SELL` when one hundred times `sell_net_cents` is greater than or equal
        to one hundred five times `hold_value_cents`; it is `HOLD` when one
        hundred times `sell_net_cents` is less than or equal to ninety-five
        times `hold_value_cents`; otherwise it is `MARGINAL`."

        Design: Corner/calculations/recommendation_hysteresis_band_boundaries
        """
        # Round-number asset: direct-cap hold value is exactly 2,000,000,000.
        asset = create_asset(gamma_asset_payload())
        common = dict(cap_rate_bps=500, discount_rate_bps=800,
                      exit_cap_rate_bps=600, hold_years=5,
                      selected_method="DIRECT_CAP", est_selling_costs_cents=0)

        a1 = create_analysis(asset["id"], est_sale_price_cents=2_100_000_000,
                             **common)
        assert a1["hold_value_cents"] == 2_000_000_000
        assert a1["recommendation"] == "SELL", "sell_net at exactly 105% of hold"

        a2 = create_analysis(asset["id"], est_sale_price_cents=1_900_000_000,
                             **common)
        assert a2["recommendation"] == "HOLD", "sell_net at exactly 95% of hold"

        a3 = create_analysis(asset["id"], est_sale_price_cents=2_000_000_000,
                             **common)
        assert a3["recommendation"] == "MARGINAL", \
            "sell_net at exactly 100% of hold sits inside the band"


class TestReviewLoop:
    def test_analysis_decide_from_draft_rejected(self, api):
        """PRD: "The generic state-machine guard comes fifth: invoking a
        transition on an entity that is not in one of that transition's
        from-states — including any write aimed at an entity in a terminal
        state — yields `ERR_INVALID_STATE_TRANSITION`."
        PRD: "The creator — and only the creator — submits it, moving `DRAFT`
        to `SUBMITTED`"

        Design: Corner/state_machines/analysis_decide_from_draft_rejected
        """
        asset = create_asset(gamma_asset_payload())
        analysis = create_analysis(asset["id"], est_sale_price_cents=2_200_000_000,
                                   est_selling_costs_cents=0, cap_rate_bps=500)
        resp = api.decide_analysis(analysis["id"], "APPROVE", IC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_analysis_creator_cannot_decide_sod(self, api):
        """PRD: "The member of the `InvestmentCommittee` who decides a hold/sell
        analysis must not be the `AssetAnalyst` who created it."
        PRD: "the decider must differ from `created_by_user_id`, or the decision
        is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/analysis_creator_cannot_decide_sod
        """
        asset = create_asset(gamma_asset_payload())
        analysis = create_analysis(asset["id"], est_sale_price_cents=2_200_000_000,
                                   est_selling_costs_cents=0, cap_rate_bps=500)
        submit_analysis(analysis["id"], ANALYST)
        # Correct role, but the same X-User-ID as the creator.
        resp = api.decide_analysis(analysis["id"], "APPROVE",
                                   make_ic_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_rbac_committee_exclusive_decide(self, api):
        """PRD: "A request whose role is not authorized for the targeted
        operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD Endpoint Definitions: the committee decide operation is authorized
        for `InvestmentCommittee` only.

        Design: Corner/rbac/rbac_committee_exclusive_decide
        """
        asset = create_asset(gamma_asset_payload())
        analysis = create_analysis(asset["id"], est_sale_price_cents=2_200_000_000,
                                   est_selling_costs_cents=0, cap_rate_bps=500)
        submit_analysis(analysis["id"], ANALYST)
        # AssetAnalyst role is not authorized to decide, even as another user.
        resp = api.decide_analysis(analysis["id"], "APPROVE",
                                   make_analyst_headers("analyst-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestListingAnalysisGates:
    def test_err_analysis_not_approved_then_hold_recommended(self, api):
        """PRD: "the asset's latest non-`SUPERSEDED` HoldSellAnalysis must be
        `APPROVED` (`ERR_ANALYSIS_NOT_APPROVED`), that analysis's
        `recommendation` must not be `HOLD` (`ERR_HOLD_RECOMMENDED`), and an
        `ACTIVE` BrokerEngagement must exist (`ERR_NO_ACTIVE_ENGAGEMENT`)."

        Design: Corner/errors/err_analysis_not_approved_then_hold_recommended
        """
        asset = create_asset(gamma_asset_payload())
        err1 = validate_error(api.list_asset_for_sale(asset["id"], DM),
                              ApiErrorId.ERR_ANALYSIS_NOT_APPROVED)
        assert err1["error_id"] == "ERR_ANALYSIS_NOT_APPROVED"

        # sell_net exactly 95% of hold 2,000,000,000 -> recommendation HOLD.
        analysis = create_analysis(asset["id"], cap_rate_bps=500,
                                   est_sale_price_cents=1_900_000_000,
                                   est_selling_costs_cents=0)
        submit_analysis(analysis["id"], ANALYST)
        decided = decide_analysis(analysis["id"], "APPROVE", IC)
        assert decided["recommendation"] == "HOLD"

        validate_error(api.list_asset_for_sale(asset["id"], DM),
                       ApiErrorId.ERR_HOLD_RECOMMENDED)

    def test_err_no_active_engagement(self, api):
        """PRD: "the asset's latest non-`SUPERSEDED` HoldSellAnalysis must be
        `APPROVED` (`ERR_ANALYSIS_NOT_APPROVED`), that analysis's
        `recommendation` must not be `HOLD` (`ERR_HOLD_RECOMMENDED`), and an
        `ACTIVE` BrokerEngagement must exist (`ERR_NO_ACTIVE_ENGAGEMENT`)."

        Design: Corner/errors/err_no_active_engagement
        """
        asset = create_asset(gamma_asset_payload())
        analysis = create_analysis(asset["id"], cap_rate_bps=500,
                                   est_sale_price_cents=2_200_000_000,
                                   est_selling_costs_cents=0)
        submit_analysis(analysis["id"], ANALYST)
        decided = decide_analysis(analysis["id"], "APPROVE", IC)
        assert decided["recommendation"] == "SELL"

        validate_error(api.list_asset_for_sale(asset["id"], DM),
                       ApiErrorId.ERR_NO_ACTIVE_ENGAGEMENT)


class TestOccOnAnalysisCreate:
    def test_occ_analysis_create_stale_version(self, api):
        """PRD: "If `expected_asset_version` does not match the asset's current
        `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD: "A successful creation computes and permanently freezes the
        valuation on the analysis row, marks any existing `DRAFT` or `SUBMITTED`
        analysis of the same asset `SUPERSEDED`, bumps the asset's `version`
        and `updated_at`"
        PRD: "Any mutation refreshes `updated_at` and increments `version`"

        Design: Corner/cross_cutting_layers/occ_analysis_create_stale_version
        """
        asset = create_asset(gamma_asset_payload())
        v0 = asset["version"]

        common = dict(cap_rate_bps=500, discount_rate_bps=800,
                      exit_cap_rate_bps=600, hold_years=5,
                      selected_method="DIRECT_CAP", est_selling_costs_cents=0)
        a1 = create_analysis(asset["id"], expected_asset_version=v0,
                             est_sale_price_cents=2_200_000_000, **common)
        assert a1["status"] == "DRAFT"

        # Second create carrying the pre-first-create version is stale.
        resp = api.create_analysis(
            create_analysis_payload(asset["id"], v0,
                                    est_sale_price_cents=2_300_000_000, **common),
            make_analyst_headers("analyst-2"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        v1 = get_asset(asset["id"])["version"]
        assert v1 == v0 + 1, "one successful superseding create bumps version by 1"

        # Fresh retry succeeds and supersedes the first DRAFT.
        a2 = create_analysis(asset["id"], expected_asset_version=v1,
                             creator=make_analyst_headers("analyst-2"),
                             est_sale_price_cents=2_300_000_000, **common)
        assert a2["status"] == "DRAFT"

        analyses = validate_success(api.list_asset_analyses(asset["id"], DM))
        assert len(analyses) == 2
        assert analyses[0]["id"] == a1["id"]
        assert analyses[0]["status"] == "SUPERSEDED"
        assert analyses[1]["id"] == a2["id"]
        assert analyses[1]["status"] == "DRAFT"

        v2 = get_asset(asset["id"])["version"]
        assert v2 == v1 + 1
