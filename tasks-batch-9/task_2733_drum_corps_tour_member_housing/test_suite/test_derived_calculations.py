"""Derived monetary and logistical figures the server computes for itself.

Every figure asserted here is one the PRD derives from inputs the test supplies,
so the expected value is arithmetic rather than an echo of the request.
"""

from test_helpers import (
    ApiErrorId,
    BUSINESS_MANAGER_HEADERS,
    PaymentMethod,
    PaymentStatus,
    PlanStatus,
    SettlementState,
    SettlementStatus,
    StopStatus,
    StopType,
    assert_payment_plan,
    assert_show_settlement,
    assert_tour_stop,
    assert_tuition_payment,
    factories as f,
    fixtures as fx,
    validate_error,
)

REHEARSAL_WINDOW = {"rehearsal_minutes": 120, "heat_index_f": 80}


def _leg(api, season_id, venue_name, city, arrive_day, miles, previous_stop_id=None):
    """Plan one empty rehearsal leg so only the mileage varies between stops."""
    overrides = {
        "venue_name": venue_name,
        "city": city,
        "state_code": "IL",
        "arrive_at": f"2027-06-{arrive_day}T06:00:00Z",
        "depart_at": f"2027-06-{arrive_day}T18:00:00Z",
        "travel_miles_from_previous": miles,
        "uniform_trunks": 0,
        "instrument_cases": 0,
        "prop_units": 0,
        "truck_count": 1,
        **REHEARSAL_WINDOW,
    }
    if previous_stop_id is not None:
        overrides["previous_stop_id"] = previous_stop_id
    return fx.create_rehearsal_stop(api, season_id, **overrides)


def test_the_fuel_stop_lands_on_the_two_hundredth_mile_not_past_it(api):
    """Three mileages either side of the fuel threshold, plus the null origin.

    PRD: "The fuel stop appears exactly *at* two hundred miles rather than beyond it, so a two-hundred-mile leg carries one fuel stop and a one-hundred-and-ninety-nine-mile leg carries none."

    Design: Corner/calculations/travel_feasibility_fuel_stop_appears_exactly_at_200_miles
    """
    season = fx.create_season(api)
    origin = _leg(api, season["id"], "Origin", "Rockford", "18", 0)
    under = _leg(api, season["id"], "Under Threshold", "Dubuque", "19", 199, origin["id"])
    at = _leg(api, season["id"], "At Threshold", "Madison", "20", 200, origin["id"])
    long_haul = _leg(api, season["id"], "Long Haul", "Indianapolis", "21", 420, origin["id"])

    assert_tour_stop(origin, required_travel_minutes=0, trucks_required=1)
    assert_tour_stop(under, required_travel_minutes=266)
    assert_tour_stop(at, required_travel_minutes=297)
    assert_tour_stop(long_haul, required_travel_minutes=620, trucks_required=2)


def test_a_payment_fills_the_late_fee_bucket_before_it_touches_principal(api):
    """10000 tendered against 3999 of accrued fees splits 3999 / 6001.

    PRD: "The first bucket is unpaid late fees: `allocated_to_late_fee_cents` is the smaller of the tendered amount and the outstanding late-fee balance, where that balance is `late_fee_accrued_cents` less `late_fee_paid_cents`."

    Design: Corner/calculations/payment_waterfall_fills_late_fees_before_principal
    """
    season = fx.create_season(api)
    built = fx.financed_member(api, season["id"], "2027-01-15")
    plan_id = built["plan"]["id"]

    fx.set_clock(api, "2027-02-20T00:00:00Z")
    fx.run_sweep(api, season["id"])

    swept = fx.get_plan(api, plan_id)
    assert_payment_plan(
        swept,
        installments_due_count=2,
        due_amount_cents=266600,
        arrears_cents=266600,
        late_fee_accrued_cents=3999,
        delinquency_strikes=1,
        status=PlanStatus.DELINQUENT,
    )

    payment = fx.post_payment(api, plan_id, 10000, "2027-02-20", PaymentMethod.ACH)
    assert_tuition_payment(
        payment,
        amount_cents=10000,
        allocated_to_late_fee_cents=3999,
        allocated_to_principal_cents=6001,
        status=PaymentStatus.POSTED,
    )

    plan = fx.get_plan(api, plan_id)
    assert_payment_plan(
        plan,
        late_fee_paid_cents=3999,
        principal_paid_cents=6001,
        arrears_cents=260599,
        outstanding_cents=393899,
        status=PlanStatus.DELINQUENT,
    )
    member = fx.get_member(api, built["member"]["id"])
    assert member["tuition_paid_cents"] == 6001, "only the principal leg reaches the member"
    assert member["tuition_balance_cents"] == 393899
    reread = fx.get_season(api, season["id"])
    assert reread["tuition_collected_cents"] == 6001
    assert reread["late_fee_collected_cents"] == 3999


