"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ORDER_STATES = {
    "CREATED", "SCHEDULED", "ROUTED", "OUT_FOR_DELIVERY", "DELIVERED",
    "REFUSED_RETRY", "SETTLED", "RETURNED", "CANCELLED",
}
SERVICE_LEVELS = {"THRESHOLD", "ROOM_OF_CHOICE", "WHITE_GLOVE"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_depot(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0


def assert_dock(data: dict):
    _assert_common(data)
    assert data["status"] in {"OPEN", "CLOSED"}
    assert isinstance(data["buffer_min"], int)


def assert_team(data: dict):
    _assert_common(data)
    assert data["status"] in {"ACTIVE", "OUT_OF_SERVICE"}
    assert isinstance(data["estimated_liability_points"], int)
    assert isinstance(data["settled_liability_points"], int)
    assert data["estimated_liability_points"] >= 0
    assert data["settled_liability_points"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ORDER_STATES, f"unexpected order status {data['status']}"
    assert data["service_level"] in SERVICE_LEVELS
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["reattempt_count"], int)


def assert_window(data: dict):
    _assert_common(data)
    assert data["status"] in {"RESERVED", "CONFIRMED", "RELEASED", "COMPLETED"}


def assert_route(data: dict):
    _assert_common(data)
    assert data["status"] in {"PLANNING", "DISPATCHED", "CLOSED"}
    assert isinstance(data["dock_ready"], bool)


def assert_route_stop(data: dict):
    _assert_common(data)
    assert data["status"] in {"PLANNED", "COMPLETED", "SKIPPED"}


def assert_dock_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in {"BOOKED", "RELEASED", "COMPLETED"}


def assert_delivery_attempt(data: dict):
    """DeliveryAttempt is append-only: only id + created_at are guaranteed,
    with no updated_at and no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only attempt must not carry updated_at"
    assert "version" not in data, "append-only attempt must not carry version"


def assert_route_committed_consistent(route: dict):
    """Route committed aggregates are non-negative (PRD §3.4)."""
    assert route["committed_stops"] >= 0
    assert route["committed_weight_lbs"] >= 0
    assert route["committed_volume_cuft"] >= 0
