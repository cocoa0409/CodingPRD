"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ADDRESS": "100 Test St",
    "DAY_LIMIT_DB": 65,
    "NIGHT_LIMIT_DB": 55,
    "DAY_START_HOUR": 7,
    "NIGHT_START_HOUR": 22,
    "PERMITTED_MAX_DB": 90,
}


def create_property_payload(**overrides) -> dict:
    defaults = {
        "address": DEFAULTS["ADDRESS"],
        "zoning_type": "RESIDENTIAL",
    }
    defaults.update(overrides)
    return defaults


def create_noise_policy_payload(**overrides) -> dict:
    defaults = {
        "zoning_type": "RESIDENTIAL",
        "day_limit_db": DEFAULTS["DAY_LIMIT_DB"],
        "night_limit_db": DEFAULTS["NIGHT_LIMIT_DB"],
        "day_start_hour": DEFAULTS["DAY_START_HOUR"],
        "night_start_hour": DEFAULTS["NIGHT_START_HOUR"],
    }
    defaults.update(overrides)
    return defaults


def create_variance_permit_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "permit_type": "CONSTRUCTION",
        "requested_start": "2026-06-01T00:00:00Z",
        "requested_end": "2026-06-05T00:00:00Z",
        "permitted_max_db": DEFAULTS["PERMITTED_MAX_DB"],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "reported_at": "2026-06-01T12:00:00Z",
        "noise_type": "MACHINERY",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "measured_decibel": 80,
        "measured_at": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(**overrides) -> dict:
    defaults = {
        "scheduled_at": "2026-06-05T10:00:00Z",
        "hearing_officer_id": "hof-9",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, expected_enforcement_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_enforcement_version": expected_enforcement_version,
    }
    defaults.update(overrides)
    return defaults


def create_abatement_order_payload(property_id, expected_property_version, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "expected_property_version": expected_property_version,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(complaint_id, **overrides) -> dict:
    defaults = {
        "complaint_id": complaint_id,
        "agency": "POLICE",
    }
    defaults.update(overrides)
    return defaults
