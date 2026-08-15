"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
from .constants import DEFAULT_EVENT_END, DEFAULT_EVENT_START, TEST_DEFAULTS

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_organizer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Test Organizer {n}",
        "email": f"organizer{n}@example.com",
        "phone": f"555-{1000 + n}",
        "address": f"{n} Maple Ave",
    }
    defaults.update(overrides)
    return defaults


def create_street_segment_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Segment {n}",
        "jurisdiction": "CITY",
        "segment_kind": "RESIDENTIAL",
        "household_count": TEST_DEFAULTS["SEGMENT_HOUSEHOLD_COUNT"],
        "length_m": TEST_DEFAULTS["SEGMENT_LENGTH_M"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_petition_payload(segment_id: str, **overrides) -> dict:
    defaults = {"segment_id": segment_id}
    defaults.update(overrides)
    return defaults


def create_signature_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "household_address": f"{n} Oak St",
        "signer_name": f"Signer {n}",
        "signer_email": f"signer{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def petition_verify_payload(decision: str, note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def create_permit_application_payload(petition_id: str, **overrides) -> dict:
    defaults = {
        "petition_id": petition_id,
        "event_start_at": DEFAULT_EVENT_START,
        "event_end_at": DEFAULT_EVENT_END,
        "expected_attendance": TEST_DEFAULTS["EXPECTED_ATTENDANCE"],
        "amplified_sound": False,
        "alcohol_served": False,
        "food_vendors": False,
    }
    defaults.update(overrides)
    return defaults


def patch_permit_application_payload(expected_application_version: int, **overrides) -> dict:
    defaults = {"expected_application_version": expected_application_version}
    defaults.update(overrides)
    return defaults


def create_traffic_control_plan_payload(**overrides) -> dict:
    defaults = {
        "barricade_count": 1,
        "cone_count": 0,
        "sign_count": 0,
        "emergency_lane_width_m": 6.0,
        "emergency_lane_continuous": True,
        "placement_notes": "barricades at both ends",
    }
    defaults.update(overrides)
    return defaults


def review_payload(decision: str, note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def create_sound_plan_payload(**overrides) -> dict:
    defaults = {
        "speaker_count": 2,
        "max_db_at_property_line": 60,
        "planned_sound_end": "21:30",
    }
    defaults.update(overrides)
    return defaults


def create_insurance_payload(expected_application_version: int, **overrides) -> dict:
    defaults = {
        "kind": "CERTIFICATE",
        "expected_application_version": expected_application_version,
        "insurer_name": "Acme Mutual",
        "policy_number": "P-1000",
        "coverage_amount_cents": TEST_DEFAULTS["INSURANCE_COVERAGE_CENTS"],
        "expires_on": TEST_DEFAULTS["INSURANCE_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_stock_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "depot_name": f"Depot {n}",
        "equipment_kind": "BARRICADE",
        "total_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(equipment_kind: str, units: int, **overrides) -> dict:
    defaults = {"equipment_kind": equipment_kind, "units": units}
    defaults.update(overrides)
    return defaults


def create_cost_share_pool_payload(target_cents: int, **overrides) -> dict:
    defaults = {"target_cents": target_cents}
    defaults.update(overrides)
    return defaults


def create_contribution_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "household_address": f"{n} Birch Rd",
        "amount_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_post_event_report_payload(**overrides) -> dict:
    defaults = {
        "cleanup_completed": True,
        "cleanup_notes": "street swept and clear",
    }
    defaults.update(overrides)
    return defaults


def inspect_report_payload(result: str, cleaning_charge_cents=None) -> dict:
    payload = {"result": result}
    if cleaning_charge_cents is not None:
        payload["cleaning_charge_cents"] = cleaning_charge_cents
    return payload


def return_payload(returned_units: int) -> dict:
    return {"returned_units": returned_units}
