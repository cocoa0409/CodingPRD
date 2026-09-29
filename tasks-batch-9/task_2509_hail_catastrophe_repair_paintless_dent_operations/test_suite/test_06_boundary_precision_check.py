"""Thresholds probed at the exact cent, dent and point where they flip."""

from test_helpers import (
    CLOCK_T0,
    DIRECTOR,
    SECOND_VEHICLE,
    assert_damage_line_pricing,
    assert_money_chain,
    assert_triage_outcome,
    assert_vehicle_variants,
    bring_vehicle_to,
    create_storm_event,
    line_by_panel,
    read_damage_lines,
    read_event,
    set_clock,
    setup_operational_facility,
    storm_event_decision_payload,
    validate_error,
    validate_success,
)

BORDERLINE_EVENT = {
    "swath_confidence": "MODELED",
    "max_hail_size_mm": 50,
    "swath_area_km2": 300,
    "competitor_shop_count": 4,
}


def _event_scoring(api, vehicle_population_estimate, name):
    set_clock(api, CLOCK_T0)
    return create_storm_event(
        api,
        name=name,
        vehicle_population_estimate=vehicle_population_estimate,
        **BORDERLINE_EVENT,
    )


def test_a_score_of_fifty_nine_is_one_point_short_of_the_trailers(api):
    """PRD §3.1: "`TARGET` is score-gated: the event's `targeting_score` must be
    at least 60, and a lower score is rejected with
    `ERR_TARGETING_SCORE_BELOW_FLOOR` — the storm is real, but not worth the
    trailers."

    PRD §3.1: "Both branches require the event to still be `EVALUATING`; a second
    decision on an already-decided event is rejected with
    `ERR_INVALID_STORM_EVENT_STATE`."

    Design: Difficulty/boundary_precision_check/targeting_floor_boundary_score_59_rejected_60_accepted
    """
    event = _event_scoring(api, 125000, "Just Below Floor")
    assert event["targeting_score"] == 59

    response = api.decide_storm_event(
        event["id"], storm_event_decision_payload("TARGET"), DIRECTOR
    )
    validate_error(response, "ERR_TARGETING_SCORE_BELOW_FLOOR", 422)

    # The refusal is not a decision, so the event is still open to one.
    after = read_event(api, event["id"])
    assert after["status"] == "EVALUATING"
    assert after["targeting_score"] == 59


def test_a_score_of_exactly_sixty_clears_the_floor(api):
    """PRD §3.1: "A `TARGET` decision moves `EVALUATING` → `TARGETED`; a
    `DECLINE` decision moves `EVALUATING` → `DECLINED`, which is terminal. Either
    way the event's `version` increments by one."

    PRD §3.1: "The **density term** rewards vehicle population at one point per
    5,000 vehicles, with the population itself capped at 250,000 vehicles before
    the division."

    Design: Difficulty/boundary_precision_check/targeting_floor_boundary_score_59_rejected_60_accepted
    """
    event = _event_scoring(api, 130000, "Exactly At Floor")
    # Five thousand more vehicles in the swath is worth exactly one point.
    assert event["targeting_score"] == 60

    response = api.decide_storm_event(
        event["id"], storm_event_decision_payload("TARGET"), DIRECTOR
    )
    decided = validate_success(response, 200)
    assert decided["status"] == "TARGETED"
    assert decided["version"] == event["version"] + 1
    assert read_event(api, event["id"])["status"] == "TARGETED"


def _both_tier_boundary_panels(api):
    """Two otherwise identical roofs, one at 15 dents and one at 16."""
    scenario = setup_operational_facility(api)
    fifteen = bring_vehicle_to(
        api, scenario, "ESTIMATED", damage_profile="tier_boundary_15"
    )
    sixteen = bring_vehicle_to(
        api,
        scenario,
        "ESTIMATED",
        damage_profile="tier_boundary_16",
        **SECOND_VEHICLE,
    )
    return scenario, fifteen, sixteen


def test_the_sixteenth_dent_drops_the_panel_into_the_cheaper_tier(api):
    """PRD §3.5: "A dent-count tier multiplier rewards volume: 1.00 when
    `dent_count` is 15 or fewer, 0.85 when `dent_count` is greater than 15 and at
    most 50, and 0.70 when `dent_count` is greater than 50."

    PRD §3.5: "The panel's raw paintless charge is the per-dent rate multiplied
    by `dent_count`, multiplied by the tier multiplier, multiplied by the aluminum
    multiplier, plus `r_and_i_hours` multiplied by the sheet's
    `labor_rate_cents_per_hour`."

    Design: Difficulty/boundary_precision_check/dent_tier_boundary_fifteen_dents_costs_more_than_sixteen
    """
    scenario, fifteen, sixteen = _both_tier_boundary_panels(api)

    assert fifteen["vehicle"]["matrix_variant_total_cents"] == 42945
    assert sixteen["vehicle"]["matrix_variant_total_cents"] == 39847
    # One extra dent makes the whole panel 3,098 cents cheaper.
    assert (
        fifteen["vehicle"]["matrix_variant_total_cents"]
        - sixteen["vehicle"]["matrix_variant_total_cents"]
        == 3098
    )


