"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_PARCEL_STATUSES = {"RECEIVED", "SORTED", "ROUTED", "DELIVERED", "RETURNED"}
_ROUTE_STATUSES = {"PLANNING", "DISPATCHED", "COMPLETED", "CANCELLED"}
_STOP_STATUSES = {
    "PENDING", "OUT_FOR_DELIVERY", "ATTEMPTED", "DELIVERED",
    "REDELIVERY_SCHEDULED", "FAILED", "CANCELLED",
}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_transit_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["hazmat_certified"], bool)
    assert isinstance(data["sort_capacity"], int) and data["sort_capacity"] >= 1
    assert isinstance(data["sorted_count"], int) and data["sorted_count"] >= 0
    assert data["status"] in {"OPEN", "CLOSED"}


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["hazmat_certified"], bool)
    assert data["vehicle_capacity_kg"] > 0
    assert data["failure_points"] >= 0, "failure_points is floored at zero"
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


def assert_parcel(data: dict):
    _assert_common(data)
    assert isinstance(data["tracking_code"], str) and len(data["tracking_code"]) > 0
    assert data["weight_kg"] > 0
    assert data["service_level"] in {"GROUND", "EXPRESS", "PRIORITY"}
    assert isinstance(data["signature_required"], bool)
    assert data["hazmat_class"] in {"NONE", "CLASS_3", "CLASS_8"}
    assert isinstance(data["driver_release_authorized"], bool)
    assert data["status"] in _PARCEL_STATUSES


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["origin_center_id"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["max_stops"], int) and data["max_stops"] >= 1
    assert data["planned_weight_kg"] >= 0
    assert data["committed_weight_kg"] >= 0
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0
    assert data["status"] in _ROUTE_STATUSES


def assert_stop(data: dict):
    _assert_common(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert data["window_end_min"] > data["window_start_min"]
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert isinstance(data["redelivery_fee_cents"], int) and data["redelivery_fee_cents"] >= 0
    assert data["status"] in _STOP_STATUSES


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["stop_id"], str)
    assert isinstance(data["requested_start_min"], int)
    assert isinstance(data["requested_end_min"], int)
    assert data["status"] in {"REQUESTED", "APPLIED", "REJECTED"}


def assert_delivery_attempt(data: dict):
    """DeliveryAttempt is append-only: id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["outcome"] in {"DELIVERED", "NO_ONE_HOME", "REFUSED", "ADDRESS_ISSUE"}
    assert isinstance(data["attempt_index"], int) and data["attempt_index"] >= 1
