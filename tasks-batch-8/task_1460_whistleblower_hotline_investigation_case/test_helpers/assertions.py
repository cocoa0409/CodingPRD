"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CASE_STATUSES = {
    "RECEIVED", "TRIAGED", "ASSIGNED", "UNDER_INVESTIGATION", "DETERMINATION_REVIEW",
    "REMEDIATION", "CLOSURE_READY", "MONITORING", "REOPENED", "CLOSED", "REJECTED", "WITHDRAWN",
}
ASSIGNMENT_STATUSES = {"PROPOSED", "CONFLICT_PENDING", "CLEARED", "ACTIVE", "RELEASED", "SUPERSEDED"}
INTERVIEW_STATUSES = {"SCHEDULED", "CONDUCTED", "NO_SHOW", "CANCELLED"}
EVIDENCE_STATUSES = {"PRESERVED", "SEALED", "EXCLUDED"}
DETERMINATION_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "SUPERSEDED"}
REMEDIATION_STATUSES = {"PROPOSED", "IN_PROGRESS", "VERIFIED", "REJECTED", "OVERDUE"}
FLAG_STATUSES = {"OPEN", "DISMISSED", "ESCALATED"}
PLAN_STATUSES = {"ACTIVE", "COMPLETED", "SUSPENDED"}
NOTICE_STATUSES = {"SENT", "ACKNOWLEDGED"}
HOLD_STATUSES = {"ACTIVE", "RELEASED"}
REPORT_STATUSES = {"DRAFT", "FINALIZED", "PRESENTED"}


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_staff_member(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["employment_status"] in {"ACTIVE", "ON_LEAVE", "TERMINATED"}
    assert isinstance(data["max_active_cases"], int) and data["max_active_cases"] >= 1
    for cap in data["capabilities"]:
        assert cap in {"INTAKE", "INVESTIGATION", "OFFICER"}


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in CASE_STATUSES
    assert data["channel"] in {"WEB_PORTAL", "PHONE", "EMAIL", "IN_PERSON", "MAIL"}
    assert data["category"] in {"FRAUD", "HARASSMENT", "SAFETY", "FINANCIAL_REPORTING",
                                "DATA_PRIVACY", "CONFLICT_OF_INTEREST", "OTHER"}
    assert data["posture"] in {"NORMAL", "FROZEN"}
    # Confidentiality firewall: staff-facing payloads NEVER carry these keys.
    assert "reporter_contact" not in data, "reporter_contact must be redacted from staff view"
    assert "reporter_access_key" not in data, "reporter_access_key must be redacted from staff view"


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ASSIGNMENT_STATUSES
    assert data["selection_mode"] in {"AUTO", "OVERRIDE"}


def assert_interview(data: dict):
    _assert_common(data)
    assert data["status"] in INTERVIEW_STATUSES
    assert data["interviewee_role"] in {"SUBJECT", "WITNESS", "REPORTER"}


def assert_evidence(data: dict):
    _assert_common(data)
    assert data["status"] in EVIDENCE_STATUSES


def assert_determination(data: dict):
    _assert_common(data)
    assert data["status"] in DETERMINATION_STATUSES
    assert data["finding"] in {"SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE"}


def assert_remediation_action(data: dict):
    _assert_common(data)
    assert data["status"] in REMEDIATION_STATUSES


def assert_flag(data: dict):
    _assert_common(data)
    assert data["status"] in FLAG_STATUSES
    assert data["reported_via"] in {"REPORTER_CHECKIN", "HR_SIGNAL", "MANUAL"}


def assert_monitoring_plan(data: dict):
    _assert_common(data)
    assert data["status"] in PLAN_STATUSES


def assert_closure_notice(data: dict):
    _assert_common(data, with_version=False)
    assert data["status"] in NOTICE_STATUSES
    # Append-only entity: version and updated_at must be absent.
    assert "version" not in data, "CaseClosureNotice carries no version field"
    assert "updated_at" not in data, "CaseClosureNotice carries no updated_at field"


def assert_legal_hold(data: dict):
    _assert_common(data)
    assert data["status"] in HOLD_STATUSES


def assert_audit_report(data: dict):
    _assert_common(data)
    assert data["status"] in REPORT_STATUSES


def assert_case_status_event(data: dict):
    _assert_common(data, with_version=False)
    assert "version" not in data, "CaseStatusEvent carries no version field"
    assert "updated_at" not in data, "CaseStatusEvent carries no updated_at field"
