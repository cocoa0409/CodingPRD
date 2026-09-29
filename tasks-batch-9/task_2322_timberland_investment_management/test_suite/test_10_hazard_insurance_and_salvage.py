"""Hazard review: the two insurance rating bases and the inventory-loss waterfall."""

from test_helpers import (
    assert_fund_cash,
    assert_money,
    assert_property_dimensions,
    assert_reallocation_entry,
    assert_stand_partition,
    assert_tons,
)
from test_helpers.factories import CANONICAL_CRUISE_PLOTS
from test_helpers.fixtures import (
    close_cruise,
    create_fund,
    create_property,
    create_stand,
    owned_tract,
    read_block,
    read_fund,
    read_hazard_event,
    read_property,
    read_stand,
    record_cruise_plot,
    record_risk_review,
    report_hazard,
    reserve_block,
    settle_hazard,
)

BIG_THICKET_PROPERTY = {
    "name": "Big Thicket Tract",
    "total_acres": 2000.00,
    "region_code": "SOUTH",
    "insured_value_usd": 4200000.00,
}
BIG_THICKET_STAND = {"stand_code": "BT-01", "acres": 1860.00}
HAZARD_INDICES = {
    "wildfire_hazard_index": 72.00,
    "insect_hazard_index": 64.00,
    "weather_hazard_index": 48.00,
}
SETTLED_CLAIM_USD = 310500.00
TOTAL_LOSS_TONS = 4647.12


def _insured_tract_with_a_settled_claim(api):
    """One insured tract carrying a single settled wildfire claim inside the trailing window."""
    fund = create_fund(api)
    tract = create_property(api, fund["id"], **BIG_THICKET_PROPERTY)
    stand = create_stand(api, tract["id"], **BIG_THICKET_STAND)
    for plot in CANONICAL_CRUISE_PLOTS:
        record_cruise_plot(api, stand["id"], **plot)
    stand = close_cruise(api, stand["id"])
    assert_tons(stand["net_merch_tons"], 72030.36, "net_merch_tons")

    event = report_hazard(
        api,
        stand["id"],
        event_type="WILDFIRE",
        occurred_at="2026-07-01T00:00:00Z",
        damaged_tons=23000.00,
    )
    settled = settle_hazard(api, event["id"], SETTLED_CLAIM_USD, 8050.00)
    return fund, tract, stand, settled


