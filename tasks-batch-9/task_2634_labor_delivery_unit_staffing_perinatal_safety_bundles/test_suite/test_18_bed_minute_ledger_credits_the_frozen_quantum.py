"""Releasing induction time gives back the quantum frozen at hold time.

Three bookings share one calendar day. Two are held and confirmed while the unit
is open and the turnover buffer is 45 minutes; the third is held only after an
uncovered walk-in strains the unit and lifts the buffer to 75. Bumping the first
and cancelling the third must move exactly the numbers frozen at their own hold
instants, leaving the untouched second booking's committed minutes intact.
"""

import pytest

from test_helpers import (
    api_client,
    assert_bed,
    assert_induction_booking,
    assert_instant_is_null,
    assert_obstetric_unit,
    bootstrap_unit,
    confirm_booking,
    create_booking,
    create_encounter,
    get_success_data,
    hold_booking,
    reload_booking,
    setup_validated_drill,
)

CLOCK_START = "2026-08-26T06:00:00Z"
DRILL_SCHEDULED = "2026-08-26T06:05:00Z"
DRILL_INCISION = "2026-08-26T06:24:00Z"
CLOCK_DOCUMENT = "2026-08-26T06:30:00Z"

INDUCTION_DAY = "2026-08-27"
P_START = "2026-08-27T08:00:00Z"
R_START = "2026-08-27T18:00:00Z"
Q_START = "2026-08-27T20:00:00Z"

P_LABOR_MINUTES = 600
R_LABOR_MINUTES = 120
Q_LABOR_MINUTES = 300

P_PROJECTION = 645
R_PROJECTION = 165
Q_PROJECTION = 375

OPEN_BUFFER = 45
STRAINED_BUFFER = 75

