"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_timestamp_equals(actual: str, expected_iso: str):
    """Two timestamps denote the same instant (formatting may differ)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"expected instant {expected_iso}, got {actual}"
    )


def assert_steward(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["status"] in ("APPLIED", "ACTIVE", "SUSPENDED", "RETIRED")
    assert isinstance(data["training_level"], int)
    assert isinstance(data["lifetime_points"], int)
    assert isinstance(data["rolling_points"], int)
    assert data["recognition_tier"] in ("NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["strike_count"], int)
    assert data.get("suspended_at") is None or is_iso8601_timestamp(data["suspended_at"])
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_training_module(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str)
    assert isinstance(data["level"], int)
    assert data.get("prerequisite_module_id") is None or isinstance(
        data["prerequisite_module_id"], str
    )
    assert isinstance(data["active"], bool)
    assert isinstance(data.get("version"), int)


def assert_training_completion(data: dict):
    """Lean record: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("steward_id", ""))
    assert is_valid_uuid(data.get("module_id", ""))
    assert isinstance(data["score"], int)
    assert data["result"] in ("PASSED", "FAILED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "TrainingCompletion must not expose updated_at"
    assert "version" not in data, "TrainingCompletion must not expose version"


def assert_box(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("steward_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["latitude"], (int, float))
    assert isinstance(data["longitude"], (int, float))
    assert isinstance(data["capacity_books"], int) and data["capacity_books"] >= 1
    assert isinstance(data["region_code"], str)
    assert data.get("charter_number") is None or isinstance(data["charter_number"], str)
    assert data["charter_status"] in (
        "DRAFT",
        "CHARTERED",
        "ACTIVE",
        "SUSPENDED",
        "DECOMMISSIONED",
    )
    assert data["listing_posture"] in ("UNLISTED", "LISTED", "FLAGGED", "DELISTED")
    assert data.get("installed_at") is None or is_iso8601_timestamp(data["installed_at"])
    assert data.get("suspended_at") is None or is_iso8601_timestamp(data["suspended_at"])
    assert data.get("last_activity_at") is None or is_iso8601_timestamp(
        data["last_activity_at"]
    )
    assert isinstance(data["current_stock"], int)
    assert isinstance(data["open_critical_maintenance_count"], int)
    assert isinstance(data["open_high_maintenance_count"], int)
    assert isinstance(data["upheld_complaints_90d"], int)
    assert data.get("days_since_activity") is None or isinstance(
        data["days_since_activity"], int
    )
    assert isinstance(data.get("version"), int)


def assert_inspection_record(data: dict):
    """Lean record: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("box_id", ""))
    assert isinstance(data["inspector_user_id"], str)
    assert data["result"] in ("CONFIRMED", "NOT_FOUND", "FAILED_CONDITION")
    assert data.get("notes") is None or isinstance(data["notes"], str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "InspectionRecord must not expose updated_at"
    assert "version" not in data, "InspectionRecord must not expose version"


def assert_maintenance_request(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("box_id", ""))
    assert data["category"] in (
        "WEATHER_DAMAGE",
        "VANDALISM",
        "WEAR",
        "INSTALLATION_DEFECT",
    )
    assert isinstance(data["description"], str)
    assert data.get("severity") is None or data["severity"] in (
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    )
    assert data["status"] in (
        "REPORTED",
        "SCHEDULED",
        "RESOLVED",
        "REOPENED",
        "WONT_FIX",
    )
    assert data["season_at_report"] in ("WINTER", "SPRING", "SUMMER", "FALL")
    assert data["season_multiplier"] in (1.0, 2.0)
    assert data.get("sla_deadline_at") is None or is_iso8601_timestamp(
        data["sla_deadline_at"]
    )
    assert data.get("triaged_at") is None or is_iso8601_timestamp(data["triaged_at"])
    assert data.get("resolved_at") is None or is_iso8601_timestamp(data["resolved_at"])
    assert isinstance(data["resolution_count"], int)
    assert data.get("reimbursement_cents") is None or isinstance(
        data["reimbursement_cents"], int
    )
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data.get("version"), int)


def assert_complaint(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("box_id", ""))
    assert data["category"] in (
        "INAPPROPRIATE_CONTENT",
        "HATE_SPEECH",
        "COMMERCIAL_SPAM",
        "OTHER",
    )
    assert data.get("target_category") is None or data["target_category"] in (
        "FICTION",
        "NONFICTION",
        "CHILDREN",
        "YOUNG_ADULT",
        "REFERENCE",
    )
    assert isinstance(data["description"], str)
    assert data["status"] in (
        "FILED",
        "STEWARD_RESPONSE_PENDING",
        "UNDER_REVIEW",
        "RESOLVED_UPHELD",
        "RESOLVED_DISMISSED",
        "ESCALATED",
        "ADJUDICATED_UPHELD",
        "ADJUDICATED_DISMISSED",
    )
    assert data.get("outcome") is None or data["outcome"] in ("UPHELD", "DISMISSED")
    assert data.get("response_due_at") is None or is_iso8601_timestamp(
        data["response_due_at"]
    )
    assert data.get("upheld_at") is None or is_iso8601_timestamp(data["upheld_at"])
    assert isinstance(data.get("version"), int)


def assert_school(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["district_code"], str)
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["region_code"], str)
    assert isinstance(data["restricted_categories"], list)
    assert data["status"] in ("REGISTERED", "ACTIVE", "INACTIVE")
    assert isinstance(data["drives_completed_count"], int)
    assert isinstance(data.get("version"), int)


def assert_drive(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert is_valid_uuid(data.get("coordinator_steward_id", ""))
    assert isinstance(data["goal_books"], int) and data["goal_books"] >= 1
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["status"] in (
        "PROPOSED",
        "APPROVED",
        "OPEN",
        "COLLECTION_CLOSED",
        "COMPLETED",
        "CANCELLED",
        "REJECTED",
    )
    assert data["school_approval_status"] in ("PENDING", "APPROVED", "REJECTED")
    assert data["network_approval_status"] in ("PENDING", "APPROVED", "REJECTED")
    assert isinstance(data["collected_count"], int)
    assert isinstance(data["accepted_count"], int)
    assert isinstance(data["fulfillment_pct_gross"], int)
    assert isinstance(data["fulfillment_pct_net"], int)
    assert isinstance(data["qualifies_for_bonus"], bool)
    assert isinstance(data.get("version"), int)


def assert_batch(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["source_type"] in ("PUBLIC_DROP", "STEWARD_TRANSFER", "BOOK_DRIVE")
    assert data.get("drive_id") is None or isinstance(data["drive_id"], str)
    assert isinstance(data["region_code"], str)
    assert data["status"] in ("RECEIVED", "SORTED", "CLOSED")
    assert isinstance(data["item_count"], int)
    assert isinstance(data["graded_count"], int)
    assert isinstance(data.get("version"), int)


def assert_book_item(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("batch_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert data["category"] in (
        "FICTION",
        "NONFICTION",
        "CHILDREN",
        "YOUNG_ADULT",
        "REFERENCE",
    )
    assert data.get("condition_grade") is None or data["condition_grade"] in (
        "A",
        "B",
        "C",
    )
    assert data["status"] in (
        "AVAILABLE",
        "ALLOCATED",
        "DISPATCHED",
        "PLACED",
        "QUARANTINED",
        "RECYCLED",
    )
    assert data.get("box_id") is None or isinstance(data["box_id"], str)
    assert isinstance(data.get("version"), int)


def assert_distribution_run(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["status"] in (
        "DRAFT",
        "CONFIRMED",
        "DISPATCHED",
        "COMPLETED",
        "SUPERSEDED",
    )
    assert isinstance(data["plan_snapshot"], list)
    for entry in data["plan_snapshot"]:
        assert is_valid_uuid(entry.get("box_id", ""))
        assert isinstance(entry["quantity"], int)
        assert isinstance(entry["need_score"], int)
    assert isinstance(data["planned_item_count"], int)
    assert isinstance(data.get("version"), int)


def assert_allocation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("run_id", ""))
    assert is_valid_uuid(data.get("book_item_id", ""))
    assert is_valid_uuid(data.get("box_id", ""))
    assert data["status"] in ("RESERVED", "DISPATCHED", "PLACED", "CANCELLED", "REMOVED")
    assert data.get("placed_at") is None or is_iso8601_timestamp(data["placed_at"])
    assert isinstance(data.get("version"), int)


def assert_recognition_event(data: dict):
    """Lean record: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("steward_id", ""))
    assert data["event_type"] in (
        "MAINTENANCE_RESOLVED",
        "ALLOCATION_PLACED",
        "DRIVE_COMPLETED",
        "COMPLAINT_UPHELD",
        "TRAINING_PASSED",
    )
    assert isinstance(data["points_delta"], int)
    assert data["source_type"] in (
        "MAINTENANCE_REQUEST",
        "ALLOCATION",
        "BOOK_DRIVE",
        "COMPLAINT",
        "TRAINING_COMPLETION",
    )
    assert isinstance(data["source_id"], str) and data["source_id"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "RecognitionEvent must not expose updated_at"
    assert "version" not in data, "RecognitionEvent must not expose version"


def assert_box_stock_invariant(box: dict, placed_allocation_count: int):
    """current_stock always equals the count of PLACED allocations for the box."""
    assert box["current_stock"] == placed_allocation_count, (
        f"current_stock {box['current_stock']} != PLACED allocations "
        f"{placed_allocation_count}"
    )
