"""Derived-figure arithmetic: appraisal variants, the tonnage residue, growth constants and the risk blend."""

from test_helpers import (
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_property_dimensions,
    assert_stand_partition,
    assert_tons,
)
from test_helpers.factories import (
    CANONICAL_CRUISE_PLOTS,
    cost_appraisal_submit_payload,
    income_appraisal_submit_payload,
    market_appraisal_submit_payload,
)
from test_helpers.fixtures import (
    close_cruise,
    commit_block,
    complete_block,
    create_carbon_project,
    create_case,
    create_fund,
    create_property,
    create_stand,
    cruised_stand,
    dedicate,
    invalidate_appraisal,
    owned_tract,
    read_block,
    read_carbon_project,
    read_fund,
    read_investor_report,
    read_property,
    read_stand,
    record_cruise_plot,
    record_risk_review,
    report_hazard,
    reserve_block,
    submit_appraisal,
)

CASCADE_RIDGE = {"name": "Cascade Ridge Tract", "region_code": "WEST"}
CASCADE_INDICES = {
    "wildfire_hazard_index": 88.00,
    "insect_hazard_index": 64.00,
    "weather_hazard_index": 48.00,
}
PROJECTION_HORIZON = {
    "planned_start_date": "2029-09-30",
    "planned_end_date": "2029-12-31",
    "planned_tons": 500.00,
}
LATER_WINDOW = {
    "planned_start_date": "2032-06-01",
    "planned_end_date": "2032-09-30",
}


def _two_species_tracts(api):
    """One fund holding a loblolly tract and a douglas-fir tract, both cruised alike."""
    pine = cruised_stand(api)
    fir_tract = create_property(api, pine.fund_id, name="Fir Ridge Tract")
    fir_stand = create_stand(
        api, fir_tract["id"], stand_code="FR-01", species_code="DOUGLAS_FIR"
    )
    for plot in CANONICAL_CRUISE_PLOTS:
        record_cruise_plot(api, fir_stand["id"], **plot)
    fir_stand = close_cruise(api, fir_stand["id"])
    assert_tons(fir_stand["net_merch_tons"], 4647.12, "net_merch_tons")
    return pine, fir_stand


def _stand_with_a_reserved_and_a_committed_block(api):
    """A cruised stand carrying 500.00 reserved tons and 500.00 committed tons."""
    ctx = cruised_stand(api)
    reserved = reserve_block(api, ctx.stand_id, planned_tons=500.00)
    later = reserve_block(api, ctx.stand_id, planned_tons=500.00, **LATER_WINDOW)
    commit_block(api, later["id"])
    return ctx, reserved, later


