"""DutyEvent append — ordering, annotation, vehicle, odometer — PRD §3.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ANNOTATION_MIN_LEN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    TEST_USERS,
    add_seconds,
    advance_clock_to_iso,
    assert_append_only_fields,
    assert_duty_event,
    create_duty_event_payload,
    create_vehicle,
    create_eld_device,
    get_driver,
    get_server_clock_iso,
    make_driver_headers,
    post_duty_event,
    setup_full_stack,
    setup_unbound_driver_and_vehicle,
    validate_error,
    validate_success,
)


# ===========================================================================
# Append success and shape — PRD §3.3
# ===========================================================================
class TestDutyEventAppend:

    def test_off_duty_event_is_append_only_no_version(self, api):
        """PRD §2.4: "The `DutyEvent` resource is an immutable audit
        record and carries only `id` and `created_at`; it has no
        `updated_at` and no `version`".

        Claim: an accepted DutyEvent response has id and created_at
        but does NOT carry updated_at or version.
        """
        state = setup_full_stack()
        driver = state["driver"]
        clock0 = get_server_clock_iso()
        payload = create_duty_event_payload(
            new_status="OFF_DUTY",
            event_time=add_seconds(clock0, 1),
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_append_only_fields(data)
        assert data["new_status"] == "OFF_DUTY"
        assert data["edit_state"] == "ACTIVE"

    def test_append_event_sets_driver_duty_status(self, api):
        """PRD §3.3: "Each accepted duty event updates the parent
        `Driver`'s `duty_status` to match `new_status`."

        Claim: posting a SLEEPER_BERTH event updates
        Driver.duty_status to SLEEPER_BERTH.
        """
        state = setup_full_stack()
        driver = state["driver"]
        clock0 = get_server_clock_iso()
        post_duty_event(
            driver, new_status="SLEEPER_BERTH",
            event_time=add_seconds(clock0, 1),
        )
        refreshed = get_driver(driver["id"])
        assert refreshed["duty_status"] == "SLEEPER_BERTH"


# ===========================================================================
# Ordering — PRD §3.3
# ===========================================================================
class TestEventOrdering:

    def test_event_time_equal_to_latest_rejected(self, api):
        """PRD §3.3: "An `event_time` that is not strictly greater
        than the latest accepted event for this driver is rejected
        with `ERR_DUTY_EVENT_OUT_OF_ORDER`."

        Claim: posting a DutyEvent with event_time exactly equal to
        the latest stored event_time fails with
        ERR_DUTY_EVENT_OUT_OF_ORDER.
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        e1_time = add_seconds(clock0, 1)
        first = post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=e1_time, vehicle_id=vehicle["id"],
            odometer_miles=100.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # Second event with identical event_time.
        payload = create_duty_event_payload(
            new_status="OFF_DUTY",
            event_time=first["event_time"],
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUTY_EVENT_OUT_OF_ORDER.value)

    def test_event_time_earlier_than_latest_rejected(self, api):
        """PRD §3.3: "An `event_time` that is not strictly greater
        than the latest accepted event for this driver is rejected
        with `ERR_DUTY_EVENT_OUT_OF_ORDER`."

        Claim: posting an event with event_time strictly earlier than
        the latest stored event_time fails with
        ERR_DUTY_EVENT_OUT_OF_ORDER.
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        e1_time = add_seconds(clock0, 60)
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=e1_time, vehicle_id=vehicle["id"],
            odometer_miles=100.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # Second event one second earlier.
        payload = create_duty_event_payload(
            new_status="OFF_DUTY",
            event_time=add_seconds(e1_time, -1),
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUTY_EVENT_OUT_OF_ORDER.value)


# ===========================================================================
# Driver-must-be-bound — PRD §3.3
# ===========================================================================
class TestDriverNotBound:

    @pytest.mark.parametrize("status", [
        "DRIVING", "ON_DUTY_NOT_DRIVING",
        "YARD_MOVES", "PERSONAL_CONVEYANCE",
    ])
    def test_driver_not_bound_rejected_for_on_vehicle_statuses(
        self, api, status,
    ):
        """PRD §3.3: "A duty event whose `new_status` is `DRIVING`,
        `ON_DUTY_NOT_DRIVING`, `YARD_MOVES`, or `PERSONAL_CONVEYANCE`
        requires `Driver.bound_vehicle_id` to be non-null; otherwise
        the request is rejected with `ERR_DRIVER_NOT_BOUND`."

        Claim: each of the four on-vehicle statuses on an unbound
        driver returns ERR_DRIVER_NOT_BOUND.
        """
        state = setup_unbound_driver_and_vehicle()
        driver = state["driver"]
        clock0 = get_server_clock_iso()
        payload = create_duty_event_payload(
            new_status=status,
            event_time=add_seconds(clock0, 60),
            vehicle_id=state["vehicle"]["id"],
            odometer_miles=100.0,
            annotation="Annotation 12345",  # >= 10 chars
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_BOUND.value)


# ===========================================================================
# Annotation — PRD §3.3
# ===========================================================================
class TestAnnotation:

    @pytest.mark.parametrize("status", ["PERSONAL_CONVEYANCE", "YARD_MOVES"])
    def test_annotation_required_for_pc_and_ym(self, api, status):
        """PRD §3.3: "`PERSONAL_CONVEYANCE` and `YARD_MOVES` events
        require an `annotation` whose length is at least ten
        characters; a shorter or absent annotation is rejected with
        `ERR_ANNOTATION_REQUIRED`."

        Claim: PC and YM events without an annotation fail with
        ERR_ANNOTATION_REQUIRED.
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        # No annotation supplied.
        payload = create_duty_event_payload(
            new_status=status,
            event_time=add_seconds(clock0, 60),
            vehicle_id=vehicle["id"],
            odometer_miles=100.0,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ANNOTATION_REQUIRED.value)

    @pytest.mark.parametrize("status", ["PERSONAL_CONVEYANCE", "YARD_MOVES"])
    def test_annotation_short_rejected(self, api, status):
        """PRD §3.3: "`PERSONAL_CONVEYANCE` and `YARD_MOVES` events
        require an `annotation` whose length is at least ten
        characters; a shorter or absent annotation is rejected with
        `ERR_ANNOTATION_REQUIRED`."

        Claim: a 9-character annotation fails with
        ERR_ANNOTATION_REQUIRED (boundary one-below the 10-char
        minimum).
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        payload = create_duty_event_payload(
            new_status=status,
            event_time=add_seconds(clock0, 60),
            vehicle_id=vehicle["id"],
            odometer_miles=100.0,
            annotation="ninechars",  # exactly 9 chars
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ANNOTATION_REQUIRED.value)


# ===========================================================================
# Vehicle mismatch — PRD §3.3
# ===========================================================================
class TestVehicleMismatch:

    def test_vehicle_mismatch_for_driving_rejected(self, api):
        """PRD §3.3: "When `new_status` is `DRIVING`,
        `ON_DUTY_NOT_DRIVING`, `YARD_MOVES`, or `PERSONAL_CONVEYANCE`,
        the request must supply a `vehicle_id` and that `vehicle_id`
        must equal the driver's currently bound vehicle; a mismatch
        (or a missing `vehicle_id` for an on-vehicle status) is
        rejected with `ERR_VEHICLE_MISMATCH`."

        Claim: posting a DRIVING event with a different (real)
        vehicle_id than the bound vehicle fails with
        ERR_VEHICLE_MISMATCH.
        """
        state = setup_full_stack()
        driver = state["driver"]
        # Create a different vehicle on the same carrier.
        device2 = create_eld_device()
        other_vehicle = create_vehicle(
            carrier_id=state["carrier"]["id"],
            eld_device_id=device2["id"],
        )
        clock0 = get_server_clock_iso()
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=add_seconds(clock0, 60),
            vehicle_id=other_vehicle["id"],
            odometer_miles=100.0,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_MISMATCH.value)


# ===========================================================================
# Odometer monotonic — PRD §3.3
# ===========================================================================
class TestOdometerMonotonic:

    def test_odometer_decreased_rejected(self, api):
        """PRD §3.3: "The `odometer_miles` of any accepted event must
        be greater than or equal to the latest accepted
        `odometer_miles` for that same vehicle - odometers do not run
        backward - and a smaller reading is rejected with
        `ERR_ODOMETER_DECREASED`."

        Claim: posting an event with odometer_miles strictly less
        than the latest reading for the same vehicle fails with
        ERR_ODOMETER_DECREASED.
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        # First event with odometer 1000.
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=add_seconds(clock0, 60),
            vehicle_id=vehicle["id"], odometer_miles=1000.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # Second event with odometer 999 — must fail.
        payload = create_duty_event_payload(
            new_status="ON_DUTY_NOT_DRIVING",
            event_time=add_seconds(clock0, 120),
            vehicle_id=vehicle["id"],
            odometer_miles=999.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ODOMETER_DECREASED.value)

    def test_odometer_equal_allowed(self, api):
        """PRD §3.3: "The `odometer_miles` of any accepted event must
        be greater than or equal to the latest accepted
        `odometer_miles` for that same vehicle".

        Claim: a subsequent event with equal odometer_miles is
        accepted (>= is monotonic non-decreasing, not strict).
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=add_seconds(clock0, 60),
            vehicle_id=vehicle["id"], odometer_miles=1000.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # Equal odometer reading must succeed.
        e2 = post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=add_seconds(clock0, 120),
            vehicle_id=vehicle["id"], odometer_miles=1000.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        assert e2["odometer_miles"] == 1000.0


# ===========================================================================
# Exemption-not-active — PRD §3.3, §3.6
# ===========================================================================
class TestExemptionReference:

    def test_unknown_exemption_id_rejected(self, api):
        """PRD §3.3: "If the event carries an
        `adverse_conditions_exemption_id`, that id must reference an
        `AdverseConditionsExemption` whose `status` is `ACTIVE`, whose
        `driver_id` matches the acting driver, and whose
        `applies_to_log_date` equals the log date computed from
        `event_time` in the driver's home-terminal timezone;
        otherwise the request is rejected with
        `ERR_EXEMPTION_NOT_ACTIVE`."

        Claim: supplying an unknown exemption id on a DRIVING event
        returns ERR_EXEMPTION_NOT_ACTIVE.
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=add_seconds(clock0, 60),
            vehicle_id=vehicle["id"],
            odometer_miles=1000.0,
            adverse_conditions_exemption_id=NON_EXISTENT_UUID,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_NOT_ACTIVE.value)
