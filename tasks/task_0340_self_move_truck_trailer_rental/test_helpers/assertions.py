"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names and presence follow the PRD contract exactly.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ── Common-field helpers ─────────────────────────────────────────────────
def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_event_fields(data: dict):
    """Append-only event record: only id + created_at, no version/updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# ── Entity assertions ────────────────────────────────────────────────────
def assert_rental_location(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["lot_capacity"], int) and data["lot_capacity"] >= 1
    assert isinstance(data["on_lot_count"], int) and data["on_lot_count"] >= 0
    assert isinstance(data["accepts_one_way_dropoff"], bool)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_equipment_class(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["category"] in ("TRUCK", "TRAILER", "TOW")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert isinstance(data["mileage_rate_cents"], int) and data["mileage_rate_cents"] >= 0
    assert isinstance(data["one_way_flat_cents"], int) and data["one_way_flat_cents"] >= 0
    assert isinstance(data["requires_coverage"], bool)


def assert_coverage_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["daily_fee_cents"], int) and data["daily_fee_cents"] >= 0
    assert isinstance(data["damage_deductible_cents"], int) and data["damage_deductible_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_moving_supply(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0
    assert isinstance(data["returnable"], bool)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_verified"], bool)
    assert data["loyalty_tier"] in ("STANDARD", "SILVER", "GOLD")


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["equipment_class_id"])
    assert is_valid_uuid(data["pickup_location_id"])
    assert is_valid_uuid(data["dropoff_location_id"])
    assert data["trip_type"] in ("ONE_WAY", "ROUND_TRIP")
    assert data["coverage_choice"] in ("SELECTED", "DECLINED")
    assert isinstance(data["planned_days"], int) and data["planned_days"] >= 1
    assert data["booking_status"] in ("PENDING", "CONFIRMED", "CANCELLED")
    assert data["fulfillment_status"] in ("AWAITING_DISPATCH", "DISPATCHED", "COMPLETED")
    assert isinstance(data["quoted_total_cents"], int)


def assert_equipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["equipment_class_id"])
    assert is_valid_uuid(data["home_location_id"])
    assert data["status"] in (
        "AVAILABLE", "RESERVED", "DISPATCHED", "IN_TRANSIT", "MAINTENANCE", "RETIRED",
    )
    assert isinstance(data["odometer_miles"], int)
    assert isinstance(data["fuel_level_eighths"], int)
    assert 0 <= data["fuel_level_eighths"] <= 8


def assert_rental_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["equipment_id"])
    assert isinstance(data["pickup_odometer_miles"], int)
    assert isinstance(data["pickup_fuel_eighths"], int)
    assert data["status"] in (
        "ACTIVE", "RETURNED_CLEAN", "RETURNED_DAMAGED", "SETTLED", "VOID",
    )
    assert isinstance(data["damage_charge_cents"], int)


def assert_drop_off_transfer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["equipment_id"])
    assert is_valid_uuid(data["from_location_id"])
    assert is_valid_uuid(data["to_location_id"])
    assert data["reason"] in ("ONE_WAY_REBALANCE", "FLEET_REBALANCE")
    assert data["status"] in ("REQUESTED", "APPROVED", "COMPLETED", "REJECTED")


def assert_damage_report(data: dict):
    _assert_event_fields(data)
    assert "version" not in data, "DamageReport is append-only: must NOT carry version"
    assert "updated_at" not in data, "DamageReport is append-only: must NOT carry updated_at"
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["assessed_cost_cents"], int) and data["assessed_cost_cents"] >= 1
    assert isinstance(data["description"], str) and len(data["description"]) > 0


def assert_charge_ledger_entry(data: dict):
    _assert_event_fields(data)
    assert "version" not in data, "ChargeLedgerEntry is append-only: must NOT carry version"
    assert "updated_at" not in data, "ChargeLedgerEntry is append-only: must NOT carry updated_at"
    assert is_valid_uuid(data["contract_id"])
    assert data["kind"] in (
        "BASE_DAYS", "MILEAGE", "ONE_WAY_FLAT", "ADDON", "COVERAGE",
        "FUEL_SHORTFALL", "LATE_RETURN", "DAMAGE", "SUPPLY", "SUPPLY_REFUND",
    )
    assert isinstance(data["amount_cents"], int)


# ── Domain helpers ───────────────────────────────────────────────────────
def ledger_lines_of_kind(ledger: list, kind: str) -> list:
    """All ChargeLedgerEntry rows with the given kind."""
    return [e for e in ledger if e.get("kind") == kind]


def sum_ledger_kind(ledger: list, kind: str) -> int:
    """Sum of amount_cents over all ledger rows of the given kind."""
    return sum(e["amount_cents"] for e in ledger if e.get("kind") == kind)