def test_the_late_fee_percentage_is_clamped_up_then_down_on_one_sweep(api):
    """100000 of arrears takes the floor while 5000000 takes the ceiling.

    PRD: "If arrears are greater than 0, the fee is computed as one and one-half percent of the arrears, rounded half up to a whole cent, and then clamped — first up to a floor of twenty-five dollars, then down to a ceiling of one hundred and fifty dollars, in that order."

    Design: Corner/calculations/late_fee_floor_and_cap_clamp_after_the_percentage
    """
    season = fx.create_season(api)
    small = fx.financed_member(
        api, season["id"], "2027-01-15", tuition_amount_cents=100000
    )
    large = fx.financed_member(
        api, season["id"], "2027-01-15", tuition_amount_cents=5000000
    )
    assert_payment_plan(
        small["plan"],
        surcharge_cents=0,
        financed_total_cents=100000,
        installment_base_cents=33333,
        installment_remainder_cents=1,
    )
    assert_payment_plan(
        large["plan"],
        surcharge_cents=0,
        financed_total_cents=5000000,
        installment_base_cents=1666666,
        installment_remainder_cents=2,
    )

    fx.set_clock(api, "2027-03-20T00:00:00Z")
    swept_season = fx.run_sweep(api, season["id"])
    assert swept_season["billing_epoch"] == 1, "one sweep advances the epoch exactly once"

    assert_payment_plan(
        fx.get_plan(api, small["plan"]["id"]),
        installments_due_count=3,
        arrears_cents=100000,
        late_fee_accrued_cents=2500,
        outstanding_cents=102500,
        delinquency_strikes=1,
        status=PlanStatus.DELINQUENT,
    )
    assert_payment_plan(
        fx.get_plan(api, large["plan"]["id"]),
        installments_due_count=3,
        arrears_cents=5000000,
        late_fee_accrued_cents=15000,
        outstanding_cents=5015000,
        delinquency_strikes=1,
        status=PlanStatus.DELINQUENT,
    )


def test_the_remittance_replay_follows_recorded_at_not_the_submitted_order(api):
    """Two identical sanction amounts arrive reversed; the earlier one charges first.

    PRD: "Lines are sorted by `recorded_at` ascending and, for lines sharing an instant, by their index in the submitted array ascending; no identifier ever participates in the ordering."

    Design: Corner/calculations/settlement_replay_sorts_by_recorded_at_not_by_submission_order
    """
    season = fx.create_season(api)
    built = fx.draft_settlement_on_show(
        api,
        season["id"],
        1200000,
        800000,
        3,
        preparer_headers=BUSINESS_MANAGER_HEADERS,
        venue_name="Allen Stadium",
        city="Allen",
        state_code="TX",
        arrive_at="2027-06-20T14:00:00Z",
        depart_at="2027-06-20T23:30:00Z",
        show_start_at="2027-06-20T20:00:00Z",
        truck_count=1,
    )
    assert_show_settlement(
        built["settlement"],
        provisional_prize_cents=128000,
        provisional_gross_cents=1328000,
        provisional_circuit_fee_cents=53120,
        provisional_net_cents=1274880,
    )

    fx.set_clock(api, "2027-06-30T00:00:00Z")
    final = fx.finalize_settlement(
        api,
        built["settlement"]["id"],
        2,
        [
            f.prize_adjustment_line(40000, "2027-06-25T09:00:00Z"),
            f.sanction_line(250000, "2027-06-27T09:00:00Z"),
            f.sanction_line(200000, "2027-06-26T09:00:00Z"),
            f.rebate_line(60000, "2027-06-28T09:00:00Z"),
        ],
    )
    assert_show_settlement(
        final,
        status=SettlementStatus.FINALIZED,
        final_prize_cents=176000,
        final_gross_cents=1416000,
        final_circuit_fee_cents=56640,
        sanctions_charged_cents=373904,
        rebate_applied_cents=56640,
        final_net_cents=1042096,
        variance_cents=-232784,
        provisional_net_cents=1274880,
        remittance_line_count=4,
    )
    assert fx.get_season(api, season["id"])["tour_revenue_cents"] == 1042096


