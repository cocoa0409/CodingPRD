"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_DUE_DATE,
    DEFAULT_OWNER_DEPARTMENT,
    DEFAULT_OWNER_EMAIL,
    DEFAULT_OWNER_NAME,
    DEFAULT_PLAN_TARGET,
    DEFAULT_POLICY_EFFECTIVE,
)

_citation_counter = {"n": 0}
_code_counter = {"n": 0}


def _next_citation() -> str:
    _citation_counter["n"] += 1
    return f"12 CFR Part {1000 + _citation_counter['n']}"


def _next_code(prefix: str) -> str:
    _code_counter["n"] += 1
    return f"{prefix}-{_code_counter['n']:04d}"


def create_business_owner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULT_OWNER_NAME,
        "department": DEFAULT_OWNER_DEPARTMENT,
        "email": DEFAULT_OWNER_EMAIL,
    }
    defaults.update(overrides)
    return defaults


def create_change_payload(**overrides) -> dict:
    defaults = {
        "citation": _next_citation(),
        "title": "Regulatory change",
        "summary": "Change summary",
        "feed_source": "MANUAL_ENTRY",
        "jurisdiction": "US-FED",
        "regulator": "OCC",
        "published_at": "2026-07-01T00:00:00Z",
        "effective_date": "2026-12-01T00:00:00Z",
        "severity_hint": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_obligation_payload(**overrides) -> dict:
    defaults = {
        "obligation_code": _next_code("OBL"),
        "title": "Obligation",
        "criticality": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_control_payload(**overrides) -> dict:
    defaults = {
        "control_code": _next_code("CTL"),
        "title": "Control",
        "owner_department": "COMP",
        "review_frequency_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_mapping_payload(**overrides) -> dict:
    defaults = {"coverage_weight": 3}
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {"due_date": DEFAULT_DUE_DATE}
    defaults.update(overrides)
    return defaults


def submit_assessment_payload(**overrides) -> dict:
    defaults = {
        "likelihood_score": 3,
        "severity_score": 3,
        "affected_business_lines": 1,
        "findings_summary": "Findings",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "title": "Implementation plan",
        "target_completion_date": DEFAULT_PLAN_TARGET,
    }
    defaults.update(overrides)
    return defaults


def create_policy_update_payload(**overrides) -> dict:
    defaults = {
        "title": "Policy update",
        "change_summary": "Policy change",
        "effective_date": DEFAULT_POLICY_EFFECTIVE,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "committee_name": "BOARD_RISK_COMMITTEE",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_artifact_payload(**overrides) -> dict:
    defaults = {"artifact_type": "POLICY_DOCUMENT", "uri": "s3://ev/artifact.pdf"}
    defaults.update(overrides)
    return defaults


def attestation_record(person_ref, department="ENG", completed=True) -> dict:
    return {"person_ref": person_ref, "department": department, "completed": completed}


def department_records(department, total, completed_count, prefix="") -> list:
    """Build `total` attestation records for one department, first
    `completed_count` completed."""
    return [
        attestation_record(f"{prefix}{department.lower()}{i:02d}", department, i <= completed_count)
        for i in range(1, total + 1)
    ]