class TestAppraisalMethodologyVariants:
    """Three methodologies price the same tract at three very different numbers."""

    def test_the_market_comparable_prices_the_whole_acreage(self, api):
        """Twelve hundred acres at 3250.00 an acre appraise at 3900000.00.

        PRD: "Under `MARKET`, the required input is `comparable_price_per_acre_usd`, and `appraised_value_usd` is the property's `total_acres` multiplied by that per-acre comparable, rounded half-up to two decimals."

        Design: Corner/calculations/appraisal_methodology_variants_diverge_on_one_property
        """
        ctx = cruised_stand(api)

        submitted = submit_appraisal(
            api, ctx.property_id, market_appraisal_submit_payload()
        )

        assert submitted["appraisal_status"] == "SUBMITTED"
        assert submitted["appraisal_methodology"] == "MARKET"
        assert_money(submitted["appraised_value_usd"], 3900000.00, "appraised_value_usd")

    def test_direct_capitalisation_prices_the_same_tract_far_lower(self, api):
        """A 210000.00 net income at 575 basis points capitalises to 3652173.91.

        PRD: "Under `INCOME`, the required inputs are `stabilized_noi_usd` and `cap_rate_bps`, and `appraised_value_usd` is `stabilized_noi_usd` divided by the quantity `cap_rate_bps` divided by 10,000 — direct capitalisation — rounded half-up to two decimals."

        Design: Corner/calculations/appraisal_methodology_variants_diverge_on_one_property
        """
        ctx = cruised_stand(api)
        submit_appraisal(api, ctx.property_id, market_appraisal_submit_payload())
        cleared = invalidate_appraisal(api, ctx.property_id)
        assert cleared["appraisal_status"] == "NONE"
        assert cleared["appraised_value_usd"] is None
        assert cleared["appraisal_methodology"] is None

        submitted = submit_appraisal(
            api, ctx.property_id, income_appraisal_submit_payload()
        )

        assert submitted["appraisal_methodology"] == "INCOME"
        assert_money(submitted["appraised_value_usd"], 3652173.91, "appraised_value_usd")

    def test_the_cost_basis_blends_bare_land_with_inventoried_timber(self, api):
        """Bare land of 1380000.00 plus 123148.68 of timber lands 2396851.32 below market.

        PRD: "Under `COST`, the required inputs are `bare_land_value_per_acre_usd` and `timber_unit_value_usd_per_ton`, and `appraised_value_usd` is the property's `total_acres` multiplied by the bare-land value per acre, plus the timber basis tonnage multiplied by the timber unit value per ton, the whole sum rounded half-up to two decimals; the timber basis tonnage is the sum of `net_merch_tons` over the property's stands whose `status` is `INVENTORIED`."

        Design: Corner/calculations/appraisal_methodology_variants_diverge_on_one_property
        """
        ctx = cruised_stand(api)
        market = submit_appraisal(
            api, ctx.property_id, market_appraisal_submit_payload()
        )
        invalidate_appraisal(api, ctx.property_id)

        cost = submit_appraisal(api, ctx.property_id, cost_appraisal_submit_payload())

        assert_money(cost["appraised_value_usd"], 1503148.68, "appraised_value_usd")
        assert_money(
            float(market["appraised_value_usd"]) - float(cost["appraised_value_usd"]),
            2396851.32,
            "methodology divergence",
        )
        assert cost["appraisal_signed_by_user_id"] is None
        assert cost["appraisal_signed_at"] is None
        assert_money(read_fund(api, ctx.fund_id)["nav_usd"], 400000.00, "nav_usd")


class TestAvailableTonsIsAFiveWayResidue:
    """Two reservations and one dedication all draw against the same pool."""

    def test_every_allocation_bucket_is_netted_out_of_the_residue(self, api):
        """Reserving 1750.00 tons and pledging 500.00 leaves 2397.12 available.

        PRD: "`available_tons` is the residue: `net_merch_tons` less `reserved_tons`, less `committed_tons`, less `dedicated_tons`, less `hbu_withdrawn_tons`, rounded half-up to two decimals."

        Design: Corner/calculations/available_tons_nets_every_allocation_bucket
        """
        ctx = owned_tract(api)
        first = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        second = reserve_block(api, ctx.stand_id, planned_tons=750.00, **LATER_WINDOW)
        project = create_carbon_project(api, ctx.property_id)

        dedication = dedicate(api, project["id"], ctx.stand_id, dedicated_tons=500.00)

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=1750.00,
            committed_tons=0.00,
            dedicated_tons=500.00,
            hbu_withdrawn_tons=0.00,
            available_tons=2397.12,
        )
        assert_tons(first["planned_tons"], 1000.00, "planned_tons")
        assert_tons(second["planned_tons"], 750.00, "planned_tons")
        assert dedication["status"] == "PENDING"
        assert dedication["permanence_end_date"] is None
        pledged = read_carbon_project(api, project["id"])
        assert_tons(pledged["dedicated_tons_total"], 500.00, "dedicated_tons_total")
        assert pledged["status"] == "DRAFT"


