"""Two deadlines a day gone by, and nothing at all happens until someone sweeps.

An implementation may realise elapsed time in three quite different places: on
the read, on a timer, or only inside the operator's own sweep call. This module
plants a capacity hold whose 120-minute life ran out 22 hours earlier and a
support pass whose 24-hour validity has since run out too, then advances the
clock a full day and reads everything without sweeping — the booking must still
be held, its bed still held, the pass still issued and the 675 frozen bed-minutes
still charged against the induction budget of a date that has now arrived. The
sweep is then called once and its own response body has to name both due rows,
with the following reads already final. Calling it a second time has to be a
documented no-op rather than a replay, because a second credit-back of the same
frozen quantum would push the day's ledger below zero.
"""

import pytest

from test_helpers import (
    api_client,
    assert_bed,
    assert_drill,
    assert_induction_booking,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_support_pass,
    bootstrap_unit,
    create_booking,
    create_encounter,
    create_pass,
    get_success_data,
    hold_booking,
    reload_booking,
    reload_encounter,
    reload_pass,
    set_clock,
    setup_validated_drill,
)

CLOCK_BOOTSTRAP = "2026-08-01T05:45:00Z"
CLOCK_DRILL_DUE = "2026-08-01T05:50:00Z"
DRILL_SCHEDULED_FOR = "2026-08-01T05:50:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:52:00Z"
SIMULATED_INCISION_AT = "2026-08-01T05:55:00Z"
CLOCK_WORKING = "2026-08-01T06:00:00Z"
CLOCK_A_DAY_LATER = "2026-08-02T06:01:00Z"
HOLD_EXPIRES_AT = "2026-08-01T08:00:00Z"
PASS_VALID_UNTIL = "2026-08-02T06:00:00Z"
BOOKING_DAY = "2026-08-02"
REQUESTED_START = "2026-08-02T08:00:00Z"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
UNIT_NAME = "Kestrel Hollow Birthing Center LDR"

EXPECTED_LABOR_MINUTES = 600
STRAINED_BUFFER_MINUTES = 75
FROZEN_PROJECTION = 675
DAILY_BUDGET = 2880
REMAINING_UNDER_THE_HOLD = 2205
EMPTY_LEDGER_MINUTES = 0
TIER_I_ANTEPARTUM_UNITS = 0.5
STANDING_DEFICIT = 0.5
NO_COVERAGE = 0.0
SWEEP_ID_ARRAYS = (
    "holds_expired_booking_ids",
    "bookings_requeued_booking_ids",
    "bookings_expired_booking_ids",
    "promoted_booking_ids",
    "missed_checklist_item_ids",
    "breached_assessment_ids",
    "rearmed_assessment_ids",
    "expired_pass_ids",
    "breached_encounter_ids",
)