class TestInsuranceRatingBasesDiverge:
    """The same hazard indices price two very different policies."""

    def test_the_actuarial_basis_loads_the_base_premium_by_the_composite_hazard(self, api):
        """A composite of 66.48 lifts the 15960.00 base premium to 26570.21.

        PRD: "Under `ACTUARIAL`, where no credible claim history exists, the premium loads the base by the composite hazard: it is the base premium multiplied by the quantity one plus `composite_risk_score` divided by one hundred, rounded half-up to two decimals, and then floored at one thousand five hundred dollars, `insurance_premium_usd` taking whichever of the two is greater."

        Design: Difficulty/dual_variant_calc/insurance_premium_actuarial_vs_experience_rated_diverges
        """
        _, tract, _, _ = _insured_tract_with_a_settled_claim(api)

        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "ACTUARIAL", **HAZARD_INDICES},
        )

        priced = read_property(api, tract["id"])
        assert priced["insurance_rating_basis"] == "ACTUARIAL"
        assert_money(priced["composite_risk_score"], 66.48, "composite_risk_score")
        assert_money(priced["insurance_premium_usd"], 26570.21, "insurance_premium_usd")

    def test_the_experience_rated_basis_prices_off_realised_losses_instead(self, api):
        """A loss ratio of 0.0739 on the same indices prices the policy at 17139.44.

        PRD: "Under `EXPERIENCE_RATED`, the composite score is ignored entirely and the loading comes from realised losses: the loss ratio is the trailing settled claims divided by `insured_value_usd`, rounded half-up to four decimals, and the premium is the base premium multiplied by the quantity one plus that loss ratio, rounded half-up to two decimals, again floored at one thousand five hundred dollars."

        Design: Difficulty/dual_variant_calc/insurance_premium_actuarial_vs_experience_rated_diverges
        """
        _, tract, _, _ = _insured_tract_with_a_settled_claim(api)

        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "EXPERIENCE_RATED", **HAZARD_INDICES},
        )

        priced = read_property(api, tract["id"])
        assert priced["insurance_rating_basis"] == "EXPERIENCE_RATED"
        assert_money(priced["insurance_premium_usd"], 17139.44, "insurance_premium_usd")

    def test_the_composite_score_is_stored_under_both_bases(self, api):
        """Re-rating the same tract keeps 66.48 while the premium falls by 9430.77.

        PRD: "It is stored under both rating bases, even though only one of them prices the policy."

        Design: Difficulty/dual_variant_calc/insurance_premium_actuarial_vs_experience_rated_diverges
        """
        _, tract, _, settled = _insured_tract_with_a_settled_claim(api)
        assert_tons(settled["salvageable_tons"], 8050.00, "salvageable_tons")
        assert_money(settled["insurance_claim_usd"], 310500.00, "insurance_claim_usd")

        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "ACTUARIAL", **HAZARD_INDICES},
        )
        actuarial = read_property(api, tract["id"])

        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "EXPERIENCE_RATED", **HAZARD_INDICES},
        )
        experience_rated = read_property(api, tract["id"])

        assert_money(
            experience_rated["composite_risk_score"], 66.48, "composite_risk_score"
        )
        assert_money(
            float(actuarial["insurance_premium_usd"])
            - float(experience_rated["insurance_premium_usd"]),
            9430.77,
            "premium divergence",
        )

    def test_every_premium_is_debited_from_the_fund_treasury(self, api):
        """The settled claim comes in and both premiums go out, leaving 666790.35.

        PRD: "debits the premium from the fund's `cash_balance_usd` and from `net_operating_cash_usd` under the cash guard of §2.11, recomputes `cash_yield_bps` and `harvest_acceleration_required`, and increments the property's `version`"

        Design: Difficulty/dual_variant_calc/insurance_premium_actuarial_vs_experience_rated_diverges
        """
        fund, tract, _, _ = _insured_tract_with_a_settled_claim(api)

        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "ACTUARIAL", **HAZARD_INDICES},
        )
        record_risk_review(
            api,
            tract["id"],
            {"insurance_rating_basis": "EXPERIENCE_RATED", **HAZARD_INDICES},
        )

        assert_fund_cash(
            read_fund(api, fund["id"]),
            cash_balance_usd=666790.35,
            net_operating_cash_usd=266790.35,
        )


