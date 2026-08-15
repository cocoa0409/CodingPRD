"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_SPONSOR_STATUSES = ["ACTIVE", "SUSPENDED"]
_APPLICATION_STATUSES = [
    "SUBMITTED", "STA_PENDING", "PENDING_REQUIREMENTS", "READY",
    "ISSUED", "DENIED", "WITHDRAWN", "EXPIRED",
]
_BADGE_CLASSES = ["SIDA", "STERILE", "AOA"]
_BADGE_STATUSES = [
    "ACTIVE", "SUSPENDED", "LOST", "STOLEN", "EXPIRED", "REVOKED", "VOIDED", "RETURNED",
]
_ESCORT_STATUSES = ["GRANTED", "REVOKED"]
_ZONE_CODES = ["PUBLIC_TERMINAL", "STERILE_CONCOURSE", "AOA_MOVEMENT", "SECURE_ID_AREA"]
_DECISIONS = ["ALLOWED", "DENIED"]
_DENIAL_REASONS = [
    "DENIED_NO_BADGE", "DENIED_BADGE_INACTIVE", "DENIED_ZONE_CLASS",
    "DENIED_ESCORT_NOT_PERMITTED", "DENIED_ESCORT_CAPACITY",
]
_VIOLATION_TYPES = [
    "FAILURE_TO_DISPLAY", "ESCORT_VIOLATION", "UNAUTHORIZED_AREA", "SECURITY_BREACH",
]
_VIOLATION_STATUSES = ["RECORDED", "SUSTAINED", "DISMISSED"]
_AUDIT_STATUSES = ["OPEN", "CLOSED"]
_COURSE_CODES = ["SIDA_INITIAL", "AOA_SAFETY", "AOA_DRIVING", "STERILE_INITIAL"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_sponsor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sponsor_code"], str) and data["sponsor_code"]
    assert data["status"] in _SPONSOR_STATUSES
    assert isinstance(data["active_badge_quota"], int) and data["active_badge_quota"] >= 1
    assert isinstance(data["active_badge_count"], int) and data["active_badge_count"] >= 0
    assert "suspended_at" in data


def assert_applicant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["government_id_number"], str)


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("applicant_id", "")), "applicant_id must be a UUID"
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert data["badge_class"] in _BADGE_CLASSES
    assert data["status"] in _APPLICATION_STATUSES
    assert data.get("chrc_outcome") in (None, "PASS", "FAIL")
    assert data.get("sta_outcome") in (None, "CLEARED", "DENIED")
    assert data.get("denial_reason") in (None, "CHRC_FAILED", "STA_DENIED",
                                         "SPONSOR_SUSPENDED")
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert is_iso8601_timestamp(data.get("application_expires_at", ""))
    assert "issued_badge_id" in data


def assert_training_completion(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    # Immutable record: version/updated_at are absent (PRD common-resource rules).
    assert "version" not in data, "TrainingCompletion must not carry version"
    assert "updated_at" not in data, "TrainingCompletion must not carry updated_at"
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert data["course_code"] in _COURSE_CODES
    assert is_iso8601_timestamp(data.get("completed_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_badge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert is_valid_uuid(data.get("sponsor_id", ""))
    assert isinstance(data["badge_number"], str) and data["badge_number"]
    assert data["badge_class"] in _BADGE_CLASSES
    assert data["status"] in _BADGE_STATUSES
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    for field in ("deactivated_at", "return_deadline", "returned_at",
                  "suspended_by", "suspended_until", "suspension_reason",
                  "superseded_by_badge_id"):
        assert field in data, f"badge must carry {field}"


def assert_escort_privilege(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("badge_id", ""))
    assert isinstance(data["max_escortees"], int)
    assert 1 <= data["max_escortees"] <= 10
    assert data["status"] in _ESCORT_STATUSES
    assert isinstance(data["granted_by"], str) and data["granted_by"]
    assert data.get("revoked_reason") in (
        None, "MANUAL", "BADGE_SUSPENDED", "BADGE_DEACTIVATED", "SUPERSEDED")


def assert_access_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    # Append-only log row: version/updated_at are absent (PRD common-resource rules).
    assert "version" not in data, "AccessEvent must not carry version"
    assert "updated_at" not in data, "AccessEvent must not carry updated_at"
    assert "badge_id" in data
    assert data["zone_code"] in _ZONE_CODES
    assert isinstance(data["escortee_count"], int) and data["escortee_count"] >= 0
    assert data["decision"] in _DECISIONS
    assert data.get("denial_reason") in [None] + _DENIAL_REASONS
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


def assert_violation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("badge_id", ""))
    assert data["violation_type"] in _VIOLATION_TYPES
    assert isinstance(data["points"], int) and data["points"] in (3, 6, 12)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert data["status"] in _VIOLATION_STATUSES
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]
    assert "sustained_by" in data
    assert "dismissed_by" in data


def assert_audit_cycle(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in _AUDIT_STATUSES
    for field in ("scoped_count", "accounted_count", "recovery_rate_pct",
                  "per_class_rates", "outcome", "due_scoped_count",
                  "due_accounted_count", "recovery_rate_provisional_pct"):
        assert field in data, f"audit cycle must carry {field}"
