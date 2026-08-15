"""Payload factories — one per creatable resource, input fields only."""
from .constants import HIRED_AT, T0, TEST_DEFAULTS, VERSION_EFFECTIVE_FROM


def create_regulator_payload(**overrides) -> dict:
    defaults = {
        "code": "REG-1",
        "name": "Test Regulator",
        "deadline_mode": "CALENDAR",
        "recordkeeping_years": TEST_DEFAULTS["RECORDKEEPING_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_role_payload(**overrides) -> dict:
    defaults = {"code": "R-1", "name": "Test Role"}
    defaults.update(overrides)
    return defaults


def create_curriculum_payload(regulator_id: str, **overrides) -> dict:
    defaults = {
        "regulator_id": regulator_id,
        "code": "CUR-1",
        "title": "Test Course",
        "passing_score_pct": TEST_DEFAULTS["PASSING_SCORE_PCT"],
        "validity_months": TEST_DEFAULTS["VALIDITY_MONTHS"],
        "evidence_requirement": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_version_payload(**overrides) -> dict:
    defaults = {
        "version_no": 1,
        "effective_from": VERSION_EFFECTIVE_FROM,
        "content_uri": "uri://content-v1",
    }
    defaults.update(overrides)
    return defaults


def create_requirement_payload(curriculum_id: str, **overrides) -> dict:
    defaults = {
        "curriculum_id": curriculum_id,
        "recurrence": "INITIAL_ONLY",
        "due_in_days": TEST_DEFAULTS["DUE_IN_DAYS"],
        "criticality": "SOFT",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(current_role_id: str, **overrides) -> dict:
    defaults = {
        "employee_no": "E-1",
        "full_name": "Test Employee",
        "hired_at": HIRED_AT,
        "current_role_id": current_role_id,
    }
    defaults.update(overrides)
    return defaults


def create_leave_payload(**overrides) -> dict:
    defaults = {
        "start_date": "2026-08-03T00:00:00Z",
        "end_date": "2026-08-07T23:59:59Z",
        "reason": "Medical",
    }
    defaults.update(overrides)
    return defaults


def create_role_change_payload(to_role_id: str, **overrides) -> dict:
    defaults = {"to_role_id": to_role_id, "effective_at": T0}
    defaults.update(overrides)
    return defaults


def create_manual_assignment_payload(role_requirement_id: str, **overrides) -> dict:
    defaults = {"role_requirement_id": role_requirement_id}
    defaults.update(overrides)
    return defaults


def submit_completion_payload(**overrides) -> dict:
    defaults = {"score_pct": 90, "evidence_type": "NONE"}
    defaults.update(overrides)
    return defaults


def grant_extension_payload(expected_assignment_version, **overrides) -> dict:
    defaults = {
        "extend_by_days": 5,
        "reason": "Business travel",
        "expected_assignment_version": expected_assignment_version,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(regulator_id: str, **overrides) -> dict:
    defaults = {
        "year": TEST_DEFAULTS["CAMPAIGN_YEAR"],
        "regulator_id": regulator_id,
        "window_open_at": TEST_DEFAULTS["CAMPAIGN_WINDOW_OPEN"],
        "window_close_at": TEST_DEFAULTS["CAMPAIGN_WINDOW_CLOSE"],
        "statement_version": "STMT-2026-08",
    }
    defaults.update(overrides)
    return defaults


def request_exception_payload(**overrides) -> dict:
    defaults = {
        "reason_code": "MEDICAL_LEAVE",
        "detail": "Scheduled surgery in August",
    }
    defaults.update(overrides)
    return defaults


def create_audit_report_payload(regulator_id: str, **overrides) -> dict:
    defaults = {
        "population_spec": {"regulator_id": regulator_id},
        "metric_variant": "STRICT",
    }
    defaults.update(overrides)
    return defaults