LEDGER_STAFF = {
    "charge": {
        "full_name": "Isadora Wachtmeister RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Ptolemy Bashorun MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Wilhelmina Osei-Bonsu MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Ottilie Vandersteen RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def two_releases_against_three_frozen_projections():
    """Two bookings frozen at a 45-minute buffer, one frozen at 75, then a bump of
    the first and a cancellation of the third."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=5,
        or_rooms=1,
        max_daily_induction_bed_minutes=5000,
        bed_specs=[
            ("LDR-01", "LDR"),
            ("LDR-02", "LDR"),
            ("LDR-03", "LDR"),
            ("LDR-04", "LDR"),
            ("LDR-05", "LDR"),
        ],
        staff_specs=LEDGER_STAFF,
        unit_overrides={"unit_name": "Kestrelmoor Regional Maternity"},
    )
    setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at=DRILL_SCHEDULED,
        incision_at=DRILL_INCISION,
        document_clock=CLOCK_DOCUMENT,
    )
    booking_p = create_booking(
        world,
        patient_record_code="PRC-IND-7701",
        gestational_age_weeks=39,
        indication_code="GDM_CONTROLLED",
        requested_start_utc=P_START,
        expected_labor_minutes=P_LABOR_MINUTES,
    )
    booking_r = create_booking(
        world,
        patient_record_code="PRC-IND-7702",
        gestational_age_weeks=39,
        indication_code="GDM_CONTROLLED",
        requested_start_utc=R_START,
        expected_labor_minutes=R_LABOR_MINUTES,
    )
    booking_q = create_booking(
        world,
        patient_record_code="PRC-IND-7703",
        gestational_age_weeks=39,
        indication_code="GDM_CONTROLLED",
        requested_start_utc=Q_START,
        expected_labor_minutes=Q_LABOR_MINUTES,
    )
    held_p = hold_booking(world, booking_p, "LDR-01")
    confirm_booking(world, booking_p)
    held_r = hold_booking(world, booking_r, "LDR-02")
    confirm_booking(world, booking_r)

    create_encounter(
        world,
        patient_record_code="PRC-WALK-7710",
        parity=1,
        gestational_age_weeks=39,
        prior_cesarean=False,
        fetus_count=1,
        presentation="VERTEX",
    )
    unit_at_q_hold = world.reload_unit()
    held_q = hold_booking(world, booking_q, "LDR-03")
    unit_before_release = world.reload_unit()

    bumped = get_success_data(
        api_client.bump_booking(booking_p["id"], world.charge_headers)
    )
    cancelled = get_success_data(
        api_client.cancel_booking(booking_q["id"], world.access_headers)
    )
    return {
        "world": world,
        "booking_p": booking_p,
        "booking_r": booking_r,
        "booking_q": booking_q,
        "held_p": held_p,
        "held_r": held_r,
        "held_q": held_q,
        "unit_at_q_hold": unit_at_q_hold,
        "unit_before_release": unit_before_release,
        "bumped": bumped,
        "cancelled": cancelled,
    }


def test_the_first_two_projections_freeze_at_the_open_buffer(
    two_releases_against_three_frozen_projections,
):
    """"This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`,
    and that frozen integer is the exact quantum every later credit and debit
    moves."

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    setup = two_releases_against_three_frozen_projections
    assert_induction_booking(setup["held_p"])
    assert_induction_booking(setup["held_r"])
    assert setup["held_p"]["projected_occupancy_minutes"] == P_PROJECTION
    assert setup["held_p"]["expected_labor_minutes"] == P_LABOR_MINUTES
    assert setup["held_r"]["projected_occupancy_minutes"] == R_PROJECTION
    assert setup["held_r"]["expected_labor_minutes"] == R_LABOR_MINUTES


def test_the_third_projection_freezes_at_the_strained_buffer(
    two_releases_against_three_frozen_projections,
):
    """An uncovered walk-in makes the deficit positive, and "`RATIO_STRAINED` when
    the deficit is greater than 0.0", after which "`turnover_buffer_minutes` is
    set to 45 when the posture is `OPEN` and 75 otherwise" — so the third hold
    freezes 75 minutes of buffer, not 45.

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    setup = two_releases_against_three_frozen_projections
    unit = setup["unit_at_q_hold"]
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.5, abs=1e-9)
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER
    assert setup["held_q"]["projected_occupancy_minutes"] == Q_PROJECTION
    assert setup["held_q"]["expected_labor_minutes"] == Q_LABOR_MINUTES


def test_the_two_ledgers_start_split_across_the_same_day(
    two_releases_against_three_frozen_projections,
):
    """"`CAPACITY_HELD` bookings are summed into the held map and `CONFIRMED` and
    `ADMITTED` bookings into the committed map, each keyed by the UTC date of
    `requested_start_utc`."

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    unit = two_releases_against_three_frozen_projections["unit_before_release"]
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == (
        P_PROJECTION + R_PROJECTION
    )
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == Q_PROJECTION


def test_the_bump_takes_back_exactly_the_frozen_six_forty_five(
    two_releases_against_three_frozen_projections,
):
    """A bump "moves the booking to `BUMPED`, increments `bump_count`, clears
    `bed_id` and `hold_expires_at`, returns the bed from `HELD` to `AVAILABLE`,
    and decrements exactly `projected_occupancy_minutes` from the held map when
    the booking was held or from the committed map when it was confirmed."

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    setup = two_releases_against_three_frozen_projections
    booking = reload_booking(setup["world"], setup["booking_p"]["id"])
    assert_induction_booking(booking)
    assert booking["status"] == "BUMPED"
    assert booking["bump_count"] == 1
    assert booking["bed_id"] is None
    assert_instant_is_null(booking["hold_expires_at"], "hold_expires_at")
    assert booking["projected_occupancy_minutes"] == P_PROJECTION
    assert booking["priority_class"] == "ELECTIVE_39_WEEK"


def test_the_cancellation_takes_back_exactly_the_frozen_three_seventy_five(
    two_releases_against_three_frozen_projections,
):
    """"A cancellation, also a `PatientAccessCoordinator` act, is available from
    `REQUESTED`, `CAPACITY_HELD` or `CONFIRMED`, releases any held bed and credits
    back exactly `projected_occupancy_minutes`" — the 375 frozen at its own hold,
    not the 345 a creation-time buffer would have produced.

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    setup = two_releases_against_three_frozen_projections
    booking = reload_booking(setup["world"], setup["booking_q"]["id"])
    assert_induction_booking(booking)
    assert booking["status"] == "CANCELLED"
    assert booking["bed_id"] is None
    assert booking["bump_count"] == 0
    assert booking["projected_occupancy_minutes"] == Q_PROJECTION


def test_the_untouched_booking_keeps_its_committed_minutes(
    two_releases_against_three_frozen_projections,
):
    """The control booking is never addressed, so it stays `CONFIRMED` on its own
    bed and its own frozen quantum, and "the bed stays `HELD`" as confirmation
    left it.

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    setup = two_releases_against_three_frozen_projections
    world = setup["world"]
    booking = reload_booking(world, setup["booking_r"]["id"])
    assert booking["status"] == "CONFIRMED"
    assert booking["bed_id"] == world.bed_id("LDR-02")
    assert booking["projected_occupancy_minutes"] == R_PROJECTION
    bed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-02"), world.charge_headers)
    )
    assert_bed(bed)
    assert bed["status"] == "HELD"
    assert bed["held_booking_id"] == booking["id"]


def test_both_released_beds_come_back_available(
    two_releases_against_three_frozen_projections,
):
    """Each release "returns the bed from `HELD` to `AVAILABLE`", and a bed that is
    `AVAILABLE` carries no `held_booking_id`.

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    world = two_releases_against_three_frozen_projections["world"]
    for label in ("LDR-01", "LDR-03"):
        bed = get_success_data(
            api_client.get_bed(world.bed_id(label), world.charge_headers)
        )
        assert_bed(bed)
        assert bed["status"] == "AVAILABLE", label
        assert bed["held_booking_id"] is None, label


def test_the_day_ledger_lands_on_the_control_booking_alone(
    two_releases_against_three_frozen_projections,
):
    """"Bookings in `REQUESTED`, `BUMPED`, `CANCELLED` and `EXPIRED` all contribute
    zero minutes to both ledgers" — so the day's committed minutes are the control
    booking's frozen figure and the held map is empty.

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    unit = two_releases_against_three_frozen_projections["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == R_PROJECTION
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0


def test_releasing_bed_minutes_never_moves_the_coverage_posture(
    two_releases_against_three_frozen_projections,
):
    """`coverage_deficit_units` is the sum "of the larger of 0.0 and
    `required_coverage_units` less `assigned_coverage_units`" over the unit's
    non-terminal encounters, which no bed-minute credit can touch, so the strained
    posture and its 75-minute buffer survive both releases.

    Design: Difficulty/compensating_invariant/bump_and_cancel_credit_back_the_hold_time_frozen_645_and_375_while_the_untouched_165_stays_committed
    """
    unit = two_releases_against_three_frozen_projections["world"].reload_unit()
    assert unit["coverage_deficit_units"] == pytest.approx(0.5, abs=1e-9)
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER
