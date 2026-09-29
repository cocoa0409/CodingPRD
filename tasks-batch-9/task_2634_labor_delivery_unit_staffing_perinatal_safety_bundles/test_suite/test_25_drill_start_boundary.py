"""The inclusive instant a readiness drill becomes startable.

At exactly the scheduled instant the drill starts and nothing but its own state
moves; one minute earlier the identical call is refused on time rather than on
the shape of the transition.
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
    bootstrap_unit,
    get_success_data,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SCHEDULED_FOR = "2026-08-01T07:00:00Z"
ONE_MINUTE_SHORT = "2026-08-01T06:59:00Z"

DRILL_STAFF = {
    "ob": {
        "full_name": "Dr Anita Bose",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Dr Owen Halvorsen",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": True,
    },
    "charge": {
        "full_name": "Tess Aluko RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


def _scheduled_drill(unit_name):
    """A unit with one AVAILABLE LDR bed and one SCHEDULED drill due at 07:00."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=DRILL_STAFF,
        unit_overrides={"unit_name": unit_name},
    )
    drill = get_success_data(
        api_client.create_drill(
            world.unit_id,
            {
                "drill_type": "DECISION_TO_INCISION",
                "scheduled_for_utc": SCHEDULED_FOR,
                "participant_staff_ids": [
                    world.staff_id("ob"),
                    world.staff_id("anesthesia"),
                ],
            },
            world.charge_headers,
        )
    )
    return world, drill


@pytest.fixture
def a_drill_started_on_its_scheduled_instant():
    """The drill started with the clock reading exactly 07:00."""
    world, drill = _scheduled_drill("Quailridge Perinatal LDR")
    set_clock(SCHEDULED_FOR)
    started = get_success_data(api_client.start_drill(drill["id"], world.charge_headers))
    return {"world": world, "drill": drill, "started": started}


@pytest.fixture
def a_drill_started_one_minute_early():
    """The same drill probed with the clock one minute short of 07:00."""
    world, drill = _scheduled_drill("Larkfield Obstetric Unit LDR")
    set_clock(ONE_MINUTE_SHORT)
    refused = api_client.start_drill(drill["id"], world.charge_headers)
    return {"world": world, "drill": drill, "refused": refused}


def test_the_boundary_instant_itself_counts_as_due(
    a_drill_started_on_its_scheduled_instant,
):
    """"A `ChargeNurse` starts the drill, moving it from `SCHEDULED` to
    `IN_PROGRESS`, once the current instant is at or after `scheduled_for_utc`,
    the boundary instant counting as due, refused otherwise with
    `ERR_DRILL_NOT_DUE`; a start is also blocked while the unit's
    `staffing_posture` is `DIVERT`, since a unit that is diverting real patients
    does not run simulations."

    Design: Corner/state_machines/a_drill_starts_on_the_exact_scheduled_instant_and_leaves_every_timing_field_null
    """
    setup = a_drill_started_on_its_scheduled_instant
    assert setup["drill"]["status"] == "SCHEDULED"
    assert setup["drill"]["version"] == 1
    started = setup["started"]
    assert_drill(started)
    assert started["status"] == "IN_PROGRESS"
    assert_instant_equals(
        started["scheduled_for_utc"], SCHEDULED_FOR, "scheduled_for_utc"
    )
    assert started["version"] == 2


def test_starting_a_drill_grants_no_currency_and_writes_no_measurement(
    a_drill_started_on_its_scheduled_instant,
):
    """"The drill opens at `SCHEDULED`, and scheduling changes nothing about
    readiness, because only a validated drill grants currency." Neither does
    starting it: the measurement fields belong to documentation and the currency
    fields to validation, so all five stay null and the unit stays `NOT_READY`.

    Design: Corner/state_machines/a_drill_starts_on_the_exact_scheduled_instant_and_leaves_every_timing_field_null
    """
    setup = a_drill_started_on_its_scheduled_instant
    drill = get_success_data(
        api_client.get_drill(setup["drill"]["id"], setup["world"].charge_headers)
    )
    assert_drill(drill)
    assert_instant_is_null(drill["decision_at"], "decision_at")
    assert_instant_is_null(drill["incision_at"], "incision_at")
    assert drill["measured_d2i_minutes"] is None
    assert_instant_is_null(drill["validated_at"], "validated_at")
    assert_instant_is_null(drill["expires_at"], "expires_at")
    assert drill["revision_count"] == 0
    unit = setup["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"


def test_one_minute_short_of_the_schedule_is_not_yet_due(
    a_drill_started_one_minute_early,
):
    """"A `ChargeNurse` starts the drill, moving it from `SCHEDULED` to
    `IN_PROGRESS`, once the current instant is at or after `scheduled_for_utc`,
    the boundary instant counting as due, refused otherwise with
    `ERR_DRILL_NOT_DUE`; a start is also blocked while the unit's
    `staffing_posture` is `DIVERT`, since a unit that is diverting real patients
    does not run simulations."

    Design: Corner/state_machines/starting_a_drill_one_minute_early_is_refused_with_drill_not_due
    """
    refused = a_drill_started_one_minute_early["refused"]
    validate_error(refused, ApiErrorId.ERR_DRILL_NOT_DUE.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    )


def test_the_early_start_leaves_the_drill_exactly_as_scheduled(
    a_drill_started_one_minute_early,
):
    """"`version` is an integer that starts at 1 when the record is created and
    increments by 1 on each mutation of that record", so a drill still sitting at
    version 1 proves the refusal wrote nothing at all.

    Design: Corner/state_machines/starting_a_drill_one_minute_early_is_refused_with_drill_not_due
    """
    setup = a_drill_started_one_minute_early
    drill = get_success_data(
        api_client.get_drill(setup["drill"]["id"], setup["world"].charge_headers)
    )
    assert_drill(drill)
    assert drill["status"] == "SCHEDULED"
    assert drill["revision_count"] == 0
    assert drill["version"] == 1