KESTREL_STAFF = {
    "charge": {
        "full_name": "Wilhelmina Ashcombe RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Genevieve Oyelaran MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "ob": {
        "full_name": "Barnaby Kilcoyne MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Rosalind Thackeray RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


def _summary(world):
    """The coordinator's per-day induction picture for the booking's own date."""
    return get_success_data(
        api_client.get_capacity_summary(
            world.unit_id, world.access_headers, params={"day": BOOKING_DAY}
        )
    )


def _held_bed(world):
    return get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )


@pytest.fixture
def one_hold_and_one_pass_left_a_day_past_their_deadlines():
    """One uncovered walk-in, one held booking, one issued pass, two sweeps.

    The drill is validated first because a unit still carrying the `NOT_READY`
    default sits in `INDUCTION_FROZEN`, and a frozen unit cannot take a hold at
    all; with the drill in hand the single uncovered patient leaves the unit on
    `RATIO_STRAINED`, which is what makes the frozen projection 675 rather than
    645. Nothing else exists on the unit — no bundles, no assessments, no
    shifts, no second booking — so the only work either sweep can find is the
    pair of lapsed deadlines planted here.
    """
    world = bootstrap_unit(
        clock=CLOCK_BOOTSTRAP,
        ldr_beds=4,
        or_rooms=1,
        max_daily_induction_bed_minutes=DAILY_BUDGET,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=KESTREL_STAFF,
        unit_overrides={"unit_name": UNIT_NAME},
    )
    set_clock(CLOCK_DRILL_DUE)
    drill = setup_validated_drill(
        world,
        DRILL_SCHEDULED_FOR,
        SIMULATED_DECISION_AT,
        SIMULATED_INCISION_AT,
        participant_keys=["ob", "anesthesia"],
        document_clock=CLOCK_WORKING,
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-KEST-5101",
        parity=1,
        gestational_age_weeks=39,
    )
    support_pass = create_pass(
        world,
        encounter,
        person_name="Dorotheus Quillfeather",
        credential_type="PARTNER",
    )
    booking = create_booking(
        world,
        patient_record_code="PRC-KEST-5102",
        gestational_age_weeks=41,
        indication_code="POST_DATES_41W",
        requested_start_utc=REQUESTED_START,
        expected_labor_minutes=EXPECTED_LABOR_MINUTES,
    )
    unit_before_the_hold = world.reload_unit()
    held = hold_booking(
        world,
        booking,
        "LDR-01",
        expected_unit_version=unit_before_the_hold["version"],
    )
    set_clock(CLOCK_A_DAY_LATER)
    booking_before_any_sweep = reload_booking(world, booking["id"])
    bed_before_any_sweep = _held_bed(world)
    pass_before_any_sweep = reload_pass(world, support_pass["id"])
    summary_before_any_sweep = _summary(world)
    unit_before_any_sweep = world.reload_unit()
    first_sweep = api_client.capacity_sweep(world.unit_id, world.access_headers)
    booking_after_the_sweep = reload_booking(world, booking["id"])
    bed_after_the_sweep = _held_bed(world)
    pass_after_the_sweep = reload_pass(world, support_pass["id"])
    summary_after_the_sweep = _summary(world)
    unit_after_the_sweep = world.reload_unit()
    second_sweep = api_client.capacity_sweep(world.unit_id, world.access_headers)
    return {
        "world": world,
        "drill": drill,
        "encounter": encounter,
        "support_pass": support_pass,
        "booking": booking,
        "unit_before_the_hold": unit_before_the_hold,
        "held": held,
        "booking_before_any_sweep": booking_before_any_sweep,
        "bed_before_any_sweep": bed_before_any_sweep,
        "pass_before_any_sweep": pass_before_any_sweep,
        "summary_before_any_sweep": summary_before_any_sweep,
        "unit_before_any_sweep": unit_before_any_sweep,
        "first_sweep": first_sweep,
        "booking_after_the_sweep": booking_after_the_sweep,
        "bed_after_the_sweep": bed_after_the_sweep,
        "pass_after_the_sweep": pass_after_the_sweep,
        "summary_after_the_sweep": summary_after_the_sweep,
        "unit_after_the_sweep": unit_after_the_sweep,
        "second_sweep": second_sweep,
        "booking_at_the_end": reload_booking(world, booking["id"]),
        "pass_at_the_end": reload_pass(world, support_pass["id"]),
        "summary_at_the_end": _summary(world),
        "unit_at_the_end": world.reload_unit(),
        "encounter_at_the_end": reload_encounter(world, encounter["id"]),
    }


def test_the_medically_indicated_hold_freezes_six_hundred_and_seventy_five_minutes(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"It is `MEDICALLY_INDICATED` when `indication_code` is `PREECLAMPSIA`,
    `POST_DATES_41W`, `FGR` or `PROM`." Also: "The booking moves `REQUESTED` to
    `CAPACITY_HELD`, the named `LDR` bed moves `AVAILABLE` to `HELD` with
    `held_booking_id` written, and `hold_expires_at` is set to the current instant plus 120
    minutes."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    held = setup["held"]
    assert_induction_booking(held)
    assert held["priority_class"] == "MEDICALLY_INDICATED"
    assert held["status"] == "CAPACITY_HELD"
    assert held["bed_id"] == setup["world"].bed_id("LDR-01")
    assert_instant_equals(held["hold_expires_at"], HOLD_EXPIRES_AT, "hold_expires_at")


def test_the_frozen_projection_carries_the_strained_buffer_and_not_the_open_one(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`, and that
    frozen integer is the exact quantum every later credit and debit moves." Also: "After
    the posture is settled, and only then, `turnover_buffer_minutes` is set to 45 when the
    posture is `OPEN` and 75 otherwise."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    unit = setup["unit_before_the_hold"]
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER_MINUTES
    held = setup["held"]
    assert held["expected_labor_minutes"] == EXPECTED_LABOR_MINUTES
    assert held["projected_occupancy_minutes"] == FROZEN_PROJECTION
    assert FROZEN_PROJECTION == EXPECTED_LABOR_MINUTES + STRAINED_BUFFER_MINUTES


def test_the_validated_drill_is_what_lets_a_strained_unit_take_a_hold_at_all(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"A `PerinatalSafetyOfficer` validates the drill, moving it from `DOCUMENTED` to
    `VALIDATED`." Also: "`INDUCTION_FROZEN` when the deficit is 4.0 or greater, or
    `escalation_breach_count` is 2 or greater, or `bundle_breach_count` is 3 or greater, or
    `cesarean_readiness_state` is `NOT_READY`, or the deficit is greater than 0.0 while some
    activation is in `STAGE_2_ESCALATED`." Also: "A hold is additionally blocked when the
    unit's posture is `INDUCTION_FROZEN` or `DIVERT`."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    drill = setup["drill"]
    assert_drill(drill)
    assert drill["status"] == "VALIDATED"
    unit = setup["unit_before_the_hold"]
    assert unit["cesarean_readiness_state"] != "NOT_READY"
    assert unit["staffing_posture"] != "INDUCTION_FROZEN"
    assert unit["coverage_deficit_units"] == pytest.approx(STANDING_DEFICIT, abs=1e-9)


def test_the_partner_pass_opens_with_a_twenty_four_hour_life(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"The pass opens at `ISSUED` with `valid_until` set to the current instant plus 24
    hours, and an issued pass occupies nothing until it is checked in."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    support_pass = setup["support_pass"]
    assert_support_pass(support_pass)
    assert support_pass["status"] == "ISSUED"
    assert support_pass["credential_type"] == "PARTNER"
    assert_instant_equals(support_pass["valid_until"], PASS_VALID_UNTIL, "valid_until")
    assert_instant_is_null(support_pass["checked_in_at"], "checked_in_at")


def test_a_full_day_of_clock_advance_does_not_expire_the_lapsed_hold(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"Because setting the clock changes nothing, the consequences of elapsed time are
    realised by an explicit operator action: the capacity sweep, run against one
    `ObstetricUnit` by a `ChargeNurse`, a `PatientAccessCoordinator` or a
    `PerinatalSafetyOfficer`." Also: "A hold that simply runs out of time moves to `EXPIRED`
    during a sweep once the current instant reaches `hold_expires_at`, the boundary instant
    itself expiring the hold."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    stale = setup["booking_before_any_sweep"]
    assert_induction_booking(stale)
    assert stale["status"] == "CAPACITY_HELD"
    assert stale["bed_id"] == setup["world"].bed_id("LDR-01")
    assert stale["projected_occupancy_minutes"] == FROZEN_PROJECTION
    assert_instant_equals(stale["hold_expires_at"], HOLD_EXPIRES_AT, "hold_expires_at")


def test_the_held_bed_is_still_held_and_the_reached_pass_still_issued(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"The sweep expires an `ISSUED` or `CHECKED_OUT` pass once `valid_until` has passed."
    Also: "The sweep executes six steps in a pinned order and no other."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    bed = setup["bed_before_any_sweep"]
    assert_bed(bed)
    assert bed["bed_label"] == "LDR-01"
    assert bed["status"] == "HELD"
    assert bed["held_booking_id"] == setup["booking"]["id"]
    stale_pass = setup["pass_before_any_sweep"]
    assert_support_pass(stale_pass)
    assert stale_pass["status"] == "ISSUED"
    assert_instant_equals(stale_pass["valid_until"], PASS_VALID_UNTIL, "valid_until")


def test_the_ledger_still_charges_the_arrived_day_for_a_dead_hold(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"A per-day capacity summary read exposes the whole picture for one UTC date, taking
    `day` as a date string and defaulting to the date of the current instant: both frozen
    ledgers, the day's load, the remaining budget and the `LDR` bed census." Also: "Bookings
    in `REQUESTED`, `BUMPED`, `CANCELLED` and `EXPIRED` all contribute zero minutes to both
    ledgers, while `CAPACITY_HELD` bookings are summed into the held map and `CONFIRMED` and
    `ADMITTED` bookings into the committed map, each keyed by the UTC date of
    `requested_start_utc`."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    summary = setup["summary_before_any_sweep"]
    assert summary["day"] == BOOKING_DAY
    assert summary["held_bed_minutes"] == FROZEN_PROJECTION
    assert summary["committed_bed_minutes"] == EMPTY_LEDGER_MINUTES
    assert summary["day_load_minutes"] == FROZEN_PROJECTION
    assert summary["remaining_bed_minutes"] == REMAINING_UNDER_THE_HOLD
    assert REMAINING_UNDER_THE_HOLD == DAILY_BUDGET - FROZEN_PROJECTION
    assert summary["held_ldr_beds"] == 1
    assert summary["available_ldr_beds"] == 1


def test_no_sweep_has_ever_run_and_the_unit_says_so(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"The sweep records `last_capacity_sweep_at` on the unit, which is null until the first
    sweep runs."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    unit = setup["unit_before_any_sweep"]
    assert_obstetric_unit(unit)
    assert_instant_is_null(unit["last_capacity_sweep_at"], "last_capacity_sweep_at")
    assert_instant_is_null(
        setup["summary_before_any_sweep"]["last_capacity_sweep_at"],
        "last_capacity_sweep_at",
    )
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER_MINUTES


def test_one_sweep_names_exactly_the_two_due_rows_in_its_own_response(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"Third, it expires bookings in `CAPACITY_HELD` whose `hold_expires_at` is at or before
    the current instant, releasing the held bed and returning the held bed-minutes." Also:
    "Alongside the booking waterfall the same sweep settles three other classes of overdue
    obligation: checklist items still `PENDING` past their grace window become `MISSED`; fetal
    escalation chains sitting past a deadline become `TIMED_OUT_BREACH`, and chains sitting in
    `REASSESSMENT_PENDING` past their reassessment deadline re-arm to `ESCALATION_DUE`; and
    support passes in `ISSUED` or `CHECKED_OUT` whose validity has elapsed become `EXPIRED`."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    assert setup["first_sweep"].status_code == 200
    swept = get_success_data(setup["first_sweep"])
    assert swept["holds_expired_booking_ids"] == [setup["booking"]["id"]]
    assert swept["expired_pass_ids"] == [setup["support_pass"]["id"]]
    for name in SWEEP_ID_ARRAYS:
        if name in ("holds_expired_booking_ids", "expired_pass_ids"):
            continue
        assert swept[name] == [], name


def test_the_sweep_reports_the_posture_it_froze_at_its_own_start(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"First, it freezes the unit's `staffing_posture` as it stands at the start of the
    sweep, together with the `turnover_buffer_minutes` derived from that posture, and uses
    those frozen values for the whole sweep." Also: "Sixth, and only once, at the very end, it
    re-derives the unit's posture."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    swept = get_success_data(setup["first_sweep"])
    assert_instant_equals(swept["swept_at"], CLOCK_A_DAY_LATER, "swept_at")
    assert swept["posture_at_sweep"] == "RATIO_STRAINED"
    assert swept["staffing_posture"] == "RATIO_STRAINED"
    assert swept["coverage_deficit_units"] == pytest.approx(STANDING_DEFICIT, abs=1e-9)


def test_neither_the_turnover_step_nor_the_promotion_step_found_work(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"Second, it clears beds in `TURNOVER` whose `turnover_clear_at` is at or before the
    current instant, returning them to `AVAILABLE`." Also: "Fifth, it promotes bookings in
    `REQUESTED` one at a time, re-testing both the day's bed-minute budget and bed
    availability after each single promotion."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    swept = get_success_data(setup["first_sweep"])
    assert swept["beds_cleared_count"] == 0
    assert swept["promoted_count"] == 0
    assert swept["promoted_booking_ids"] == []
    assert setup["bed_before_any_sweep"]["status"] != "TURNOVER"
    assert setup["booking_before_any_sweep"]["status"] != "REQUESTED"


def test_the_booking_is_already_expired_on_the_very_next_read(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"A hold that simply runs out of time moves to `EXPIRED` during a sweep once the current
    instant reaches `hold_expires_at`, the boundary instant itself expiring the hold." Also:
    "This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`, and that frozen
    integer is the exact quantum every later credit and debit moves."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    expired = setup["booking_after_the_sweep"]
    assert_induction_booking(expired)
    assert expired["status"] == "EXPIRED"
    assert expired["projected_occupancy_minutes"] == FROZEN_PROJECTION


def test_the_bed_and_the_pass_are_final_in_the_same_instant(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"Third, it expires bookings in `CAPACITY_HELD` whose `hold_expires_at` is at or before
    the current instant, releasing the held bed and returning the held bed-minutes." Also:
    "The sweep expires an `ISSUED` or `CHECKED_OUT` pass once `valid_until` has passed."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    bed = setup["bed_after_the_sweep"]
    assert_bed(bed)
    assert bed["status"] == "AVAILABLE"
    released_pass = setup["pass_after_the_sweep"]
    assert_support_pass(released_pass)
    assert released_pass["status"] == "EXPIRED"
    assert_instant_is_null(released_pass["checked_in_at"], "checked_in_at")


def test_the_credit_back_moves_exactly_the_frozen_quantum(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"The day's `held_bed_minutes_by_day` entry for the UTC date of `requested_start_utc` is
    increased by it." Also: "The sweep records `last_capacity_sweep_at` on the unit, which is
    null until the first sweep runs."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    summary = setup["summary_after_the_sweep"]
    assert summary["day"] == BOOKING_DAY
    assert summary["held_bed_minutes"] == EMPTY_LEDGER_MINUTES
    assert summary["committed_bed_minutes"] == EMPTY_LEDGER_MINUTES
    assert summary["day_load_minutes"] == EMPTY_LEDGER_MINUTES
    assert summary["remaining_bed_minutes"] == DAILY_BUDGET
    assert summary["held_ldr_beds"] == 0
    assert summary["available_ldr_beds"] == 2
    unit = setup["unit_after_the_sweep"]
    assert_obstetric_unit(unit)
    assert_instant_equals(
        unit["last_capacity_sweep_at"], CLOCK_A_DAY_LATER, "last_capacity_sweep_at"
    )
    assert_instant_equals(
        summary["last_capacity_sweep_at"], CLOCK_A_DAY_LATER, "last_capacity_sweep_at"
    )


def test_the_second_identical_sweep_is_a_documented_no_op(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"A sweep with nothing due is not an error: every counter it reports is 0, no record is
    touched, and the response is a normal 200 OK."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    assert setup["second_sweep"].status_code == 200
    swept = get_success_data(setup["second_sweep"])
    assert swept["beds_cleared_count"] == 0
    assert swept["promoted_count"] == 0
    for name in SWEEP_ID_ARRAYS:
        assert swept[name] == [], name
    assert_instant_equals(swept["swept_at"], CLOCK_A_DAY_LATER, "swept_at")
    assert swept["posture_at_sweep"] == "RATIO_STRAINED"
    assert swept["staffing_posture"] == "RATIO_STRAINED"


def test_the_same_bed_minutes_are_not_credited_back_twice(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"Bookings in `REQUESTED`, `BUMPED`, `CANCELLED` and `EXPIRED` all contribute zero
    minutes to both ledgers, while `CAPACITY_HELD` bookings are summed into the held map and
    `CONFIRMED` and `ADMITTED` bookings into the committed map, each keyed by the UTC date of
    `requested_start_utc`." Also: "After the posture is settled, and only then,
    `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75 otherwise."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    still_expired = setup["booking_at_the_end"]
    assert_induction_booking(still_expired)
    assert still_expired["status"] == "EXPIRED"
    assert still_expired["projected_occupancy_minutes"] == FROZEN_PROJECTION
    summary = setup["summary_at_the_end"]
    assert summary["held_bed_minutes"] == EMPTY_LEDGER_MINUTES
    assert summary["day_load_minutes"] == EMPTY_LEDGER_MINUTES
    assert summary["remaining_bed_minutes"] == DAILY_BUDGET
    assert summary["available_ldr_beds"] == 2
    unit = setup["unit_at_the_end"]
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER_MINUTES
    assert unit["coverage_deficit_units"] == pytest.approx(STANDING_DEFICIT, abs=1e-9)


def test_the_expired_pass_stays_expired_across_the_second_sweep(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"The sweep expires an `ISSUED` or `CHECKED_OUT` pass once `valid_until` has passed."
    Also: "The pass opens at `ISSUED` with `valid_until` set to the current instant plus 24
    hours, and an issued pass occupies nothing until it is checked in."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    final_pass = setup["pass_at_the_end"]
    assert_support_pass(final_pass)
    assert final_pass["status"] == "EXPIRED"
    assert_instant_equals(final_pass["valid_until"], PASS_VALID_UNTIL, "valid_until")


def test_the_uncovered_patient_is_untouched_by_either_sweep(
    one_hold_and_one_pass_left_a_day_past_their_deadlines,
):
    """"The third step produces `required_coverage_units`: 0.0 when `labor_phase` is
    `DISCHARGED` or `TRANSFERRED_OUT`; otherwise 4.0 when one-to-one coverage is required;
    otherwise the acuity weight multiplied by the phase multiplier from the table above."

    Design: Corner/consistency_model/clock_driven_edges_do_not_settle_on_their_own_and_wait_for_an_explicit_capacity_sweep
    """
    setup = one_hold_and_one_pass_left_a_day_past_their_deadlines
    patient = setup["encounter_at_the_end"]
    assert_labor_encounter(patient)
    assert patient["acuity_tier"] == "TIER_I"
    assert patient["labor_phase"] == "ANTEPARTUM"
    assert patient["staffing_state"] == "UNASSIGNED"
    assert patient["required_coverage_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert patient["assigned_coverage_units"] == pytest.approx(NO_COVERAGE, abs=1e-9)
