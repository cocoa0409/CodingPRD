"""Payload factories — one per entity, input fields only."""
import hashlib
import itertools
import uuid

_ctr = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_ctr)}-{uuid.uuid4().hex[:8]}"


DEFAULT_CHECKSUM = hashlib.sha256(b"evidence-content").hexdigest()


def create_staff_member_payload(**overrides) -> dict:
    defaults = {
        "display_name": f"Staff {_uniq('user')}",
        "email": f"{_uniq('staff')}@corp.example",
        "department": "Ethics",
        "capabilities": ["OFFICER"],
        "max_active_cases": 5,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "channel": "WEB_PORTAL",
        "category": "FRAUD",
        "description": "Allegation of expense fraud discovered during Q2 close.",
        "region": "NORTH",
        "subject_employee_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_triage_payload(**overrides) -> dict:
    defaults = {
        "confirmed_category": "FRAUD",
        "subject_seniority": "STAFF",
        "financial_exposure_band": "NONE",
        "reporter_vulnerability": "NONE",
        "triage_decision": "PROCEED",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(expected_case_version: int, **overrides) -> dict:
    defaults = {"expected_case_version": expected_case_version}
    defaults.update(overrides)
    return defaults


def create_screen_payload(**overrides) -> dict:
    defaults = {"outcome": "CLEAR"}
    defaults.update(overrides)
    return defaults


def create_waiver_payload(**overrides) -> dict:
    defaults = {"waiver_justification": "Conflict is remote, documented, and monitored."}
    defaults.update(overrides)
    return defaults


def create_interview_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "interviewee_role": "WITNESS",
        "interviewee_identifier": _uniq("wit"),
        "scheduled_start": "2026-08-03T10:00:00Z",
        "scheduled_end": "2026-08-03T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_conclude_payload(**overrides) -> dict:
    defaults = {
        "outcome": "CONDUCTED",
        "summary": "Interview conducted on site with the witness present throughout.",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "evidence_type": "DOCUMENT",
        "description": "Expense report PDF export",
        "checksum": DEFAULT_CHECKSUM,
        "captured_at": "2026-08-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_exclusion_payload(**overrides) -> dict:
    defaults = {"exclusion_reason": "Obtained outside the records retention scope."}
    defaults.update(overrides)
    return defaults


def create_determination_payload(expected_case_version: int, **overrides) -> dict:
    defaults = {
        "finding": "UNSUBSTANTIATED",
        "rationale": "Evidence reviewed shows the allegation is not supported on the balance of proof.",
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    defaults = {"decision": "APPROVE", "review_notes": "Reviewed and accepted."}
    defaults.update(overrides)
    return defaults


def create_remediation_action_payload(**overrides) -> dict:
    defaults = {
        "action_type": "TRAINING",
        "owner_department": "Finance",
        "description": "Refresh anti-fraud training",
        "due_date": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_flag_payload(**overrides) -> dict:
    defaults = {
        "reported_via": "HR_SIGNAL",
        "description": "Manager excluded reporter from meetings",
    }
    defaults.update(overrides)
    return defaults


def create_legal_hold_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "start_at": "2026-08-10T00:00:00Z",
        "end_at": "2026-08-20T00:00:00Z",
        "reason": "Pending litigation review",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
