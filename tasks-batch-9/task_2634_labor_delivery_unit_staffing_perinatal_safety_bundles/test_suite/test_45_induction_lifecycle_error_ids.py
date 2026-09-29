"""Four induction refusals off one queue of five requests.

The bump rule carries two clauses and the queue is built so each clause can be
reached on its own: a booking that is medically indicated by its indication code
has never been bumped, while a booking driven twice around the hold-bump-requeue
loop is medically indicated only because the counter says so. The requeue
refusal depends on the clock rather than on the booking — the identical call
would have been accepted four hours earlier — and the admission refusal fires
against a booking whose own hold is still perfectly good.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

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
    set_clock,
    setup_validated_drill,
)

CLOCK_START = "2026-08-01T06:00:00Z"
CLOCK_AFTER_THE_START_INSTANT = "2026-08-01T10:00:00Z"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
LABOR_ESTIMATE = 60
OPEN_POSTURE_BUFFER = 45
FROZEN_PROJECTION = LABOR_ESTIMATE + OPEN_POSTURE_BUFFER
INDUCTION_DAY = "2026-08-01"
NEXT_DAY = "2026-08-02"

COPPICE_STAFF = {
    "ob": {
        "full_name": "Dr Renata Falk",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Dr Emeka Nwosu",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "charge": {
        "full_name": "Wilhelmina Osei RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Sabine Rautenberg RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


def _held(unit, day=INDUCTION_DAY) -> int:
    return unit["held_bed_minutes_by_day"].get(day, 0)


def _committed(unit, day=INDUCTION_DAY) -> int:
    return unit["committed_bed_minutes_by_day"].get(day, 0)


def _bed(world, bed_label) -> dict:
    return get_success_data(
        api_client.get_bed(world.bed_id(bed_label), world.charge_headers)
    )


@pytest.fixture
def five_requests_walked_into_four_refusals():
    """One queue of five requests on a unit that stays OPEN throughout.

    Four LDR beds mean the free-bed count never reaches zero, so the posture
    never flips and the turnover buffer never moves off 45. A validated drill
    measured at ten minutes with no OR_STANDBY entry on the roster settles
    readiness at DEGRADED, which is good enough to confirm a booking.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=5,
        or_rooms=1,
        bed_specs=[
            ("LDR-01", "LDR"),
            ("LDR-02", "LDR"),
            ("LDR-03", "LDR"),
            ("LDR-04", "LDR"),
        ],
        staff_specs=COPPICE_STAFF,
        unit_overrides={"unit_name": "Coppice Hollow Maternity LDR"},
    )
    drill = setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at="2026-08-01T05:50:00Z",
        incision_at=CLOCK_START,
    )
    unit_before_any_hold = world.reload_unit()

    def _request(patient_record_code, weeks, indication_code, start):
        return create_booking(
            world,
            patient_record_code=patient_record_code,
            gestational_age_weeks=weeks,
            indication_code=indication_code,
            requested_start_utc=start,
            expected_labor_minutes=LABOR_ESTIMATE,
        )

    elective = _request(
        "PRC-COPP-4401", 38, "ELECTIVE_NO_INDICATION", "2026-08-01T12:00:00Z"
    )
    indicated = _request("PRC-COPP-4402", 39, "PREECLAMPSIA", "2026-08-01T12:00:00Z")
    cycled = _request("PRC-COPP-4403", 39, "GDM_CONTROLLED", "2026-08-01T20:00:00Z")
    overtaken = _request("PRC-COPP-4404", 39, "GDM_CONTROLLED", "2026-08-01T09:00:00Z")
    tomorrow = _request("PRC-COPP-4405", 39, "PREECLAMPSIA", "2026-08-02T00:00:00Z")

    indicated_hold = hold_booking(world, indicated, bed_label="LDR-01")
    unit_after_one_hold = world.reload_unit()
    never_bumped = api_client.bump_booking(indicated["id"], world.charge_headers)

    hold_booking(world, cycled, bed_label="LDR-02")
    first_bump = get_success_data(
        api_client.bump_booking(cycled["id"], world.charge_headers)
    )
    first_requeue = get_success_data(
        api_client.requeue_booking(cycled["id"], world.access_headers)
    )
    hold_booking(world, cycled, bed_label="LDR-02")
    second_bump = get_success_data(
        api_client.bump_booking(cycled["id"], world.charge_headers)
    )
    second_requeue = get_success_data(
        api_client.requeue_booking(cycled["id"], world.access_headers)
    )
    third_hold = hold_booking(world, cycled, bed_label="LDR-02")
    third_bump = api_client.bump_booking(cycled["id"], world.charge_headers)

    hold_booking(world, overtaken, bed_label="LDR-03")
    get_success_data(api_client.bump_booking(overtaken["id"], world.access_headers))
    set_clock(CLOCK_AFTER_THE_START_INSTANT)
    late_requeue = api_client.requeue_booking(overtaken["id"], world.access_headers)

    hold_booking(world, tomorrow, bed_label="LDR-04")
    confirmed = confirm_booking(world, tomorrow)
    early_admission = api_client.admit_booking(tomorrow["id"], world.charge_headers)
    unit_at_the_end = world.reload_unit()
    return {
        "world": world,
        "drill": drill,
        "unit_before_any_hold": unit_before_any_hold,
        "unit_after_one_hold": unit_after_one_hold,
        "unit_at_the_end": unit_at_the_end,
        "elective": elective,
        "indicated": indicated,
        "cycled": cycled,
        "overtaken": overtaken,
        "tomorrow": tomorrow,
        "indicated_hold": indicated_hold,
        "never_bumped": never_bumped,
        "first_bump": first_bump,
        "first_requeue": first_requeue,
        "second_bump": second_bump,
        "second_requeue": second_requeue,
        "third_hold": third_hold,
        "third_bump": third_bump,
        "late_requeue": late_requeue,
        "confirmed": confirmed,
        "early_admission": early_admission,
    }


