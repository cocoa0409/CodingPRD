"""Values sitting exactly on an inclusive threshold, and their neighbours."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_index,
    assert_money,
    assert_scenario_funding,
    assert_scenario_totals,
)
from test_helpers.constants import (
    AREA_MAPLE,
    CLOCK_2028_09_30,
    CLOCK_2028_10_01,
    CRACK_SEAL,
    CUT_FEE_TIER_1_5,
    CUT_FEE_TIER_2_0,
    ELM_CANDIDATE_COST,
    FLOOR_70_CANDIDATE_COST,
    GRAND_CANDIDATE_COST,
    MAPLE_CANDIDATE_COST,
    MILL_AND_OVERLAY,
    OBS_699,
    OBS_699_DEDUCT,
    OBS_699_INDEX,
    OBS_70,
    OBS_70_DEDUCT,
    OBS_70_INDEX,
    OBS_CS75,
    OBS_RECON,
    SEG_CEDAR,
    SEG_ELM,
    SEG_GRAND,
    SEG_MAPLE,
)
from test_helpers.test_users import OFFICER

# Maple St is created first and measures exactly 70.0; Cedar St is created
# second, is geometrically identical, and measures one tenth of a point lower.
FLOOR_PAIR = [(SEG_MAPLE, OBS_70), (SEG_CEDAR, OBS_699)]

# An unaffordable ARTERIAL candidate ranked first, an affordable LOCAL one second.
WATERFALL_PAIR = [(SEG_GRAND, OBS_RECON), (SEG_ELM, OBS_CS75)]


def test_treatment_selection_at_exactly_seventy_takes_the_cheaper_treatment(api):
    """The inclusive floor turns a 0.1-point step into a 7.2x cost swing.

    PRD: "Treatment follows from the snapshot: an index of at least 70.0 selects
    `CRACK_SEAL`, an index below 70.0 but at least 40.0 selects
    `MILL_AND_OVERLAY`, and an index below 40.0 selects `RECONSTRUCTION`. The
    floors are inclusive, so exactly 70.0 selects crack seal while 69.9 selects
    mill-and-overlay, and exactly 40.0 selects mill-and-overlay while 39.9 selects
    reconstruction."

    PRD: "Candidates are generated worst-first: ordered by the segment's
    `condition_index` ascending, with ties broken by the segment's `created_at`
    ascending."

    Both segments are 1000.00 ft by 30.00 ft, so the whole 1486665-versus-10743323
    gap comes from the single tenth of a point that separates their indexes.

    Design: Difficulty/boundary_precision_check/treatment_selection_at_crack_seal_floor_exactly_seventy
    """
    ctx = fixtures.sealed_survey(api, FLOOR_PAIR)

    candidates = fixtures.generate_candidates(api, ctx["survey"]["id"])

    assert len(candidates) == 2
    below, at_floor = candidates
    assert below["segment_id"] == ctx["segments"]["Cedar St"]["id"]
    assert_index(below["selection_condition_index"], OBS_699_INDEX)
    assert below["treatment_type"] == MILL_AND_OVERLAY
    assert_money(below["estimated_cost_cents"], MAPLE_CANDIDATE_COST)
    assert_index(below["treatment_pci_gain"], 30.1)
    assert below["expected_service_life_years"] == 15

    assert at_floor["segment_id"] == ctx["segments"]["Maple St"]["id"]
    assert_index(at_floor["selection_condition_index"], OBS_70_INDEX)
    assert at_floor["treatment_type"] == CRACK_SEAL
    assert_money(at_floor["estimated_cost_cents"], FLOOR_70_CANDIDATE_COST)
    assert_index(at_floor["treatment_pci_gain"], 8.0)
    assert at_floor["expected_service_life_years"] == 5
    assert at_floor["estimated_cost_cents"] != MAPLE_CANDIDATE_COST, (
        "exactly at the floor the cheaper treatment is selected"
    )


def test_the_network_index_over_the_boundary_pair_rounds_half_up(api):
    """An area-weighted mean landing on 69.95 publishes 70.0, not 69.9.

    PRD: "Sealing stamps `sealed_at` with the logical clock and computes
    `network_condition_index` as the area-weighted mean measured index over the
    accepted observations: for each accepted observation, multiply its segment's
    `area_sy` by the observation's `measured_condition_index`; sum those products;
    divide by the sum of the same segments' `area_sy`; round to one decimal place."

    The two 3333.33-SY segments weigh equally, so the mean of 70.0 and 69.9 is
    exactly 69.95 and the one-decimal rounding resolves it upward.

    Design: Difficulty/boundary_precision_check/treatment_selection_at_crack_seal_floor_exactly_seventy
    """
    ctx = fixtures.sealed_survey(api, FLOOR_PAIR)

    assert ctx["observations"]["Maple St"]["deduct_total"] == OBS_70_DEDUCT
    assert_index(ctx["observations"]["Maple St"]["measured_condition_index"], OBS_70_INDEX)
    assert ctx["observations"]["Cedar St"]["deduct_total"] == OBS_699_DEDUCT
    assert_index(ctx["observations"]["Cedar St"]["measured_condition_index"], OBS_699_INDEX)
    assert ctx["segments"]["Maple St"]["area_sy"] == AREA_MAPLE
    assert ctx["segments"]["Cedar St"]["area_sy"] == AREA_MAPLE

    assert_index(ctx["survey"]["network_condition_index"], 70.0)
    assert ctx["survey"]["network_condition_index"] != 69.9, (
        "the half-way mean 69.95 rounds up"
    )


def _waterfall_at_exact_remainder(api):
    """A WORST_FIRST scenario funded at exactly the rank-2 candidate's estimate."""
    ctx = fixtures.survey_with_candidates(api, WATERFALL_PAIR)
    assert_money(
        fixtures.candidate_for(ctx, "Grand Blvd")["estimated_cost_cents"], GRAND_CANDIDATE_COST
    )
    assert_money(fixtures.candidate_for(ctx, "Elm St")["estimated_cost_cents"], ELM_CANDIDATE_COST)

    ctx["scenario"] = fixtures.create_scenario(
        api, ctx["survey"]["id"], funding_cents=ELM_CANDIDATE_COST
    )
    return ctx


