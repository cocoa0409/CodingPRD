"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_zone(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Zone.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Zone.created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["grid_code"], str) and len(data["grid_code"]) > 0
    assert isinstance(data["is_airport"], bool)
    assert isinstance(data["base_fare_cents"], int)
    assert isinstance(data["open_demand_count"], int) and data["open_demand_count"] >= 0
    assert isinstance(data["available_supply_count"], int) and data["available_supply_count"] >= 0
    assert data["heat_level"] in ("COOL", "WARM", "HOT", "BLAZING")
    assert isinstance(data["version"], int)


def assert_driver(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Driver.id must be a UUID"
    assert data["status"] in ("OFFLINE", "AVAILABLE", "ON_TRIP")
    assert is_valid_uuid(data["home_zone_id"])
    assert is_valid_uuid(data["current_zone_id"])


def assert_rider(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Rider.id must be a UUID"
    assert isinstance(data["wallet_balance_cents"], int) and data["wallet_balance_cents"] >= 0
    assert is_valid_uuid(data["home_zone_id"])


def assert_surge_snapshot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "SurgeSnapshot.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "SurgeSnapshot.created_at must be ISO 8601"
    # Immutable event-log row: carries NO updated_at and NO version.
    assert "version" not in data, "SurgeSnapshot must not carry a version field"
    assert "updated_at" not in data, "SurgeSnapshot must not carry an updated_at field"
    assert isinstance(data["multiplier"], (int, float))
    assert isinstance(data["ratio"], (int, float))
    assert isinstance(data["capped"], bool)


def assert_trip(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Trip.id must be a UUID"
    assert data["status"] in ("REQUESTED", "MATCHED", "ENROUTE", "COMPLETED", "CANCELLED", "EXPIRED")
    assert is_valid_uuid(data["rider_id"])
    assert is_valid_uuid(data["pickup_zone_id"])
    assert is_valid_uuid(data["dropoff_zone_id"])
    assert isinstance(data["final_fare_cents"], int)
    assert isinstance(data["driver_payout_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_airport_queue_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "AirportQueueEntry.id must be a UUID"
    assert data["status"] in ("WAITING", "DISPATCHED", "WITHDRAWN")
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["driver_id"])


def assert_quest(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Quest.id must be a UUID"
    assert data["status"] in ("ACTIVE", "EARNED", "EXPIRED")
    assert is_valid_uuid(data["driver_id"])
    assert isinstance(data["target_trips"], int)
    assert isinstance(data["bonus_cents"], int)
    assert isinstance(data["completed_trips"], int)
    assert isinstance(data["paid_out_cents"], int)


def assert_dispute(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Dispute.id must be a UUID"
    assert data["status"] in ("OPEN", "UPHELD", "REJECTED")
    assert is_valid_uuid(data["trip_id"])
    assert is_valid_uuid(data["rider_id"])
    assert data["reason"] in ("OVERCHARGED", "DRIVER_NO_SHOW", "ROUTE_ERROR")
    assert isinstance(data["refund_cents"], int)
