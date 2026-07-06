"""Entity assertions for the Survey & Market-Research Panel API.

Each assert_{entity}() checks id/timestamp formats and the field/enum
contract for that resource. Immutable audit records (Consent, AttentionCheck)
are checked WITHOUT updated_at / version (they carry only id + created_at).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields for entities with common_fields:true."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def _assert_audit_common(data: dict):
    """Common fields for immutable audit records (common_fields:false)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_study(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["irb_protocol_number"], str)
    assert isinstance(data["estimated_minutes"], int) and data["estimated_minutes"] >= 1
    assert isinstance(data["base_incentive_points"], int) and data["base_incentive_points"] >= 0
    assert isinstance(data["screener_min_age"], int) and data["screener_min_age"] >= 0
    assert isinstance(data["required_consent_version"], int) and data["required_consent_version"] >= 1
    assert isinstance(data["target_total_n"], int)
    assert isinstance(data["committed_total_n"], int)
    assert data["status"] in ["DRAFT", "FIELDING", "PAUSED", "CLOSED", "DELIVERED"], \
        f"unexpected study status {data['status']!r}"


def assert_quota_cell(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", "")), "study_id must be a valid UUID"
    assert isinstance(data["segment_key"], str) and len(data["segment_key"]) > 0
    assert isinstance(data["target_n"], int) and data["target_n"] >= 1
    assert isinstance(data["reserved_n"], int) and data["reserved_n"] >= 0
    assert isinstance(data["committed_n"], int) and data["committed_n"] >= 0
    assert isinstance(data["available_n"], int) and data["available_n"] >= 0
    assert data["fill_status"] in ["OPEN", "FILLED"], f"unexpected fill_status {data['fill_status']!r}"


def assert_panelist(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["age"], int) and data["age"] >= 0
    assert isinstance(data["segment_key"], str)
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["lifetime_invited_n"], int) and data["lifetime_invited_n"] >= 0
    assert isinstance(data["lifetime_completed_n"], int) and data["lifetime_completed_n"] >= 0
    assert isinstance(data["health_score"], int) and 0 <= data["health_score"] <= 100
    assert data["status"] in ["ACTIVE", "AT_RISK", "CHURNED", "SUSPENDED"], \
        f"unexpected panelist status {data['status']!r}"


def assert_consent(data: dict):
    _assert_audit_common(data)
    # Immutable audit record: must NOT carry updated_at / version.
    assert "version" not in data, "Consent is immutable and must not carry a version field"
    assert "updated_at" not in data, "Consent is immutable and must not carry an updated_at field"
    assert is_valid_uuid(data.get("panelist_id", "")), "panelist_id must be a valid UUID"
    assert is_valid_uuid(data.get("study_id", "")), "study_id must be a valid UUID"
    assert isinstance(data["consent_version"], int) and data["consent_version"] >= 1
    assert data["decision"] in ["ACCEPTED", "DECLINED", "WITHDRAWN"]
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"


def assert_participation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", "")), "study_id must be a valid UUID"
    assert is_valid_uuid(data.get("panelist_id", "")), "panelist_id must be a valid UUID"
    assert is_valid_uuid(data.get("quota_cell_id", "")), "quota_cell_id must be a valid UUID"
    assert data["screening_status"] in [
        "SCREENING", "SCREENED_IN", "QUALIFIED", "SCREENED_OUT", "VOIDED"]
    assert data["completion_status"] in [
        "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "ABANDONED"]
    assert data["quality_status"] in ["PENDING", "PASS", "FLAGGED", "FAIL"]
    assert isinstance(data["rescreen_count"], int) and data["rescreen_count"] >= 0


def assert_attention_check(data: dict):
    _assert_audit_common(data)
    assert "version" not in data, "AttentionCheck is immutable and must not carry a version field"
    assert "updated_at" not in data, "AttentionCheck is immutable and must not carry an updated_at field"
    assert is_valid_uuid(data.get("participation_id", "")), "participation_id must be a valid UUID"
    assert data["check_kind"] in ["TRAP_QUESTION", "INSTRUCTED_RESPONSE", "TIMING"]
    assert isinstance(data["passed"], bool)
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"


def assert_incentive_accrual(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("panelist_id", "")), "panelist_id must be a valid UUID"
    assert is_valid_uuid(data.get("participation_id", "")), "participation_id must be a valid UUID"
    assert data["accrual_kind"] in ["PROVISIONAL", "FINALIZED", "REVERSAL"]
    assert isinstance(data["points"], int)
    assert data["status"] in ["HELD", "CREDITED", "VOID"]


def assert_payout_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("panelist_id", "")), "panelist_id must be a valid UUID"
    assert data["payout_method"] in ["CASH", "GIFT_CARD"]
    assert isinstance(data["points_requested"], int) and data["points_requested"] >= 1
    assert isinstance(data["cash_cents"], int)
    assert data["status"] in ["REQUESTED", "APPROVED", "PAID", "REJECTED", "CANCELLED"]


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0
    assert data["status"] in ["AVAILABLE", "OFFLINE"]


def assert_focus_group(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", "")), "study_id must be a valid UUID"
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert isinstance(data["seats"], int) and data["seats"] >= 1
    assert isinstance(data["booked_n"], int) and data["booked_n"] >= 0
    assert data["status"] in ["SCHEDULED", "CANCELLED", "COMPLETED"]


def assert_focus_group_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("focus_group_id", "")), "focus_group_id must be a valid UUID"
    assert is_valid_uuid(data.get("panelist_id", "")), "panelist_id must be a valid UUID"
    assert data["status"] in ["CONFIRMED", "CANCELLED", "NO_SHOW", "ATTENDED"]


def assert_data_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("study_id", "")), "study_id must be a valid UUID"
    assert isinstance(data["included_completes_n"], int) and data["included_completes_n"] >= 0
    assert data["report_format"] in ["CSV", "SPSS", "DASHBOARD"]
    assert data["status"] in ["BUILDING", "READY", "DELIVERED", "REVOKED"]
