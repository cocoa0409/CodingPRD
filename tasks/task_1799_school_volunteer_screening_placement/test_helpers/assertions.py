"""Entity assertions and domain invariant checkers.

Mutable resources carry id + created_at + updated_at + version; configuration
and append-only resources (campus, training module, training record,
recognition award) carry only id + created_at — the PRD states both
`updated_at` and `version` are absent from them.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VOLUNTEER_STATUSES = [
    "APPLIED", "UNDER_SCREENING", "CLEARANCE_GRANTED", "ACTIVE",
    "RESCREEN_REQUIRED", "SUSPENDED", "DENIED", "REMOVED",
]
CHECK_STATUSES = ["PENDING", "CLEARED", "CLEARED_WITH_FLAGS", "DENIED", "EXPIRED"]
OPPORTUNITY_STATUSES = ["DRAFT", "OPEN", "COMPLETED", "CANCELLED"]
PLACEMENT_STATUSES = ["REQUESTED", "CONFIRMED", "CANCELLED", "COMPLETED"]
HOUR_ENTRY_STATUSES = ["PENDING", "VERIFIED", "REJECTED", "REVOKED"]
CHECKIN_STATUSES = ["OPEN", "CLOSED"]
INCIDENT_STATUSES = ["OPEN", "SUBSTANTIATED", "UNFOUNDED"]


def assert_clock_instant(actual, expected_prefix: str):
    """Assert a server-minted timestamp names the expected logical-clock
    instant. Serialization may append fractional digits or a zone suffix, so
    the comparison is made on the whole-second prefix."""
    assert isinstance(actual, str), f"expected timestamp string, got {actual!r}"
    assert actual.startswith(expected_prefix), (
        f"expected instant {expected_prefix}..., got {actual}"
    )


def _assert_mutable_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an int"


def _assert_append_only_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_campus(data: dict):
    _assert_append_only_common(data, "Campus")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["campus_code"], str) and data["campus_code"]
    assert isinstance(data["badge_prefix"], str) and data["badge_prefix"]


def assert_volunteer(data: dict):
    _assert_mutable_common(data, "Volunteer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["contact_type"] in ["SUPERVISED", "UNSUPERVISED"]
    assert data["status"] in VOLUNTEER_STATUSES
    assert data["required_check_level"] in ["BASIC", "ENHANCED"]
    assert isinstance(data["restriction_flags"], list)
    assert "clearance_expires_at" in data
    assert isinstance(data["total_verified_hours"], (int, float))
    assert isinstance(data["total_provisional_hours"], (int, float))
    assert isinstance(data["recognition_points"], (int, float))
    assert data["recognition_tier"] in ["NONE", "BRONZE", "SILVER", "GOLD"]
    assert "prior_status" in data
    assert "suspension_incident_id" in data


def assert_background_check(data: dict):
    _assert_mutable_common(data, "BackgroundCheck")
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["level"] in ["BASIC", "ENHANCED"]
    assert data["status"] in CHECK_STATUSES
    assert "findings" in data
    assert "decided_at" in data
    assert "expires_at" in data


def assert_training_module(data: dict):
    _assert_append_only_common(data, "TrainingModule")
    assert isinstance(data["module_code"], str) and data["module_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["required_contact_types"], list)
    assert len(data["required_contact_types"]) >= 1
    assert "validity_days" in data


def assert_training_record(data: dict):
    _assert_append_only_common(data, "TrainingRecord")
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert is_valid_uuid(data.get("module_id", ""))
    assert is_iso8601_timestamp(data.get("completed_at", ""))
    assert "expires_at" in data


def assert_opportunity(data: dict):
    _assert_mutable_common(data, "Opportunity")
    assert is_valid_uuid(data.get("campus_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert data["required_contact_type"] in ["SUPERVISED", "UNSUPERVISED"]
    assert data["restricted_category"] in ["NONE", "TRANSPORT", "ONE_ON_ONE"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["status"] in OPPORTUNITY_STATUSES
    assert isinstance(data["committed_count"], int)
    assert isinstance(data["projected_count"], int)


def assert_placement(data: dict):
    _assert_mutable_common(data, "Placement")
    assert is_valid_uuid(data.get("opportunity_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["status"] in PLACEMENT_STATUSES
    assert "confirmed_at" in data
    assert "cancel_reason" in data


def assert_hour_entry(data: dict):
    _assert_mutable_common(data, "HourEntry")
    assert is_valid_uuid(data.get("placement_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert isinstance(data["worked_date"], str) and data["worked_date"]
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0
    assert data["activity_category"] in ["STANDARD", "TUTORING", "MENTORING"]
    assert data["status"] in HOUR_ENTRY_STATUSES
    assert isinstance(data["points"], (int, float))


def assert_check_in(data: dict):
    _assert_mutable_common(data, "VisitCheckIn")
    assert is_valid_uuid(data.get("campus_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert "placement_id" in data
    assert is_iso8601_timestamp(data.get("checked_in_at", ""))
    assert "checked_out_at" in data
    assert data["status"] in CHECKIN_STATUSES
    assert isinstance(data["badge_code"], str) and data["badge_code"]
    assert "close_reason" in data


def assert_incident_report(data: dict):
    _assert_mutable_common(data, "IncidentReport")
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert "placement_id" in data
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["description"], str)
    assert data["status"] in INCIDENT_STATUSES


def assert_recognition_award(data: dict):
    _assert_append_only_common(data, "RecognitionAward")
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert data["source"] in ["AUTO", "MANUAL"]
