"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Films LLC",
    "FEIN": "20-0000001",
    "SCOPE": "THEATRICAL",
    "SLATE_BUDGET_CENTS": 20_000_000,
    "TITLE": "Test Production",
    "TIER": "ULTRA_LOW_BUDGET",
    "BUDGET_CENTS": 20_000_000,
    "CREW_MEMBER_REF": "W-CAM-1",
    "DEPARTMENT": "CAMERA",
    "CLASSIFICATION": "CAMERA_OPERATOR",
    "DAILY_RATE_CENTS": 100_000,
    "WORK_DATE": "2026-08-10",
    "CALL_TIME_MINUTES": 480,
    "WRAP_TIME_MINUTES": 960,
    "MEAL_BREAKS": [{"start_minutes": 600, "end_minutes": 630}],
    "CATEGORY": "PAY",
    "INCIDENT_DATE": "2026-07-20",
    "DESCRIPTION": "Test grievance",
    "PERIOD_INDEX": 1,
    "EVENT_TYPE": "STRIKE",
    "START_DATE": "2026-08-05",
}


def create_producer_company_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["LEGAL_NAME"], "fein": DEFAULTS["FEIN"]}
    defaults.update(overrides)
    return defaults


def create_signatory_application_payload(**overrides) -> dict:
    defaults = {
        "producer_company_id": None,
        "requested_agreement_scope": DEFAULTS["SCOPE"],
        "estimated_slate_budget_cents": DEFAULTS["SLATE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_production_payload(**overrides) -> dict:
    defaults = {
        "producer_company_id": None,
        "title": DEFAULTS["TITLE"],
        "agreement_tier": DEFAULTS["TIER"],
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(**overrides) -> dict:
    defaults = {
        "production_id": None,
        "crew_member_ref": DEFAULTS["CREW_MEMBER_REF"],
        "department": DEFAULTS["DEPARTMENT"],
        "classification": DEFAULTS["CLASSIFICATION"],
        "daily_rate_cents": DEFAULTS["DAILY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_work_day_log_payload(**overrides) -> dict:
    defaults = {
        "crew_assignment_id": None,
        "work_date": DEFAULTS["WORK_DATE"],
        "call_time_minutes": DEFAULTS["CALL_TIME_MINUTES"],
        "wrap_time_minutes": DEFAULTS["WRAP_TIME_MINUTES"],
        "meal_breaks": [dict(m) for m in DEFAULTS["MEAL_BREAKS"]],
    }
    defaults.update(overrides)
    return defaults


def create_grievance_payload(**overrides) -> dict:
    defaults = {
        "production_id": None,
        "category": DEFAULTS["CATEGORY"],
        "incident_date": DEFAULTS["INCIDENT_DATE"],
        "description": DEFAULTS["DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_contribution_report_payload(**overrides) -> dict:
    defaults = {
        "production_id": None,
        "period_index": DEFAULTS["PERIOD_INDEX"],
        "work_day_log_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {"production_id": None, "scope_period_indices": [1]}
    defaults.update(overrides)
    return defaults


def create_force_majeure_event_payload(**overrides) -> dict:
    defaults = {
        "production_id": None,
        "event_type": DEFAULTS["EVENT_TYPE"],
        "start_date": DEFAULTS["START_DATE"],
    }
    defaults.update(overrides)
    return defaults
