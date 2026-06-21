"""Fleet setup CRUD, defaults, uniqueness, listing, and computed reads
(PRD §2.3, §2.4, §2.9, §3.1, §3.7, §3.8).

Covers corner entities/endpoints instances and the difficulty
cross_entity_state_dependency certify-blocked-by-open-event instance.
"""
import pytest

from test_helpers import fixtures, factories
from test_helpers.test_users import make_driver_headers, TEST_USERS
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_driver, assert_pc_segment, assert_no_version_field,
)


ADMIN = TEST_USERS["carrier_admin_headers"]


# =====================================================================
# Corner / entities — creation, defaults, computed, constraints
# =====================================================================
def test_create_driver_returns_201_with_all_fields(api):
    """PRD §3.1: "A new driver is created with status ACTIVE, version 1, a current_duty_status
    of OFF_DUTY because no events yet exist, and the three optional fields defaulting
    respectively to an offset of 0, a cycle_rule of SEVENTY_HOUR_8_DAY, and pc_authorized set
    to false."

    Design: Corner/entities/create_driver_returns_201_with_all_fields
    """
    resp = api.create_driver(factories.create_driver_payload(full_name="Zeta Driver"), ADMIN)
    data = validate_success(resp, 201)
    assert_driver(data)
    assert data["version"] == 1
    assert data["status"] == "ACTIVE"
    assert data["current_duty_status"] == "OFF_DUTY"
    assert data["cycle_on_duty_minutes"] == 0


def test_get_driver_not_found_returns_404(api):
    """PRD §2.7: "the server validates that identifier's existence before proceeding; an
    unknown path identifier yields ERR_NOT_FOUND."

    Design: Corner/entities/get_driver_not_found_returns_404
    """
    resp = api.get_driver("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, "ERR_NOT_FOUND")


def test_create_driver_missing_license_number_invalid_request(api):
    """PRD §2.9: "required body fields must be present and of the correct type ... A request
    failing any of these structural checks is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_driver_missing_required_field_returns_invalid_request
    """
    resp = api.create_driver({"full_name": "No License"}, ADMIN)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_driver_defaults_pc_authorized_and_cycle_rule(api):
    """PRD §3.1: "the three optional fields defaulting respectively to an offset of 0, a
    cycle_rule of SEVENTY_HOUR_8_DAY, and pc_authorized set to false."

    Design: Corner/entities/create_driver_default_pc_authorized_false_and_cycle_rule
    """
    data = validate_success(api.create_driver(factories.create_driver_payload(full_name="Default Driver"), ADMIN), 201)
    assert data["pc_authorized"] is False
    assert data["cycle_rule"] == "SEVENTY_HOUR_8_DAY"
    assert data["home_terminal_tz_offset_minutes"] == 0


def test_driver_current_duty_status_derived_from_latest_event(api):
    """PRD §3.3: "The event records the vehicle on a computed vehicle_id snapshot copied from
    the device's installed vehicle at append time."
    PRD §2.5: "A driver's current_duty_status and cycle_on_duty_minutes ... are all derived
    fields."

    Design: Corner/entities/driver_computed_current_duty_status_ignores_input
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:30:00Z")
    data = fixtures.get_driver(d_id)
    assert data["current_duty_status"] == "DRIVING"


def test_create_driver_invalid_cycle_rule_enum_rejected(api):
    """PRD §2.9: "every enum-valued field must carry a value inside its declared domain ... A
    request failing any of these structural checks is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_driver_invalid_cycle_rule_enum_rejected
    """
    resp = api.create_driver(
        factories.create_driver_payload(full_name="Bad Cycle", cycle_rule="NINETY_HOUR"), ADMIN)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_duplicate_license_number_rejected(api):
    """PRD §2.9: "A Driver's license_number must be unique across all drivers; a duplicate is
    rejected with ERR_DUPLICATE_LICENSE."

    Design: Corner/entities/duplicate_license_number_rejected
    """
    validate_success(api.create_driver({"license_number": "CDL-DUP", "full_name": "First"}, ADMIN), 201)
    resp = api.create_driver({"license_number": "CDL-DUP", "full_name": "Second"}, ADMIN)
    validate_error(resp, "ERR_DUPLICATE_LICENSE")


def test_duplicate_unit_number_rejected(api):
    """PRD §2.9: "A Vehicle's unit_number must be unique across all vehicles; a duplicate is
    rejected with ERR_DUPLICATE_UNIT."

    Design: Corner/entities/duplicate_unit_number_rejected
    """
    validate_success(api.create_vehicle({"unit_number": "UDUP", "vin": "VINDUP1"}, ADMIN), 201)
    resp = api.create_vehicle({"unit_number": "UDUP", "vin": "VINDUP2"}, ADMIN)
    validate_error(resp, "ERR_DUPLICATE_UNIT")


def test_duplicate_serial_number_rejected(api):
    """PRD §2.9: "An ELDDevice's serial_number must be unique across all devices; a duplicate
    is rejected with ERR_DUPLICATE_SERIAL."

    Design: Corner/entities/duplicate_serial_number_rejected
    """
    vehicle = fixtures.create_vehicle()
    validate_success(api.create_device({"serial_number": "SDUP", "vehicle_id": vehicle["id"]}, ADMIN), 201)
    resp = api.create_device({"serial_number": "SDUP", "vehicle_id": vehicle["id"]}, ADMIN)
    validate_error(resp, "ERR_DUPLICATE_SERIAL")


def test_pc_segment_has_no_version_field(api):
    """PRD §2.4: "The PersonalConveyanceSegment resource is the sole exception: it is a derived
    audit record carrying only id and created_at. It has neither an updated_at nor a version
    field".
    PRD §3.7: "The segment records the driver_id, the event_id of the PC event it summarizes,
    and a computed minutes_excluded equal to that event's duration_minutes".

    Design: Corner/entities/pc_segment_immutable_no_version_field
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z",
                                        driver_overrides={"pc_authorized": True})
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:00:00Z",
                  special_driving_category="PERSONAL_CONVEYANCE", annotation="Drove to motel.")  # 90 min PC
    stream.append("OFF_DUTY", "2026-06-01T07:30:00Z")  # closes PC interval

    data, meta = validate_paginated(api.list_pc_segments(ADMIN, params={"driver_id": d_id}))
    assert meta["total_count"] == 1
    seg = data[0]
    assert_pc_segment(seg)
    assert seg["minutes_excluded"] == 90
    assert_no_version_field(seg)