def test_the_conventional_variant_never_notices_the_dent_count(api):
    """PRD §3.5: "The **conventional variant** prices the same panel as
    `conventional_labor_hours` multiplied by the sheet's
    `labor_rate_cents_per_hour`, plus `conventional_paint_materials_cents`,
    rounded half up to whole cents and stored as `conventional_line_cents`; it
    ignores dent counts, tier multipliers and the aluminum multiplier entirely,
    and the paintless variant in turn ignores paint materials entirely, which is
    why identical panel rows produce genuinely different variant totals."

    PRD §3.5: "The rounded value is then compared against the sheet's
    `panel_cap_cents`: if it is strictly greater than the cap, `capped` becomes
    true and `pdr_line_cents` is reduced to exactly the cap; otherwise `capped`
    stays false and the rounded value stands."

    Design: Difficulty/boundary_precision_check/dent_tier_boundary_fifteen_dents_costs_more_than_sixteen
    """
    scenario, fifteen, sixteen = _both_tier_boundary_panels(api)

    assert fifteen["vehicle"]["conventional_variant_total_cents"] == 104000
    assert sixteen["vehicle"]["conventional_variant_total_cents"] == 104000

    assert_damage_line_pricing(
        line_by_panel(read_damage_lines(api, fifteen["vehicle_id"]), "ROOF"),
        pdr_line_cents=42945,
        conventional_line_cents=104000,
        capped=False,
        routed_to="PDR",
    )
    assert_damage_line_pricing(
        line_by_panel(read_damage_lines(api, sixteen["vehicle_id"]), "ROOF"),
        pdr_line_cents=39847,
        conventional_line_cents=104000,
        capped=False,
        routed_to="PDR",
    )


TOTALLING_ACV_CENTS = 128272
REPAIRABLE_ACV_CENTS = 128273


def _triaged_at_acv(api, acv_cents, **overrides):
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(
        api,
        scenario,
        "TRIAGED",
        damage_profile="single_panel_pdr",
        acv_cents=acv_cents,
        **overrides,
    )
    return scenario, car


def test_a_sum_exactly_on_the_total_loss_floor_totals_the_car(api):
    """PRD §3.6: "Next the total-loss floor is computed as 75 percent of the
    vehicle's `acv_cents`, rounded half up to whole cents. The candidate cost plus
    the projected rental exposure is compared against that floor, and the
    comparison is **inclusive**: if the sum is greater than or equal to the floor,
    the vehicle is totalled — `triage_disposition` becomes `TOTAL_LOSS` and
    `approved_repair_cents` is set to 0 — and a sum exactly equal to the floor
    totals the car."

    PRD §3.6: "A disposition of `TOTAL_LOSS` moves the vehicle `ESTIMATED` →
    `TOTAL_LOSS_PENDING`, leaving `approved_repair_cents` at 0 so that the whole
    money chain recomputes to zero — an administrative fee on a zero subtotal is
    zero."

    Design: Difficulty/boundary_precision_check/total_loss_floor_inclusive_boundary_at_acv_128272
    """
    scenario, car = _triaged_at_acv(api, TOTALLING_ACV_CENTS)
    vehicle = car["vehicle"]

    assert_vehicle_variants(
        vehicle,
        matrix_variant_total_cents=51204,
        conventional_variant_total_cents=56000,
        pdr_feasible=True,
    )
    # 51,204 of paintless work plus 45,000 of projected rental is 96,204, and
    # the floor on this value is 96,204 as well.
    assert_triage_outcome(
        vehicle,
        triage_disposition="TOTAL_LOSS",
        approved_repair_cents=0,
        repair_status="TOTAL_LOSS_PENDING",
    )
    assert_money_chain(
        vehicle,
        admin_fee_cents=0,
        gross_billable_cents=0,
        discount_cents=0,
        net_billable_cents=0,
    )


def test_one_more_cent_of_value_keeps_the_car_repairable(api):
    """PRD §3.6: "It first projects the rental exposure the job will carry: when
    `rental_required` is true, the projection is the pinned sheet's
    `rental_cap_days` multiplied by its `rental_daily_rate_cents`; when
    `rental_required` is false, the projection is zero."

    PRD §3.6: "A disposition of `PDR_REPAIR` or `CONVENTIONAL` moves the vehicle
    `ESTIMATED` → `TRIAGED` and resets `rework_count` to 0."

    Design: Difficulty/boundary_precision_check/total_loss_floor_inclusive_boundary_at_acv_128272
    """
    scenario, car = _triaged_at_acv(api, REPAIRABLE_ACV_CENTS)
    vehicle = car["vehicle"]

    assert_vehicle_variants(
        vehicle,
        matrix_variant_total_cents=51204,
        conventional_variant_total_cents=56000,
        pdr_feasible=True,
    )
    # The floor rounds up to 96,205, one cent above the same 96,204 exposure.
    assert_triage_outcome(
        vehicle,
        triage_disposition="PDR_REPAIR",
        approved_repair_cents=51204,
        repair_status="TRIAGED",
    )
    assert vehicle["rework_count"] == 0
    assert_money_chain(
        vehicle,
        admin_fee_cents=2560,
        gross_billable_cents=53764,
        discount_cents=0,
        net_billable_cents=53764,
    )
