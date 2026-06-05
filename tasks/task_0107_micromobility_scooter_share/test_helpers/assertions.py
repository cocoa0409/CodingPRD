"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates field presence, types, and enum membership for a
resource returned by the API, using the framework's generic UUID/timestamp
validators. Field names match the PRD exactly.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_VEHICLE_STATUSES = {"AVAILABLE", "RESERVED", "IN_USE", "LOW_BATTERY", "MAINTENANCE", "RETIRED"}
_TRIP_STATUSES = {"ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"}
_TASK_STATUSES = {"OPEN", "ASSIGNED", "COMPLETED", "CANCELLED"}
_SETTLEMENT_STATUSES = {"PENDING", "SETTLED", "DISPUTED", "WAIVED"}
_APP_STATUSES = {"SUBMITTED", "APPROVED", "REJECTED"}
_REPORT_STATUSES = {"DRAFT", "FINALIZED"}
_TXN_TYPES = {"TOPUP", "TRIP_CHARGE", "TRIP_REFUND", "FINE_CHARGE", "FINE_REFUND"}


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-typed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_event_common(data: dict):
    """Append-only event record: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_plan(data: dict):
    _assert_common(data)
    assert data["code"] in ("STANDARD", "LOW_INCOME"), f"bad plan code {data.get('code')!r}"
    assert isinstance(data["unlock_fee_cents"], int) and data["unlock_fee_cents"] >= 0
    assert isinstance(data["per_minute_cents"], int) and data["per_minute_cents"] >= 0
    assert isinstance(data["daily_cap_cents"], int) and data["daily_cap_cents"] >= 0
    assert 0 <= data["slow_zone_discount_pct"] <= 1
    assert isinstance(data["active"], bool)


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["zone_type"] in ("RIDE_OK", "SLOW", "NO_RIDE", "NO_PARK")
    assert isinstance(data["priority"], int) and data["priority"] >= 1


def assert_vehicle(data: dict):
    _assert_common(data)
    assert data["vehicle_type"] in ("SCOOTER", "EBIKE")
    assert isinstance(data["qr_code"], str) and len(data["qr_code"]) > 0
    assert isinstance(data["battery_pct"], int) and 0 <= data["battery_pct"] <= 100
    assert is_valid_uuid(data.get("current_zone_id", "")), "current_zone_id must be a UUID"
    assert data["status"] in _VEHICLE_STATUSES, f"bad vehicle status {data.get('status')!r}"


def assert_rider(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["wallet_balance_cents"], int)
    assert isinstance(data["outstanding_fine_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_trip(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rider_id", "")), "rider_id must be a UUID"
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert is_valid_uuid(data.get("start_zone_id", "")), "start_zone_id must be a UUID"
    assert data["status"] in _TRIP_STATUSES, f"bad trip status {data.get('status')!r}"
    assert isinstance(data["estimated_fare_cents"], int)
    assert isinstance(data["final_fare_cents"], int)
    assert isinstance(data["billable_minutes"], int)


def assert_trip_segment(data: dict):
    _assert_event_common(data)
    assert is_valid_uuid(data.get("trip_id", "")), "trip_id must be a UUID"
    assert data["segment_type"] in ("RIDE", "PAUSE")
    assert isinstance(data["duration_seconds"], int)
    # Append-only event: must NOT carry updated_at / version.
    assert "updated_at" not in data, "TripSegment must not carry updated_at"
    assert "version" not in data, "TripSegment must not carry version"


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data.get("depot_zone_id", "")), "depot_zone_id must be a UUID"
    assert isinstance(data["on_shift"], bool)


def assert_rebalancing_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert data["task_type"] in ("MOVE", "SWAP")
    assert data["status"] in _TASK_STATUSES, f"bad task status {data.get('status')!r}"


def assert_fine(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rider_id", "")), "rider_id must be a UUID"
    assert is_valid_uuid(data.get("trip_id", "")), "trip_id must be a UUID"
    assert data["reason"] in ("BAD_PARKING_NO_PARK", "BAD_PARKING_OUT_OF_ZONE")
    assert isinstance(data["amount_cents"], int)
    assert data["settlement_status"] in _SETTLEMENT_STATUSES


def assert_low_income_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rider_id", "")), "rider_id must be a UUID"
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert data["status"] in _APP_STATUSES


def assert_wallet_transaction(data: dict):
    _assert_event_common(data)
    assert is_valid_uuid(data.get("rider_id", "")), "rider_id must be a UUID"
    assert data["txn_type"] in _TXN_TYPES, f"bad txn_type {data.get('txn_type')!r}"
    assert isinstance(data["amount_cents"], int)
    assert "updated_at" not in data, "WalletTransaction must not carry updated_at"
    assert "version" not in data, "WalletTransaction must not carry version"


def assert_mds_report(data: dict):
    _assert_common(data)
    assert isinstance(data["trip_count"], int)
    assert isinstance(data["total_billable_minutes"], int)
    assert isinstance(data["avg_available_vehicles"], (int, float))
    assert data["status"] in _REPORT_STATUSES
