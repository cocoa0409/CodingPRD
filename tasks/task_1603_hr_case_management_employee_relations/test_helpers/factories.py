"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _next(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:05d}"


def create_employee_payload(**overrides) -> dict:
    n = _next("E")
    defaults = {
        "employee_number": n,
        "full_name": f"Employee {n}",
        "email": f"{n.lower()}@example.com",
        "location_code": "SF",
        "department": "Ops",
        "hire_date": "2020-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_investigator_payload(employee_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "certification_level": "LEVEL_3",
        "max_active_cases": 10,
    }
    defaults.update(overrides)
    return defaults


def create_intake_channel_payload(**overrides) -> dict:
    defaults = {
        "channel_code": "HOTLINE",
        "display_name": "Hotline",
        "default_category": "HARASSMENT",
        "default_severity": "MEDIUM",
        "sla_business_days": 10,
    }
    defaults.update(overrides)
    return defaults


def create_holiday_payload(**overrides) -> dict:
    defaults = {
        "holiday_date": "2026-12-25T00:00:00Z",
        "label": "Christmas",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(intake_channel_id: str, subject_employee_id: str, **overrides) -> dict:
    defaults = {
        "intake_channel_id": intake_channel_id,
        "subject_employee_id": subject_employee_id,
        "category": "HARASSMENT",
        "severity": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(interviewee_employee_id: str, **overrides) -> dict:
    defaults = {
        "interviewee_employee_id": interviewee_employee_id,
        "scheduled_start": "2026-07-27T09:00:00Z",
        "scheduled_end": "2026-07-27T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(submitted_by_employee_id: str, **overrides) -> dict:
    defaults = {
        "submitted_by_employee_id": submitted_by_employee_id,
        "evidence_type": "DOCUMENT",
        "description": "Evidence item submitted for review.",
    }
    defaults.update(overrides)
    return defaults


def create_credibility_assessment_payload(subject_employee_id: str, **overrides) -> dict:
    defaults = {
        "subject_employee_id": subject_employee_id,
        "corroboration_count": 3,
        "contradiction_count": 0,
        "account_age_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "rationale_text": (
            "Rationale: the evidence and interviews together establish the "
            "conclusion on the balance of probabilities and are documented here."
        ),
    }
    defaults.update(overrides)
    return defaults


def create_action_payload(**overrides) -> dict:
    defaults = {
        "action_type": "COACHING",
        "severity_points": 20,
        "justification": "This action is proportionate to the finding reached.",
    }
    defaults.update(overrides)
    return defaults


def create_closure_notice_payload(recipient_employee_id: str, **overrides) -> dict:
    defaults = {
        "recipient_employee_id": recipient_employee_id,
        "recipient_role": "SUBJECT",
        "confidentiality_tier": "TIER_2_LIMITED",
        "body_text": "The investigation concerning you has concluded.",
    }
    defaults.update(overrides)
    return defaults


def create_trend_snapshot_payload(scope_type: str, scope_key: str, window_kind: str, **overrides) -> dict:
    defaults = {
        "scope_type": scope_type,
        "scope_key": scope_key,
        "window_kind": window_kind,
    }
    defaults.update(overrides)
    return defaults
