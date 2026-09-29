"""Three multi-factor formulas whose step order decides the answer.

Each of these combines several independent inputs, and each pins the sequence in
which rounding happens; performing the same arithmetic in a different order
yields a figure that is close enough to look right and is wrong.
"""

from test_helpers import (
    Duty,
    VolunteerRoleType,
    assert_payment_plan,
    assert_tour_stop,
    fixtures as fx,
    meal_cost_cents,
    round_half_up,
)

SHOW_STOP = {
    "venue_name": "Allen Stadium",
    "city": "Allen",
    "state_code": "TX",
    "arrive_at": "2027-06-20T14:00:00Z",
    "depart_at": "2027-06-20T23:30:00Z",
    "show_start_at": "2027-06-20T20:00:00Z",
    "travel_miles_from_previous": 0,
    "uniform_trunks": 0,
    "instrument_cases": 0,
    "prop_units": 0,
    "truck_count": 1,
    "rehearsal_minutes": 0,
    "heat_index_f": 80,
}


# ------------------------------------------- installment schedule, three steps
def test_extended_six_surcharges_the_whole_principal_then_splits_it(api):
    """The surcharge lands on the principal once, before any division.

    PRD: "Step one applies the financing surcharge to the whole principal exactly
    once: the surcharge rate is zero for a `STANDARD_3` plan and two and one-half
    percent for an `EXTENDED_6` plan, and `surcharge_cents` is the principal
    multiplied by that rate, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/installment_schedule_whole_principal_surcharge_then_integer_split
    """
    season = fx.create_season(api)
    built = fx.financed_member(
        api,
        season["id"],
        first_due_date="2027-01-15",
        tuition_amount_cents=399900,
        payment_plan_type="EXTENDED_6",
    )

    assert_payment_plan(
        built["plan"],
        plan_type="EXTENDED_6",
        installment_count=6,
        principal_cents=399900,
        surcharge_cents=9998,
        financed_total_cents=409898,
        installment_base_cents=68316,
        installment_remainder_cents=2,
        first_due_date="2027-01-15",
        status="ACTIVE",
        delinquency_strikes=0,
        principal_paid_cents=0,
        late_fee_accrued_cents=0,
        late_fee_paid_cents=0,
        installments_due_count=0,
        due_amount_cents=0,
        arrears_cents=0,
        outstanding_cents=409898,
    )
    assert built["plan"]["surcharge_cents"] == round_half_up(399900 * 0.025)
    assert (
        built["plan"]["installment_base_cents"] * 6
        + built["plan"]["installment_remainder_cents"]
        == built["plan"]["financed_total_cents"]
    )


def test_the_two_stray_cents_ride_on_the_earliest_installments(api):
    """Two elapsed due dates carry base plus one cent each.

    PRD: "Step three distributes that remainder one cent at a time onto the
    earliest installments in due-date order, so installment number one through
    installment number `installment_remainder_cents` each carry the base amount
    plus one cent and every later installment carries the base amount exactly."

    Design: Difficulty/combinatorial_formula/installment_schedule_whole_principal_surcharge_then_integer_split
    """
    season = fx.create_season(api)
    built = fx.financed_member(
        api,
        season["id"],
        first_due_date="2027-01-15",
        tuition_amount_cents=399900,
        payment_plan_type="EXTENDED_6",
    )

    fx.set_clock(api, "2027-02-20T00:00:00Z")
    plan = fx.get_plan(api, built["plan"]["id"])

    assert_payment_plan(
        plan,
        installments_due_count=2,
        due_amount_cents=136634,
        arrears_cents=136634,
        outstanding_cents=409898,
        status="ACTIVE",
        delinquency_strikes=0,
    )
    assert plan["due_amount_cents"] == 2 * plan["installment_base_cents"] + 2


# ------------------------------------------------- meal cost, per-class rounding
def _boarded_roster_with_three_diets(api, season_id):
    for dob, diet in (
        ("2005-03-04", "NONE"),
        ("2004-07-19", "GLUTEN_FREE"),
        ("2004-02-08", "SEVERE_ALLERGEN"),
    ):
        fx.contracted_member(api, season_id, date_of_birth=dob, dietary_flag=diet)
    cook = fx.screened_volunteer(api, VolunteerRoleType.COOK, "2026-08-01",
                                 full_name="Robin Vega")
    fx.set_clock(api, "2027-06-12T06:00:00Z")
    fx.run_sweep(api, season_id)
    return cook


def test_meal_cost_rounds_each_dietary_class_before_multiplying(api):
    """Three diets, three heads, three meals: 12939 cents, not 12937.

    PRD: "Step two multiplies each **already-rounded** unit by that class's head
    count and by the three meals served per stop, then sums those products across
    the four classes."

    Design: Difficulty/combinatorial_formula/stop_meal_cost_per_dietary_class_rounding_before_multiplication
    """
    season = fx.create_season(api)
    cook = _boarded_roster_with_three_diets(api, season["id"])

    stop = fx.create_stop(api, season["id"], **SHOW_STOP)
    fx.approved_shift(api, cook["id"], stop["id"], Duty.COOK,
                      "2027-06-20T15:00:00Z", "2027-06-20T22:00:00Z")
    confirmed = fx.confirm_stop(api, stop["id"])

    assert_tour_stop(
        confirmed,
        roster_head_count=3,
        minor_head_count=0,
        required_cook_count=1,
        required_chaperone_count=0,
        meal_cost_cents=12939,
        status="CONFIRMED",
    )


