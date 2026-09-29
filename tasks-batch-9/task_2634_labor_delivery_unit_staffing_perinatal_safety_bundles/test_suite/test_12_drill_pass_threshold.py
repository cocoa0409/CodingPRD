"""The drill pass threshold is a floor against an inclusive ceiling.

Two drills documented one second apart land on opposite sides of it: thirty
minutes and fifty-nine seconds truncates to a measured thirty and passes,
while thirty-one minutes flat truncates to thirty-one and is refused.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_drill,
    assert_instant_equals,
    assert_instant_is_null,
    assert_obstetric_unit,
    assert_staff_member,
    bootstrap_unit,
    get_success_data,
    set_clock,
)

DRILL_DAY_START = "2026-08-18T06:00:00Z"
DOCUMENT_CLOCK = "2026-08-18T08:00:00Z"
SIMULATED_DECISION = "2026-08-18T06:00:00Z"
INCISION_PASSING = "2026-08-18T06:30:59Z"
INCISION_FAILING = "2026-08-18T06:31:00Z"
EXPECTED_EXPIRY = "2026-11-16T08:00:00Z"

DRILL_STAFF = {
    "ob": {
        "full_name": "Eleftheria Vasilakis MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-10-31T00:00:00Z",
        "or_circulating_qualified": True,
    },
    "anesthesia": {
        "full_name": "Jaroslaw Wisniewski MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-10-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "charge": {
        "full_name": "Marguerite Delacroix RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-10-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Nkechi Obiageli RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-10-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


def _schedule(world):
    return get_success_data(
        api_client.create_drill(
            world.unit_id,
            {
                "drill_type": "DECISION_TO_INCISION",
                "scheduled_for_utc": DRILL_DAY_START,
                "participant_staff_ids": [world.staff_id("ob"), world.staff_id("anesthesia")],
            },
            world.anesthesia_headers,
        )
    )


def _document(world, drill, incision_at):
    return get_success_data(
        api_client.document_drill(
            drill["id"],
            {
                "decision_at": SIMULATED_DECISION,
                "incision_at": incision_at,
                "documented_by_staff_id": world.staff_id("anesthesia"),
            },
            world.anesthesia_headers,
        )
    )


@pytest.fixture
def two_drills_one_second_apart():
    """Two decision-to-incision drills whose simulated intervals differ by a
    single second, both validated by an officer who documented neither."""
    world = bootstrap_unit(
        clock=DRILL_DAY_START,
        ldr_beds=2,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=DRILL_STAFF,
        unit_overrides={"unit_name": "Kirkwall Coastal Maternity"},
    )
    drill_pass = _schedule(world)
    drill_fail = _schedule(world)
    get_success_data(api_client.start_drill(drill_pass["id"], world.charge_headers))
    get_success_data(api_client.start_drill(drill_fail["id"], world.charge_headers))

    set_clock(DOCUMENT_CLOCK)
    documented_pass = _document(world, drill_pass, INCISION_PASSING)
    documented_fail = _document(world, drill_fail, INCISION_FAILING)

    validated = api_client.validate_drill(drill_pass["id"], world.officer_headers)
    refused = api_client.validate_drill(drill_fail["id"], world.officer_headers)
    return {
        "world": world,
        "drill_pass": drill_pass,
        "drill_fail": drill_fail,
        "documented_pass": documented_pass,
        "documented_fail": documented_fail,
        "validated": validated,
        "refused": refused,
    }


def test_the_measurement_truncates_rather_than_rounds(two_drills_one_second_apart):
    """"`measured_d2i_minutes` is computed by the same truncating rule as a real
    event: the elapsed seconds from `decision_at` to `incision_at` divided by 60
    with the remainder discarded." 1859 seconds is 30, 1860 seconds is 31.

    Design: Difficulty/boundary_precision_check/drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat
    """
    setup = two_drills_one_second_apart
    assert setup["documented_pass"]["measured_d2i_minutes"] == 30
    assert setup["documented_fail"]["measured_d2i_minutes"] == 31


def test_exactly_thirty_minutes_passes_validation(two_drills_one_second_apart):
    """"This requires `measured_d2i_minutes` to be less than or equal to 30, with exactly 30
    passing, refused otherwise with `ERR_DRILL_PERFORMANCE_FAILED`, and requires the
    acting `X-User-ID` to differ from `documented_by_staff_id`, refused otherwise
    with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Difficulty/boundary_precision_check/drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat
    """
    setup = two_drills_one_second_apart
    drill = get_success_data(setup["validated"])
    assert_drill(drill)
    assert drill["status"] == "VALIDATED"
    assert drill["measured_d2i_minutes"] == 30


def test_thirty_one_minutes_is_refused(two_drills_one_second_apart):
    """The drill one second slower fails the same inclusive test and is "refused
    otherwise with `ERR_DRILL_PERFORMANCE_FAILED`", which the error table places
    at HTTP 422.

    Design: Difficulty/boundary_precision_check/drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat
    """
    validate_error(
        two_drills_one_second_apart["refused"],
        ApiErrorId.ERR_DRILL_PERFORMANCE_FAILED.value,
        422,
    )


def test_the_refused_drill_stays_documented(two_drills_one_second_apart):
    """Validation is what moves a drill "from `DOCUMENTED` to `VALIDATED`" and
    what sets `validated_at` and `expires_at`, so a refused validation leaves all
    three untouched, and "a first documentation from `IN_PROGRESS` does not touch
    that counter".

    Design: Difficulty/boundary_precision_check/drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat
    """
    setup = two_drills_one_second_apart
    world = setup["world"]
    drill = get_success_data(
        api_client.get_drill(setup["drill_fail"]["id"], world.charge_headers)
    )
    assert_drill(drill)
    assert drill["status"] == "DOCUMENTED"
    assert drill["measured_d2i_minutes"] == 31
    assert_instant_is_null(drill["validated_at"], "validated_at")
    assert_instant_is_null(drill["expires_at"], "expires_at")
    assert drill["revision_count"] == 0


def test_validation_stamps_a_ninety_day_expiry_from_the_clock(
    two_drills_one_second_apart,
):
    """"Validation sets `validated_at` to the current instant, `expires_at` to
    `validated_at` plus 90 days, and `validated_by_user_id` to the acting user; it
    stamps every participant's `last_validated_drill_at` with the drill's simulated
    `decision_at` and moves each participant's `drill_currency_state` from `LAPSED`
    to `CURRENT`."

    Design: Difficulty/boundary_precision_check/drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat
    """
    setup = two_drills_one_second_apart
    drill = get_success_data(setup["validated"])
    assert_instant_equals(drill["validated_at"], DOCUMENT_CLOCK, "validated_at")
    assert_instant_equals(drill["expires_at"], EXPECTED_EXPIRY, "expires_at")
    assert drill["validated_by_user_id"] == setup["world"].staff_id("officer")


def test_participants_are_back_dated_to_the_simulated_decision(
    two_drills_one_second_apart,
):
    """"it stamps every participant's `last_validated_drill_at` with the drill's
    simulated `decision_at` and moves each participant's `drill_currency_state`
    from `LAPSED` to `CURRENT`" — the simulated instant, not the clock, and only
    for participants.

    Design: Difficulty/boundary_precision_check/drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat
    """
    world = two_drills_one_second_apart["world"]
    for key in ("ob", "anesthesia"):
        member = get_success_data(
            api_client.get_staff_member(world.staff_id(key), world.charge_headers)
        )
        assert_staff_member(member)
        assert member["drill_currency_state"] == "CURRENT"
        assert_instant_equals(
            member["last_validated_drill_at"], SIMULATED_DECISION, "last_validated_drill_at"
        )
    non_participant = get_success_data(
        api_client.get_staff_member(world.staff_id("charge"), world.charge_headers)
    )
    assert non_participant["drill_currency_state"] == "LAPSED"
    assert non_participant["last_validated_drill_at"] is None


def test_the_boundary_win_buys_only_degraded_readiness(two_drills_one_second_apart):
    """"otherwise `DEGRADED` when the standby test is not satisfied" — with no
    `OR_STANDBY` roster entry and an empty rolling window the unit that now owns
    a passing current drill still stops short of `READY`.

    Design: Difficulty/boundary_precision_check/drill_pass_threshold_admits_thirty_minutes_fifty_nine_seconds_and_refuses_thirty_one_minutes_flat
    """
    setup = two_drills_one_second_apart
    unit = setup["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert unit["current_drill_id"] == setup["drill_pass"]["id"]
    assert_instant_equals(
        unit["current_drill_expires_at"], EXPECTED_EXPIRY, "current_drill_expires_at"
    )
    assert unit["mean_d2i_minutes"] is None
    assert unit["staffing_posture"] == "OPEN"