def test_the_waterfall_funds_a_candidate_costing_exactly_the_remaining_balance(api):
    """The scan runs past the unaffordable leader and funds at exact equality.

    PRD: "Critically, **the scan does not stop at the first candidate that does not
    fit**: a later, cheaper candidate that still fits within the remaining balance
    is funded."

    PRD: "a candidate costing exactly the remaining balance is funded."

    Funding is exactly 1487905 cents: the rank-1 reconstruction candidate at
    237099941 is deferred without consuming anything, and the rank-2 crack-seal
    candidate consumes the balance down to precisely zero.

    Design: Difficulty/boundary_precision_check/waterfall_funds_candidate_costing_exactly_the_remaining_balance
    """
    ctx = _waterfall_at_exact_remainder(api)

    fixtures.run_scenario(api, ctx["scenario"]["id"])
    rows, _meta = validate_paginated(
        api.list_allocations(OFFICER, {"scenario_id": ctx["scenario"]["id"], "limit": 100})
    )

    assert len(rows) == 2
    first, second = rows
    assert first["rank"] == 1
    assert first["candidate_id"] == fixtures.candidate_for(ctx, "Grand Blvd")["id"]
    assert first["allocation_status"] == "DEFERRED"
    assert_money(first["allocated_cents"], 0)
    assert second["rank"] == 2
    assert second["candidate_id"] == fixtures.candidate_for(ctx, "Elm St")["id"]
    assert second["allocation_status"] == "FUNDED"
    assert_money(second["allocated_cents"], ELM_CANDIDATE_COST)


def test_the_exact_remainder_run_spends_the_whole_funding_line(api):
    """Funding is exhausted to the cent while the deferred cost becomes backlog.

    PRD: "After the walk, `funded_cost_cents` is the sum of `allocated_cents` over
    funded rows, `backlog_cents` is the sum of the candidates'
    `estimated_cost_cents` over deferred rows, `allocation_count` is the number of
    funded plus deferred rows, and `uncommitted_cents` is refreshed."

    Design: Difficulty/boundary_precision_check/waterfall_funds_candidate_costing_exactly_the_remaining_balance
    """
    ctx = _waterfall_at_exact_remainder(api)

    scenario = fixtures.run_scenario(api, ctx["scenario"]["id"])

    assert scenario["scenario_status"] == "COMPUTED"
    assert_scenario_totals(scenario, 2, ELM_CANDIDATE_COST, GRAND_CANDIDATE_COST)
    assert_scenario_funding(scenario, ELM_CANDIDATE_COST, 0, ELM_CANDIDATE_COST)


