"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

PRIORITIES = ["LOW", "STANDARD", "HIGH", "EMERGENCY"]
REQUEST_STATUSES = [
    "SUBMITTED", "TRIAGED", "ROUTED", "IN_PROGRESS",
    "RESOLVED", "REOPENED", "CLOSED", "DUPLICATE",
]
WORK_ORDER_STATUSES = ["OPEN", "IN_PROGRESS", "COMPLETED", "REOPENED", "CANCELLED"]
CLUSTER_STATUSES = ["OPEN", "MERGED_CLOSED"]
ESCALATION_STATUSES = ["OPEN", "RESOLVED"]
ESCALATION_TIERS = ["TIER1", "TIER2", "MANUAL"]
SURVEY_STATUSES = ["SENT", "COMPLETED", "EXPIRED"]
NOTIFY_CHANNELS = ["EMAIL", "SMS", "NONE"]
WINDOW_TYPES = ["MAINTENANCE", "BLACKOUT"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_category(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["default_priority"] in PRIORITIES
    assert isinstance(data["requires_geolocation"], bool)
    assert isinstance(data["active"], bool)


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for f in ("min_lat", "max_lat", "min_lng", "max_lng"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_department(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["open_work_order_count"], int)
    assert data["open_work_order_count"] >= 0
    assert isinstance(data["backlog_threshold"], int)
    assert isinstance(data["congested"], bool)
    assert_department_backlog_invariant(data)


def assert_department_backlog_invariant(data: dict):
    """congested is exactly open_work_order_count >= backlog_threshold (inclusive)."""
    expected = data["open_work_order_count"] >= data["backlog_threshold"]
    assert data["congested"] == expected, (
        f"congested {data['congested']} inconsistent with "
        f"open_work_order_count {data['open_work_order_count']} "
        f">= backlog_threshold {data['backlog_threshold']}"
    )


def assert_sla_policy(data: dict):
    _assert_common(data)
    assert data["priority"] in PRIORITIES
    assert isinstance(data["resolution_sla_hours"], int)
    assert isinstance(data["escalation_tier1_hours"], int)
    assert isinstance(data["escalation_tier2_hours"], int)
    assert data["escalation_tier2_hours"] > data["escalation_tier1_hours"]


def assert_citizen(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["notify_channel"] in NOTIFY_CHANNELS


def assert_agent(data: dict):
    _assert_common(data)
    assert isinstance(data["department_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["is_supervisor"], bool)


def assert_service_request(data: dict):
    _assert_common(data)
    assert isinstance(data["citizen_id"], str)
    assert isinstance(data["category_id"], str)
    assert isinstance(data["description"], str)
    assert data["status"] in REQUEST_STATUSES
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["reopen_count"], int)
    assert data["reopen_count"] >= 0
    if data.get("priority") is not None:
        assert data["priority"] in PRIORITIES


def assert_duplicate_cluster(data: dict):
    _assert_common(data)
    assert isinstance(data["category_id"], str)
    assert isinstance(data["canonical_request_id"], str)
    assert data["status"] in CLUSTER_STATUSES
    assert isinstance(data["member_count"], int)
    assert data["member_count"] >= 0


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["request_id"], str)
    assert isinstance(data["department_id"], str)
    assert data["status"] in WORK_ORDER_STATUSES


def assert_satisfaction_survey(data: dict):
    _assert_common(data)
    assert isinstance(data["request_id"], str)
    assert data["status"] in SURVEY_STATUSES
    if data.get("score") is not None:
        assert isinstance(data["score"], int)
        assert 1 <= data["score"] <= 5


def assert_service_window(data: dict):
    _assert_common(data)
    assert data["window_type"] in WINDOW_TYPES
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_escalation(data: dict):
    _assert_append_only(data)
    assert isinstance(data["request_id"], str)
    assert data["tier"] in ESCALATION_TIERS
    assert data["status"] in ESCALATION_STATUSES


def assert_status_notification(data: dict):
    _assert_append_only(data)
    assert isinstance(data["request_id"], str)
    assert data["channel"] in NOTIFY_CHANNELS
    assert isinstance(data["from_status"], str)
    assert isinstance(data["to_status"], str)
