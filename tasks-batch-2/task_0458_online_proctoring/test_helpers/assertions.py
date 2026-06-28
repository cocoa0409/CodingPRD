"""Entity assertions and domain invariant checkers for the Online Proctoring API.

Each assert_{entity}() validates the response structure against the PRD contract.
Versioned entities carry the full audit triple (id + created_at + updated_at +
version); the two append-only records (IdentityVerification, IncidentFlag) carry
only id + created_at and MUST NOT expose updated_at or version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_triple(data: dict):
    """Versioned resources carry id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_append_only(data: dict):
    """Append-only records carry only id + created_at; no version, no updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "version" not in data, "append-only record must not expose version"
    assert "updated_at" not in data, "append-only record must not expose updated_at"


def assert_institution(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["report_threshold_score"], (int, float))
    assert 0 <= data["report_threshold_score"] <= 100


def assert_proctor(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["institution_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["concurrent_capacity"], int) and data["concurrent_capacity"] >= 1
    assert isinstance(data["active_session_count"], int) and data["active_session_count"] >= 0
    assert isinstance(data["load_factor"], (int, float)) and data["load_factor"] >= 0
    assert data["status"] in ("AVAILABLE", "SUSPENDED")


def assert_candidate(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["institution_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_exam(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["institution_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["base_duration_minutes"], int) and data["base_duration_minutes"] >= 1
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["monitoring_mode"] in ("LIVE", "RECORD_REVIEW")
    assert isinstance(data["lockdown_required"], bool)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_accommodation(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["exam_id"], str)
    assert isinstance(data["extra_time_pct"], int) and 0 <= data["extra_time_pct"] <= 100
    assert data["status"] in ("APPROVED", "REVOKED")


def assert_appointment(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["exam_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["proctor_id"], str)
    assert isinstance(data["effective_duration_minutes"], int)
    assert is_iso8601_timestamp(data["effective_end_utc"])
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "NO_SHOW", "CANCELLED", "CONSUMED")


def assert_identity_verification(data: dict):
    _assert_append_only(data)
    assert isinstance(data["appointment_id"], str)
    assert data["result"] in ("PASS", "FAIL")


def assert_proctoring_session(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["proctor_id"], str)
    assert data["monitoring_mode"] in ("LIVE", "RECORD_REVIEW")
    assert isinstance(data["integrity_score"], (int, float))
    assert 0 <= data["integrity_score"] <= 100
    assert data["status"] in ("ACTIVE", "PAUSED", "COMPLETED", "VOIDED", "REVIEW_HELD")
    if data.get("void_reason") is not None:
        assert data["void_reason"] in ("AUTO_THRESHOLD", "ESCALATION_UPHELD")


def assert_incident_flag(data: dict):
    _assert_append_only(data)
    assert isinstance(data["session_id"], str)
    assert data["kind"] in (
        "LOCKDOWN_BREACH", "GAZE_OFF_SCREEN", "SECOND_FACE",
        "PROHIBITED_MATERIAL", "NETWORK_DROP",
    )
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in ("OPEN", "ESCALATED", "RESOLVED")


def assert_escalation(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["incident_flag_id"], str)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "UPHELD", "DISMISSED")
    if data.get("verdict") is not None:
        assert data["verdict"] in ("UPHELD", "DISMISSED")


def assert_integrity_report(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["institution_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["exam_id"], str)
    assert isinstance(data["session_ids"], list)
    assert data["status"] in ("DRAFT", "DELIVERED")
    if data.get("disposition") is not None:
        assert data["disposition"] in ("CLEARED", "ESCALATED_TO_INSTITUTION")


def assert_retake_authorization(data: dict):
    _assert_audit_triple(data)
    assert isinstance(data["voided_session_id"], str)
    assert data["status"] in ("AUTHORIZED", "REBOOKED", "EXPIRED")
