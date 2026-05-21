"""Driver ↔ Vehicle binding lifecycle — PRD §3.2."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bind_driver_to_vehicle,
    bind_payload,
    create_carrier,
    create_driver,
    create_eld_device,
    create_vehicle,
    get_driver,
    get_vehicle,
    make_driver_headers,
    post_duty_event,
    setup_full_stack,
    setup_unbound_driver_and_vehicle,
    unbind_driver,
    validate_error,
    validate_success,
)


# ===========================================================================
# Successful bind — PRD §3.2
# ===========================================================================
class TestBindSuccess:

    def test_bind_sets_bound_vehicle_and_device_atomically(self, api):
        """PRD §3.2: "On success, the server atomically sets the
        driver's `bound_vehicle_id` to the supplied `vehicle_id`, sets
        the driver's `bound_eld_device_id` to that vehicle's
        `eld_device_id`, and sets the vehicle's `current_driver_id` to
        the driver's id".

        Claim: after a successful bind, Driver.bound_vehicle_id ==
        vehicle.id, Driver.bound_eld_device_id == vehicle.eld_device_id,
        and Vehicle.current_driver_id == Driver.id.
        """
        state = setup_unbound_driver_and_vehicle()
        driver = state["driver"]
        vehicle = state["vehicle"]
        resp = api.bind_driver(
            driver["id"], bind_payload(vehicle_id=vehicle["id"]),
            make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["bound_vehicle_id"] == vehicle["id"]
        assert data["bound_eld_device_id"] == vehicle["eld_device_id"]
        v_after = get_vehicle(vehicle["id"])
        assert v_after["current_driver_id"] == driver["id"]


# ===========================================================================
# Bind rejections — PRD §3.2
# ===========================================================================
class TestBindRejections:

    def test_bind_when_driver_already_bound_returns_err(self, api):
        """PRD §3.2: "a bind by a driver already bound to a different
        vehicle is rejected with `ERR_DRIVER_ALREADY_BOUND`".

        Claim: a second bind by the same Driver (to any vehicle) fails
        with ERR_DRIVER_ALREADY_BOUND.
        """
        state = setup_full_stack()  # driver already bound
        driver = state["driver"]
        # Build a second vehicle for the same carrier with a fresh ELD.
        device2 = create_eld_device()
        vehicle2 = create_vehicle(
            carrier_id=state["carrier"]["id"], eld_device_id=device2["id"],
        )
        resp = api.bind_driver(
            driver["id"], bind_payload(vehicle_id=vehicle2["id"]),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_ALREADY_BOUND.value)

    def test_bind_when_vehicle_already_bound_returns_err(self, api):
        """PRD §3.2: "a bind whose vehicle is already paired to another
        driver is rejected with `ERR_VEHICLE_ALREADY_BOUND`".

        Claim: a second driver attempting to bind to an already-bound
        vehicle (same carrier) fails with ERR_VEHICLE_ALREADY_BOUND.
        """
        state = setup_full_stack()
        vehicle = state["vehicle"]
        # New driver on the same carrier.
        driver2 = create_driver(carrier_id=state["carrier"]["id"])
        resp = api.bind_driver(
            driver2["id"], bind_payload(vehicle_id=vehicle["id"]),
            make_driver_headers(driver2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_ALREADY_BOUND.value)

    def test_bind_cross_carrier_rejected(self, api):
        """PRD §3.2: "a bind whose vehicle and driver belong to
        different carriers is rejected with `ERR_CROSS_CARRIER_BIND`".

        Claim: when Vehicle.carrier_id != Driver.carrier_id, bind
        returns ERR_CROSS_CARRIER_BIND at HTTP 422.
        """
        carrier1 = create_carrier()
        carrier2 = create_carrier()
        device = create_eld_device()
        vehicle2 = create_vehicle(
            carrier_id=carrier2["id"], eld_device_id=device["id"],
        )
        # Driver belongs to carrier1, but vehicle belongs to carrier2.
        driver1 = create_driver(carrier_id=carrier1["id"])
        resp = api.bind_driver(
            driver1["id"], bind_payload(vehicle_id=vehicle2["id"]),
            make_driver_headers(driver1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_CARRIER_BIND.value)

    def test_bind_uncertified_eld_rejected(self, api):
        """PRD §3.2: "a bind whose device is not FMCSA-certified is
        rejected with `ERR_ELD_NOT_CERTIFIED`".

        Claim: when Vehicle's installed device has
        certified_for_fmcsa=false, bind fails with
        ERR_ELD_NOT_CERTIFIED.
        """
        carrier = create_carrier()
        device = create_eld_device(certified_for_fmcsa=False)
        vehicle = create_vehicle(
            carrier_id=carrier["id"], eld_device_id=device["id"],
        )
        driver = create_driver(carrier_id=carrier["id"])
        resp = api.bind_driver(
            driver["id"], bind_payload(vehicle_id=vehicle["id"]),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ELD_NOT_CERTIFIED.value)


# NOTE: PRD §3.2 names ERR_INVALID_DUTY_STATUS_FOR_BIND on the bind
# path too, but every PRD-described transition out of OFF_DUTY
# requires Driver.bound_vehicle_id to be non-null. Reaching a state
# where a driver is non-OFF_DUTY and unbound is not possible from
# PRD-described operations, so the bind-side branch of the rule is
# exercised on the unbind path below.


# ===========================================================================
# Unbind — PRD §3.2
# ===========================================================================
class TestUnbind:

    def test_unbind_when_driving_rejected(self, api):
        """PRD §3.2: "The reverse transition, from `BOUND` to
        `UNBOUND`, requires only that the driver's current
        `duty_status` be either `OFF_DUTY` or `SLEEPER_BERTH`; if she
        is in any other status, the unbind is rejected with
        `ERR_INVALID_DUTY_STATUS_FOR_BIND`."

        Claim: unbinding a driver whose duty_status is DRIVING fails
        with ERR_INVALID_DUTY_STATUS_FOR_BIND.
        """
        from test_helpers import (
            add_seconds,
            advance_clock_to_iso,
            get_server_clock_iso,
        )
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        # Post DRIVING — for a fresh driver, both
        # available_driving_hours (660 - 0 = 660 > 0) and
        # available_on_duty_window (840 > 0) hold.
        drive_time = add_seconds(clock0, 60)
        advance_clock_to_iso(drive_time)
        post_duty_event(driver, new_status="DRIVING",
                        event_time=drive_time,
                        vehicle_id=vehicle["id"], odometer_miles=1000.0)
        # Now driver.duty_status == DRIVING. Unbind should fail.
        resp = api.unbind_driver(
            driver["id"], make_driver_headers(driver["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_DUTY_STATUS_FOR_BIND.value,
        )

    def test_unbind_when_off_duty_clears_fields(self, api):
        """PRD §3.2: "On a successful unbind the server atomically
        clears `Driver.bound_vehicle_id`, clears
        `Driver.bound_eld_device_id`, and clears
        `Vehicle.current_driver_id`."

        Claim: after a successful unbind, all three fields are null.
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        resp = api.unbind_driver(
            driver["id"], make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["bound_vehicle_id"] is None
        assert data["bound_eld_device_id"] is None
        v_after = get_vehicle(vehicle["id"])
        assert v_after["current_driver_id"] is None