def test_rounding_the_grand_total_instead_would_lose_two_cents(api):
    """The per-class order is observable: the naive figure is 12937.

    PRD: "Rounding a grand total assembled from unrounded products would produce a
    different and incorrect figure; the rounding happens per dietary class, before
    any multiplication or summation."

    Design: Difficulty/combinatorial_formula/stop_meal_cost_per_dietary_class_rounding_before_multiplication
    """
    season = fx.create_season(api)
    cook = _boarded_roster_with_three_diets(api, season["id"])

    stop = fx.create_stop(api, season["id"], **SHOW_STOP)
    assert stop["meal_cost_cents"] == 0
    fx.approved_shift(api, cook["id"], stop["id"], Duty.COOK,
                      "2027-06-20T15:00:00Z", "2027-06-20T22:00:00Z")
    confirmed = fx.confirm_stop(api, stop["id"])

    per_class = meal_cost_cents({"NONE": 1, "GLUTEN_FREE": 1, "SEVERE_ALLERGEN": 1})
    grand_total_first = round_half_up(1175 * (1.00 + 1.22 + 1.45) * 3)
    assert per_class == 12939
    assert grand_total_first == 12937
    assert confirmed["meal_cost_cents"] == per_class
    assert confirmed["meal_cost_cents"] != grand_total_first


# ------------------------------------------ transport plan, four dimensions
REHEARSAL_LEG = {
    "venue_name": "Rockford High School",
    "city": "Rockford",
    "state_code": "IL",
    "arrive_at": "2027-06-18T10:00:00Z",
    "depart_at": "2027-06-18T22:00:00Z",
    "travel_miles_from_previous": 0,
    "rehearsal_minutes": 120,
    "heat_index_f": 78,
    "truck_count": 4,
}

BIG_LEG = {
    "venue_name": "Grand Rapids Stadium",
    "city": "Grand Rapids",
    "state_code": "MI",
    "arrive_at": "2027-06-19T10:00:00Z",
    "depart_at": "2027-06-19T23:00:00Z",
    "show_start_at": "2027-06-19T20:00:00Z",
    "travel_miles_from_previous": 352,
    "uniform_trunks": 40,
    "instrument_cases": 95,
    "prop_units": 25,
    "truck_count": 4,
    "rehearsal_minutes": 0,
    "heat_index_f": 80,
}

SMALL_LEG = dict(BIG_LEG, travel_miles_from_previous=349, prop_units=24, truck_count=2)


def test_oversize_props_and_a_long_haul_each_add_their_own_trailer(api):
    """Two ceilings then two surcharges: four trailers for a 352-mile leg.

    PRD: "Only then do the two additive surcharges apply, and they apply to that
    maximum rather than being folded into either ceiling: one extra trailer is
    added whenever `prop_units` exceeds twenty-four, to escort oversize props, and
    one further trailer is added whenever `travel_miles_from_previous` is at least
    three hundred and fifty, to carry a relief tractor."

    Design: Difficulty/combinatorial_formula/transport_plan_four_dimension_truck_requirement
    """
    season = fx.create_season(api)
    leg_one = fx.create_rehearsal_stop(api, season["id"], **REHEARSAL_LEG)
    big = fx.create_stop(api, season["id"], previous_stop_id=leg_one["id"], **BIG_LEG)

    assert_tour_stop(
        big,
        total_load_cuft=3360,
        total_load_lbs=22725,
        trucks_required=4,
        required_travel_minutes=500,
        status="PLANNED",
    )
    assert big["total_load_cuft"] == 40 * 22 + 95 * 14 + 25 * 46
    assert big["total_load_lbs"] == 40 * 180 + 95 * 95 + 25 * 260


def test_one_prop_and_three_miles_fewer_drops_two_trailers(api):
    """Both surcharges fall away together just below their thresholds.

    PRD: "A stop is therefore capable of needing four trucks where a stop one prop
    unit and three miles smaller needs only two."

    Design: Difficulty/combinatorial_formula/transport_plan_four_dimension_truck_requirement
    """
    season = fx.create_season(api)
    leg_one = fx.create_rehearsal_stop(api, season["id"], **REHEARSAL_LEG)
    big = fx.create_stop(api, season["id"], previous_stop_id=leg_one["id"], **BIG_LEG)
    small = fx.create_stop(api, season["id"], previous_stop_id=leg_one["id"], **SMALL_LEG)

    assert_tour_stop(
        small,
        total_load_cuft=3314,
        total_load_lbs=22465,
        trucks_required=2,
        required_travel_minutes=496,
        status="PLANNED",
    )
    assert big["trucks_required"] - small["trucks_required"] == 2
    assert big["required_travel_minutes"] - small["required_travel_minutes"] == 4
