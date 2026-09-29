"""An induction booking may traverse the REQUESTED -> CAPACITY_HELD ->
CONFIRMED -> BUMPED -> REQUESTED loop twice, and the second requeue promotes
its priority class on the strength of the bump counter alone.

Lap 1 bumps out of CONFIRMED, so the credit-back leaves the committed ledger;
lap 2 bumps out of CAPACITY_HELD, so the same edge credits the held ledger.
"""

import pytest
from prd_bench_local_runner.testing import validate_error_is_one_of

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_induction_booking,
    assert_obstetric_unit,
    bootstrap_unit,
    confirm_booking,
    create_booking,
    get_success_data,
    hold_booking,
    reload_booking,
    setup_validated_drill,
)

INDUCTION_DAY = "2026-08-05"
REQUESTED_START = "2026-08-05T08:00:00Z"

CYCLE_STAFF = {
    "ob": {"staff_role": "OB_ATTENDING", "fetal_monitoring_cert_level": "ADVANCED"},
    "anesthesia": {"staff_role": "ANESTHESIOLOGIST", "fetal_monitoring_cert_level": "BASIC"},
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "officer": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "BASIC"},
}


def _held(unit) -> int:
    return unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0)


def _committed(unit) -> int:
    return unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0)


@pytest.fixture
def booking_driven_twice_around_the_cycle():
    """Two complete laps of the booking cycle on one quiet unit.

    Two LDR beds and no encounters keep the deficit at 0.0, the posture OPEN
    and the turnover buffer at 45 for the whole fixture, so both holds freeze
    the same projection. One validated drill measured at 22 minutes with no
    OR_STANDBY entry settles readiness at DEGRADED, which confirmation accepts.
    """
    world = bootstrap_unit(
        clock="2026-08-04T09:00:00Z",
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=CYCLE_STAFF,
    )
    drill = setup_validated_drill(
        world,
        scheduled_for_utc="2026-08-04T09:00:00Z",
        decision_at="2026-08-04T09:00:00Z",
        incision_at="2026-08-04T09:22:00Z",
        document_clock="2026-08-04T09:30:00Z",
    )

    booking = create_booking(
        world,
        gestational_age_weeks=39,
        indication_code="GDM_CONTROLLED",
        requested_start_utc=REQUESTED_START,
        expected_labor_minutes=600,
    )
    at_create = dict(booking)

    lap_1_hold = hold_booking(world, booking, bed_label="LDR-01")
    unit_after_lap_1_hold = world.reload_unit()

    confirm_booking(world, booking)
    unit_after_confirm = world.reload_unit()

    lap_1_bump = get_success_data(
        api_client.bump_booking(booking["id"], world.charge_headers)
    )
    unit_after_lap_1_bump = world.reload_unit()

    lap_1_requeue = get_success_data(
        api_client.requeue_booking(booking["id"], world.access_headers)
    )

    lap_2_hold = hold_booking(world, booking, bed_label="LDR-01")
    unit_after_lap_2_hold = world.reload_unit()

    lap_2_bump = get_success_data(
        api_client.bump_booking(booking["id"], world.access_headers)
    )
    unit_after_lap_2_bump = world.reload_unit()

    lap_2_requeue = get_success_data(
        api_client.requeue_booking(booking["id"], world.access_headers)
    )

    return {
        "world": world,
        "drill": drill,
        "booking_id": booking["id"],
        "at_create": at_create,
        "lap_1_hold": lap_1_hold,
        "lap_1_bump": lap_1_bump,
        "lap_1_requeue": lap_1_requeue,
        "lap_2_hold": lap_2_hold,
        "lap_2_bump": lap_2_bump,
        "lap_2_requeue": lap_2_requeue,
        "unit_after_lap_1_hold": unit_after_lap_1_hold,
        "unit_after_confirm": unit_after_confirm,
        "unit_after_lap_1_bump": unit_after_lap_1_bump,
        "unit_after_lap_2_hold": unit_after_lap_2_hold,
        "unit_after_lap_2_bump": unit_after_lap_2_bump,
    }


