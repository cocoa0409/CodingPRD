"""Payload factories — one per create endpoint, input fields only.

Each factory returns a dict of the client-supplied input fields the PRD names for
that resource, with sensible defaults that callers can override.
"""

DEFAULTS = {
    "CLIENT_FEE_CENTS": 15000,
    "BASE_FEE_CENTS": 2000,
    "REIMBURSE_CAP_CENTS": 5000,
    "HOME_LAT": 40.0,
    "HOME_LNG": -74.0,
    "LOC_LAT": 40.5,
    "LOC_LNG": -74.5,
    "WINDOW_START": "2026-06-01T00:00:00Z",
    "WINDOW_END": "2026-06-30T00:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    """POST /clients — company_name, billing_email, fee_per_completed_shop_cents."""
    payload = {
        "company_name": "Test Client",
        "billing_email": "ap@test.example",
        "fee_per_completed_shop_cents": DEFAULTS["CLIENT_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_shopper_payload(**overrides) -> dict:
    """POST /shoppers — full_name, email, home_lat, home_lng, tax_id_on_file?."""
    payload = {
        "full_name": "Test Shopper",
        "email": "shopper@test.example",
        "home_lat": DEFAULTS["HOME_LAT"],
        "home_lng": DEFAULTS["HOME_LNG"],
    }
    payload.update(overrides)
    return payload


def create_location_payload(**overrides) -> dict:
    """POST /clients/{id}/locations — label, lat, lng, scenario_family."""
    payload = {
        "label": "Test Store",
        "lat": DEFAULTS["LOC_LAT"],
        "lng": DEFAULTS["LOC_LNG"],
        "scenario_family": "RETAIL",
    }
    payload.update(overrides)
    return payload


def create_script_payload(**overrides) -> dict:
    """POST /clients/{id}/scripts — title, scenario_family, required_photo_count,
    receipt_required?, reimburse_cap_cents, base_fee_cents, weights_json, passing_score.
    """
    payload = {
        "title": "Test Script",
        "scenario_family": "RETAIL",
        "required_photo_count": 1,
        "receipt_required": True,
        "reimburse_cap_cents": DEFAULTS["REIMBURSE_CAP_CENTS"],
        "base_fee_cents": DEFAULTS["BASE_FEE_CENTS"],
        "weights_json": {"greeting": 0.3, "cleanliness": 0.3, "service": 0.4},
        "passing_score": 70,
    }
    payload.update(overrides)
    return payload


def create_wave_payload(**overrides) -> dict:
    """POST /clients/{id}/waves — name, field_window_start, field_window_end,
    rotation_cooldown_days?.
    """
    payload = {
        "name": "Test Wave",
        "field_window_start": DEFAULTS["WINDOW_START"],
        "field_window_end": DEFAULTS["WINDOW_END"],
        "rotation_cooldown_days": 30,
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(wave_id, shopper_id, location_id, script_id,
                              due_at, **overrides) -> dict:
    """POST /assignments — wave_id, shopper_id, location_id, script_id, due_at."""
    payload = {
        "wave_id": wave_id,
        "shopper_id": shopper_id,
        "location_id": location_id,
        "script_id": script_id,
        "due_at": due_at,
    }
    payload.update(overrides)
    return payload


def create_certification_payload(**overrides) -> dict:
    """POST /shoppers/{id}/certification-attempts — raw_score, scenario_family."""
    payload = {
        "raw_score": 90,
        "scenario_family": "RETAIL",
    }
    payload.update(overrides)
    return payload


def create_evidence_payload(kind, object_uri, **overrides) -> dict:
    """POST /assignments/{id}/evidence — kind, object_uri, section_key?,
    receipt_amount_cents?.
    """
    payload = {
        "kind": kind,
        "object_uri": object_uri,
    }
    payload.update(overrides)
    return payload


def create_scorecard_payload(section_scores_json, **overrides) -> dict:
    """POST /assignments/{id}/scorecard — section_scores_json."""
    payload = {"section_scores_json": section_scores_json}
    payload.update(overrides)
    return payload
