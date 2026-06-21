"""Device identity-binding lifecycle: login, logout, malfunction (PRD §3.2).

Covers difficulty cross_entity_state_dependency (device->vehicle) and
resource_temporal_overlap (single-occupancy), plus corner state_machines for devices.
"""
from test_helpers import fixtures
from test_helpers.test_users import make_driver_headers, TEST_USERS
from test_helpers import validate_success, validate_error, factories


ADMIN = TEST_USERS["carrier_admin_headers"]


# =====================================================================
# Difficulty / cross_entity_state_dependency — login blocked by OUT_OF_SERVICE vehicle
# =====================================================================
def test_login_blocked_when_vehicle_out_of_service(api):
    """PRD §3.2: "The device's vehicle must be IN_SERVICE; a login against a device whose
    vehicle is OUT_OF_SERVICE is rejected with ERR_VEHICLE_OUT_OF_SERVICE."

    Design: Difficulty/cross_entity_state_dependency/device_login_blocked_by_vehicle_out_of_service
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    driver = fixtures.create_driver()
    # Take the vehicle OUT_OF_SERVICE.
    fixtures.get_success_data = fixtures.get_success_data  # no-op, keep import explicit
    patched = api.update_vehicle(vehicle["id"],
                                 {"status": "OUT_OF_SERVICE", "expected_vehicle_version": vehicle["version"]},
                                 ADMIN)
    validate_success(patched, 200)

    resp = api.login_device(device["id"], make_driver_headers(driver["id"]))
    validate_error(resp, "ERR_VEHICLE_OUT_OF_SERVICE")

    after = validate_success(api.get_device(device["id"], ADMIN), 200)
    assert after["status"] == "UNBOUND"
    assert after["bound_driver_id"] is None


def test_device_stays_unbound_after_out_of_service_login_rejection(api):
    """PRD §3.2: "Login is permitted only when the device is UNBOUND".
    PRD §3.2: "a login against a device whose vehicle is OUT_OF_SERVICE is rejected with
    ERR_VEHICLE_OUT_OF_SERVICE."

    Design: Difficulty/cross_entity_state_dependency/device_login_blocked_by_vehicle_out_of_service
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    driver = fixtures.create_driver()
    validate_success(
        api.update_vehicle(vehicle["id"],
                           {"status": "OUT_OF_SERVICE", "expected_vehicle_version": vehicle["version"]},
                           ADMIN), 200)
    validate_error(api.login_device(device["id"], make_driver_headers(driver["id"])),
                   "ERR_VEHICLE_OUT_OF_SERVICE")
    after = validate_success(api.get_device(device["id"], ADMIN), 200)
    assert after["status"] == "UNBOUND" and after["bound_driver_id"] is None


# =====================================================================
# Difficulty / resource_temporal_overlap — single-occupancy second login rejected
# =====================================================================
def test_second_driver_login_to_bound_device_rejected(api):
    """PRD §3.2: "Login is permitted only when the device is UNBOUND; attempting it on a
    device that is not UNBOUND is rejected with ERR_DEVICE_ALREADY_BOUND."

    Design: Difficulty/resource_temporal_overlap/device_binding_single_occupancy_rejects_second_login
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    d1 = fixtures.create_driver()
    d2 = fixtures.create_driver()
    fixtures.login(device["id"], d1["id"])

    resp = api.login_device(device["id"], make_driver_headers(d2["id"]))
    validate_error(resp, "ERR_DEVICE_ALREADY_BOUND")

    after = validate_success(api.get_device(device["id"], ADMIN), 200)
    assert after["bound_driver_id"] == d1["id"], "binding unchanged after rejected second login"


def test_bound_device_status_unchanged_after_second_login_rejection(api):
    """PRD §3.2: "attempting it on a device that is not UNBOUND is rejected with
    ERR_DEVICE_ALREADY_BOUND."

    Design: Difficulty/resource_temporal_overlap/device_binding_single_occupancy_rejects_second_login
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    d1 = fixtures.create_driver()
    d2 = fixtures.create_driver()
    fixtures.login(device["id"], d1["id"])
    validate_error(api.login_device(device["id"], make_driver_headers(d2["id"])),
                   "ERR_DEVICE_ALREADY_BOUND")
    after = validate_success(api.get_device(device["id"], ADMIN), 200)
    assert after["status"] == "BOUND"
    assert after["bound_driver_id"] == d1["id"]