class TestBlockRevenueVariants:
    """The planned figure is priced at creation; the realised figure at completion."""

    def test_the_provisional_figure_prices_the_planned_tonnage_at_creation(self, api):
        """One thousand planned tons at an index of 1.05 price provisionally at 22889.55.

        PRD: "At creation the tonnage is `planned_tons` and the index is `price_index_factor`, and the result is written to `provisional_net_revenue_usd`; the provisional figure never touches fund cash."

        Design: Corner/calculations/block_revenue_uses_provisional_at_creation_and_final_at_completion
        """
        ctx = cruised_stand(api)

        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)

        assert_money(
            block["provisional_net_revenue_usd"],
            22889.55,
            "provisional_net_revenue_usd",
        )
        assert_money(block["severance_tax_usd"], 1248.45, "severance_tax_usd")
        assert block["final_net_revenue_usd"] is None
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=400000.00)

    def test_completion_reprices_on_realised_tonnage_and_index(self, api):
        """Nine hundred forty and a half tons at 0.92 realise 15858.07 beside the planned 22889.55.

        PRD: "The final revenue variant runs the identical arithmetic described above with `actual_tons` as the tonnage and `realized_price_index_factor` as the index, writing the result to `final_net_revenue_usd` and refreshing `severance_tax_usd` from that same pass."

        Design: Corner/calculations/block_revenue_uses_provisional_at_creation_and_final_at_completion
        """
        ctx = cruised_stand(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        commit_block(api, block["id"])

        completed = complete_block(api, block["id"], 940.50, 0.92)

        assert completed["status"] == "COMPLETED"
        assert_money(
            completed["final_net_revenue_usd"], 15858.07, "final_net_revenue_usd"
        )
        assert_money(completed["severance_tax_usd"], 1028.79, "severance_tax_usd")
        assert_money(
            read_block(api, block["id"])["provisional_net_revenue_usd"],
            22889.55,
            "provisional_net_revenue_usd",
        )
        assert_tons(completed["planned_tons"], 1000.00, "planned_tons")
        assert completed["voided_reason"] is None
        assert_tons(
            read_stand(api, ctx.stand_id)["net_merch_tons"], 3706.62, "net_merch_tons"
        )


class TestCompletionCreditsTheRealisedRevenueOnly:
    """Only the final variant reaches the treasury."""

    def test_only_the_final_variant_is_credited_to_the_fund(self, api):
        """Cash rises by 15858.07, not by the provisional 22889.55 nor by both.

        PRD: "`final_net_revenue_usd` is credited to both the fund's `cash_balance_usd` and its `net_operating_cash_usd`, and `cash_yield_bps` and `harvest_acceleration_required` are recomputed."

        Design: Corner/calculations/completion_credits_only_the_final_variant_to_fund_cash
        """
        ctx = cruised_stand(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        commit_block(api, block["id"])

        complete_block(api, block["id"], 940.50, 0.92)

        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(
            fund,
            cash_balance_usd=415858.07,
            net_operating_cash_usd=15858.07,
            nav_usd=415858.07,
        )
        assert_bps(fund["cash_yield_bps"], 317, "cash_yield_bps")
        assert fund["harvest_acceleration_required"] is False
        assert fund["replan_property_count"] == 0
        report = read_investor_report(api, ctx.fund_id)
        assert_tons(
            report["standing_inventory_tons"], 3706.62, "standing_inventory_tons"
        )


class TestGrowthConstantsAreKeyedBySpecies:
    """Two identically cruised stands project apart because their species differ."""

    def test_the_geometric_variant_compounds_at_the_species_percentage(self, api):
        """Three years of growth give the pine 5257.59 tons and the fir 5092.84.

        PRD: "The periodic growth percentages are 4.2 for `LOBLOLLY_PINE`, 3.1 for `DOUGLAS_FIR` and 2.4 for `NORTHERN_HARDWOOD`."

        Design: Corner/calculations/growth_percentages_are_keyed_by_species_code
        """
        pine, fir_stand = _two_species_tracts(api)

        pine_block = reserve_block(api, pine.stand_id, **PROJECTION_HORIZON)
        fir_block = reserve_block(api, fir_stand["id"], **PROJECTION_HORIZON)

        assert pine_block["years_to_start"] == 3
        assert fir_block["years_to_start"] == 3
        assert_tons(
            pine_block["projected_available_tons"],
            5257.59,
            "projected_available_tons",
        )
        assert_tons(
            fir_block["projected_available_tons"],
            5092.84,
            "projected_available_tons",
        )
        assert_money(
            pine_block["provisional_net_revenue_usd"],
            11444.77,
            "provisional_net_revenue_usd",
        )

    def test_the_linear_variant_adds_the_species_annual_increment(self, api):
        """The same horizon under mean annual increment gives 5403.12 and 5223.12.

        PRD: "Those increments are 2.1 tons per acre per year for `LOBLOLLY_PINE`, 1.6 for `DOUGLAS_FIR` and 0.9 for `NORTHERN_HARDWOOD`."

        Design: Corner/calculations/growth_percentages_are_keyed_by_species_code
        """
        pine, fir_stand = _two_species_tracts(api)

        pine_block = reserve_block(
            api, pine.stand_id, growth_variant="MAI_LINEAR", **PROJECTION_HORIZON
        )
        fir_block = reserve_block(
            api, fir_stand["id"], growth_variant="MAI_LINEAR", **PROJECTION_HORIZON
        )

        assert_tons(
            pine_block["projected_available_tons"],
            5403.12,
            "projected_available_tons",
        )
        assert_tons(
            fir_block["projected_available_tons"],
            5223.12,
            "projected_available_tons",
        )
        assert_stand_partition(
            read_stand(api, pine.stand_id),
            reserved_tons=500.00,
            available_tons=4147.12,
        )


class TestInvestorReportAppliesTheStaleHaircut:
    """A staled appraisal still carries value, twelve percent lighter."""

    def test_the_reporting_pack_carries_the_stale_appraisal_at_the_haircut(self, api):
        """A 3900000.00 appraisal gone stale reports 3432000.00 and lifts nav to 3732000.00.

        PRD: "One whose `appraisal_status` is `STALE` contributes `appraised_value_usd` multiplied by the quantity one minus twelve divided by one hundred, rounded half-up to two decimals."

        Design: Corner/calculations/investor_report_carries_a_stale_appraisal_at_the_haircut
        """
        ctx = owned_tract(api)

        staled = invalidate_appraisal(api, ctx.property_id)
        assert staled["appraisal_status"] == "STALE"

        report = read_investor_report(api, ctx.fund_id)
        assert_money(
            report["appraised_value_total_usd"],
            3432000.00,
            "appraised_value_total_usd",
        )
        assert_money(report["nav_usd"], 3732000.00, "nav_usd")
        assert_money(report["cash_balance_usd"], 300000.00, "cash_balance_usd")
        assert_bps(report["cash_yield_bps"], 0, "cash_yield_bps")
        assert report["harvest_acceleration_required"] is False
        assert report["valuation_basis_stale_count"] == 1
        assert report["owned_property_count"] == 1
        assert report["replan_property_count"] == 0

    def test_the_haircut_never_rewrites_the_stored_appraised_value(self, api):
        """The tract keeps its 3900000.00 figure and its 100000.00 cost basis.

        PRD: "Invalidating a `SIGNED` appraisal instead moves `appraisal_status` to `STALE`, which does not erase `appraised_value_usd` but subjects the property's contribution to fund net asset value to a twelve percent haircut, and recomputes `valuation_basis_stale_count`."

        Design: Corner/calculations/investor_report_carries_a_stale_appraisal_at_the_haircut
        """
        ctx = owned_tract(api)

        invalidate_appraisal(api, ctx.property_id)

        tract = read_property(api, ctx.property_id)
        assert_property_dimensions(tract, status="OWNED", appraisal_status="STALE")
        assert_money(tract["appraised_value_usd"], 3900000.00, "appraised_value_usd")
        assert_money(
            tract["acquisition_price_usd"], 100000.00, "acquisition_price_usd"
        )
        assert_tons(
            read_investor_report(api, ctx.fund_id)["standing_inventory_tons"],
            4647.12,
            "standing_inventory_tons",
        )


class TestWaterfallBreaksTheReservedClaimFirst:
    """Reserved tonnage is the cheapest claim, so it absorbs the whole shortfall."""

    def test_the_reserved_block_absorbs_the_shortfall_before_the_committed_one(self, api):
        """A 252.88-ton shortfall trims the reserved block and leaves the committed block whole.

        PRD: "is the stand's harvest blocks whose `status` is `RESERVED`, taken in ascending `created_at` order"

        Design: Corner/calculations/reserved_blocks_are_cut_before_committed_blocks
        """
        ctx, reserved, committed = _stand_with_a_reserved_and_a_committed_block(api)

        event = report_hazard(
            api,
            ctx.stand_id,
            event_type="INSECT",
            occurred_at="2026-07-25T00:00:00Z",
            damaged_tons=3900.00,
        )

        assert_tons(event["salvageable_tons"], 2145.00, "salvageable_tons")
        assert_money(event["insurance_claim_usd"], 52650.00, "insurance_claim_usd")
        assert_tons(
            event["inventory_shortfall_tons"], 252.88, "inventory_shortfall_tons"
        )
        trimmed = read_block(api, reserved["id"])
        assert_tons(trimmed["planned_tons"], 247.12, "planned_tons")
        assert trimmed["status"] == "RESERVED"
        assert trimmed["voided_reason"] is None
        untouched = read_block(api, committed["id"])
        assert_tons(untouched["planned_tons"], 500.00, "planned_tons")
        assert untouched["status"] == "COMMITTED"

    def test_only_the_cut_target_is_logged_and_the_books_rebalance(self, api):
        """One log record names the reserved block and the stand's buckets close to zero.

        PRD: "Walking the buckets in that order, the waterfall cuts each target by the lesser of the remaining shortfall and that target's own remaining tonnage, stopping as soon as the remaining shortfall reaches zero."

        Design: Corner/calculations/reserved_blocks_are_cut_before_committed_blocks
        """
        ctx, reserved, _ = _stand_with_a_reserved_and_a_committed_block(api)

        event = report_hazard(
            api,
            ctx.stand_id,
            event_type="INSECT",
            occurred_at="2026-07-25T00:00:00Z",
            damaged_tons=3900.00,
        )

        assert len(event["reallocation_log"]) == 1, (
            "the reserved block alone covered the shortfall, so one record was appended"
        )
        entry = event["reallocation_log"][0]
        assert entry["target_type"] == "HARVEST_BLOCK"
        assert entry["target_id"] == reserved["id"]
        assert_tons(entry["tons_cut"], 252.88, "tons_cut")
        assert entry["resulting_status"] == "RESERVED"
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "SALVAGE_PENDING"
        assert_stand_partition(
            stand,
            net_merch_tons=747.12,
            reserved_tons=247.12,
            committed_tons=500.00,
            available_tons=0.00,
        )
        assert_property_dimensions(
            read_property(api, ctx.property_id), harvest_plan_status="REPLAN_REQUIRED"
        )
        assert read_fund(api, ctx.fund_id)["replan_property_count"] == 1


class TestCompositeRiskCapsTheAdjustedComponents:
    """A western tract's wildfire leg is held at one hundred before it is weighted."""

    def test_the_region_adjusted_wildfire_leg_is_capped_before_weighting(self, api):
        """An index of 88.00 loaded by 1.25 enters the blend at 100.00, not 110.00.

        PRD: "The wildfire component is `wildfire_hazard_index` multiplied by the region's wildfire multiplier — 1.00 for `SOUTH`, 1.25 for `WEST`, 0.80 for `NORTHEAST` — rounded half-up to two decimals, then held down to at most 100.00."

        Design: Corner/calculations/risk_score_caps_the_region_adjusted_wildfire_index_at_one_hundred
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"], **CASCADE_RIDGE)
        create_stand(api, tract["id"], stand_code="CR-01")

        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "ACTUARIAL", **CASCADE_INDICES},
        )

        priced = read_property(api, tract["id"])
        assert_money(priced["composite_risk_score"], 79.08, "composite_risk_score")
        assert abs(float(priced["composite_risk_score"]) - 83.58) > 0.01, (
            "the uncapped wildfire leg must not have reached the blend"
        )
        assert_money(priced["wildfire_hazard_index"], 88.00, "wildfire_hazard_index")
        assert priced["market_access_tier"] == "TIER_B"

    def test_the_capped_blend_prices_the_actuarial_premium(self, api):
        """A composite of 79.08 loads the 15960.00 base to 28581.17, not 29299.37.

        PRD: "The composite score is a weighted hazard blend with two region- and species-specific adjustments, and both adjustments are capped at 100.00."

        Design: Corner/calculations/risk_score_caps_the_region_adjusted_wildfire_index_at_one_hundred
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"], **CASCADE_RIDGE)
        create_stand(api, tract["id"], stand_code="CR-01")

        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "ACTUARIAL", **CASCADE_INDICES},
        )

        priced = read_property(api, tract["id"])
        assert_money(
            priced["insurance_premium_usd"], 28581.17, "insurance_premium_usd"
        )
        assert abs(float(priced["insurance_premium_usd"]) - 29299.37) > 0.01, (
            "the uncapped blend must not have priced the policy"
        )
        assert_fund_cash(
            read_fund(api, fund["id"]),
            cash_balance_usd=371418.83,
            net_operating_cash_usd=-28581.17,
        )


