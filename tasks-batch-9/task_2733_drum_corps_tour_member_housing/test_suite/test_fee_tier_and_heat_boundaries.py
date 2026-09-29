"""Inclusive-comparison probes either side of four pinned thresholds.

The circuit-fee tier turns on a strict less-than against fifteen thousand dollars
and a prize share that lands on an exact half cent; the athletic-trainer and
extreme-heat gates turn on at-least comparisons against 95 and 105 degrees.
"""

from test_helpers import (
    ApiErrorId,
    Duty,
    TOUR_MANAGER_HEADERS,
    VolunteerRoleType,
    assert_all_nulls,
    assert_show_settlement,
    assert_site_booking,
    factories as f,
    fixtures as fx,
    validate_error,
)

STOP_SHAPE = {
    "travel_miles_from_previous": 0,
    "uniform_trunks": 0,
    "instrument_cases": 0,
    "prop_units": 0,
    "truck_count": 1,
    "rehearsal_minutes": 0,
    "heat_index_f": 80,
}


def _three_completed_show_stops(api, season_id):
    stops = []
    for venue, city, day in (("Allen Stadium", "Allen", "20"),
                             ("Denton Bowl", "Denton", "21"),
                             ("Waco Field", "Waco", "22")):
        stops.append(fx.create_stop(
            api, season_id, venue_name=venue, city=city, state_code="TX",
            arrive_at=f"2027-06-{day}T14:00:00Z",
            depart_at=f"2027-06-{day}T23:30:00Z",
            show_start_at=f"2027-06-{day}T20:00:00Z",
            **STOP_SHAPE,
        ))
    for stop in stops:
        fx.confirm_stop(api, stop["id"])
    fx.set_clock(api, "2027-06-23T00:00:00Z")
    for stop in stops:
        fx.complete_stop(api, stop["id"])
    return stops


def test_a_gross_one_cent_below_the_tier_ceiling_pays_four_percent(api):
    """1499999 cents of gross is still inside the first tier.

    PRD: "`provisional_circuit_fee_cents` is that gross multiplied by the fee rate
    the *same* gross selects, rounded half up."

    Design: Difficulty/boundary_precision_check/circuit_fee_tier_boundary_and_half_up_tie_at_settlement_draft
    """
    season = fx.create_season(api)
    stops = _three_completed_show_stops(api, season["id"])

    settlement = fx.open_settlement(api, stops[0]["id"], 1399999, 625000, 3)

    assert_show_settlement(
        settlement,
        provisional_prize_cents=100000,
        provisional_gross_cents=1499999,
        provisional_circuit_fee_cents=60000,
        provisional_net_cents=1439999,
        status="DRAFT",
    )
    assert_all_nulls(settlement, "final_net_cents", "variance_cents")


def test_the_tier_boundary_itself_pays_the_higher_rate(api):
    """One cent more of gross costs 22500 cents more in fee.

    PRD: "The **circuit fee rate** is tiered on the *full* gross rather than
    marginally: four percent when the gross falls below fifteen thousand dollars,
    five and one-half percent when it falls below thirty thousand dollars, and seven
    percent at thirty thousand dollars or above."

    Design: Difficulty/boundary_precision_check/circuit_fee_tier_boundary_and_half_up_tie_at_settlement_draft
    """
    season = fx.create_season(api)
    stops = _three_completed_show_stops(api, season["id"])

    below = fx.open_settlement(api, stops[0]["id"], 1399999, 625000, 3)
    at_boundary = fx.open_settlement(api, stops[1]["id"], 1400000, 625000, 3)

    assert_show_settlement(
        at_boundary,
        provisional_prize_cents=100000,
        provisional_gross_cents=1500000,
        provisional_circuit_fee_cents=82500,
        provisional_net_cents=1417500,
        status="DRAFT",
    )
    assert at_boundary["provisional_gross_cents"] - below["provisional_gross_cents"] == 1
    assert (
        at_boundary["provisional_circuit_fee_cents"]
        - below["provisional_circuit_fee_cents"]
        == 22500
    )
    assert_all_nulls(at_boundary, "final_net_cents", "variance_cents")