def test_two_laps_return_the_booking_to_requested_with_the_counter_at_two(
    booking_driven_twice_around_the_cycle,
):
    """"A requeue, a `PatientAccessCoordinator` act, returns a `BUMPED` booking to
    `REQUESTED` and re-derives `priority_class`; it is refused with
    `ERR_INDUCTION_WINDOW_PASSED` once `requested_start_utc` is at or before the
    current instant, and moves no bed-minutes, because bookings in `REQUESTED` and
    `BUMPED` both contribute zero to both maps." Both bumps cleared the
    booking's bed and hold, so the loop closes with nothing reserved.

    Design: Difficulty/non_linear_state_machine/induction_booking_two_laps_of_hold_confirm_bump_requeue_cycle_promotes_to_medically_indicated
    """
    setup = booking_driven_twice_around_the_cycle
    booking = reload_booking(setup["world"], setup["booking_id"])
    assert_induction_booking(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["bump_count"] == 2
    assert booking["bed_id"] is None
    assert booking["hold_expires_at"] is None
    assert booking["encounter_id"] is None
    assert booking["projected_occupancy_minutes"] == 645


def test_the_bump_counter_alone_promotes_the_priority_class(
    booking_driven_twice_around_the_cycle,
):
    """"After that assignment, a `bump_count` of 2 or greater overrides the
    result to `MEDICALLY_INDICATED`, which as a side effect also makes the
    booking unbumpable — a booking that has been pushed aside twice can no
    longer be pushed aside." The indication code and the gestational age never
    move, so nothing but the counter can explain the promotion.

    Design: Difficulty/non_linear_state_machine/induction_booking_two_laps_of_hold_confirm_bump_requeue_cycle_promotes_to_medically_indicated
    """
    setup = booking_driven_twice_around_the_cycle
    assert setup["at_create"]["priority_class"] == "ELECTIVE_39_WEEK"
    assert setup["lap_1_bump"]["bump_count"] == 1
    assert setup["lap_1_requeue"]["priority_class"] == "ELECTIVE_39_WEEK"
    assert setup["lap_2_bump"]["bump_count"] == 2
    assert setup["lap_2_requeue"]["priority_class"] == "MEDICALLY_INDICATED"

    booking = reload_booking(setup["world"], setup["booking_id"])
    assert booking["indication_code"] == "GDM_CONTROLLED"
    assert booking["gestational_age_weeks"] == 39


def test_each_bump_credits_the_ledger_the_booking_was_actually_sitting_in(
    booking_driven_twice_around_the_cycle,
):
    """"A bump, available to a `ChargeNurse` or `PatientAccessCoordinator` from
    `CAPACITY_HELD` or `CONFIRMED`, moves the booking to `BUMPED`, increments
    `bump_count`, clears `bed_id` and `hold_expires_at`, returns the bed from `HELD`
    to `AVAILABLE`, and decrements exactly `projected_occupancy_minutes` from the
    held map when the booking was held or from the committed map when it was
    confirmed." Lap 1 bumps a CONFIRMED booking and lap 2 bumps a held one, so
    the same edge label empties two different maps.

    Design: Difficulty/non_linear_state_machine/induction_booking_two_laps_of_hold_confirm_bump_requeue_cycle_promotes_to_medically_indicated
    """
    setup = booking_driven_twice_around_the_cycle
    assert _held(setup["unit_after_lap_1_hold"]) == 645
    assert _committed(setup["unit_after_lap_1_hold"]) == 0

    assert _held(setup["unit_after_confirm"]) == 0
    assert _committed(setup["unit_after_confirm"]) == 645

    assert _held(setup["unit_after_lap_1_bump"]) == 0
    assert _committed(setup["unit_after_lap_1_bump"]) == 0

    assert _held(setup["unit_after_lap_2_hold"]) == 645
    assert _committed(setup["unit_after_lap_2_hold"]) == 0

    assert _held(setup["unit_after_lap_2_bump"]) == 0
    assert _committed(setup["unit_after_lap_2_bump"]) == 0


def test_both_holds_freeze_the_same_projection_because_the_buffer_never_moves(
    booking_driven_twice_around_the_cycle,
):
    """"This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`,
    and that frozen integer is the exact quantum every later credit and debit
    moves." The quiet unit stays OPEN, so the buffer stays 45 across both laps.

    Design: Difficulty/non_linear_state_machine/induction_booking_two_laps_of_hold_confirm_bump_requeue_cycle_promotes_to_medically_indicated
    """
    setup = booking_driven_twice_around_the_cycle
    assert setup["lap_1_hold"]["projected_occupancy_minutes"] == 645
    assert setup["lap_2_hold"]["projected_occupancy_minutes"] == 645

    unit = setup["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == 45
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_promotion_seals_the_cycle_against_a_third_bump(
    booking_driven_twice_around_the_cycle,
):
    """A bump "is refused with `ERR_INDUCTION_BUMP_LIMIT_REACHED` once
    `bump_count` has reached 2, and refused with `ERR_INDUCTION_NOT_BUMPABLE`
    for a `MEDICALLY_INDICATED` booking." A third lap therefore cannot start:
    the booking may be held again, but it can never be pushed aside again.

    Design: Difficulty/non_linear_state_machine/induction_booking_two_laps_of_hold_confirm_bump_requeue_cycle_promotes_to_medically_indicated
    """
    setup = booking_driven_twice_around_the_cycle
    world = setup["world"]
    booking = reload_booking(world, setup["booking_id"])
    third_hold = hold_booking(world, booking, bed_label="LDR-01")
    assert third_hold["status"] == "CAPACITY_HELD"
    assert third_hold["projected_occupancy_minutes"] == 645

    response = api_client.bump_booking(setup["booking_id"], world.access_headers)
    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_INDUCTION_NOT_BUMPABLE.value,
            ApiErrorId.ERR_INDUCTION_BUMP_LIMIT_REACHED.value,
        ],
    )


def test_the_released_bed_and_the_validated_drill_survive_the_cycle(
    booking_driven_twice_around_the_cycle,
):
    """A bump "returns the bed from `HELD` to `AVAILABLE`", and readiness rests
    on the drill: "`NOT_READY` when the current drill is null, or when the mean
    is non-null and strictly greater than 45.00; otherwise `DEGRADED` when the
    standby test is not satisfied, or when the mean is non-null and strictly
    greater than 30.00; otherwise `READY`."

    Design: Difficulty/non_linear_state_machine/induction_booking_two_laps_of_hold_confirm_bump_requeue_cycle_promotes_to_medically_indicated
    """
    setup = booking_driven_twice_around_the_cycle
    world = setup["world"]
    for label in ("LDR-01", "LDR-02"):
        bed = get_success_data(
            api_client.get_bed(world.bed_id(label), world.charge_headers)
        )
        assert_bed(bed)
        assert bed["status"] == "AVAILABLE"
        assert bed["held_booking_id"] is None

    assert setup["drill"]["measured_d2i_minutes"] == 22
    assert setup["drill"]["status"] == "VALIDATED"
    assert world.reload_unit()["cesarean_readiness_state"] == "DEGRADED"
