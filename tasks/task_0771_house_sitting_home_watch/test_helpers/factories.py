"""Payload factories — one per entity/action, input fields only."""

DEFAULTS = {
    "CLIENT_NAME": "Ada Client",
    "CLIENT_EMAIL": "ada@x.com",
    "SITTER_NAME": "Sam Sitter",
    "SITTER_EMAIL": "sam@x.com",
    "PROPERTY_LABEL": "Cabin",
    "PROPERTY_ADDRESS": "1 Lake Rd",
    "CENTER_LAT": 40.0,
    "CENTER_LNG": -70.0,
    "BASE_VISIT_RATE_CENTS": 4000,
    "PROVIDER_REF": "PRV-1",
    "BG_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "COVERAGE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "COVERAGE_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "BOND_COVERAGE_CENTS": 1000000,
    "PHOTO_URL": "http://x/1.jpg",
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "email": DEFAULTS["CLIENT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "label": DEFAULTS["PROPERTY_LABEL"],
        "address": DEFAULTS["PROPERTY_ADDRESS"],
        "size_tier": "SMALL",
        "has_pets": False,
        "checklist_config": ["MAIL"],
        "center_lat": DEFAULTS["CENTER_LAT"],
        "center_lng": DEFAULTS["CENTER_LNG"],
        "key_copies_total": 1,
    }
    payload.update(overrides)
    return payload


def create_sitter_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["SITTER_NAME"],
        "email": DEFAULTS["SITTER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_background_check_payload(sitter_id, **overrides) -> dict:
    payload = {
        "sitter_id": sitter_id,
        "provider_ref": DEFAULTS["PROVIDER_REF"],
        "expires_at": DEFAULTS["BG_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_coverage_policy_payload(sitter_id, expected_sitter_version,
                                   policy_type="BOND", **overrides) -> dict:
    payload = {
        "sitter_id": sitter_id,
        "policy_type": policy_type,
        "coverage_amount_cents": DEFAULTS["BOND_COVERAGE_CENTS"],
        "effective_from": DEFAULTS["COVERAGE_EFFECTIVE_FROM"],
        "expires_at": DEFAULTS["COVERAGE_EXPIRES_AT"],
        "expected_sitter_version": expected_sitter_version,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(property_id, booking_type="VACATION",
                           start_date="2026-06-01T00:00:00Z",
                           end_date="2026-06-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "booking_type": booking_type,
        "start_date": start_date,
        "end_date": end_date,
        "base_visit_rate_cents": DEFAULTS["BASE_VISIT_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_key_assignment_payload(property_id, sitter_id, booking_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "sitter_id": sitter_id,
        "booking_id": booking_id,
    }
    payload.update(overrides)
    return payload


def create_visit_log_payload(visit_id, entry_type="PHOTO",
                             captured_at="2026-06-01T09:06:00Z", **overrides) -> dict:
    payload = {
        "visit_id": visit_id,
        "entry_type": entry_type,
        "gps_lat": DEFAULTS["CENTER_LAT"],
        "gps_lng": DEFAULTS["CENTER_LNG"],
        "captured_at": captured_at,
    }
    if entry_type == "PHOTO":
        payload["photo_url"] = DEFAULTS["PHOTO_URL"]
    payload.update(overrides)
    return payload


def create_incident_payload(visit_id, category="OTHER", severity="MINOR", **overrides) -> dict:
    payload = {
        "visit_id": visit_id,
        "category": category,
        "severity": severity,
    }
    payload.update(overrides)
    return payload


def check_in_payload(gps_lat=40.0, gps_lng=-70.0, **overrides) -> dict:
    payload = {"gps_lat": gps_lat, "gps_lng": gps_lng}
    payload.update(overrides)
    return payload


def check_out_payload(completed_tasks=None, **overrides) -> dict:
    payload = {"completed_tasks": completed_tasks if completed_tasks is not None else ["MAIL"]}
    payload.update(overrides)
    return payload


def decide_payload(decision="CLEARED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resolve_payload(assessed_damage_cents=0, **overrides) -> dict:
    payload = {"assessed_damage_cents": assessed_damage_cents}
    payload.update(overrides)
    return payload
