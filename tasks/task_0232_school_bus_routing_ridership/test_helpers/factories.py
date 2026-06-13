"""Payload factories — one per entity, input fields only (PRD §3).

Coordinate conventions used throughout the suite (school anchored at 40.0,-75.0):
  - far home   (40.05, -75.0) -> 3.45 mi  (DISTANCE eligible)
  - near home  (40.01, -75.0) -> 0.69 mi  (HAZARD/NONE)
  - edge home  (40.02171, -75.0) -> rounds to 1.50 mi (boundary)
"""

SCHOOL_LAT = 40.0
SCHOOL_LNG = -75.0


def create_district_payload(**overrides) -> dict:
    """POST /districts — required: name, school_lat, school_lng.
    Optional: walk_threshold_miles, hazard_override_enabled, missed_bus_grace_minutes.
    """
    defaults = {
        "name": "Test District",
        "school_lat": SCHOOL_LAT,
        "school_lng": SCHOOL_LNG,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(district_id, **overrides) -> dict:
    """POST /routes — required: district_id, name, seat_capacity.
    Optional: wheelchair_capacity.
    """
    defaults = {
        "district_id": district_id,
        "name": "Test Route",
        "seat_capacity": 20,
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(route_id, sequence, scheduled_departure, **overrides) -> dict:
    """POST /stops — required: route_id, label, lat, lng, sequence, scheduled_departure."""
    defaults = {
        "route_id": route_id,
        "label": f"Stop {sequence}",
        "lat": SCHOOL_LAT,
        "lng": SCHOOL_LNG,
        "sequence": sequence,
        "scheduled_departure": scheduled_departure,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(district_id, parent_id, rfid_uid, **overrides) -> dict:
    """POST /students — required: district_id, parent_id, full_name, grade,
    home_lat, home_lng, rfid_uid. Optional: hazard_zone, special_needs.
    """
    defaults = {
        "district_id": district_id,
        "parent_id": parent_id,
        "full_name": "Test Student",
        "grade": 5,
        "home_lat": 40.05,
        "home_lng": SCHOOL_LNG,
        "rfid_uid": rfid_uid,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(
    district_id, student_id, requested_route_id, requested_stop_id, **overrides
) -> dict:
    """POST /ridership-applications — required: district_id, student_id,
    requested_route_id, requested_stop_id.
    """
    defaults = {
        "district_id": district_id,
        "student_id": student_id,
        "requested_route_id": requested_route_id,
        "requested_stop_id": requested_stop_id,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(district_id, **overrides) -> dict:
    """POST /drivers — required: district_id, full_name. Optional: is_substitute."""
    defaults = {
        "district_id": district_id,
        "full_name": "Test Driver",
    }
    defaults.update(overrides)
    return defaults


def create_driver_assignment_payload(driver_id, expected_route_version, **overrides) -> dict:
    """POST /routes/{id}/driver-assignments — required: driver_id, expected_route_version.
    Optional: role (default PRIMARY), replaces_assignment_id (substitute only).
    """
    defaults = {
        "driver_id": driver_id,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def create_bus_trip_payload(route_id, driver_assignment_id, **overrides) -> dict:
    """POST /bus-trips — required: route_id, driver_assignment_id."""
    defaults = {
        "route_id": route_id,
        "driver_assignment_id": driver_assignment_id,
    }
    defaults.update(overrides)
    return defaults


def create_tap_payload(rfid_uid, direction, stop_sequence, **overrides) -> dict:
    """POST /bus-trips/{id}/taps — required: rfid_uid, direction, stop_sequence."""
    defaults = {
        "rfid_uid": rfid_uid,
        "direction": direction,
        "stop_sequence": stop_sequence,
    }
    defaults.update(overrides)
    return defaults


def create_missed_bus_report_payload(
    district_id, student_id, bus_trip_id, reported_stop_sequence, **overrides
) -> dict:
    """POST /missed-bus-reports — required: district_id, student_id, bus_trip_id,
    reported_stop_sequence.
    """
    defaults = {
        "district_id": district_id,
        "student_id": student_id,
        "bus_trip_id": bus_trip_id,
        "reported_stop_sequence": reported_stop_sequence,
    }
    defaults.update(overrides)
    return defaults