def test_the_priority_ladder_is_read_off_the_indication_and_the_weeks(
    five_requests_walked_into_four_refusals,
):
    """"It is `MEDICALLY_INDICATED` when `indication_code` is `PREECLAMPSIA`,
    `POST_DATES_41W`, `FGR` or `PROM`. It is `ELECTIVE_39_WEEK` when `indication_code`
    is `GDM_CONTROLLED` or `ELECTIVE_NO_INDICATION` and `gestational_age_weeks` is 39 or
    greater. It is `PATIENT_REQUEST` otherwise."

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    assert setup["elective"]["priority_class"] == "PATIENT_REQUEST"
    assert setup["indicated"]["priority_class"] == "MEDICALLY_INDICATED"
    assert setup["cycled"]["priority_class"] == "ELECTIVE_39_WEEK"
    assert setup["overtaken"]["priority_class"] == "ELECTIVE_39_WEEK"
    assert setup["tomorrow"]["priority_class"] == "MEDICALLY_INDICATED"
    for key in ("elective", "indicated", "cycled", "overtaken", "tomorrow"):
        booking = setup[key]
        assert_induction_booking(booking)
        assert booking["status"] == "REQUESTED"
        assert booking["bump_count"] == 0
        assert booking["projected_occupancy_minutes"] is None


def test_the_hold_freezes_the_estimate_plus_the_open_posture_buffer(
    five_requests_walked_into_four_refusals,
):
    """"This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`, and that
    frozen integer is the exact quantum every later credit and debit moves." The unit
    keeps free beds and carries no coverage deficit, so "`turnover_buffer_minutes` is
    set to 45 when the posture is `OPEN` and 75 otherwise" resolves to 45.

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    before = setup["unit_before_any_hold"]
    assert_obstetric_unit(before)
    assert before["cesarean_readiness_state"] == "DEGRADED"
    assert before["turnover_buffer_minutes"] == OPEN_POSTURE_BUFFER
    assert before["staffing_posture"] == "OPEN"
    assert setup["drill"]["measured_d2i_minutes"] == 10
    held = setup["indicated_hold"]
    assert_induction_booking(held)
    assert held["status"] == "CAPACITY_HELD"
    assert held["projected_occupancy_minutes"] == FROZEN_PROJECTION
    assert _held(setup["unit_after_one_hold"]) == FROZEN_PROJECTION
    assert _committed(setup["unit_after_one_hold"]) == 0