def test_new_driver_initial_state_off_duty_active(api):
    """PRD §3.1: "A new driver is created with status ACTIVE, version 1, a current_duty_status
    of OFF_DUTY because no events yet exist".

    Design: Corner/state_machines/new_driver_initial_current_duty_status_off_duty
    """
    data = validate_success(api.create_driver(factories.create_driver_payload(full_name="Fresh Driver"), ADMIN), 201)
    assert data["current_duty_status"] == "OFF_DUTY"
    assert data["status"] == "ACTIVE"
    assert data["cycle_on_duty_minutes"] == 0


# =====================================================================
# Corner / entities — listing & pagination
# =====================================================================
def test_list_drivers_pagination_envelope(api):
    """PRD §2.3: "the meta object on a list response carries the four pagination fields limit,
    offset, total_count, and has_more, where total_count is the size of the full filtered set
    and has_more indicates whether records remain beyond the returned page."

    Design: Corner/entities/list_drivers_pagination_envelope
    """
    fixtures.create_driver(full_name="Page One")
    fixtures.create_driver(full_name="Page Two")
    data, meta = validate_paginated(api.list_drivers(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# =====================================================================
# Corner / endpoints — computed reads & reverse-reachability
# =====================================================================
def test_get_duty_event_returns_computed_duration(api):
    """PRD §2.8: "The duration an event occupies is the whole number of minutes from that
    event's event_time to the next surviving event's event_time for the same driver".

    Design: Corner/endpoints/get_duty_event_by_id_returns_computed_duration
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    evt = stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")
    stream.append("DRIVING", "2026-06-01T06:30:00Z")  # closes ON_DUTY at 30 min
    data = fixtures.get_event(evt["id"])
    assert data["duration_minutes"] == 30


def test_list_duty_events_filtered_by_vehicle(api):
    """PRD §3.6: "Events may be listed and filtered by driver_id, device_id, vehicle_id,
    record_status, or edited_from_event_id".

    Design: Corner/endpoints/list_duty_events_filtered_by_vehicle
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id, veh_id = setup["driver_id"], setup["vehicle_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:30:00Z")

    data, meta = validate_paginated(api.list_duty_events(ADMIN, params={"vehicle_id": veh_id}))
    assert meta["total_count"] == 1
    assert data[0]["vehicle_id"] == veh_id


# =====================================================================
# Difficulty / cross_entity_state_dependency — certify blocked by open event
# =====================================================================
def test_certify_closed_day_blocked_by_open_event(api):
    """PRD §3.8: "a past day — one whose log_date is earlier than today — cannot be certified
    while any ACTIVE event in that day still has a null duration_minutes, because an open event
    means the day is not yet closed; such an attempt is rejected with
    ERR_OPEN_EVENT_ON_CLOSED_DAY."

    Design: Difficulty/cross_entity_state_dependency/certify_blocked_by_open_event_on_closed_day
    """
    vehicle = fixtures.create_vehicle()
    device = fixtures.create_device(vehicle["id"])
    driver = fixtures.create_driver()
    d_id = driver["id"]
    fixtures.pin_clock("2026-05-30T08:00:00Z")
    fixtures.login(device["id"], d_id)
    stream = fixtures.EventStream(d_id, device["id"])
    stream.append("ON_DUTY_NOT_DRIVING", "2026-05-30T07:00:00Z")  # open event (no successor)
    log = fixtures.open_daily_log(d_id, "2026-05-30")
    # Advance the clock so 2026-05-30 is a closed past day.
    fixtures.pin_clock("2026-06-01T08:00:00Z")

    resp = api.certify_daily_log(log["id"], make_driver_headers(d_id))
    validate_error(resp, "ERR_OPEN_EVENT_ON_CLOSED_DAY")
    after = validate_success(api.get_daily_log(log["id"], ADMIN), 200)
    assert after["certification_status"] == "UNCERTIFIED"


def test_certify_future_day_blocked_independent_of_open_event(api):
    """PRD §3.8: "A log whose log_date is in the future relative to the server's current clock
    cannot be certified and is rejected with ERR_CANNOT_CERTIFY_FUTURE."

    Design: Difficulty/cross_entity_state_dependency/certify_blocked_by_open_event_on_closed_day
    """
    driver = fixtures.create_driver()
    fixtures.pin_clock("2026-06-01T12:00:00Z")
    log = fixtures.open_daily_log(driver["id"], "2026-06-10")
    resp = api.certify_daily_log(log["id"], make_driver_headers(driver["id"]))
    validate_error(resp, "ERR_CANNOT_CERTIFY_FUTURE")
