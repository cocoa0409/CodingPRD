"""Entity assertions and domain helpers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(s: str) -> datetime:
    """Parse an ISO 8601 timestamp (Z or +00:00, optional fractional) into a
    timezone-aware UTC datetime, so timestamps can be compared as instants
    regardless of the exact string spelling the server emits."""
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    a = _parse_instant(actual)
    e = _parse_instant(expected)
    assert a == e, f"{label}: expected instant {expected}, got {actual}"


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be a positive int"


def assert_asset(data: dict):
    _assert_common(data)
    assert data["asset_class"] in ("ROAD", "SIGN", "SIGNAL")
    assert data["status"] in ("ACTIVE", "UNDER_REPAIR", "RETIRED")
    assert isinstance(data["replacement_value_cents"], int) and data["replacement_value_cents"] >= 0
    assert isinstance(data["maintenance_cost_to_date_cents"], int)
    assert isinstance(data["capital_cost_to_date_cents"], int)
    if data.get("condition_state") is not None:
        assert data["condition_state"] in ("GOOD", "FAIR", "POOR", "FAILED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["inspection_type"] in ("PREVENTIVE", "CONDITION")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_service_request(data: dict):
    _assert_common(data)
    assert data["channel"] in ("PHONE", "WEB", "APP")
    assert data["category"] in ("POTHOLE", "SIGN_DAMAGE", "SIGNAL_OUTAGE")
    assert data["priority"] in ("LOW", "MEDIUM", "HIGH", "EMERGENCY")
    assert data["status"] in ("NEW", "TRIAGED", "LINKED", "CLOSED", "DUPLICATE")


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["work_type"] in ("MAINTENANCE", "CAPITAL")
    assert data["origin"] in ("INSPECTION", "SERVICE_REQUEST", "PREVENTIVE")
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "DISPATCHED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED"
    )
    assert isinstance(data["labor_cost_cents"], int)
    assert isinstance(data["material_cost_cents"], int)
    assert isinstance(data["actual_cost_cents"], int)
    assert isinstance(data["capitalized"], bool)


def assert_crew(data: dict):
    _assert_common(data)
    assert data["crew_type"] in ("PAVING", "SIGNS", "SIGNALS")
    assert data["status"] in ("AVAILABLE", "ON_ASSIGNMENT")
    assert isinstance(data["committed_minutes"], int)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_dispatch(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "ACTIVE", "RELEASED", "CANCELLED")
    assert isinstance(data["labor_cost_cents"], int)


def assert_yard(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)


def assert_material_item(data: dict):
    _assert_common(data)
    assert data["material_type"] in ("ASPHALT_TON", "SIGN_BLANK", "SIGNAL_LAMP")
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"]


def assert_material_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "CONSUMED", "RELEASED")
    assert isinstance(data["consumed_cost_cents"], int)


def assert_row_permit(data: dict):
    _assert_common(data)
    assert data["permit_type"] in ("LANE_CLOSURE", "EXCAVATION", "UTILITY_COORD")
    assert data["status"] in ("REQUESTED", "APPROVED", "ACTIVE", "DENIED", "RELEASED")
