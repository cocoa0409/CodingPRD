"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "ACCOUNT_NAME": "Test Facility Co",
    "HOURLY_RATE_CENTS": 20000,
    "EVENT_BASE_FEE_CENTS": 150000,
    "EVENT_PER_RESCUER_CENTS": 25000,
    "CREDIT_LIMIT_CENTS": 100000000,
    "SPACE_CODE": "TK-1",
    "MAX_ENTRANTS": 2,
    "REQUIRED_TEAM_SIZE": 1,
    "RETRIEVAL_SYSTEM_TYPE": "TRIPOD",
    "PURPOSE": "Routine vessel inspection",
    "PERIOD_START": "2026-08-03T00:00:00Z",
    "PERIOD_END": "2026-08-04T00:00:00Z",
}


def create_personnel_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Worker",
        "role_qualifications": [],
    }
    defaults.update(overrides)
    return defaults


def create_client_account_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ACCOUNT_NAME"],
        "billing_mode": "HOURLY_STANDBY",
        "hourly_standby_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "event_base_fee_cents": DEFAULTS["EVENT_BASE_FEE_CENTS"],
        "event_per_rescuer_cents": DEFAULTS["EVENT_PER_RESCUER_CENTS"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_confined_space_payload(**overrides) -> dict:
    defaults = {
        "space_code": DEFAULTS["SPACE_CODE"],
        "classification": "PERMIT_REQUIRED",
        "requires_continuous_monitoring": False,
        "max_entrants": DEFAULTS["MAX_ENTRANTS"],
        "ventilation_required": False,
        "blind_flange_required": False,
        "exposure_standard": "TWA8",
    }
    defaults.update(overrides)
    return defaults


def create_rescue_plan_payload(expected_space_version, **overrides) -> dict:
    defaults = {
        "required_team_size": DEFAULTS["REQUIRED_TEAM_SIZE"],
        "required_certifications": ["CONFINED_SPACE_RESCUE"],
        "retrieval_system_type": DEFAULTS["RETRIEVAL_SYSTEM_TYPE"],
        "expected_space_version": expected_space_version,
    }
    defaults.update(overrides)
    return defaults


def approve_plan_payload(expected_space_version) -> dict:
    return {"expected_space_version": expected_space_version}


def create_entry_permit_payload(expected_space_version, **overrides) -> dict:
    defaults = {
        "purpose": DEFAULTS["PURPOSE"],
        "planned_start_at": "2026-08-03T05:00:00Z",
        "planned_end_at": "2026-08-03T20:00:00Z",
        "expected_space_version": expected_space_version,
    }
    defaults.update(overrides)
    return defaults


def create_isolation_verification_payload(**overrides) -> dict:
    defaults = {
        "isolation_type": "VENTILATION",
        "evidence_ref": "evidence-1",
    }
    defaults.update(overrides)
    return defaults


def create_roster_entry_payload(personnel_id, **overrides) -> dict:
    defaults = {
        "personnel_id": personnel_id,
        "assignment_role": "ENTRANT",
        "scheduled_start_at": "2026-08-03T05:00:00Z",
        "scheduled_end_at": "2026-08-03T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_atmospheric_reading_payload(**overrides) -> dict:
    defaults = {
        "reading_kind": "PRE_ENTRY",
        "o2_pct": 20.9,
        "lel_pct": 0,
        "h2s_ppm": 0,
        "co_ppm": 0,
    }
    defaults.update(overrides)
    return defaults


def create_standby_assignment_payload(rescuer_id, **overrides) -> dict:
    defaults = {
        "rescuer_id": rescuer_id,
        "standby_start_at": "2026-08-03T05:00:00Z",
        "standby_end_at": "2026-08-03T20:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "severity": "MINOR",
        "kind": "EQUIPMENT",
        "description": "Equipment anomaly observed",
    }
    defaults.update(overrides)
    return defaults


def generate_statement_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def statement_adjustment_payload(**overrides) -> dict:
    defaults = {
        "credit_amount_cents": 1000,
        "reason": "Goodwill credit",
    }
    defaults.update(overrides)
    return defaults
