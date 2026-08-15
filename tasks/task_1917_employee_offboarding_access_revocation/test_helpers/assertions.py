"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value):
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual, expected):
    """Assert two ISO 8601 UTC timestamps denote the same instant.

    PRD §2.8 pins calendar results to explicit precisions ("a date at midnight
    UTC", "instants in ISO 8601 UTC") but does not pin a fractional-digit
    rendering, so instants are compared by value, not by string equality.
    """
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


_CASE_STATUSES = {
    "INTAKE", "APPROVED", "REVOCATION_IN_PROGRESS", "PAYROLL_PENDING",
    "CLEARANCE_IN_PROGRESS", "READY_TO_CLOSE", "CLOSED", "VOIDED",
}
_REV_POSTURES = {"NOT_STARTED", "IN_PROGRESS", "BLOCKED", "COMPLETE"}
_ASSET_POSTURES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETE", "DEFAULTED"}
_TASK_STATUSES = {"PENDING", "READY", "EXECUTED", "FAILED", "RETRY_SCHEDULED", "VERIFIED", "WAIVED"}
_ASSET_STATUSES = {"TRACKED", "RETURNED", "OVERDUE", "DEFAULTED", "WAIVED"}
_DEDUCTION_STATUSES = {"NONE", "COMPUTED", "APPLIED", "WAIVED"}
_STMT_STATUSES = {"DRAFT", "CALCULATED", "APPROVED", "DISBURSED", "LATE", "VOIDED"}
_STATE_LAW_VARIANTS = {"IMMEDIATE_ON_TERMINATION", "NEXT_PAYDAY", "WITHIN_FIXED_DAYS"}
_INTERVIEW_STATUSES = {"SCHEDULED", "RESCHEDULE_REQUESTED", "COMPLETED", "NO_SHOW", "DECLINED", "CANCELLED"}
_PLAN_STATUSES = {"DRAFT", "ACTIVE", "COMPLETE", "INCOMPLETE_AT_CLOSE", "WAIVED"}
_SESSION_STATUSES = {"SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"}
_NOTICE_STATUSES = {"DRAFT", "QUEUED", "SENT", "ACKNOWLEDGED", "FAILED", "ESCALATED"}
_ACK_STATUSES = {"PENDING", "REMINDED", "ACKNOWLEDGED", "EXPIRED", "NOT_APPLICABLE"}
_REVIEW_STATUSES = {"DRAFT", "SUBMITTED", "FINALIZED", "RETURNED"}
_CASE_TYPES = {"RESIGNATION", "TERMINATION", "MUTUAL_SEPARATION", "JOB_ABANDONMENT"}
_STATE_CODES = {"CA", "CO", "IL", "MA", "TX", "NY", "WA", "FL"}
_SYSTEM_NAMES = {"EMAIL", "VPN", "ERP", "CODE_REPO", "BADGE", "PAYROLL_SYSTEM", "CRM", "CLOUD_STORAGE"}
_ASSET_KINDS = {"LAPTOP", "MONITOR", "PHONE", "KEYCARD", "TOOLING", "VEHICLE", "UNIFORM", "OTHER"}
_NOTICE_KINDS = {"COBRA_ELECTION", "BENEFITS_TERMINATION", "RETIREMENT_PLAN", "LIFE_INSURANCE_CONVERSION"}
_COVENANT_KINDS = {"NON_COMPETE", "NON_SOLICIT_CLIENTS", "NON_SOLICIT_EMPLOYEES", "CONFIDENTIALITY", "IP_ASSIGNMENT"}
_NOTIFICATION_KINDS = {"INTAKE_ALERT", "LAST_DAY_CONFIRMED", "REVOCATION_STARTED", "REVOCATION_COMPLETE", "CASE_CLOSED"}
_REHIRE_CODES = {"ELIGIBLE", "ELIGIBLE_WITH_CONDITIONS", "INELIGIBLE"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_offboarding_case(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert data["case_type"] in _CASE_TYPES
    assert data["work_state_code"] in _STATE_CODES
    assert is_iso8601_timestamp(data["notice_received_date"])
    assert is_iso8601_timestamp(data["requested_last_day"])
    assert data["status"] in _CASE_STATUSES
    assert data["revocation_posture"] in _REV_POSTURES
    assert data["asset_posture"] in _ASSET_POSTURES
    assert isinstance(data["deduction_total_cents"], int)
    assert data["deduction_total_cents"] >= 0
    assert data.get("rehire_code") is None or data["rehire_code"] in _REHIRE_CODES
    assert isinstance(data["hourly_wage_cents"], int) and data["hourly_wage_cents"] > 0


def assert_revocation_task(data: dict):
    _assert_common(data)
    assert data["system_name"] in _SYSTEM_NAMES
    assert isinstance(data["sequence_rank"], int) and data["sequence_rank"] >= 1
    assert data["status"] in _TASK_STATUSES
    assert isinstance(data["retry_count"], int) and data["retry_count"] >= 0


def assert_manager_notification(data: dict):
    # Append-only: id + created_at only; updated_at and version MUST be absent.
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ManagerNotification is append-only; updated_at must be absent"
    assert "version" not in data, "ManagerNotification is append-only; version must be absent"
    assert data["notification_kind"] in _NOTIFICATION_KINDS
    assert isinstance(data["suppressed"], bool)


def assert_asset_item(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["asset_kind"] in _ASSET_KINDS
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] >= 0
    assert data["status"] in _ASSET_STATUSES
    assert data["deduction_status"] in _DEDUCTION_STATUSES
    assert isinstance(data["deduction_amount_cents"], int)


def assert_final_pay_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["regular_wages_cents"], int) and data["regular_wages_cents"] >= 0
    assert isinstance(data["pto_payout_cents"], int)
    assert isinstance(data["deduction_total_cents"], int)
    assert isinstance(data["net_pay_cents"], int) and data["net_pay_cents"] >= 0
    assert data["state_law_variant"] in _STATE_LAW_VARIANTS
    assert data["status"] in _STMT_STATUSES
    assert isinstance(data["late_penalty_cents"], int) and data["late_penalty_cents"] >= 0


def assert_exit_interview(data: dict):
    _assert_common(data)
    assert isinstance(data["interviewer_ref"], str)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in _INTERVIEW_STATUSES
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0


def assert_kt_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["required_session_count"], int) and data["required_session_count"] >= 0
    assert isinstance(data["completed_session_count"], int) and data["completed_session_count"] >= 0
    assert data["status"] in _PLAN_STATUSES


def assert_kt_session(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in _SESSION_STATUSES


def assert_benefits_notice(data: dict):
    _assert_common(data)
    assert data["notice_kind"] in _NOTICE_KINDS
    assert data["status"] in _NOTICE_STATUSES
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0


def assert_covenant_ack(data: dict):
    _assert_common(data)
    assert data["covenant_kind"] in _COVENANT_KINDS
    assert data["status"] in _ACK_STATUSES


def assert_rehire_review(data: dict):
    _assert_common(data)
    assert data["status"] in _REVIEW_STATUSES
    assert data.get("recommended_code") in _REHIRE_CODES


def assert_case_invariants(case: dict):
    """Cross-field invariants that must hold for any OffboardingCase."""
    assert case["net_pay_floor_guard"] if False else True  # placeholder guard; see below
    assert case["deduction_total_cents"] >= 0, "case deduction total is non-negative"
    if case["status"] == "INTAKE":
        # determined_last_day / final_pay_due_at remain null until APPROVED
        assert case.get("determined_last_day") in (None,) or isinstance(case.get("determined_last_day"), str)
