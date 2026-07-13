"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. System- and
computed-source fields (status, sign_status, amount_due_cents, tonnage, etc.)
are never sent by the client.
"""

DEFAULTS = {
    "ROUTE_NAME": "Test Route",
    "ZONE_CODE": "Z1",
    "SWEEP_WEEKDAY": "TUE",
    "BLOCK_LABEL": "100-BLK MAIN ST",
    "SIDE": "BOTH",
    "RESTRICTION_START": "08:00",
    "RESTRICTION_END": "10:00",
    "LINEAR_FEET": 300,
    "UNIT_NUMBER": "SW-1",
    "EQUIPMENT_TYPE": "MECHANICAL",
    "HOPPER_CAPACITY_LBS": 20000,
    "OPERATOR_NAME": "Sam",
    "SHIFT_DATE": "2026-03-10",
    "SHIFT_START_UTC": "2026-03-10T06:00:00Z",
    "SHIFT_END_UTC": "2026-03-10T20:00:00Z",
    "SCHEDULED_DATE": "2026-03-10",
    "WINDOW_START_UTC": "2026-03-10T06:00:00Z",
    "WINDOW_END_UTC": "2026-03-10T07:00:00Z",
    "PLATE": "ABC123",
    "SCANNED_AT_UTC": "2026-03-10T08:30:00Z",
    "SIGN_EXPIRES_AT": "2026-12-31T00:00:00Z",
    "RESIDENT_EMAIL": "resident@example.com",
    "RESIDENT_NAME": "Rae Resident",
}


def create_route_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROUTE_NAME"],
        "zone_code": DEFAULTS["ZONE_CODE"],
        "sweep_weekday": DEFAULTS["SWEEP_WEEKDAY"],
    }
    defaults.update(overrides)
    return defaults


def create_block_payload(route_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "block_label": DEFAULTS["BLOCK_LABEL"],
        "side": DEFAULTS["SIDE"],
        "restriction_start_local": DEFAULTS["RESTRICTION_START"],
        "restriction_end_local": DEFAULTS["RESTRICTION_END"],
        "linear_feet": DEFAULTS["LINEAR_FEET"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "type": DEFAULTS["EQUIPMENT_TYPE"],
        "hopper_capacity_lbs": DEFAULTS["HOPPER_CAPACITY_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(equipment_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "operator_name": DEFAULTS["OPERATOR_NAME"],
        "shift_date": DEFAULTS["SHIFT_DATE"],
        "start_utc": DEFAULTS["SHIFT_START_UTC"],
        "end_utc": DEFAULTS["SHIFT_END_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_sweep_event_payload(block_id, **overrides) -> dict:
    defaults = {
        "block_id": block_id,
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
        "window_start_utc": DEFAULTS["WINDOW_START_UTC"],
        "window_end_utc": DEFAULTS["WINDOW_END_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_suspension_payload(**overrides) -> dict:
    defaults = {
        "reason": "HOLIDAY",
        "scope": "SYSTEM",
        "start_date": "2026-03-09",
        "end_date": "2026-03-11",
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(block_id, sweep_event_id=None, **overrides) -> dict:
    defaults = {
        "block_id": block_id,
        "plate": DEFAULTS["PLATE"],
        "scanned_at_utc": DEFAULTS["SCANNED_AT_UTC"],
    }
    if sweep_event_id is not None:
        defaults["sweep_event_id"] = sweep_event_id
    defaults.update(overrides)
    return defaults


def create_resident_payload(home_block_id, **overrides) -> dict:
    defaults = {
        "email": DEFAULTS["RESIDENT_EMAIL"],
        "full_name": DEFAULTS["RESIDENT_NAME"],
        "home_block_id": home_block_id,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(resident_id, block_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "block_id": block_id,
        "category": "MISSED_BLOCK",
    }
    defaults.update(overrides)
    return defaults


def post_sign_payload(expected_block_version, sign_expires_at=None) -> dict:
    return {
        "expected_block_version": expected_block_version,
        "sign_expires_at": sign_expires_at or DEFAULTS["SIGN_EXPIRES_AT"],
    }
