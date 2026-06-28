"""Payload factories — one per entity, input fields only.

Each factory builds a minimal valid request body; pass **overrides to control
the values a test cares about. FK fields (facility_id, lane_id, member_id, ...)
have no sensible default and must be supplied by the caller.
"""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "LANE_LABEL": "Cage 1",
    "MEMBER_NAME": "Test Member",
    "INSTRUCTOR_NAME": "Test Coach",
    "HOURLY_RATE_CENTS": 4000,
    "TOKEN_PRICE_CENTS": 500,
}


def create_facility_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["FACILITY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_lane_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "label": DEFAULTS["LANE_LABEL"],
        "kind": "CAGE",
        "buffer_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(facility_id: str, lane_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "lane_id": lane_id,
        "model": "WHEEL",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_payload(
    facility_id: str, lane_id: str, start_utc: str, end_utc: str, severity: str, **overrides
) -> dict:
    defaults = {
        "facility_id": facility_id,
        "lane_id": lane_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "full_name": DEFAULTS["MEMBER_NAME"],
        "tier": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(facility_id: str, member_id: str, **overrides) -> dict:
    defaults = {"facility_id": facility_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_instructor_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "full_name": DEFAULTS["INSTRUCTOR_NAME"],
        "rate_cents_per_hour": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(
    facility_id: str,
    lane_id: str,
    member_id: str,
    kind: str,
    pay_mode: str,
    start_utc: str,
    end_utc: str,
    **overrides,
) -> dict:
    defaults = {
        "facility_id": facility_id,
        "lane_id": lane_id,
        "member_id": member_id,
        "kind": kind,
        "pay_mode": pay_mode,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(
    facility_id: str,
    lane_id: str,
    kind: str,
    capacity: int,
    price_cents: int,
    session_start_utc: str,
    session_end_utc: str,
    **overrides,
) -> dict:
    defaults = {
        "facility_id": facility_id,
        "lane_id": lane_id,
        "kind": kind,
        "capacity": capacity,
        "price_cents": price_cents,
        "session_start_utc": session_start_utc,
        "session_end_utc": session_end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(member_id: str, expected_program_version: int, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults
