"""Payload factories — one per creation endpoint, input fields only."""

from .constants import TEST_DEFAULTS


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Organization",
        "org_type": "INTERNAL_DEPARTMENT",
        "contact_email": "contact@univ.edu",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": "ROOM-1",
        "building_code": "TST",
        "capacity": 30,
        "internal_hourly_rate_cents": TEST_DEFAULTS["INTERNAL_RATE"],
        "student_hourly_rate_cents": TEST_DEFAULTS["STUDENT_RATE"],
        "external_hourly_rate_cents": TEST_DEFAULTS["EXTERNAL_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = {
        "name": "Fall 2026",
        "term_start_date": "2026-09-01T00:00:00Z",
        "term_end_date": "2026-12-15T00:00:00Z",
        "priority_open_at": "2026-08-10T00:00:00Z",
        "general_open_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_academic_block_payload(term_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "course_code": "TST-100",
        "instructor_name": "Dr. Test",
        "enrollment": 50,
        "days_of_week": ["MON"],
        "start_time": "10:00",
        "end_time": "11:00",
    }
    defaults.update(overrides)
    return defaults


def create_scheduling_run_payload(term_id, expected_term_version, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "expected_term_version": expected_term_version,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(room_id, expected_room_version, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "title": "Test Event",
        "expected_attendance": 10,
        "start_at": "2026-09-14T14:00:00Z",
        "end_at": "2026-09-14T15:00:00Z",
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_service_order_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "category": "AV",
        "quantity": 1,
        "service_start_at": "2026-09-14T13:30:00Z",
        "service_end_at": "2026-09-14T15:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_crew_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Crew",
        "category": "AV",
        "concurrent_capacity": 1,
        "shift_start": "08:00",
        "shift_end": "20:00",
    }
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "grant_type": "PHYSICAL_KEY",
    }
    defaults.update(overrides)
    return defaults
