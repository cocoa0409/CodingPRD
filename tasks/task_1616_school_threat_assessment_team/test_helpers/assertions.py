"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. CaseDocument and AuditEvent are append-only
records and must NOT expose updated_at/version (PRD common-resource-properties
section); every other resource carries the four system-managed fields.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CASE_STATUSES = (
    "INTAKE", "TRIAGED", "UNDER_ASSESSMENT", "PLAN_ACTIVE",
    "REMOVED", "CLOSED_NO_THREAT", "CLOSED_MANAGED", "PURGED",
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only records must not expose updated_at"
    assert "version" not in data, "append-only records must not expose version"


def _assert_nullable_str(data: dict, field: str):
    assert field in data, f"{field} must be present (possibly null)"
    assert data[field] is None or isinstance(data[field], str)


def assert_school(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert isinstance(data["enrollment_count"], int) and data["enrollment_count"] >= 0
    assert isinstance(data["retention_days"], int) and data["retention_days"] >= 30


def assert_threat_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_id"], str)
    assert isinstance(data["subject_alias"], str) and data["subject_alias"]
    assert data["reporter_channel"] in ("TIP_LINE", "STAFF_REFERRAL")
    assert isinstance(data["summary"], str)
    assert data["status"] in CASE_STATUSES
    assert data["triage_priority"] in (None, "ROUTINE", "URGENT", "EMERGENT")
    assert data["screening_score"] is None or (
        isinstance(data["screening_score"], int) and 0 <= data["screening_score"] <= 6)
    assert data["screening_outcome"] in (None, "SUBSTANTIVE", "NON_SUBSTANTIVE")
    assert data["risk_level"] in (None, "LOW", "MODERATE", "HIGH", "IMMINENT")
    assert data["monitoring_cadence_days"] is None or (
        isinstance(data["monitoring_cadence_days"], int)
        and data["monitoring_cadence_days"] > 0)
    assert isinstance(data["consecutive_missed_count"], int)
    assert data["consecutive_missed_count"] >= 0
    assert isinstance(data["escalation_flag"], bool)
    assert data["removal_type"] in (None, "EMERGENCY_REMOVAL", "DISCIPLINARY_EXCLUSION")
    for field in ("closed_at", "retention_purge_after", "purged_at"):
        assert field in data, f"{field} must be present (possibly null)"


def assert_interview(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["interviewee_type"] in ("SUBJECT", "WITNESS", "PARENT", "REPORTER")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["findings_score"] is None or (
        isinstance(data["findings_score"], int) and 0 <= data["findings_score"] <= 10)
    _assert_nullable_str(data, "summary")
    assert "completed_at" in data


def assert_risk_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["variant"] in ("STANDARD", "EXPEDITED")
    assert isinstance(data["factors"], list)
    for factor in data["factors"]:
        assert factor["factor_code"] in (
            "WEAPON_ACCESS", "PLAN_SPECIFICITY", "GRIEVANCE_HISTORY",
            "PEER_REPORTS", "BEHAVIORAL_ESCALATION", "SUPERVISION_GAP")
        assert isinstance(factor["severity"], int) and 0 <= factor["severity"] <= 3
    assert isinstance(data["raw_score"], int) and 0 <= data["raw_score"] <= 100
    assert data["risk_level"] in ("LOW", "MODERATE", "HIGH", "IMMINENT")
    assert data["status"] in ("DRAFT", "SUBMITTED", "FINALIZED", "SUPERSEDED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    for field in ("finalized_at", "superseded_at"):
        assert field in data, f"{field} must be present (possibly null)"


def assert_management_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["cadence_mode"] in ("FROM_COMPLETION", "FIXED_ANCHOR")
    assert isinstance(data["cadence_days"], int) and data["cadence_days"] > 0
    assert isinstance(data["conditions"], list) and len(data["conditions"]) > 0
    assert all(isinstance(c, str) and c for c in data["conditions"])
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "CLOSED")
    assert isinstance(data["needs_review"], bool)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert "activated_at" in data


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["referral_type"] in ("LAW_ENFORCEMENT", "MENTAL_HEALTH")
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert data["urgency"] in ("ROUTINE", "URGENT")
    assert data["status"] in ("SENT", "ACKNOWLEDGED", "DECLINED", "WITHDRAWN")
    assert isinstance(data["auto_created"], bool)
    assert is_iso8601_timestamp(data["sla_due_at"])
    assert isinstance(data["sla_breached"], bool)
    _assert_nullable_str(data, "decline_reason")


def assert_monitoring_check_in(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["due_date"], str) and len(data["due_date"]) == 10
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED")
    assert isinstance(data["auto_created"], bool)
    assert data["outcome"] in (None, "ON_TRACK", "CONCERNS_ESCALATED")
    _assert_nullable_str(data, "notes")
    assert "completed_at" in data


def assert_reentry_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["conditions"], list) and len(data["conditions"]) > 0
    for condition in data["conditions"]:
        assert isinstance(condition["description"], str) and condition["description"]
        assert condition["status"] in ("UNMET", "MET")
        assert "evidence_note" in condition
    assert data["status"] in ("PROPOSED", "APPROVED", "DENIED", "REENTERED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    _assert_nullable_str(data, "denial_reason")


def assert_case_document(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["doc_type"] in (
        "INTAKE_NOTE", "INTERVIEW_SUMMARY", "PLAN_DOCUMENT", "LEGAL_HOLD", "OTHER")
    assert data["body"] is None or isinstance(data["body"], str)
    assert isinstance(data["sealed"], bool)
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]
    assert isinstance(data["purged"], bool)


def assert_audit_event(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["detail"], str)
