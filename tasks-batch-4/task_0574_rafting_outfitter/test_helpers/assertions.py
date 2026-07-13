"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_river_trip(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "OPEN", "FULL", "WEATHER_HOLD", "CANCELLED", "COMPLETED",
    ], f"unexpected trip status {data.get('status')}"
    assert data["booking_mode"] in ["GROUP", "PRIVATE"]
    assert data["difficulty_class"] in ["CLASS_I", "CLASS_II", "CLASS_III", "CLASS_IV", "CLASS_V"]
    assert isinstance(data["committed_guests"], int) and data["committed_guests"] >= 0
    assert isinstance(data["assigned_guide_count"], int) and data["assigned_guide_count"] >= 0
    assert isinstance(data["deposits_held_cents"], int) and data["deposits_held_cents"] >= 0
    assert isinstance(data["max_capacity"], int) and data["max_capacity"] >= 1


def assert_guide(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert data["max_class"] in ["CLASS_I", "CLASS_II", "CLASS_III", "CLASS_IV", "CLASS_V"]


def assert_guide_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ASSIGNED", "RELEASED"]
    assert data["role"] in ["LEAD", "SAFETY", "SWEEP"]
    assert isinstance(data["provisional_gratuity_share_cents"], int)
    assert isinstance(data["final_gratuity_share_cents"], int)


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ["UNPAID", "DEPOSIT_PAID", "SETTLED", "REFUNDED"]
    assert data["fulfillment_status"] in [
        "PENDING", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED",
    ]
    assert data["booking_type"] in ["GROUP", "PRIVATE"]
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["estimated_total_cents"], int)


def assert_guest(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "CHECKED_IN", "REMOVED"]
    assert isinstance(data["age"], int) and data["age"] >= 0


def assert_waiver(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "SIGNED", "VOID"]
    assert isinstance(data["guardian_required"], bool)


def assert_gear_item(data: dict):
    _assert_common(data)
    assert data["status"] in ["AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"]
    assert data["gear_type"] in ["RAFT", "WETSUIT", "PFD"]


def assert_gear_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ASSIGNED", "RELEASED"]


def assert_shuttle_run(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "CANCELLED"]
    assert data["direction"] in ["TO_PUT_IN", "FROM_TAKE_OUT"]


def assert_condition_reading(data: dict):
    """RiverConditionReading is append-only: carries only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["resulting_band"] in ["SAFE", "MARGINAL", "UNSAFE"]
