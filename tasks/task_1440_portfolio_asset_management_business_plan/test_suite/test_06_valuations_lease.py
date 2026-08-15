"""Valuation drafting/confirmation (dual pricing methods, regressive dates,
OCC) and the lease-strategy rate recommendation with its supersede rule."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_valuation_fresh,
    create_and_recommend_strategy,
    create_lease_strategy_payload,
    create_valuation_payload,
    get_asset,
    get_success_data,
    setup_asset_with_noi,
    setup_base_asset,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
ANALYST = TEST_USERS["analyst"]


class TestValuationDualMethod:
    """Difficulty instance: dual_variant_calc /
    valuation_external_vs_internal_cap.

    Setup: trailing-actuals annualized NOI is exactly 30,000,000 (FY2026
    plan, 4 accepted months at RENT 3,000,000 / CAM 500,000).
    """

    def _setup(self, api):
        return setup_asset_with_noi(fiscal_year=2026, months=4)

    def test_external_appraisal_takes_value_directly(self, api):
        """PRD §3.5: "An external appraisal takes the appraiser's figure
        directly as `implied_value_cents`, ignores NOI, and leaves
        `noi_used_cents` null."

        Design: Difficulty/dual_variant_calc/valuation_external_vs_internal_cap
        """
        ctx = self._setup(api)
        ext = validate_success(api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=520000000),
            ANALYST), 201)
        assert ext["implied_value_cents"] == 520000000
        assert ext["noi_used_cents"] is None
        assert ext["status"] == "DRAFT"

    def test_internal_cap_capitalizes_trailing_noi(self, api):
        """PRD §3.5: "An internal capitalization snapshots the asset's
        `current_annualized_noi_cents` — the TRAILING_ACTUALS figure of §3.3 —
        into `noi_used_cents` at creation ... the implied value is then that
        NOI times ten thousand, divided by the cap rate in basis points,
        rounded half-up to a whole cent."
        PRD §3.5: "the same asset state generally yields a different implied
        value under the two methods."

        Design: Difficulty/dual_variant_calc/valuation_external_vs_internal_cap
        """
        ctx = self._setup(api)
        ext = validate_success(api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=520000000),
            ANALYST), 201)
        internal = validate_success(api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                     "INTERNAL_CAP", cap_rate_bps=600),
            ANALYST), 201)
        assert internal["noi_used_cents"] == 30000000, \
            "TRAILING_ACTUALS snapshot at creation"
        assert internal["implied_value_cents"] == 500000000, \
            "round_half_up(30,000,000 * 10000 / 600)"
        assert ext["implied_value_cents"] != internal["implied_value_cents"]


class TestValuationConfirm:
    def test_valuation_confirm_supersedes_prior(self, api):
        """PRD §3.5: "Confirming moves the draft to `CONFIRMED`, supersedes
        whatever valuation was previously `CONFIRMED` for that asset (that
        valuation goes to `SUPERSEDED`, terminal), sets the asset's
        `current_value_cents` to the newly implied value, bumps the asset's
        `version` by one, and recomputes the portfolio's
        `total_value_cents`."

        Design: Corner/state_machines/valuation_confirm_supersedes_prior
        """
        ctx = setup_base_asset()
        asset_id = ctx["asset"]["id"]
        v1 = get_success_data(api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST))
        v2 = get_success_data(api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-15",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=520000000), ANALYST))

        v1_confirmed = confirm_valuation_fresh(v1["id"], asset_id)
        assert v1_confirmed["status"] == "CONFIRMED"
        assert get_asset(asset_id)["current_value_cents"] == 500000000

        v2_confirmed = confirm_valuation_fresh(v2["id"], asset_id)
        assert v2_confirmed["status"] == "CONFIRMED"
        asset = get_asset(asset_id)
        assert asset["current_value_cents"] == 520000000

        valuations, _ = validate_paginated(api.list_asset_valuations(asset_id,
                                                                     ANALYST))
        by_id = {v["id"]: v for v in valuations}
        assert by_id[v1["id"]]["status"] == "SUPERSEDED", \
            "the previously CONFIRMED valuation is superseded by the new one"
        assert by_id[v2["id"]]["status"] == "CONFIRMED"

    def test_occ_valuation_confirm_stale_asset_version(self, api):
        """PRD §2.7: "Confirming a valuation (`POST
        /api/valuations/{id}/confirm`) requires `expected_asset_version`
        matching the asset's current `version`; a mismatch is rejected with
        `ERR_STALE_ASSET_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_valuation_confirm_stale_asset_version
        """
        ctx = setup_base_asset()
        asset_id = ctx["asset"]["id"]
        stale_version = ctx["asset"]["version"]
        v1 = get_success_data(api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST))
        v2 = get_success_data(api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-15",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=520000000), ANALYST))

        ok = validate_success(api.confirm_valuation(
            v1["id"], {"expected_asset_version": stale_version}, DIRECTOR), 200)
        assert ok["status"] == "CONFIRMED"

        res = api.confirm_valuation(
            v2["id"], {"expected_asset_version": stale_version}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_STALE_ASSET_VERSION)

        ok2 = confirm_valuation_fresh(v2["id"], asset_id)
        assert ok2["status"] == "CONFIRMED", "fresh version confirms cleanly"
        valuations, _ = validate_paginated(api.list_asset_valuations(asset_id,
                                                                     ANALYST))
        by_id = {v["id"]: v for v in valuations}
        assert by_id[v1["id"]]["status"] == "SUPERSEDED"

    def test_valuation_regressive_effective_date_rejected(self, api):
        """PRD §3.5: "The draft's `effective_date` must also be strictly later
        than the effective date of the asset's currently confirmed valuation,
        if one exists — a regressive or equal date is
        `ERR_VALUATION_REGRESSIVE`."

        Design: Corner/validations/valuation_regressive_effective_date_rejected
        """
        ctx = setup_base_asset()
        asset_id = ctx["asset"]["id"]
        v1 = get_success_data(api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-15",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST))
        confirm_valuation_fresh(v1["id"], asset_id)
        v2 = get_success_data(api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-10",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=520000000), ANALYST))
        asset = get_asset(asset_id)
        res = api.confirm_valuation(
            v2["id"], {"expected_asset_version": asset["version"]}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_VALUATION_REGRESSIVE)
        asset_after = get_asset(asset_id)
        assert asset_after["current_value_cents"] == 500000000, \
            "a regressive confirm must not move the asset's value"

    def test_valuation_future_and_conditional_fields_rejected(self, api):
        """PRD §3.5: "an `effective_date` that must not fall after the current
        clock date (`ERR_FUTURE_PERIOD`)".
        PRD §3.5: "`appraised_value_cents` is required when the method is
        `EXTERNAL_APPRAISAL` and forbidden otherwise; `cap_rate_bps` is
        required when the method is `INTERNAL_CAP` and forbidden otherwise —
        a missing conditional field, or a forbidden one supplied anyway, is
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/valuation_future_and_conditional_fields_rejected
        """
        ctx = setup_base_asset()
        asset_id = ctx["asset"]["id"]
        # 2026-08-02 is after the untouched default clock date 2026-08-01.
        res1 = api.create_valuation(
            create_valuation_payload(asset_id, "2026-08-02",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST)
        validate_error(res1, ApiErrorId.ERR_FUTURE_PERIOD)

        res2 = api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-01", "INTERNAL_CAP",
                                     cap_rate_bps=600,
                                     appraised_value_cents=500000000), ANALYST)
        validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST)

    def test_internal_cap_without_noi_rejected(self, api):
        """PRD §3.5: "An internal capitalization snapshots the asset's
        `current_annualized_noi_cents` — the TRAILING_ACTUALS figure of §3.3 —
        into `noi_used_cents` at creation, and when no such figure exists
        creation fails with `ERR_VALUATION_NO_NOI_EVIDENCE`".

        Design: Corner/validations/internal_cap_without_noi_rejected
        """
        ctx = setup_base_asset()  # no plan, hence no NOI evidence at all
        res = api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                     "INTERNAL_CAP", cap_rate_bps=600), ANALYST)
        validate_error(res, ApiErrorId.ERR_VALUATION_NO_NOI_EVIDENCE)

    def test_analyst_cannot_confirm_valuation(self, api):
        """PRD §4: `POST /api/valuations/{id}/confirm` authorizes
        PortfolioDirector only.
        PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/analyst_cannot_confirm_valuation
        """
        ctx = setup_base_asset()
        asset_id = ctx["asset"]["id"]
        v1 = get_success_data(api.create_valuation(
            create_valuation_payload(asset_id, "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST))
        res = api.confirm_valuation(
            v1["id"], {"expected_asset_version": ctx["asset"]["version"]},
            ANALYST)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        valuations, _ = validate_paginated(api.list_asset_valuations(asset_id,
                                                                     ANALYST))
        assert valuations[0]["status"] == "DRAFT", \
            "the Analyst drafts but cannot confirm — valuation stays DRAFT"


class TestLeaseRateRecommendation:
    """Difficulty instance: combinatorial_formula /
    lease_rate_tiered_clamp_with_boundaries."""

    def _setup(self, api):
        return setup_base_asset()

    def test_occupancy_tier_adjusts_market_rate(self, api):
        """PRD §3.5: "The market comparable is adjusted by occupancy tier:
        below 70 percent occupancy, the comparable is marked down 1000 basis
        points; at 70 up to but not including 85 percent, down 500 basis
        points; at 85 up to but not including 95 percent, it is left
        unadjusted; and at 95 through 100 percent inclusive, it is marked up
        500 basis points — the adjusted figure is the comparable times (10000
        plus the tier adjustment) divided by ten thousand, rounded half-up."

        Design: Difficulty/combinatorial_formula/lease_rate_tiered_clamp_with_boundaries
        """
        ctx = self._setup(api)
        asset_id = ctx["asset"]["id"]
        # occupancy 82 -> tier [70,85) -> -500 bps: adjusted 3000*0.95 = 2850
        s82 = create_and_recommend_strategy(asset_id, "OFFICE_SUITE", 82,
                                            2800, 3000)
        assert s82["status"] == "RECOMMENDED"
        assert s82["recommended_rate_psf_cents"] == 2850, (
            "tier [70,85): adjusted 2850; floor round(2800*0.95)=2660; "
            "ceiling round(3000*1.10)=3300; min(max(2850,2660),3300)")

    def test_tier_boundary_moves_recommendation(self, api):
        """PRD §3.5: "That adjusted market figure is then clamped between a
        floor of 95 percent of the proposed asking rate and a ceiling of 110
        percent of the market comparable, each bound computed with half-up
        rounding to a whole cent: the recommended rate is the adjusted figure
        raised to the floor when it falls short, or capped at the ceiling when
        it overshoots."

        Design: Difficulty/combinatorial_formula/lease_rate_tiered_clamp_with_boundaries
        """
        ctx = self._setup(api)
        asset_id = ctx["asset"]["id"]
        # occupancy 85 -> tier [85,95) -> unadjusted: clamp no-op at 3000
        s85 = create_and_recommend_strategy(asset_id, "RETAIL_BAY", 85,
                                            2800, 3000)
        assert s85["recommended_rate_psf_cents"] == 3000, (
            "the 82->85 boundary crosses tiers: -500bps becomes 0bps")
        # occupancy 96 -> tier [95,100] -> +500 bps: 3000*1.05 = 3150
        s96 = create_and_recommend_strategy(asset_id, "INDUSTRIAL_BAY", 96,
                                            2800, 3000)
        assert s96["recommended_rate_psf_cents"] == 3150

    def test_lease_strategy_ratify_supersedes_prior(self, api):
        """PRD §3.5: "Ratifying a strategy supersedes whatever strategy was
        previously `RATIFIED` for the same asset and space type — the older
        one moves to `SUPERSEDED` — so exactly one ratified strategy exists
        per space type at any time."

        Design: Corner/state_machines/lease_strategy_ratify_supersedes_prior
        """
        ctx = self._setup(api)
        asset_id = ctx["asset"]["id"]
        s1 = create_and_recommend_strategy(asset_id, "OFFICE_SUITE", 82,
                                           2800, 3000)
        get_success_data(api.ratify_lease_strategy(s1["id"], DIRECTOR))
        s2 = create_and_recommend_strategy(asset_id, "OFFICE_SUITE", 96,
                                           2800, 3000)
        ratified = validate_success(api.ratify_lease_strategy(s2["id"],
                                                              DIRECTOR), 200)
        assert ratified["status"] == "RATIFIED"
        strategies, _ = validate_paginated(
            api.list_asset_lease_strategies(asset_id, ANALYST))
        by_id = {s["id"]: s for s in strategies}
        assert by_id[s1["id"]]["status"] == "SUPERSEDED"
        assert by_id[s2["id"]]["status"] == "RATIFIED"