class TestHazardLossCascadesThroughTheBooks:
    """A total loss walks from the stand through the block to the property and the fund."""

    def test_a_total_loss_computes_its_salvage_and_its_indemnity_ceiling(self, api):
        """Thirty-five percent of the loss is recoverable and the ceiling is 62736.12.

        PRD: "`insurance_claim_usd` is `damaged_tons` multiplied by an indemnity rate of twenty-two dollars fifty cents per ton and then by an indemnity share of sixty percent, rounded half-up to two decimals; it is the ceiling on what the carrier can be made to pay."

        Design: Difficulty/transitive_cascade/hazard_event_cascades_stand_block_property_and_fund
        """
        ctx = owned_tract(api)
        reserve_block(api, ctx.stand_id, planned_tons=1000.00)

        event = report_hazard(
            api,
            ctx.stand_id,
            event_type="WILDFIRE",
            occurred_at="2026-08-01T00:00:00Z",
            damaged_tons=TOTAL_LOSS_TONS,
        )

        assert_tons(event["salvageable_tons"], 1626.49, "salvageable_tons")
        assert_money(event["insurance_claim_usd"], 62736.12, "insurance_claim_usd")
        assert event["status"] == "REPORTED"

    def test_the_unsettled_claim_moves_no_fund_cash(self, api):
        """A reported event is only a claim, so the treasury stays where the closing left it.

        PRD: "events still in `REPORTED` contribute 0.00 to that sum however large their computed claim"

        Design: Difficulty/transitive_cascade/hazard_event_cascades_stand_block_property_and_fund
        """
        ctx = owned_tract(api)
        reserve_block(api, ctx.stand_id, planned_tons=1000.00)

        report_hazard(
            api,
            ctx.stand_id,
            event_type="WILDFIRE",
            occurred_at="2026-08-01T00:00:00Z",
            damaged_tons=TOTAL_LOSS_TONS,
        )

        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=300000.00,
            net_operating_cash_usd=0.00,
        )

    def test_the_damaged_stand_is_emptied_and_awaits_salvage(self, api):
        """Every ton is gone, so the pool and all its buckets read zero.

        PRD: "The stand's `net_merch_tons` is then reduced by `damaged_tons`, rounded half-up to two decimals, and the stand moves from `INVENTORIED` to `SALVAGE_PENDING`."

        Design: Difficulty/transitive_cascade/hazard_event_cascades_stand_block_property_and_fund
        """
        ctx = owned_tract(api)
        reserve_block(api, ctx.stand_id, planned_tons=1000.00)

        report_hazard(
            api,
            ctx.stand_id,
            event_type="WILDFIRE",
            occurred_at="2026-08-01T00:00:00Z",
            damaged_tons=TOTAL_LOSS_TONS,
        )

        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "SALVAGE_PENDING"
        assert_stand_partition(
            stand,
            net_merch_tons=0.00,
            reserved_tons=0.00,
            committed_tons=0.00,
            dedicated_tons=0.00,
            hbu_withdrawn_tons=0.00,
            available_tons=0.00,
        )

    def test_the_waterfall_cuts_the_reserved_block_to_nothing_and_logs_it(self, api):
        """The 1000.00-ton shortfall is clawed back from the only reserved block.

        PRD: "Allocated tonnage is the sum of `reserved_tons`, `committed_tons`, `dedicated_tons` and `hbu_withdrawn_tons`, rounded half-up to two decimals; `inventory_shortfall_tons` is the greater of zero and that allocated total less the stand's post-damage `net_merch_tons`, rounded half-up to two decimals."

        Design: Difficulty/transitive_cascade/hazard_event_cascades_stand_block_property_and_fund
        """
        ctx = owned_tract(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)

        event = report_hazard(
            api,
            ctx.stand_id,
            event_type="WILDFIRE",
            occurred_at="2026-08-01T00:00:00Z",
            damaged_tons=TOTAL_LOSS_TONS,
        )

        assert_tons(
            event["inventory_shortfall_tons"], 1000.00, "inventory_shortfall_tons"
        )
        assert len(event["reallocation_log"]) == 1, (
            "exactly one target was cut, so the log carries one record"
        )
        assert_reallocation_entry(
            event["reallocation_log"][0],
            "HARVEST_BLOCK",
            target_id=block["id"],
            tons_cut=1000.00,
            resulting_status="VOIDED",
        )
        assert_tons(
            read_hazard_event(api, event["id"])["inventory_shortfall_tons"],
            1000.00,
            "inventory_shortfall_tons",
        )

    def test_the_gutted_block_is_voided_for_hazard_loss(self, api):
        """A block cut all the way to zero is voided with the hazard reason.

        PRD: "a block reduced all the way to 0.00 additionally becomes `VOIDED` with `voided_reason` `HAZARD_LOSS`"

        Design: Difficulty/transitive_cascade/hazard_event_cascades_stand_block_property_and_fund
        """
        ctx = owned_tract(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)

        report_hazard(
            api,
            ctx.stand_id,
            event_type="WILDFIRE",
            occurred_at="2026-08-01T00:00:00Z",
            damaged_tons=TOTAL_LOSS_TONS,
        )

        voided = read_block(api, block["id"])
        assert voided["status"] == "VOIDED"
        assert voided["voided_reason"] == "HAZARD_LOSS"
        assert_tons(voided["planned_tons"], 0.00, "planned_tons")

    def test_the_cut_raises_a_replanning_obligation_on_the_tract_and_the_fund(self, api):
        """Any cut flags the property for replanning and counts it on the fund.

        PRD: "Cutting a harvest block reduces its `planned_tons` by the cut amount, rounded half-up to two decimals, and sets the property's `harvest_plan_status` to `REPLAN_REQUIRED` — any cut does this, whether or not the block survives — which in turn increments the fund's `replan_property_count`"

        Design: Difficulty/transitive_cascade/hazard_event_cascades_stand_block_property_and_fund
        """
        ctx = owned_tract(api)
        reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        assert_property_dimensions(
            read_property(api, ctx.property_id), harvest_plan_status="ALIGNED"
        )
        assert read_fund(api, ctx.fund_id)["replan_property_count"] == 0

        report_hazard(
            api,
            ctx.stand_id,
            event_type="WILDFIRE",
            occurred_at="2026-08-01T00:00:00Z",
            damaged_tons=TOTAL_LOSS_TONS,
        )

        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="OWNED",
            harvest_plan_status="REPLAN_REQUIRED",
        )
        assert read_fund(api, ctx.fund_id)["replan_property_count"] == 1