def test_a_booking_indicated_by_its_own_diagnosis_is_never_bumpable(
    five_requests_walked_into_four_refusals,
):
    """"It is refused with `ERR_INDUCTION_BUMP_LIMIT_REACHED` once `bump_count` has
    reached 2, and refused with `ERR_INDUCTION_NOT_BUMPABLE` for a
    `MEDICALLY_INDICATED` booking." This booking has never been bumped, so only the
    second clause can be the reason.

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    refused = setup["never_bumped"]
    validate_error(refused, ApiErrorId.ERR_INDUCTION_NOT_BUMPABLE.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INDUCTION_BUMP_LIMIT_REACHED.value
    )
    still_held = reload_booking(setup["world"], setup["indicated"]["id"])
    assert_induction_booking(still_held)
    assert still_held["status"] == "CAPACITY_HELD"
    assert still_held["bump_count"] == 0
    assert still_held["bed_id"] == setup["world"].bed_id("LDR-01")


def test_two_full_laps_promote_the_class_on_the_counter_alone(
    five_requests_walked_into_four_refusals,
):
    """"After that assignment, a `bump_count` of 2 or greater overrides the result to
    `MEDICALLY_INDICATED`, which as a side effect also makes the booking unbumpable — a
    booking that has been pushed aside twice can no longer be pushed aside."

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    assert setup["first_bump"]["bump_count"] == 1
    assert setup["first_bump"]["status"] == "BUMPED"
    assert setup["first_requeue"]["status"] == "REQUESTED"
    assert setup["first_requeue"]["priority_class"] == "ELECTIVE_39_WEEK"
    assert setup["second_bump"]["bump_count"] == 2
    assert setup["second_requeue"]["status"] == "REQUESTED"
    assert setup["second_requeue"]["priority_class"] == "MEDICALLY_INDICATED"
    promoted = reload_booking(setup["world"], setup["cycled"]["id"])
    assert_induction_booking(promoted)
    assert promoted["indication_code"] == "GDM_CONTROLLED"
    assert promoted["gestational_age_weeks"] == 39


