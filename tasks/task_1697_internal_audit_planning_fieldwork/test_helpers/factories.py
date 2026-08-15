"""Payload factories — one per entity, input fields only (PRD §3)."""

# Canonical fieldwork window used by factories (well after the test clock date
# so the cooling-period rule never fires accidentally).
DEFAULT_WINDOW_START = "2026-02-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-02-28T00:00:00Z"
DEFAULT_ASSIGNMENT_END = "2026-03-01T00:00:00Z"  # half-open: [start, end)


def create_auditable_entity_payload(**overrides) -> dict:
    defaults = {"name": "Core Payments", "business_owner": "CFO"}
    defaults.update(overrides)
    return defaults


def create_auditor_payload(**overrides) -> dict:
    defaults = {"full_name": "Mary Manager", "grade": "MANAGER"}
    defaults.update(overrides)
    return defaults


def create_risk_assessment_payload(auditable_entity_id, expected_auditable_entity_version,
                                   **overrides) -> dict:
    defaults = {
        "auditable_entity_id": auditable_entity_id,
        "fiscal_year": 2026,
        "likelihood": 3,
        "impact": 3,
        "expected_auditable_entity_version": expected_auditable_entity_version,
    }
    defaults.update(overrides)
    return defaults


def create_rating_criteria_config_payload(**overrides) -> dict:
    defaults = {"name": "standard-bands"}
    defaults.update(overrides)
    return defaults


def create_audit_plan_payload(**overrides) -> dict:
    defaults = {"fiscal_year": 2026, "title": "FY2026 Audit Plan"}
    defaults.update(overrides)
    return defaults


def create_engagement_payload(audit_plan_id, auditable_entity_id, expected_audit_plan_version,
                              **overrides) -> dict:
    defaults = {
        "audit_plan_id": audit_plan_id,
        "auditable_entity_id": auditable_entity_id,
        "title": "Engagement",
        "scope_summary": "Full-scope audit",
        "budget_hours": 100,
        "start_date": DEFAULT_WINDOW_START,
        "end_date": DEFAULT_WINDOW_END,
        "expected_audit_plan_version": expected_audit_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_engagement_assignment_payload(engagement_id, auditor_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "auditor_id": auditor_id,
        "role_in_engagement": "STAFF",
        "start_date": DEFAULT_WINDOW_START,
        "end_date": DEFAULT_ASSIGNMENT_END,
        "allocated_hours": 40,
    }
    defaults.update(overrides)
    return defaults


def create_workpaper_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "reference": "A-1",
        "title": "Workpaper",
        "hours_worked": 5,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "title": "Finding",
        "likelihood": 3,
        "impact": 4,
    }
    defaults.update(overrides)
    return defaults


def create_management_response_payload(finding_id, **overrides) -> dict:
    defaults = {
        "finding_id": finding_id,
        "response_text": "We agree and will remediate.",
        "proposed_due_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_action_plan_payload(finding_id, **overrides) -> dict:
    defaults = {
        "finding_id": finding_id,
        "description": "Remediate the control gap",
        "owner_name": "Ops Owner",
        "due_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_extension_request_payload(action_plan_id, **overrides) -> dict:
    defaults = {
        "action_plan_id": action_plan_id,
        "requested_due_date": "2026-07-01T00:00:00Z",
        "reason": "Vendor dependency",
    }
    defaults.update(overrides)
    return defaults


def create_audit_report_payload(engagement_id, **overrides) -> dict:
    defaults = {"engagement_id": engagement_id, "title": "Draft Report"}
    defaults.update(overrides)
    return defaults


def create_qa_review_payload(engagement_id, **overrides) -> dict:
    defaults = {"engagement_id": engagement_id, "scope": "INTERNAL"}
    defaults.update(overrides)
    return defaults


def create_qa_complete_payload(**overrides) -> dict:
    defaults = {
        "doc_quality_score": 4,
        "fieldwork_quality_score": 4,
        "reporting_quality_score": 4,
        "independence_score": 4,
    }
    defaults.update(overrides)
    return defaults


def create_committee_pack_payload(audit_plan_id, **overrides) -> dict:
    defaults = {
        "audit_plan_id": audit_plan_id,
        "meeting_date": "2026-03-15T00:00:00Z",
        "title": "Q1 Committee Pack",
    }
    defaults.update(overrides)
    return defaults
