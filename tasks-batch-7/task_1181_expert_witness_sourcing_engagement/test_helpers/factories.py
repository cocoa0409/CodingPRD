"""Payload factories — one per entity, input fields only."""
import uuid

DEFAULTS = {
    "SPECIALTY_AREA": "med",
    "COURT": "SDNY",
    "BUDGET_CENTS": 1_000_000,
    "TRIAL_DATE": "2026-09-01T00:00:00Z",
    "REPORT_DEADLINE": "2026-07-01T17:00:00Z",
    "HOURLY_RATE_CENTS": 40_000,
    "RETAINER_CENTS": 0,
    "EXPENSE_CAP_CENTS": 0,
    "PERIOD_START": "2026-05-04T00:00:00Z",
    "PERIOD_END": "2026-05-08T00:00:00Z",
}


def unique_case_number(prefix="CV") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_expert_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Expert {uuid.uuid4().hex[:6]}",
        "specialty_area": DEFAULTS["SPECIALTY_AREA"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "case_number": unique_case_number(),
        "court": DEFAULTS["COURT"],
        "title": "Test Matter",
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
        "trial_date": DEFAULTS["TRIAL_DATE"],
        "report_deadline": DEFAULTS["REPORT_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_request_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "specialty_area": DEFAULTS["SPECIALTY_AREA"],
    }
    defaults.update(overrides)
    return defaults


def create_conflict_check_payload(expert_id: str, **overrides) -> dict:
    defaults = {
        "expert_id": expert_id,
        "adverse_parties": [],
    }
    defaults.update(overrides)
    return defaults


def create_credential_review_payload(expert_id: str, **overrides) -> dict:
    defaults = {
        "expert_id": expert_id,
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(engagement_request_id: str, expert_id: str, **overrides) -> dict:
    defaults = {
        "engagement_request_id": engagement_request_id,
        "expert_id": expert_id,
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "retainer_cents": DEFAULTS["RETAINER_CENTS"],
        "expense_cap_cents": DEFAULTS["EXPENSE_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_document_production_payload(**overrides) -> dict:
    defaults = {
        "title": "Production",
        "privilege_tier": "DISCOVERABLE",
        "content_ref": "s3://bucket/doc",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "title": "Expert Report",
        "report_type": "LIABILITY",
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": f"Suite {uuid.uuid4().hex[:4]}",
        "location": "NYC",
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(**overrides) -> dict:
    defaults = {
        "kind": "DEPOSITION",
        "start_at": "2026-06-15T10:00:00Z",
        "end_at": "2026-06-15T12:00:00Z",
        "estimated_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "line_items": [{"kind": "PREP", "hours": 1}],
        "travel_expense_cents": 0,
        "total_cents": 40_000,
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(**overrides) -> dict:
    defaults = {
        "overall_score": 4.0,
    }
    defaults.update(overrides)
    return defaults