def test_only_a_completed_show_stop_may_carry_one_settlement(api):
    """A confirmed show, a completed rehearsal and a duplicate draft are all refused.

    PRD: "The parent stop must have `status` `COMPLETED` and `stop_type` `SHOW`, or the request reports `ERR_STOP_NOT_COMPLETED`; a stop may carry at most one settlement, so a second attempt reports `ERR_SETTLEMENT_ALREADY_EXISTS`."

    Design: Corner/calculations/settlement_input_set_requires_a_completed_show_stop
    """
    season = fx.create_season(api)
    confirmed_show = fx.create_stop(
        api,
        season["id"],
        stop_type=StopType.SHOW,
        venue_name="Confirmed Show",
        city="Allen",
        state_code="TX",
        arrive_at="2027-06-25T14:00:00Z",
        depart_at="2027-06-25T23:30:00Z",
        show_start_at="2027-06-25T20:00:00Z",
        truck_count=1,
    )
    rehearsal = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="Rehearsal Only",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-19T06:00:00Z",
        depart_at="2027-06-19T18:00:00Z",
        truck_count=1,
        rehearsal_minutes=120,
    )
    completed_show = fx.create_stop(
        api,
        season["id"],
        stop_type=StopType.SHOW,
        venue_name="Completed Show",
        city="Peoria",
        state_code="IL",
        arrive_at="2027-06-20T14:00:00Z",
        depart_at="2027-06-20T23:30:00Z",
        show_start_at="2027-06-20T20:00:00Z",
        truck_count=1,
    )
    for stop in (confirmed_show, rehearsal, completed_show):
        fx.confirm_stop(api, stop["id"])
    fx.set_clock(api, "2027-06-21T00:00:00Z")
    fx.complete_stop(api, rehearsal["id"])
    fx.complete_stop(api, completed_show["id"])

    assert_tour_stop(
        fx.get_stop(api, rehearsal["id"]),
        status=StopStatus.COMPLETED,
        settlement_state=SettlementState.NONE,
    )

    validate_error(
        api.create_show_settlement(
            f.show_settlement_payload(confirmed_show["id"], 100000, 500000, 3),
            BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.STOP_NOT_COMPLETED,
        409,
    )
    validate_error(
        api.create_show_settlement(
            f.show_settlement_payload(rehearsal["id"], 100000, 500000, 3),
            BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.STOP_NOT_COMPLETED,
        409,
    )

    settlement = fx.open_settlement(
        api, completed_show["id"], 100000, 500000, 7, headers=BUSINESS_MANAGER_HEADERS
    )
    assert_show_settlement(
        settlement,
        provisional_prize_cents=25000,
        provisional_gross_cents=125000,
        provisional_circuit_fee_cents=5000,
        provisional_net_cents=120000,
        status=SettlementStatus.DRAFT,
    )

    validate_error(
        api.create_show_settlement(
            f.show_settlement_payload(completed_show["id"], 100000, 500000, 3),
            BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.SETTLEMENT_ALREADY_EXISTS,
        409,
    )
    assert_show_settlement(fx.get_settlement(api, settlement["id"]), version=1)
    assert fx.get_season(api, season["id"])["tour_revenue_cents"] == 0
