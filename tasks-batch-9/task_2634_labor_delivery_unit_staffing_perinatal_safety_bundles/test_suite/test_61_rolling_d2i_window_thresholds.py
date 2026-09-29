"""Six measurements, one sliding window of three, and both ceilings walked to the penny.

The readiness state is the one rate in this domain: not a running total and not
an instantaneous reading, but a mean over the last three measured events,
compared against two ceilings the contract calls strict. This module walks a
single unit through every declared edge of that rate — the empty window that is
explicitly not a failure, a mean sitting exactly on 30.00 that stays READY, a
mean sitting exactly on 45.00 that stops at DEGRADED, a fourth measurement that
pushes the oldest reading out and makes the mean rise where a lifetime average
would fall, a backdated incision that is a perfectly valid measurement yet never
enters the window at all, and finally a genuinely newer fast event that lifts the
unit back out of NOT_READY with no drill, roster or administrative act in
between. Every event is a crash section, which bypasses the readiness
precondition on mobilisation, so the rate is measured by itself and never gated
by itself.
"""

import pytest

from test_helpers import (
    api_client,
    assert_cesarean_event,
    assert_drill,
    assert_instant_equals,
    assert_obstetric_unit,
    bootstrap_unit,
    create_active_shift,
    create_encounter,
    get_success_data,
    set_clock,
    setup_validated_drill,
)

CLOCK_BOOTSTRAP = "2026-08-01T05:45:00Z"
CLOCK_DRILL_DUE = "2026-08-01T05:50:00Z"
DRILL_SCHEDULED_FOR = "2026-08-01T05:50:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:52:00Z"
SIMULATED_INCISION_AT = "2026-08-01T05:55:00Z"
CLOCK_ROSTERED = "2026-08-01T06:00:00Z"
SHIFT_WINDOW = ("2026-08-01T06:00:00Z", "2026-08-01T12:00:00Z")
DECISION_AT_OPENING_FIVE = "2026-08-01T06:00:00Z"
CLOCK_FIRST_INCISIONS = "2026-08-01T06:30:00Z"
CLOCK_THIRD_INCISION = "2026-08-01T07:15:00Z"
INCISION_ONE = "2026-08-01T06:30:00Z"
INCISION_TWO = "2026-08-01T06:30:00Z"
INCISION_THREE = "2026-08-01T07:15:00Z"
INCISION_FOUR = "2026-08-01T06:31:00Z"
INCISION_FIVE = "2026-08-01T06:20:00Z"
CLOCK_SIXTH_DECLARED = "2026-08-01T07:16:00Z"
CLOCK_SIXTH_INCISION = "2026-08-01T07:30:00Z"
INCISION_SIX = "2026-08-01T07:30:00Z"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
UNIT_NAME = "Bellcairn Perinatal Center LDR"

CRASH_TARGET_MINUTES = 15
DRILL_MEASURED_MINUTES = 3
ROLLING_EVENT_WINDOW = 3
READY_CEILING = 30.00
DEGRADED_CEILING = 45.00

D2I_ONE = 30
D2I_TWO = 30
D2I_THREE = 75
D2I_FOUR = 31
D2I_FIVE = 20
D2I_SIX = 14

MEAN_ON_THE_READY_CEILING = 30.00
MEAN_ON_THE_DEGRADED_CEILING = 45.00
MEAN_OVER_THE_DEGRADED_CEILING = 45.33
MEAN_AFTER_THE_WINDOW_SLID = 40.00
LIFETIME_MEAN_OF_THE_FIRST_FOUR = 41.50