def test_an_exact_half_cent_prize_share_rounds_away_from_zero(api):
    """1050 at nine percent is 94.5 cents, which settles at 95.

    PRD: "Wherever a percentage or a proportion enters a computation, the
    intermediate product is rounded to a whole number of cents using **round half
    up** — a result whose fractional part is exactly one half rounds away from zero,
    upward."

    Design: Difficulty/boundary_precision_check/circuit_fee_tier_boundary_and_half_up_tie_at_settlement_draft
    """
    season = fx.create_season(api)
    stops = _three_completed_show_stops(api, season["id"])

    settlement = fx.open_settlement(api, stops[2]["id"], 100000, 1050, 5)

    assert_show_settlement(
        settlement,
        provisional_prize_cents=95,
        provisional_gross_cents=100095,
        provisional_circuit_fee_cents=4004,
        provisional_net_cents=96091,
        status="DRAFT",
    )
    assert_all_nulls(settlement, "final_net_cents", "variance_cents")


# ------------------------------------------- heat thresholds at 94/95 and 104/105
REHEARSAL_SHAPE = {
    "travel_miles_from_previous": 0,
    "uniform_trunks": 0,
    "instrument_cases": 0,
    "prop_units": 0,
    "truck_count": 1,
}


def _heat_scenario(api, season_id):
    air_conditioned = fx.signed_agreement_with_school(
        api, season_id, usage_type="TOUR_REHEARSAL",
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL", "sleeping_space_count": 30,
                          "capacity_per_space": 12, "rehearsal_field_count": 2,
                          "has_air_conditioning": True},
        start_date="2027-06-18", end_date="2027-06-25",
        nightly_rate_cents=400, minimum_billable_beds=0,
    )
    sweltering = fx.signed_agreement_with_school(
        api, season_id, usage_type="TOUR_REHEARSAL",
        school_overrides={"name": "Dubuque Senior High", "city": "Dubuque",
                          "state_code": "IA", "sleeping_space_count": 20,
                          "capacity_per_space": 10, "rehearsal_field_count": 1,
                          "has_air_conditioning": False},
        start_date="2027-06-18", end_date="2027-06-25",
        nightly_rate_cents=400, minimum_billable_beds=0,
    )
    stops = {}
    for heat, rehearsal, day, venue, city, state in (
        (94, 239, "19", "Rockford AM block", "Rockford", "IL"),
        (95, 120, "20", "Rockford PM block", "Rockford", "IL"),
        (104, 120, "21", "Dubuque hot block", "Dubuque", "IA"),
        (105, 120, "22", "Dubuque extreme block", "Dubuque", "IA"),
    ):
        stops[heat] = fx.create_rehearsal_stop(
            api, season_id, venue_name=venue, city=city, state_code=state,
            arrive_at=f"2027-06-{day}T08:00:00Z",
            depart_at=f"2027-06-{day}T22:00:00Z",
            rehearsal_minutes=rehearsal, heat_index_f=heat, **REHEARSAL_SHAPE,
        )
    trainer = fx.screened_volunteer(
        api, VolunteerRoleType.ATHLETIC_TRAINER, "2026-08-01",
        full_name="Dr. Lee Marsh", credential_id="ATC-77120",
    )
    return {"ac": air_conditioned, "no_ac": sweltering, "stops": stops,
            "trainer": trainer}


