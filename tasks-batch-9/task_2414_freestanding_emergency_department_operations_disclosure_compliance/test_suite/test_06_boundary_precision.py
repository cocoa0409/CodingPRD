"""Three boundaries that are exact to the last unit: one second, one hour, one cent.

Each pair drives the same operation twice — once standing exactly on the boundary,
once one unit past it — so an implementation that uses a strict comparison where the
specification is inclusive fails one half of the pair and passes the other.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_defect_count,
    assert_hours_equal,
    assert_instant_equals,
    assert_ledger_entry,
    assert_money_conservation,
    assert_no_ledger_entry,
    assert_posture,
    assert_pre_award_snapshots_equal,
)
from test_helpers.factories import make_award_payload
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    IDRE,
    OFFICER,
    acknowledge_disclosure,
    add_resulted_line,
    adjudicate_claim,
    begin_mse,
    create_claim,
    create_dispute_case,
    create_volume_forecast,
    discharge,
    initiate_idr,
    ledger_entries,
    negotiate_rounds,
    open_facility,
    protected_nsa_contract,
    read_claim,
    read_encounter,
    read_facility,
    register_encounter,
    screen_encounter,
    set_clock,
)

BOUNDARY_FACILITY = {
    "observation_bed_count": 4,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
ARRIVAL_INSTANT = "2026-08-01T08:00:00Z"
DEADLINE_INSTANT = "2026-08-01T08:30:00Z"
ONE_SECOND_LATE_INSTANT = "2026-08-01T08:30:01Z"
NEGOTIATION_ROUNDS = ((240000, 200000), (235000, 205000), (230000, 210000))
BAND_FLOOR_CENTS = 210000
ONE_CENT_BELOW_THE_BAND = 209999


def _two_patients_arriving_at_eight_in_the_morning():
    """Two registrations sharing one arrival instant, and therefore one deadline."""
    context = open_facility(
        clock=ARRIVAL_INSTANT, facility_overrides=BOUNDARY_FACILITY
    )
    facility_id = context["facility_id"]
    first = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-6001",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    second = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-6002",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    context.update(
        {
            "first_encounter": first,
            "first_encounter_id": first["id"],
            "second_encounter": second,
            "second_encounter_id": second["id"],
        }
    )
    return context


def test_screening_begun_exactly_at_the_thirty_minute_deadline_is_on_time():
    """Standing on the deadline instant is inside it, and costs the facility nothing.

    PRD 3.7: "`mse_timeliness` becomes `ON_TIME` when `mse_started_at` is at or before
    `mse_start_deadline_at` and `LATE` when it is strictly after. The boundary is
    inclusive to the second — a start at exactly thirty minutes after `arrival_at` is
    `ON_TIME`, and one second later is `LATE`."  The deadline itself comes from PRD 3.6:
    "`mse_start_deadline_at` is computed as `arrival_at` plus half an hour (30 minutes),
    with `mse_timeliness` reading `PENDING` until screening actually begins."

    Design: Difficulty/boundary_precision_check/mse_start_at_exactly_thirty_minutes_is_on_time_and_one_second_later_is_late
    """
    context = _two_patients_arriving_at_eight_in_the_morning()

    assert_instant_equals(
        context["first_encounter"]["arrival_at"], ARRIVAL_INSTANT, "arrival_at"
    )
    assert_instant_equals(
        context["first_encounter"]["mse_start_deadline_at"],
        DEADLINE_INSTANT,
        "mse_start_deadline_at",
    )
    assert context["first_encounter"]["mse_timeliness"] == "PENDING"

    set_clock(DEADLINE_INSTANT)
    begun = begin_mse(
        context["first_encounter_id"], screening_note="screened at the deadline instant"
    )

    assert_instant_equals(begun["mse_started_at"], DEADLINE_INSTANT, "mse_started_at")
    assert begun["mse_timeliness"] == "ON_TIME"
    assert begun["clinical_state"] == "MSE_IN_PROGRESS"

    facility = read_facility(context["facility_id"])
    assert_defect_count(facility, 0)
    assert_posture(facility, "OPEN")
    assert_no_ledger_entry(ledger_entries(context["facility_id"]), "SCREENING_DELAY")


def test_screening_begun_one_second_past_the_deadline_is_late_and_counts_a_defect():
    """One second past the deadline is a counted compliance defect, on the same facility.

    PRD 3.7: "A `LATE` result is a counted compliance defect: it appends a ledger entry
    with `event_type` `SCREENING_DELAY`, `severity` `MAJOR`, `subject_type` `ENCOUNTER`,
    `subject_id` the encounter's id and `defect_counted` true, increments the facility's
    `open_compliance_defect_count` by 1, and cascades into the posture recomputation".
    One defect is short of the threshold PRD 2.8 sets — "The defect threshold is
    inclusive — a count of exactly 3 restricts the facility, a count of 2 does not." — so
    the posture holds at `OPEN`.

    Design: Difficulty/boundary_precision_check/mse_start_at_exactly_thirty_minutes_is_on_time_and_one_second_later_is_late
    """
    context = _two_patients_arriving_at_eight_in_the_morning()

    set_clock(DEADLINE_INSTANT)
    on_time = begin_mse(
        context["first_encounter_id"], screening_note="screened at the deadline instant"
    )
    assert on_time["mse_timeliness"] == "ON_TIME"

    set_clock(ONE_SECOND_LATE_INSTANT)
    late = begin_mse(
        context["second_encounter_id"], screening_note="screened one second past the deadline"
    )

    assert_instant_equals(
        late["mse_started_at"], ONE_SECOND_LATE_INSTANT, "mse_started_at"
    )
    assert late["mse_timeliness"] == "LATE"
    assert late["clinical_state"] == "MSE_IN_PROGRESS"
    assert read_encounter(context["first_encounter_id"])["mse_timeliness"] == "ON_TIME"

    facility = read_facility(context["facility_id"])
    assert_defect_count(facility, 1)
    assert_posture(facility, "OPEN")

    assert_ledger_entry(
        ledger_entries(context["facility_id"]),
        "SCREENING_DELAY",
        severity="MAJOR",
        subject_type="ENCOUNTER",
        subject_id=context["second_encounter_id"],
        defect_counted=True,
        count=1,
    )


def test_an_empty_history_takes_the_floor_only_branch_at_twelve_hours_a_day():
    """No history at all still requires the statutory twelve hours, not zero.

    PRD 3.4: "When `historical_daily_volumes` is empty, the forecast has no history to
    reason from and the **statutory floor alone** governs: `forecast_basis` is set to
    `FLOOR_ONLY`, `forecast_daily_volume` is 0.00, and `required_physician_hours_per_day`
    is set to the coverage floor of 12 hours per day — emphatically not 0, because a
    licensed emergency department must be staffed whether or not anyone predicted
    arrivals."  Seven days of that floor is 84.00 hours, and PRD 3.4's board-certification
    rule — "`required_board_certified_hours_total` is that total multiplied by the
    board-certification minimum share of three quarters, rounded half up to two decimals"
    — puts 63.00 of them on board-certified physicians.

    Design: Difficulty/boundary_precision_check/coverage_floor_hours_boundary_across_empty_and_exactly_floor_and_just_over_floor_histories
    """
    context = open_facility(facility_overrides=BOUNDARY_FACILITY)

    empty_history = create_volume_forecast(
        context["facility_id"],
        period_start_date="2026-09-01",
        period_days=7,
        historical_daily_volumes=[],
        method="TRAILING_MEAN",
    )

    assert empty_history["forecast_basis"] == "FLOOR_ONLY"
    assert_hours_equal(empty_history["forecast_daily_volume"], "0.00", "floor-only volume")
    assert_hours_equal(
        empty_history["required_physician_hours_per_day"], "12.00", "floor per day"
    )
    assert_hours_equal(
        empty_history["required_physician_hours_total"], "84.00", "floor total"
    )
    assert_hours_equal(
        empty_history["required_board_certified_hours_total"], "63.00", "floor board-cert"
    )


def test_eighteen_patients_a_day_sits_exactly_on_the_floor_and_nineteen_clears_it():
    """The floor wins at eighteen arrivals and loses by three quarters of an hour at nineteen.

    PRD 3.4: "The forecast volume is then converted to raw hours by dividing by a
    throughput of 1.5 patients per physician hour. Those raw hours are raised to the next
    whole quarter hour — multiply by four, take the ceiling, divide by four — and
    `required_physician_hours_per_day` is the larger of that quarter-hour figure and the
    12-hour statutory floor."  Eighteen arrivals give exactly 12.00 raw hours, which ties
    the floor; nineteen give 12.666... raw hours, which the quarter-hour ceiling raises to
    12.75 and the floor can no longer beat.  Seven days of 12.75 is 89.25 hours, and with
    nothing on the schedule PRD 3.4's deficit rule — "`coverage_deficit_hours` is the
    shortfall of `required_physician_hours_total` against `scheduled_physician_hours`" —
    leaves the whole requirement outstanding.  Each new forecast also displaces its
    predecessors, because PRD 3.4 states that "every other `ACTIVE` forecast of the same
    facility becomes `SUPERSEDED` in the same operation".

    Design: Difficulty/boundary_precision_check/coverage_floor_hours_boundary_across_empty_and_exactly_floor_and_just_over_floor_histories
    """
    context = open_facility(facility_overrides=BOUNDARY_FACILITY)
    facility_id = context["facility_id"]

    empty_history = create_volume_forecast(
        facility_id,
        period_start_date="2026-09-01",
        period_days=7,
        historical_daily_volumes=[],
        method="TRAILING_MEAN",
    )
    exactly_on_the_floor = create_volume_forecast(
        facility_id,
        period_start_date="2026-09-08",
        period_days=7,
        historical_daily_volumes=[18],
        method="TRAILING_MEAN",
    )
    just_over_the_floor = create_volume_forecast(
        facility_id,
        period_start_date="2026-09-15",
        period_days=7,
        historical_daily_volumes=[19],
        method="TRAILING_MEAN",
    )

    assert exactly_on_the_floor["forecast_basis"] == "HISTORY"
    assert_hours_equal(
        exactly_on_the_floor["forecast_daily_volume"], "18.00", "tying volume"
    )
    assert_hours_equal(
        exactly_on_the_floor["required_physician_hours_per_day"], "12.00", "tying per day"
    )
    assert_hours_equal(
        exactly_on_the_floor["required_physician_hours_total"], "84.00", "tying total"
    )
    assert_hours_equal(
        exactly_on_the_floor["required_board_certified_hours_total"],
        "63.00",
        "tying board-cert",
    )

    assert just_over_the_floor["forecast_basis"] == "HISTORY"
    assert_hours_equal(
        just_over_the_floor["forecast_daily_volume"], "19.00", "clearing volume"
    )
    assert_hours_equal(
        just_over_the_floor["required_physician_hours_per_day"],
        "12.75",
        "clearing per day",
    )
    assert_hours_equal(
        just_over_the_floor["required_physician_hours_total"], "89.25", "clearing total"
    )
    assert_hours_equal(
        just_over_the_floor["required_board_certified_hours_total"],
        "66.94",
        "clearing board-cert",
    )
    assert_hours_equal(
        just_over_the_floor["scheduled_physician_hours"], "0.00", "scheduled"
    )
    assert_hours_equal(
        just_over_the_floor["coverage_deficit_hours"], "89.25", "deficit"
    )

    for superseded_id in (empty_history["id"], exactly_on_the_floor["id"]):
        refreshed = validate_success(
            api_client.get_volume_forecast(superseded_id, ADMIN)
        )
        assert refreshed["status"] == "SUPERSEDED"
    assert just_over_the_floor["status"] == "ACTIVE"


def _award_ready_case_with_a_band_floor_of_two_hundred_ten_thousand():
    """Three closed rounds leaving the band running from 210000 up to 230000 cents."""
    context = open_facility(facility_overrides=BOUNDARY_FACILITY)
    facility_id = context["facility_id"]
    contract = protected_nsa_contract(facility_id, OFFICER, payer_name="Lone Star Health")
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-6101",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    add_resulted_line(encounter["id"], "IMAGING", "CT", 2)
    discharge(encounter["id"])
    claim = create_claim(encounter["id"], contract["id"])
    adjudicated = adjudicate_claim(claim["id"])
    case = create_dispute_case(claim["id"], OFFICER, dispute_note="band edge determination")
    negotiate_rounds(case["id"], NEGOTIATION_ROUNDS)
    escalated = initiate_idr(case["id"], OFFICER)
    context.update(
        {
            "claim_id": claim["id"],
            "adjudicated_claim": adjudicated,
            "case_id": case["id"],
            "case": escalated,
        }
    )
    return context


def test_an_award_one_cent_below_the_inclusive_band_is_rejected():
    """209999 is outside a band that starts at 210000, by exactly one cent.

    PRD 3.9: "it must fall inside the inclusive band whose endpoints are
    `last_offer_cents` and `last_counteroffer_cents`, in whichever order those two happen
    to sit — the band runs from the smaller of the two to the larger of the two, and both
    endpoints are acceptable values. An award outside that band is
    `ERR_AWARD_OUT_OF_RANGE`."  The last round left the payer at 210000 and the facility
    at 230000, so the smaller endpoint is the floor and a cent below it is out of range.

    Design: Difficulty/boundary_precision_check/idr_award_at_the_inclusive_band_edge_is_accepted_while_one_cent_below_is_rejected
    """
    context = _award_ready_case_with_a_band_floor_of_two_hundred_ten_thousand()

    assert context["case"]["status"] == "IDR_INITIATED"
    assert context["case"]["last_offer_cents"] == 230000
    assert context["case"]["last_counteroffer_cents"] == BAND_FLOOR_CENTS
    assert context["case"]["round_index"] == 3

    validate_error(
        api_client.award_dispute(
            context["case_id"], make_award_payload(ONE_CENT_BELOW_THE_BAND), IDRE
        ),
        ApiErrorId.ERR_AWARD_OUT_OF_RANGE.value,
    )

    case = validate_success(api_client.get_dispute_case(context["case_id"], IDRE))
    assert case["status"] == "IDR_INITIATED"
    assert case["idr_award_cents"] is None
    assert case["awarded_at"] is None
    assert read_claim(context["claim_id"])["status"] == "IDR_PENDING"


def test_an_award_standing_exactly_on_the_lower_band_edge_is_accepted():
    """The endpoint itself is an acceptable value, and it becomes the allowed total.

    PRD 3.9: "On acceptance the case moves `IDR_INITIATED → AWARDED`, `idr_award_cents`
    is set to the awarded figure, `awarded_at` is stamped with the logical clock".  The
    claim then follows PRD 3.9's snapshot-then-recompute: "Then the awarded figure becomes
    the allowed total and steps three through six of the settlement are re-run with it —
    same ordered line set, same deductible input, same `protection_variant` — producing
    new `allowed_amount_cents`, `plan_paid_cents`, `patient_responsibility_cents`,
    `balance_bill_amount_cents` and `written_off_cents`. The claim moves
    `IDR_PENDING → RESOLVED`."

    Design: Difficulty/boundary_precision_check/idr_award_at_the_inclusive_band_edge_is_accepted_while_one_cent_below_is_rejected
    """
    context = _award_ready_case_with_a_band_floor_of_two_hundred_ten_thousand()
    pre_award = context["adjudicated_claim"]
    assert pre_award["allowed_amount_cents"] == 190000

    awarded = validate_success(
        api_client.award_dispute(
            context["case_id"], make_award_payload(BAND_FLOOR_CENTS), IDRE
        )
    )

    assert awarded["status"] == "AWARDED"
    assert awarded["idr_award_cents"] == BAND_FLOOR_CENTS

    claim = read_claim(context["claim_id"])
    assert claim["status"] == "RESOLVED"
    assert claim["allowed_amount_cents"] == BAND_FLOOR_CENTS
    assert claim["balance_bill_amount_cents"] == 0
    assert_pre_award_snapshots_equal(
        claim,
        allowed=pre_award["allowed_amount_cents"],
        plan_paid=pre_award["plan_paid_cents"],
        patient_responsibility=pre_award["patient_responsibility_cents"],
        written_off=pre_award["written_off_cents"],
    )
    assert_money_conservation(claim)