class TestUnderwritingCountsInventoriedStandsOnly:
    """A stand still in cruise contributes neither tonnage nor a species key."""

    def test_only_the_inventoried_stand_feeds_the_valuation_stack(self, api):
        """The loblolly cruise alone drives a 194890.35 timber present value.

        PRD: "Only the property's stands whose `status` is `INVENTORIED` contribute: their `net_merch_tons` are summed into a base tonnage and their `acres` into a base acreage."

        Design: Corner/calculations/underwriting_base_tons_counts_only_inventoried_stands
        """
        ctx = cruised_stand(api)
        create_stand(
            api,
            ctx.property_id,
            stand_code="PC-02",
            acres=150.00,
            species_code="DOUGLAS_FIR",
        )

        case = create_case(api, ctx.property_id)

        assert_money(case["timber_pv_usd"], 194890.35, "timber_pv_usd")
        assert_money(case["pre_fee_value_usd"], 194890.35, "pre_fee_value_usd")
        assert_money(case["acquisition_fee_pct"], 1.50, "acquisition_fee_pct")
        assert_money(case["acquisition_fee_usd"], 2923.36, "acquisition_fee_usd")
        assert_money(
            case["underwritten_value_usd"], 191966.99, "underwritten_value_usd"
        )
        assert abs(float(case["timber_pv_usd"]) - 190852.86) > 0.01, (
            "the uncruised douglas-fir stand must not have keyed the growth constants"
        )

    def test_the_uncruised_stand_stays_empty_and_outside_the_stack(self, api):
        """The larger stand holds no tons and leaves the case in draft on a prospect tract.

        PRD: "Stands still `CRUISE_OPEN` (never cruised), stands in `SALVAGE_PENDING` (loss not yet settled) and stands in `DISPOSED` (sold as HBU land) are all excluded."

        Design: Corner/calculations/underwriting_base_tons_counts_only_inventoried_stands
        """
        ctx = cruised_stand(api)
        second = create_stand(
            api,
            ctx.property_id,
            stand_code="PC-02",
            acres=150.00,
            species_code="DOUGLAS_FIR",
        )

        case = create_case(api, ctx.property_id)

        uncruised = read_stand(api, second["id"])
        assert uncruised["status"] == "CRUISE_OPEN"
        assert uncruised["plot_count"] == 0
        assert_tons(uncruised["net_merch_tons"], 0.00, "net_merch_tons")
        assert case["status"] == "DRAFT"
        assert case["authored_by_user_id"] == "analyst-1"
        assert_property_dimensions(
            read_property(api, ctx.property_id), status="PROSPECT"
        )
