"""Which edges exist, and what a record looks like before any of them fires.

A brand-new induction request reserves nothing at all yet still knows its own
priority; confirmation, declared only out of a held booking, is refused from the
request state; a roster entry whose window has not opened yet cannot be
activated even though the edge itself is legal; and a cancelled roster entry
refuses both of the triggers that remain.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bed,
    assert_induction_booking,
    assert_shift_assignment,
    bootstrap_unit,
    create_shift,
    get_success_data,
    TEST_USERS,
)

CLOCK_START = "2026-08-01T06:00:00Z"
REQUESTED_START = "2026-08-02T08:00:00Z"
ELECTIVE_LABOR_MINUTES = 600
DEFAULT_LABOR_MINUTES = 720
NIGHT_SHIFT_START = "2026-08-01T16:00:00Z"
NIGHT_SHIFT_END = "2026-08-02T02:00:00Z"
DAY_SHIFT_START = "2026-08-01T05:00:00Z"
DAY_SHIFT_END = "2026-08-01T15:00:00Z"
ACCESS_HEADERS = TEST_USERS["access_coordinator_headers"]

EDGE_STAFF = {
    "charge": {
        "full_name": "Priya Raman RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Marcus Feld MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


def _unit(unit_name):
    """One unit with a single AVAILABLE LDR bed and a two-person roster."""
    return bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=EDGE_STAFF,
        unit_overrides={"unit_name": unit_name},
    )


@pytest.fixture
def one_untouched_induction_request():
    """A single elective request at 39 weeks, created and then left alone."""
    world = _unit("Tamarack Maternity LDR")
    booking = get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": "PRC-IND-7007",
                "gestational_age_weeks": 39,
                "indication_code": "ELECTIVE_NO_INDICATION",
                "requested_start_utc": REQUESTED_START,
                "expected_labor_minutes": ELECTIVE_LABOR_MINUTES,
            },
            ACCESS_HEADERS,
        )
    )
    return {"world": world, "booking": booking}


@pytest.fixture
def a_confirm_fired_from_the_request_state():
    """A medically indicated request that never held capacity, then confirmed."""
    world = _unit("Chokecherry Womens Center LDR")
    booking = get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": "PRC-IND-8008",
                "gestational_age_weeks": 41,
                "indication_code": "POST_DATES_41W",
                "requested_start_utc": REQUESTED_START,
            },
            ACCESS_HEADERS,
        )
    )
    refused = api_client.confirm_booking(booking["id"], world.ob_headers)
    return {"world": world, "booking": booking, "refused": refused}


def test_a_new_request_reserves_absolutely_nothing(one_untouched_induction_request):
    """"The booking opens in `REQUESTED` with `bump_count` at 0, `bed_id`,
    `encounter_id`, `hold_expires_at` and `projected_occupancy_minutes` all null,
    and consumes no budget at all."

    Design: Corner/state_machines/newly_requested_induction_booking_starts_in_requested_with_no_capacity_committed
    """
    booking = one_untouched_induction_request["booking"]
    assert_induction_booking(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["bump_count"] == 0
    assert booking["bed_id"] is None
    assert booking["encounter_id"] is None
    assert booking["hold_expires_at"] is None
    assert booking["projected_occupancy_minutes"] is None
    assert booking["expected_labor_minutes"] == ELECTIVE_LABOR_MINUTES
    assert booking["version"] == 1
    unit = one_untouched_induction_request["world"].reload_unit()
    assert unit["committed_bed_minutes_by_day"].get("2026-08-02", 0) == 0
    assert unit["held_bed_minutes_by_day"].get("2026-08-02", 0) == 0


def test_the_priority_class_is_settled_at_request_time(
    one_untouched_induction_request,
):
    """"`priority_class` is derived immediately and re-derived on every requeue"
    — and it "is `ELECTIVE_39_WEEK` when `indication_code` is `GDM_CONTROLLED` or
    `ELECTIVE_NO_INDICATION` and `gestational_age_weeks` is 39 or greater", so
    the class is known before any bed is touched.

    Design: Corner/state_machines/newly_requested_induction_booking_starts_in_requested_with_no_capacity_committed
    """
    setup = one_untouched_induction_request
    assert setup["booking"]["priority_class"] == "ELECTIVE_39_WEEK"
    bed = get_success_data(
        api_client.get_bed(setup["world"].bed_id("LDR-01"), setup["world"].charge_headers)
    )
    assert_bed(bed)
    assert bed["status"] == "AVAILABLE"
    assert bed["held_booking_id"] is None


def test_confirming_a_booking_that_never_held_is_an_undeclared_edge(
    a_confirm_fired_from_the_request_state,
):
    """"Confirmation is an `ObstetricianAttending` act moving `CAPACITY_HELD` to
    `CONFIRMED`" — so from `REQUESTED` the request is caught by the declared-
    transition guard, "an attempt to move a record from a state for which the
    requested edge is not declared yields `ERR_INVALID_STATE_TRANSITION` at HTTP
    409", rather than by the lapsed-hold test that comes later in the same
    endpoint.

    Design: Corner/state_machines/confirming_a_booking_that_never_held_capacity_returns_invalid_state_transition
    """
    refused = a_confirm_fired_from_the_request_state["refused"]
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INDUCTION_HOLD_EXPIRED.value
    )


def test_the_refused_confirm_performed_no_implicit_hold(
    a_confirm_fired_from_the_request_state,
):
    """A hold is the only thing that writes those fields — "This is also the
    moment `projected_occupancy_minutes` is frozen" — and `version` "increments
    by 1 on each mutation of that record", so a booking left at version 1 proves
    nothing at all happened.

    Design: Corner/state_machines/confirming_a_booking_that_never_held_capacity_returns_invalid_state_transition
    """
    setup = a_confirm_fired_from_the_request_state
    world = setup["world"]
    booking = get_success_data(
        api_client.get_booking(setup["booking"]["id"], ACCESS_HEADERS)
    )
    assert_induction_booking(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["priority_class"] == "MEDICALLY_INDICATED"
    assert booking["expected_labor_minutes"] == DEFAULT_LABOR_MINUTES
    assert booking["hold_expires_at"] is None
    assert booking["projected_occupancy_minutes"] is None
    assert booking["bed_id"] is None
    assert booking["version"] == 1
    bed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert bed["status"] == "AVAILABLE"


@pytest.fixture
def an_activation_ten_hours_ahead_of_its_window():
    """A SCHEDULED night CHARGE entry activated while the clock still reads 06:00."""
    world = _unit("Mulberry Perinatal Care LDR")
    shift = create_shift(
        world,
        staff_key="charge",
        role_slot="CHARGE",
        shift_start_utc=NIGHT_SHIFT_START,
        shift_end_utc=NIGHT_SHIFT_END,
    )
    refused = api_client.activate_shift(shift["id"], world.charge_headers)
    return {"world": world, "shift": shift, "refused": refused}


@pytest.fixture
def a_cancelled_entry_probed_twice():
    """A CHARGE entry cancelled inside its own live window, then re-activated and
    re-cancelled."""
    world = _unit("Persimmon Grove Maternity LDR")
    shift = create_shift(
        world,
        staff_key="charge",
        role_slot="CHARGE",
        shift_start_utc=DAY_SHIFT_START,
        shift_end_utc=DAY_SHIFT_END,
    )
    cancelled = get_success_data(
        api_client.cancel_shift(shift["id"], world.charge_headers)
    )
    refused_activate = api_client.activate_shift(shift["id"], world.charge_headers)
    refused_cancel = api_client.cancel_shift(shift["id"], world.charge_headers)
    return {
        "world": world,
        "cancelled": cancelled,
        "refused_activate": refused_activate,
        "refused_cancel": refused_cancel,
    }


def test_activating_before_the_window_opens_is_refused(
    an_activation_ten_hours_ahead_of_its_window,
):
    """"The window must contain the current instant, failing which the attempt is
    refused with `ERR_SHIFT_WINDOW_NOT_CURRENT`." The edge itself is declared out
    of `SCHEDULED`, so the earlier declared-transition guard cannot be the answer.

    Design: Corner/state_machines/activating_a_shift_before_its_window_opens_returns_shift_window_not_current
    """
    refused = an_activation_ten_hours_ahead_of_its_window["refused"]
    validate_error(refused, ApiErrorId.ERR_SHIFT_WINDOW_NOT_CURRENT.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    )


def test_a_failed_activation_leaves_no_capacity_snapshot(
    an_activation_ten_hours_ahead_of_its_window,
):
    """"Activation, a `ChargeNurse` act, is where a roster entry becomes real:
    `SCHEDULED` becomes `ACTIVE` and `capacity_units_effective` is frozen." The
    snapshot is frozen BY activation, so a refused activation may not leave one
    behind.

    Design: Corner/state_machines/activating_a_shift_before_its_window_opens_returns_shift_window_not_current
    """
    setup = an_activation_ten_hours_ahead_of_its_window
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["status"] == "SCHEDULED"
    assert shift["capacity_units_effective"] is None
    assert shift["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
    assert shift["version"] == 1


def test_neither_trigger_survives_the_terminal_cancelled_state(
    a_cancelled_entry_probed_twice,
):
    """"Cancellation is available only from `SCHEDULED`, again to a `ChargeNurse`"
    — and activation is declared only on the same source state, so from
    `CANCELLED` both calls hit the declared-transition guard at HTTP 409, the
    activation despite the clock sitting squarely inside the entry's window.

    Design: Corner/state_machines/a_cancelled_shift_cannot_be_activated_or_cancelled_again
    """
    setup = a_cancelled_entry_probed_twice
    assert setup["cancelled"]["status"] == "CANCELLED"
    validate_error(
        setup["refused_activate"], ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409
    )
    validate_error(
        setup["refused_cancel"], ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409
    )


def test_the_cancelled_entry_kept_the_version_it_landed_on(
    a_cancelled_entry_probed_twice,
):
    """"`version` is an integer that starts at 1 when the record is created and
    increments by 1 on each mutation of that record", so two refused calls must
    leave the entry on the version its cancellation produced, and with no
    capacity snapshot it never acquired.

    Design: Corner/state_machines/a_cancelled_shift_cannot_be_activated_or_cancelled_again
    """
    setup = a_cancelled_entry_probed_twice
    shift = get_success_data(
        api_client.get_shift(setup["cancelled"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["status"] == "CANCELLED"
    assert shift["capacity_units_effective"] is None
    assert shift["version"] == setup["cancelled"]["version"]