BELLCAIRN_STAFF = {
    "charge": {
        "full_name": "Marisol Bellcairn RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Rosalind Ekwueme MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Tobias Marchetti MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "tech": {
        "full_name": "Yusra Delacroix ST",
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "neonatal": {
        "full_name": "Ephraim Nakashima NNP",
        "staff_role": "NEONATAL_RESUSCITATOR",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Hesper Oyelaran RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_unit_walked_through_six_measurements():
    """One unit, six theatres, six crash events and six readings of the same rate.

    Every encounter is admitted before the first declaration, because a declared
    event drives the unit into `DIVERT` and a diverting unit refuses new
    walk-ins; every event gets its own operating room, because mobilisation
    takes a room to `OCCUPIED` and this run never records a delivery. No
    induction booking exists anywhere, so the drop to `NOT_READY` has nothing to
    bump and cannot perturb a reading.
    """
    world = bootstrap_unit(
        clock=CLOCK_BOOTSTRAP,
        ldr_beds=8,
        or_rooms=6,
        bed_specs=[
            ("LDR-01", "LDR"),
            ("LDR-02", "LDR"),
            ("OR-01", "OR"),
            ("OR-02", "OR"),
            ("OR-03", "OR"),
            ("OR-04", "OR"),
            ("OR-05", "OR"),
            ("OR-06", "OR"),
        ],
        staff_specs=BELLCAIRN_STAFF,
        unit_overrides={"unit_name": UNIT_NAME},
    )
    set_clock(CLOCK_DRILL_DUE)
    drill = setup_validated_drill(
        world,
        DRILL_SCHEDULED_FOR,
        SIMULATED_DECISION_AT,
        SIMULATED_INCISION_AT,
        participant_keys=["ob", "anesthesia", "tech"],
        document_clock=CLOCK_ROSTERED,
    )
    create_active_shift(world, "tech", "OR_STANDBY", *SHIFT_WINDOW)
    create_active_shift(world, "anesthesia", "TRIAGE", *SHIFT_WINDOW)
    create_active_shift(world, "neonatal", "TRIAGE", *SHIFT_WINDOW)
    encounters = [
        create_encounter(
            world,
            patient_record_code=f"PRC-BELL-310{index}",
            parity=1,
            gestational_age_weeks=39,
        )
        for index in range(1, 7)
    ]
    theatre_team = [
        world.staff_id("anesthesia"),
        world.staff_id("tech"),
        world.staff_id("neonatal"),
    ]
    events = []
    for encounter in encounters[:5]:
        events.append(
            get_success_data(
                api_client.create_cesarean(
                    {
                        "encounter_id": encounter["id"],
                        "urgency_class": "CATEGORY_1_CRASH",
                    },
                    world.ob_headers,
                )
            )
        )
    for index, event in enumerate(events, start=1):
        get_success_data(
            api_client.mobilize_team(
                event["id"],
                {
                    "or_bed_id": world.bed_id(f"OR-0{index}"),
                    "staff_ids": theatre_team,
                },
                world.ob_headers,
            )
        )
    unit_at_the_empty_window = world.reload_unit()

    def measure(event, incision_at):
        return get_success_data(
            api_client.record_incision(
                event["id"], {"incision_at": incision_at}, world.ob_headers
            )
        )

    set_clock(CLOCK_FIRST_INCISIONS)
    incision_one = measure(events[0], INCISION_ONE)
    unit_after_one = world.reload_unit()
    incision_two = measure(events[1], INCISION_TWO)
    unit_after_two = world.reload_unit()
    set_clock(CLOCK_THIRD_INCISION)
    incision_three = measure(events[2], INCISION_THREE)
    unit_after_three = world.reload_unit()
    incision_four = measure(events[3], INCISION_FOUR)
    unit_after_four = world.reload_unit()
    incision_five = measure(events[4], INCISION_FIVE)
    unit_after_five = world.reload_unit()
    set_clock(CLOCK_SIXTH_DECLARED)
    sixth_event = get_success_data(
        api_client.create_cesarean(
            {"encounter_id": encounters[5]["id"], "urgency_class": "CATEGORY_1_CRASH"},
            world.ob_headers,
        )
    )
    sixth_mobilisation = api_client.mobilize_team(
        sixth_event["id"],
        {"or_bed_id": world.bed_id("OR-06"), "staff_ids": theatre_team},
        world.ob_headers,
    )
    set_clock(CLOCK_SIXTH_INCISION)
    incision_six = measure(sixth_event, INCISION_SIX)
    unit_at_the_end = world.reload_unit()
    return {
        "world": world,
        "drill": drill,
        "encounters": encounters,
        "events": events,
        "unit_at_the_empty_window": unit_at_the_empty_window,
        "incision_one": incision_one,
        "unit_after_one": unit_after_one,
        "incision_two": incision_two,
        "unit_after_two": unit_after_two,
        "incision_three": incision_three,
        "unit_after_three": unit_after_three,
        "incision_four": incision_four,
        "unit_after_four": unit_after_four,
        "incision_five": incision_five,
        "unit_after_five": unit_after_five,
        "sixth_event": sixth_event,
        "sixth_mobilisation": sixth_mobilisation,
        "incision_six": incision_six,
        "unit_at_the_end": unit_at_the_end,
    }


def test_the_empty_rolling_window_is_not_a_failure(
    one_unit_walked_through_six_measurements,
):
    """"The empty rolling window is not a failure: a unit with a current validated drill,
    standby staffed and no measured emergency events at all is `READY`." Also:
    "`mean_d2i_minutes` is null when that set is empty, and otherwise the sum of their
    `decision_to_incision_minutes` divided by the count of them, rounded to 2 decimal places
    half-up."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    drill = setup["drill"]
    assert_drill(drill)
    assert drill["status"] == "VALIDATED"
    assert drill["measured_d2i_minutes"] == DRILL_MEASURED_MINUTES
    unit = setup["unit_at_the_empty_window"]
    assert_obstetric_unit(unit)
    assert unit["current_drill_id"] == drill["id"]
    assert unit["mean_d2i_minutes"] is None
    assert unit["cesarean_readiness_state"] == "READY"


def test_the_first_measurement_truncates_and_misses_the_crash_target(
    one_unit_walked_through_six_measurements,
):
    """"`decision_to_incision_minutes` is the number of whole minutes in the interval from
    `decision_at` to `incision_at`, obtained by dividing the elapsed seconds by 60 and
    discarding any remainder — the figure always truncates downward and is never rounded up."
    Also: "The `urgency_class` is immutable, because it fixes the decision-to-incision target
    at 15 minutes for `CATEGORY_1_CRASH` and 30 minutes for `CATEGORY_2_URGENT`."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    measured = setup["incision_one"]
    assert_cesarean_event(measured)
    assert measured["status"] == "INCISION_RECORDED"
    assert_instant_equals(
        measured["decision_at"], DECISION_AT_OPENING_FIVE, "decision_at"
    )
    assert_instant_equals(measured["incision_at"], INCISION_ONE, "incision_at")
    assert measured["decision_to_incision_minutes"] == D2I_ONE
    assert D2I_ONE > CRASH_TARGET_MINUTES
    assert measured["met_target"] is False


def test_the_ready_ceiling_is_strict_on_one_sample(
    one_unit_walked_through_six_measurements,
):
    """"Both ceilings are strict, so a mean of exactly 30.00 stays `READY` and a mean of
    exactly 45.00 stays `DEGRADED`." Also: "The state is then decided by the first matching
    branch: `NOT_READY` when the current drill is null, or when the mean is non-null and
    strictly greater than 45.00; otherwise `DEGRADED` when the standby test is not satisfied,
    or when the mean is non-null and strictly greater than 30.00; otherwise `READY`."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    unit = setup["unit_after_one"]
    assert_obstetric_unit(unit)
    assert unit["mean_d2i_minutes"] == pytest.approx(
        MEAN_ON_THE_READY_CEILING, abs=1e-9
    )
    assert not MEAN_ON_THE_READY_CEILING > READY_CEILING
    assert unit["cesarean_readiness_state"] == "READY"


def test_a_second_identical_sample_cannot_move_a_mean(
    one_unit_walked_through_six_measurements,
):
    """"`mean_d2i_minutes` is null when that set is empty, and otherwise the sum of their
    `decision_to_incision_minutes` divided by the count of them, rounded to 2 decimal places
    half-up." Also: "Both ceilings are strict, so a mean of exactly 30.00 stays `READY` and a
    mean of exactly 45.00 stays `DEGRADED`."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    second = setup["incision_two"]
    assert_cesarean_event(second)
    assert second["decision_to_incision_minutes"] == D2I_TWO
    unit = setup["unit_after_two"]
    assert unit["mean_d2i_minutes"] == pytest.approx(
        MEAN_ON_THE_READY_CEILING, abs=1e-9
    )
    assert (D2I_ONE + D2I_TWO) / 2 == pytest.approx(
        MEAN_ON_THE_READY_CEILING, abs=1e-9
    )
    assert unit["cesarean_readiness_state"] == "READY"


def test_the_degraded_ceiling_is_strict_on_the_third_sample(
    one_unit_walked_through_six_measurements,
):
    """"Both ceilings are strict, so a mean of exactly 30.00 stays `READY` and a mean of
    exactly 45.00 stays `DEGRADED`." Also: "The state is then decided by the first matching
    branch: `NOT_READY` when the current drill is null, or when the mean is non-null and
    strictly greater than 45.00; otherwise `DEGRADED` when the standby test is not satisfied,
    or when the mean is non-null and strictly greater than 30.00; otherwise `READY`."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    third = setup["incision_three"]
    assert_cesarean_event(third)
    assert third["decision_to_incision_minutes"] == D2I_THREE
    unit = setup["unit_after_three"]
    assert unit["mean_d2i_minutes"] == pytest.approx(
        MEAN_ON_THE_DEGRADED_CEILING, abs=1e-9
    )
    assert (D2I_ONE + D2I_TWO + D2I_THREE) / 3 == pytest.approx(
        MEAN_ON_THE_DEGRADED_CEILING, abs=1e-9
    )
    assert not MEAN_ON_THE_DEGRADED_CEILING > DEGRADED_CEILING
    assert unit["current_drill_id"] is not None
    assert unit["cesarean_readiness_state"] == "DEGRADED"


def test_the_window_truncates_at_three_and_is_not_a_lifetime_average(
    one_unit_walked_through_six_measurements,
):
    """"The rolling set is the emergency cesarean events on this unit whose
    `decision_to_incision_minutes` is non-null and whose `status` is `INCISION_RECORDED`,
    `DELIVERED`, `REVIEW_PENDING` or `CLOSED`, ordered by `incision_at` descending with
    `created_at` descending as the tie-break, taking at most the first 3; aborted events,
    having no measurement, never enter it." Also: "`mean_d2i_minutes` is null when that set is
    empty, and otherwise the sum of their `decision_to_incision_minutes` divided by the count
    of them, rounded to 2 decimal places half-up."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    fourth = setup["incision_four"]
    assert_cesarean_event(fourth)
    assert_instant_equals(fourth["incision_at"], INCISION_FOUR, "incision_at")
    assert fourth["decision_to_incision_minutes"] == D2I_FOUR
    unit = setup["unit_after_four"]
    assert_obstetric_unit(unit)
    assert unit["mean_d2i_minutes"] == pytest.approx(
        MEAN_OVER_THE_DEGRADED_CEILING, abs=1e-9
    )
    newest_three = [D2I_THREE, D2I_FOUR, D2I_TWO]
    assert len(newest_three) == ROLLING_EVENT_WINDOW
    assert round(sum(newest_three) / ROLLING_EVENT_WINDOW, 2) == pytest.approx(
        MEAN_OVER_THE_DEGRADED_CEILING, abs=1e-9
    )
    every_measurement = [D2I_ONE, D2I_TWO, D2I_THREE, D2I_FOUR]
    assert sum(every_measurement) / len(every_measurement) == pytest.approx(
        LIFETIME_MEAN_OF_THE_FIRST_FOUR, abs=1e-9
    )
    assert not LIFETIME_MEAN_OF_THE_FIRST_FOUR > DEGRADED_CEILING


def test_crossing_the_degraded_ceiling_lands_the_unit_on_not_ready(
    one_unit_walked_through_six_measurements,
):
    """"The state is then decided by the first matching branch: `NOT_READY` when the current
    drill is null, or when the mean is non-null and strictly greater than 45.00; otherwise
    `DEGRADED` when the standby test is not satisfied, or when the mean is non-null and
    strictly greater than 30.00; otherwise `READY`." Also: "The derivation re-runs on drill
    validation and invalidation, on roster activation, relief and cancellation, on the
    recording of an incision, and in the capacity sweep, and it publishes
    `cesarean_readiness_state`, `readiness_reason`, `current_drill_id`,
    `current_drill_expires_at` and `mean_d2i_minutes` on the unit."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    unit = setup["unit_after_four"]
    assert MEAN_OVER_THE_DEGRADED_CEILING > DEGRADED_CEILING
    assert unit["current_drill_id"] == setup["drill"]["id"]
    assert unit["cesarean_readiness_state"] == "NOT_READY"


def test_a_backdated_measurement_never_enters_the_window(
    one_unit_walked_through_six_measurements,
):
    """"The rolling set is the emergency cesarean events on this unit whose
    `decision_to_incision_minutes` is non-null and whose `status` is `INCISION_RECORDED`,
    `DELIVERED`, `REVIEW_PENDING` or `CLOSED`, ordered by `incision_at` descending with
    `created_at` descending as the tie-break, taking at most the first 3; aborted events,
    having no measurement, never enter it."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    backdated = setup["incision_five"]
    assert_cesarean_event(backdated)
    assert backdated["status"] == "INCISION_RECORDED"
    assert_instant_equals(backdated["incision_at"], INCISION_FIVE, "incision_at")
    assert backdated["decision_to_incision_minutes"] == D2I_FIVE
    assert backdated["incision_at"] < setup["incision_two"]["incision_at"]
    unit = setup["unit_after_five"]
    assert_obstetric_unit(unit)
    assert unit["mean_d2i_minutes"] == pytest.approx(
        MEAN_OVER_THE_DEGRADED_CEILING, abs=1e-9
    )
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    write_ordered_window = [D2I_FIVE, D2I_FOUR, D2I_THREE]
    assert round(
        sum(write_ordered_window) / ROLLING_EVENT_WINDOW, 2
    ) != pytest.approx(MEAN_OVER_THE_DEGRADED_CEILING, abs=1e-9)


def test_a_crash_section_is_mobilised_by_a_unit_its_own_rate_has_condemned(
    one_unit_walked_through_six_measurements,
):
    """"For a `CATEGORY_2_URGENT` event the unit's `cesarean_readiness_state` must not be
    `NOT_READY`, refused otherwise with `ERR_CESAREAN_READINESS_NOT_MET`; a
    `CATEGORY_1_CRASH` event bypasses that check entirely, because a crash section is never
    refused for a paperwork lapse." Also: "Both routes produce an identical row: status
    `DECISION_DECLARED` with `decision_at` at the current instant, the two triggering
    references left null on a clinician declaration unless supplied."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    assert setup["unit_after_five"]["cesarean_readiness_state"] == "NOT_READY"
    declared = setup["sixth_event"]
    assert_cesarean_event(declared)
    assert declared["urgency_class"] == "CATEGORY_1_CRASH"
    assert_instant_equals(
        declared["decision_at"], CLOCK_SIXTH_DECLARED, "decision_at"
    )
    assert declared["triggering_assessment_id"] is None
    assert declared["triggering_activation_id"] is None
    assert setup["sixth_mobilisation"].status_code == 200
    mobilised = get_success_data(setup["sixth_mobilisation"])
    assert_cesarean_event(mobilised)
    assert mobilised["status"] == "TEAM_MOBILIZED"
    assert mobilised["or_bed_id"] == setup["world"].bed_id("OR-06")


def test_the_late_decision_instant_manufactures_a_fast_measurement(
    one_unit_walked_through_six_measurements,
):
    """"`met_target` is true when that figure is less than or equal to the event's target, the
    boundary counting as met: a measurement of exactly 15 on a `CATEGORY_1_CRASH` meets its
    target, and an interval of 30 minutes and 1 second measures 30 whole minutes and still
    meets a 30-minute target, so only 31 whole minutes fails." Also: "Recording the incision
    moves the event from `TEAM_MOBILIZED` to `INCISION_RECORDED` and produces the headline
    measurement."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    fast = setup["incision_six"]
    assert_cesarean_event(fast)
    assert fast["status"] == "INCISION_RECORDED"
    assert_instant_equals(fast["incision_at"], INCISION_SIX, "incision_at")
    assert fast["decision_to_incision_minutes"] == D2I_SIX
    assert D2I_SIX <= CRASH_TARGET_MINUTES
    assert fast["met_target"] is True


def test_the_rate_threshold_recovers_once_the_window_slides(
    one_unit_walked_through_six_measurements,
):
    """"The state is then decided by the first matching branch: `NOT_READY` when the current
    drill is null, or when the mean is non-null and strictly greater than 45.00; otherwise
    `DEGRADED` when the standby test is not satisfied, or when the mean is non-null and
    strictly greater than 30.00; otherwise `READY`." Also: "The rolling set is the emergency
    cesarean events on this unit whose `decision_to_incision_minutes` is non-null and whose
    `status` is `INCISION_RECORDED`, `DELIVERED`, `REVIEW_PENDING` or `CLOSED`, ordered by
    `incision_at` descending with `created_at` descending as the tie-break, taking at most the
    first 3; aborted events, having no measurement, never enter it."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    unit = setup["unit_at_the_end"]
    assert_obstetric_unit(unit)
    assert unit["mean_d2i_minutes"] == pytest.approx(
        MEAN_AFTER_THE_WINDOW_SLID, abs=1e-9
    )
    slid_window = [D2I_SIX, D2I_THREE, D2I_FOUR]
    assert round(sum(slid_window) / ROLLING_EVENT_WINDOW, 2) == pytest.approx(
        MEAN_AFTER_THE_WINDOW_SLID, abs=1e-9
    )
    assert not MEAN_AFTER_THE_WINDOW_SLID > DEGRADED_CEILING
    assert MEAN_AFTER_THE_WINDOW_SLID > READY_CEILING
    assert unit["cesarean_readiness_state"] == "DEGRADED"


def test_nothing_but_the_sliding_window_lifted_the_unit(
    one_unit_walked_through_six_measurements,
):
    """"The current drill is the drill on this unit whose `status` is `VALIDATED` and whose
    `expires_at` is strictly after the current instant, ordered by `validated_at` descending
    with `created_at` descending as the tie-break, taking the first; if none qualifies the
    current drill is null, and `INVALIDATED`, `DOCUMENTED` and `ABANDONED` drills contribute
    nothing."

    Design: Corner/cross_cutting_complexity_layers/rolling_d2i_window_walks_both_readiness_ceilings_and_recovers_once_the_window_slides
    """
    setup = one_unit_walked_through_six_measurements
    world = setup["world"]
    drill = setup["drill"]
    first = setup["unit_at_the_empty_window"]
    last = setup["unit_at_the_end"]
    assert last["current_drill_id"] == drill["id"]
    assert last["current_drill_id"] == first["current_drill_id"]
    assert_instant_equals(
        last["current_drill_expires_at"],
        first["current_drill_expires_at"],
        "current_drill_expires_at",
    )
    still_validated = get_success_data(
        api_client.get_drill(drill["id"], world.charge_headers)
    )
    assert_drill(still_validated)
    assert still_validated["status"] == "VALIDATED"