def test_the_third_bump_is_refused_by_the_induction_lifecycle_rule(
    five_requests_walked_into_four_refusals,
):
    """"**8.09** induction lifecycle guards, yielding `ERR_INDUCTION_HOLD_EXPIRED`,
    `ERR_INDUCTION_BUMP_LIMIT_REACHED`, `ERR_INDUCTION_NOT_BUMPABLE`,
    `ERR_INDUCTION_WINDOW_PASSED` or `ERR_INDUCTION_ALREADY_ADMITTED`, on induction
    confirmation, bump, requeue and cancellation." Two laps have armed both bump clauses
    of that one rule at once, and it answers with one of them at its own status.

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    refused = setup["third_bump"]
    assert refused.status_code == 409
    validate_error_is_one_of(
        refused,
        [
            ApiErrorId.ERR_INDUCTION_BUMP_LIMIT_REACHED.value,
            ApiErrorId.ERR_INDUCTION_NOT_BUMPABLE.value,
        ],
    )
    assert setup["third_hold"]["status"] == "CAPACITY_HELD"
    assert setup["third_hold"]["projected_occupancy_minutes"] == FROZEN_PROJECTION
    world = setup["world"]
    survivor = reload_booking(world, setup["cycled"]["id"])
    assert survivor["status"] == "CAPACITY_HELD"
    assert survivor["bump_count"] == 2
    reserved = _bed(world, "LDR-02")
    assert_bed(reserved)
    assert reserved["status"] == "HELD"
    assert reserved["held_booking_id"] == setup["cycled"]["id"]


def test_a_requeue_after_the_requested_start_instant_is_refused(
    five_requests_walked_into_four_refusals,
):
    """"A requeue, a `PatientAccessCoordinator` act, returns a `BUMPED` booking to
    `REQUESTED` and re-derives `priority_class`; it is refused with
    `ERR_INDUCTION_WINDOW_PASSED` once `requested_start_utc` is at or before the current
    instant, and moves no bed-minutes, because bookings in `REQUESTED` and `BUMPED` both
    contribute zero to both maps."

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    validate_error(
        setup["late_requeue"], ApiErrorId.ERR_INDUCTION_WINDOW_PASSED.value, 409
    )
    world = setup["world"]
    stranded = reload_booking(world, setup["overtaken"]["id"])
    assert_induction_booking(stranded)
    assert stranded["status"] == "BUMPED"
    assert stranded["bump_count"] == 1
    assert stranded["bed_id"] is None
    assert stranded["hold_expires_at"] is None
    released = _bed(world, "LDR-03")
    assert_bed(released)
    assert released["status"] == "AVAILABLE"
    assert released["held_booking_id"] is None


def test_an_admission_earlier_than_the_thirty_minute_window_is_refused(
    five_requests_walked_into_four_refusals,
):
    """"Admission is a `ChargeNurse` act moving `CONFIRMED` to `ADMITTED`, permitted
    from 30 minutes before `requested_start_utc` onwards, with that boundary instant
    itself allowed and anything earlier refused as `ERR_INDUCTION_ADMIT_TOO_EARLY`."

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    assert setup["confirmed"]["status"] == "CONFIRMED"
    assert setup["confirmed"]["hold_expires_at"] is None
    validate_error(
        setup["early_admission"], ApiErrorId.ERR_INDUCTION_ADMIT_TOO_EARLY.value, 422
    )
    world = setup["world"]
    unadmitted = reload_booking(world, setup["tomorrow"]["id"])
    assert_induction_booking(unadmitted)
    assert unadmitted["status"] == "CONFIRMED"
    assert unadmitted["encounter_id"] is None
    assert unadmitted["bed_id"] == world.bed_id("LDR-04")
    reserved = _bed(world, "LDR-04")
    assert_bed(reserved)
    assert reserved["status"] == "HELD"
    assert reserved["current_encounter_id"] is None


def test_the_two_ledgers_hold_only_the_bookings_that_still_reserve_something(
    five_requests_walked_into_four_refusals,
):
    """"Bookings in `REQUESTED`, `BUMPED`, `CANCELLED` and `EXPIRED` all contribute zero
    minutes to both ledgers, while `CAPACITY_HELD` bookings are summed into the held map
    and `CONFIRMED` and `ADMITTED` bookings into the committed map, each keyed by the UTC
    date of `requested_start_utc`."

    Design: Corner/errors/five_induction_lifecycle_ids_across_two_full_bump_laps_one_clock_advance_and_one_elective_38_week
    """
    setup = five_requests_walked_into_four_refusals
    unit = setup["unit_at_the_end"]
    assert_obstetric_unit(unit)
    assert _held(unit) == 2 * FROZEN_PROJECTION
    assert _committed(unit) == 0
    assert _committed(unit, NEXT_DAY) == FROZEN_PROJECTION
    assert _held(unit, NEXT_DAY) == 0
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == OPEN_POSTURE_BUFFER
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    untouched = reload_booking(setup["world"], setup["elective"]["id"])
    assert_induction_booking(untouched)
    assert untouched["status"] == "REQUESTED"
    assert untouched["bed_id"] is None
    assert untouched["projected_occupancy_minutes"] is None