# =====================================================================
# Corner / state_machines — device transitions
# =====================================================================
def test_logout_unbound_device_fails_ownership_check(api):
    """PRD §3.2: "Only the driver currently bound to the device may log it out; a logout by
    anyone other than the bound driver is rejected with ERR_UNAUTHORIZED."

    Design: Corner/state_machines/logout_unbound_device_returns_invalid_state
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    driver = fixtures.create_driver()
    resp = api.logout_device(device["id"], make_driver_headers(driver["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED")


def test_clear_malfunction_on_bound_device_invalid_state(api):
    """PRD §3.2: "Clearing the malfunction transitions the device MALFUNCTION → UNBOUND and
    clears bound_driver_id; it is permitted only from MALFUNCTION and otherwise rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/clear_malfunction_on_bound_device_returns_invalid_state
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    driver = fixtures.create_driver()
    fixtures.login(device["id"], driver["id"])

    resp = api.clear_malfunction(device["id"], ADMIN)
    validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_device(device["id"], ADMIN), 200)
    assert after["status"] == "BOUND"


def test_malfunction_device_blocks_duty_event_append(api):
    """PRD §3.3: "The referenced device must be BOUND and its bound_driver_id must equal the
    supplied driver_id; if the device is not bound to the driver, the append is rejected with
    ERR_DEVICE_NOT_BOUND."

    Design: Corner/state_machines/malfunction_device_blocks_duty_event_append
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    validate_success(api.flag_malfunction(dev_id, ADMIN), 200)

    v = fixtures.driver_version(d_id)
    payload = factories.create_duty_event_payload(d_id, dev_id, "DRIVING", "2026-06-01T06:30:00Z", v)
    resp = api.create_duty_event(payload, make_driver_headers(d_id))
    validate_error(resp, "ERR_DEVICE_NOT_BOUND")


def test_driver_already_bound_blocks_second_device_login(api):
    """PRD §3.2: "The acting driver must not already hold another bound device — a driver may
    be bound to at most one device at a time — and a second concurrent binding is rejected with
    ERR_DRIVER_ALREADY_BOUND."

    Design: Corner/state_machines/driver_already_bound_blocks_second_device_login
    """
    v1 = fixtures.create_vehicle()
    v2 = fixtures.create_vehicle()
    dev1 = fixtures.create_device(v1["id"])
    dev2 = fixtures.create_device(v2["id"])
    driver = fixtures.create_driver()
    fixtures.login(dev1["id"], driver["id"])

    resp = api.login_device(dev2["id"], make_driver_headers(driver["id"]))
    validate_error(resp, "ERR_DRIVER_ALREADY_BOUND")
    after = validate_success(api.get_device(dev2["id"], ADMIN), 200)
    assert after["status"] == "UNBOUND"


def test_cannot_logout_while_driving(api):
    """PRD §3.2: "Logout is also blocked while the driver is actually driving: if the
    driver's current_duty_status is DRIVING, the logout is rejected with
    ERR_CANNOT_LOGOUT_WHILE_DRIVING".

    Design: Corner/state_machines/cannot_logout_while_driving
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, dev_id = setup["driver_id"], setup["device_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:30:00Z")  # current_duty_status -> DRIVING

    resp = api.logout_device(dev_id, make_driver_headers(d_id))
    validate_error(resp, "ERR_CANNOT_LOGOUT_WHILE_DRIVING")
    after = validate_success(api.get_device(dev_id, ADMIN), 200)
    assert after["status"] == "BOUND"
