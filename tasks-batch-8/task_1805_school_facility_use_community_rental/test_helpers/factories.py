"""Payload factories — one per creatable entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "SITE_CODE": "RHS",
    "SITE_NAME": "Riverview High",
    "SITE_TIMEZONE": "America/Los_Angeles",
    "FACILITY_CODE": "GYM",
    "FACILITY_TIER": "STANDARD",
    "CAPACITY": 300,
    "BUFFER_MINUTES": 30,
    "POLICY_CODE": "NP-STD",
    "HOURLY_RATE_CENTS": 5000,
    "CUSTODIAL_HOURLY_CENTS": 4000,
    "DEPOSIT_BASIS_POINTS": 2000,
    "DEPOSIT_FLOOR_CENTS": 10000,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "ORG_NAME": "Riverview PTA",
    "NONPROFIT_EIN": "12-3456789",
    "INSURER_NAME": "Aegis Mutual",
    "PER_OCCURRENCE_LIMIT_CENTS": 200000000,
    "AGGREGATE_LIMIT_CENTS": 400000000,
    "CERT_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "CERT_EFFECTIVE_TO": "2027-01-01T00:00:00Z",
    "EVENT_TITLE": "Community Event",
    "HEADCOUNT": 100,
}


def create_site_payload(**overrides) -> dict:
    defaults = {
        "site_code": DEFAULTS["SITE_CODE"],
        "display_name": DEFAULTS["SITE_NAME"],
        "rental_timezone": DEFAULTS["SITE_TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "facility_code": DEFAULTS["FACILITY_CODE"],
        "facility_tier": DEFAULTS["FACILITY_TIER"],
        "capacity": DEFAULTS["CAPACITY"],
        "setup_buffer_minutes": DEFAULTS["BUFFER_MINUTES"],
        "teardown_buffer_minutes": DEFAULTS["BUFFER_MINUTES"],
        "requires_custodian": True,
    }
    defaults.update(overrides)
    return defaults


def create_rate_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_code": DEFAULTS["POLICY_CODE"],
        "rate_class": "NONPROFIT",
        "facility_tier": DEFAULTS["FACILITY_TIER"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "deposit_basis_points": DEFAULTS["DEPOSIT_BASIS_POINTS"],
        "custodial_hourly_cents": DEFAULTS["CUSTODIAL_HOURLY_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "deposit_floor_cents": DEFAULTS["DEPOSIT_FLOOR_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_renter_payload(**overrides) -> dict:
    defaults = {
        "org_name": DEFAULTS["ORG_NAME"],
        "rate_class": "NONPROFIT",
        "nonprofit_registration_no": DEFAULTS["NONPROFIT_EIN"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_payload(**overrides) -> dict:
    defaults = {
        "insurer_name": DEFAULTS["INSURER_NAME"],
        "per_occurrence_limit_cents": DEFAULTS["PER_OCCURRENCE_LIMIT_CENTS"],
        "aggregate_limit_cents": DEFAULTS["AGGREGATE_LIMIT_CENTS"],
        "effective_from": DEFAULTS["CERT_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["CERT_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_calendar_event_payload(**overrides) -> dict:
    defaults = {
        "title": "School Event",
        "starts_at": "2026-12-01T01:00:00Z",
        "ends_at": "2026-12-01T03:00:00Z",
        "event_priority_tier": 0,
    }
    defaults.update(overrides)
    return defaults


def create_request_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "event_title": DEFAULTS["EVENT_TITLE"],
        "headcount_estimate": DEFAULTS["HEADCOUNT"],
        "starts_at": "2026-12-01T01:00:00Z",
        "ends_at": "2026-12-01T03:00:00Z",
        "district_sponsored": False,
    }
    defaults.update(overrides)
    return defaults


def create_damage_assessment_payload(**overrides) -> dict:
    defaults = {
        "line_items": [{"description": "Floor damage", "repair_cost_cents": 8000}],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "txn_kind": "DEPOSIT_CAPTURE",
        "amount_cents": 10000,
        "idempotency_key": "dep-1",
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_permit_payload(renter_org_id: str, facility_id: str, **overrides) -> dict:
    defaults = {
        "renter_org_id": renter_org_id,
        "facility_id": facility_id,
        "series_name": "Fall Soccer Saturdays",
        "recurrence_rule": "WEEKLY:SAT:18:00-21:00",
        "season_start": "2026-10-03T00:00:00Z",
        "season_end": "2026-10-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
