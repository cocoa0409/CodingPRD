"""Entity assertions and domain invariant checkers for the Car Rental Operations API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

VEHICLE_STATES = ["AVAILABLE", "RESERVED", "ON_RENT", "MAINTENANCE", "RETIRED"]
RESERVATION_STATES = ["QUOTED", "CONFIRMED", "PICKED_UP", "CANCELLED", "NO_SHOW", "EXPIRED"]
AGREEMENT_STATES = ["OPEN", "CLOSED", "WRITE_OFF"]
INCIDENT_STATES = ["FILED", "RESOLVED", "VOID"]
MEMBER_TIERS = ["STANDARD", "SILVER", "GOLD"]
LEDGER_KINDS = [
    "BASE_RENTAL", "MILEAGE_OVERAGE", "FUEL", "ADDONS", "YOUNG_DRIVER",
    "ONE_WAY_DROP", "DAMAGE", "LOYALTY_DISCOUNT", "INCIDENT_REVERSAL",
]
ACCRUAL_KINDS = ["ACCRUAL", "REDEMPTION", "REVERSAL"]


def _assert_full_entity_fields(data: dict):
    """id + created_at + updated_at + version for full (common_fields:true) entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """id + created_at only for append-only (common_fields:false) entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_location(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["one_way_drop_fee_cents"], int) and data["one_way_drop_fee_cents"] >= 0
    assert isinstance(data["young_driver_surcharge_per_day_cents"], int)
    assert data["young_driver_surcharge_per_day_cents"] >= 0


def assert_vehicle_class(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["tier_rank"], int) and data["tier_rank"] >= 1
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert isinstance(data["weekly_rate_cents"], int) and data["weekly_rate_cents"] > 0
    assert isinstance(data["included_miles_per_day"], int) and data["included_miles_per_day"] >= 0
    assert isinstance(data["overage_per_mile_cents"], int) and data["overage_per_mile_cents"] >= 0
    assert isinstance(data["ldw_per_day_cents"], int) and data["ldw_per_day_cents"] >= 0
    assert isinstance(data["pai_per_day_cents"], int) and data["pai_per_day_cents"] >= 0
    assert isinstance(data["total_count"], int) and data["total_count"] >= 0
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert data["available_count"] <= data["total_count"], "available_count must not exceed total_count"


def assert_rate_plan(data: dict):
    _assert_full_entity_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["class_id"])
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert isinstance(data["weekly_rate_cents"], int) and data["weekly_rate_cents"] > 0
    assert isinstance(data["active"], bool)
    assert is_iso8601_timestamp(data["effective_from"])


def assert_vehicle(data: dict):
    _assert_full_entity_fields(data)
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["class_id"])
    assert isinstance(data["plate"], str) and len(data["plate"]) > 0
    assert data["status"] in VEHICLE_STATES, f"unexpected vehicle status {data['status']}"
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["fuel_level_eighths"], int) and 0 <= data["fuel_level_eighths"] <= 8
    held = data.get("held_by_reservation_id")
    assert held is None or is_valid_uuid(held)


def assert_member(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["driver_age"], int) and data["driver_age"] >= 18
    assert data["tier"] in MEMBER_TIERS, f"unexpected tier {data['tier']}"
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["lifetime_points"], int)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_reservation(data: dict):
    _assert_full_entity_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["pickup_location_id"])
    assert is_valid_uuid(data["dropoff_location_id"])
    assert is_valid_uuid(data["class_id"])
    assert is_iso8601_timestamp(data["pickup_at"])
    assert is_iso8601_timestamp(data["dropoff_at"])
    assert isinstance(data["rental_days"], int) and data["rental_days"] >= 1
    assert isinstance(data["ldw_selected"], bool)
    assert isinstance(data["pai_selected"], bool)
    assert data["status"] in RESERVATION_STATES, f"unexpected reservation status {data['status']}"


def assert_rental_agreement(data: dict):
    _assert_full_entity_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["odometer_out"], int) and data["odometer_out"] >= 0
    assert isinstance(data["fuel_out_eighths"], int) and 0 <= data["fuel_out_eighths"] <= 8
    assert data["status"] in AGREEMENT_STATES, f"unexpected agreement status {data['status']}"


def assert_incident_report(data: dict):
    _assert_full_entity_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["severity"] in ["MINOR", "MAJOR", "TOTAL"]
    assert isinstance(data["assessed_damage_cents"], int) and data["assessed_damage_cents"] >= 0
    assert isinstance(data["member_liability_cents"], int) and data["member_liability_cents"] >= 0
    assert data["status"] in INCIDENT_STATES, f"unexpected incident status {data['status']}"


def assert_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only LedgerEntry must not carry updated_at"
    assert "version" not in data, "append-only LedgerEntry must not carry version"
    assert is_valid_uuid(data["agreement_id"])
    assert data["kind"] in LEDGER_KINDS, f"unexpected ledger kind {data['kind']}"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["memo"], str)


def assert_loyalty_accrual(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only LoyaltyAccrual must not carry updated_at"
    assert "version" not in data, "append-only LoyaltyAccrual must not carry version"
    assert is_valid_uuid(data["member_id"])
    assert data["kind"] in ACCRUAL_KINDS, f"unexpected accrual kind {data['kind']}"
    assert isinstance(data["delta_points"], int)


def ledger_sum(entries: list) -> int:
    """Sum of amount_cents across an agreement's ledger entries."""
    return sum(e["amount_cents"] for e in entries)


def find_ledger_entries(entries: list, kind: str) -> list:
    """Return ledger entries of a given kind."""
    return [e for e in entries if e["kind"] == kind]