def test_heat_ninety_four_and_rehearsal_two_thirty_nine_need_no_trainer(api):
    """Both trainer triggers are at-least comparisons, so neither fires yet.

    PRD: "Athletic-trainer coverage requires at least one approved `TRAINER` shift
    whenever the stop is strenuous or hot: whenever `rehearsal_minutes` is at least
    two hundred and forty, that is four hours or more of on-site rehearsal, **or**
    `heat_index_f` is at least 95."

    Design: Difficulty/boundary_precision_check/heat_index_thresholds_at_94_95_104_and_105
    """
    season = fx.create_season(api)
    built = _heat_scenario(api, season["id"])

    confirmed = fx.confirm_stop(api, built["stops"][94]["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["heat_index_f"] == 94
    assert confirmed["rehearsal_minutes"] == 239
    assert fx.get_volunteer(api, built["trainer"]["id"])["assignment_count"] == 0


def test_heat_ninety_five_blocks_confirmation_until_a_trainer_is_approved(api):
    """One degree higher demands the trainer, and only an approved shift counts.

    PRD: "Either condition alone suffices to require the trainer, and its absence
    reports `ERR_TRAINER_COVERAGE_REQUIRED`."

    Design: Difficulty/boundary_precision_check/heat_index_thresholds_at_94_95_104_and_105
    """
    season = fx.create_season(api)
    built = _heat_scenario(api, season["id"])
    stop = built["stops"][95]

    refused = api.confirm_tour_stop(stop["id"], TOUR_MANAGER_HEADERS)
    validate_error(refused, ApiErrorId.TRAINER_COVERAGE_REQUIRED, 409)
    assert fx.get_stop(api, stop["id"])["status"] == "PLANNED"

    fx.approved_shift(api, built["trainer"]["id"], stop["id"], Duty.TRAINER,
                      "2027-06-20T09:00:00Z", "2027-06-20T21:00:00Z")
    confirmed = fx.confirm_stop(api, stop["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert fx.get_volunteer(api, built["trainer"]["id"])["assignment_count"] == 1


def test_heat_one_hundred_and_four_still_permits_an_outdoor_block(api):
    """Just below the protocol the outdoor field is available even without AC.

    PRD: "When the parent stop's `heat_index_f` stands at 105 or above, a rehearsal
    block may be created only if it is both indoors and at an air-conditioned school
    — `indoor` must be true **and** the school's `has_air_conditioning` must be
    true."

    Design: Difficulty/boundary_precision_check/heat_index_thresholds_at_94_95_104_and_105
    """
    season = fx.create_season(api)
    built = _heat_scenario(api, season["id"])

    block = fx.create_booking(
        api, built["stops"][104]["id"], built["no_ac"]["school"]["id"],
        built["no_ac"]["agreement"]["id"],
        "2027-06-21T14:00:00Z", "2027-06-21T18:00:00Z", indoor=False,
    )

    assert_site_booking(block, status="HELD", indoor=False)
    assert fx.get_school(api, built["no_ac"]["school"]["id"])["booked_block_count"] == 1


def test_heat_one_hundred_and_five_needs_both_indoors_and_air_conditioning(api):
    """Outdoors fails, indoors without AC fails, indoors with AC is held.

    PRD: "An outdoor block, or an indoor block at a school without air conditioning,
    is prohibited under the extreme-heat protocol and reports
    `ERR_EXTREME_HEAT_OUTDOOR_PROHIBITED`."

    Design: Difficulty/boundary_precision_check/heat_index_thresholds_at_94_95_104_and_105
    """
    season = fx.create_season(api)
    built = _heat_scenario(api, season["id"])
    stop_id = built["stops"][105]["id"]
    window = ("2027-06-22T14:00:00Z", "2027-06-22T18:00:00Z")

    for indoor in (False, True):
        refused = api.create_site_booking(
            f.site_booking_payload(stop_id, built["no_ac"]["school"]["id"],
                                   built["no_ac"]["agreement"]["id"], *window,
                                   indoor=indoor),
            TOUR_MANAGER_HEADERS,
        )
        validate_error(refused, ApiErrorId.EXTREME_HEAT_OUTDOOR_PROHIBITED, 409)

    held = fx.create_booking(api, stop_id, built["ac"]["school"]["id"],
                             built["ac"]["agreement"]["id"], *window, indoor=True)

    assert_site_booking(held, status="HELD", indoor=True)
    assert fx.get_school(api, built["ac"]["school"]["id"])["booked_block_count"] == 1
    assert fx.get_school(api, built["no_ac"]["school"]["id"])["booked_block_count"] == 0