def _segment_under_a_three_year_moratorium(api):
    """Maple St resurfaced on 2026-10-01, so its moratorium runs to 2029-10-01."""
    ctx = fixtures.maple_accepted(api)
    segment = fixtures.segment_for(ctx, "Maple St")
    assert ctx["project"]["accepted_at"].startswith("2026-10-01T00:00:00")
    assert segment["moratorium_until"].startswith("2029-10-01T00:00:00")
    assert segment["last_treatment_type"] == MILL_AND_OVERLAY
    return segment["id"]


def test_a_permit_filed_with_366_days_remaining_pays_the_two_point_zero_tier(api):
    """The day count lands on the inclusive tier edge and takes the higher tier.

    PRD: "Second, a tier multiplier follows from that remaining count: 3.0 when at
    least 1,096 days remain, 2.0 when at least 366 remain, 1.5 when at least 1
    remains, and 1.0 when none remains. The comparisons are inclusive, so exactly
    366 remaining days takes 2.0 while 365 takes 1.5."

    A 100.00 sqft trench prices at 85000 cents, above the 45000-cent minimum, so
    the doubled fee is 170000.

    Design: Difficulty/boundary_precision_check/moratorium_fee_tier_at_366_versus_365_remaining_days
    """
    segment_id = _segment_under_a_three_year_moratorium(api)
    fixtures.set_clock(api, CLOCK_2028_09_30)

    permit = fixtures.apply_cut_permit(
        api,
        segment_id,
        requested_start="2028-10-05T00:00:00Z",
        requested_end="2028-10-07T00:00:00Z",
        cut_area_sqft=100.0,
        emergency=False,
    )

    assert permit["permit_status"] == "MORATORIUM_REVIEW"
    assert permit["moratorium_remaining_days"] == 366
    assert permit["fee_multiplier"] == 2.0
    assert_money(permit["degradation_fee_cents"], CUT_FEE_TIER_2_0)


def test_one_day_of_clock_movement_drops_the_same_permit_to_the_lower_tier(api):
    """365 days is one short of the edge, and the identical trench costs 42500 less.

    PRD: "First, `moratorium_remaining_days` is zero when the segment's
    `moratorium_until` is null; otherwise it is the whole seconds from the logical
    clock to `moratorium_until` divided by the 86,400 seconds in a day with the
    fraction discarded, floored at zero."

    PRD: "`degradation_fee_cents` is that base fee multiplied by `fee_multiplier`,
    rounded to whole cents."

    Design: Difficulty/boundary_precision_check/moratorium_fee_tier_at_366_versus_365_remaining_days
    """
    segment_id = _segment_under_a_three_year_moratorium(api)
    fixtures.set_clock(api, CLOCK_2028_09_30)
    earlier = fixtures.apply_cut_permit(
        api,
        segment_id,
        requested_start="2028-10-05T00:00:00Z",
        requested_end="2028-10-07T00:00:00Z",
        cut_area_sqft=100.0,
        emergency=False,
    )
    fixtures.set_clock(api, CLOCK_2028_10_01)

    later = fixtures.apply_cut_permit(
        api,
        segment_id,
        requested_start="2028-10-05T00:00:00Z",
        requested_end="2028-10-07T00:00:00Z",
        cut_area_sqft=100.0,
        emergency=False,
    )

    assert later["permit_status"] == "MORATORIUM_REVIEW"
    assert later["moratorium_remaining_days"] == 365
    assert later["fee_multiplier"] == 1.5
    assert_money(later["degradation_fee_cents"], CUT_FEE_TIER_1_5)
    assert earlier["moratorium_remaining_days"] == 366
    assert earlier["degradation_fee_cents"] - later["degradation_fee_cents"] == 42500
