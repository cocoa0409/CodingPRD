"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version for full common-field entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def _assert_common_append_only(data: dict):
    """id + created_at only; append-only rows carry no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, \
        "append-only record must not carry an updated_at field"


def assert_rate_card(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for f in ("daily_rate_cents", "weekly_rate_cents", "four_week_rate_cents",
              "deposit_cents", "damage_waiver_daily_cents",
              "fuel_refill_cents_per_liter", "cleaning_fee_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be int >= 0"
    assert isinstance(data["late_fee_multiplier"], (int, float))
    assert data["late_fee_multiplier"] >= 1.0
    assert isinstance(data["active"], bool)


def assert_catalog_item(data: dict):
    _assert_common_full(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("HAND_TOOL", "POWER_TOOL", "HEAVY_EQUIPMENT")
    assert isinstance(data["requires_delivery"], bool)
    assert isinstance(data["fuel_capacity_liters"], int)
    assert data["fuel_capacity_liters"] >= 0
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 0
    assert isinstance(data["available_unit_count"], int)
    assert data["available_unit_count"] >= 0


def assert_equipment_unit(data: dict):
    _assert_common_full(data)
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert data["availability_state"] in (
        "AVAILABLE", "ON_RENT", "OUT_OF_SERVICE")
    assert isinstance(data["fuel_level_liters"], int)
    assert isinstance(data["lifetime_rental_days"], int)
    assert data["lifetime_rental_days"] >= 0
    assert isinstance(data["service_due_at_days"], int)
    assert data["service_due_at_days"] >= 1


def assert_contractor_account(data: dict):
    _assert_common_full(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_reservation_count"], int)
    assert data["open_reservation_count"] >= 0


def assert_delivery_truck(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0


def assert_reservation(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("contractor_account_id", ""))
    assert is_valid_uuid(data.get("catalog_item_id", ""))
    assert data["fulfillment_method"] in ("PICKUP", "DELIVERY")
    assert isinstance(data["rental_start_date"], str)
    assert isinstance(data["rental_end_date"], str)
    assert isinstance(data["damage_waiver_opted"], bool)
    assert data["reservation_state"] in (
        "CONFIRMED", "DISPATCHED_DELIVERY", "PICKED_UP",
        "ON_RENT", "CANCELLED", "FULFILLED")
    assert isinstance(data["estimated_rental_cents"], int)
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["delivery_fee_cents"], int)


def assert_rental_agreement(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert is_valid_uuid(data.get("equipment_unit_id", ""))
    assert is_valid_uuid(data.get("contractor_account_id", ""))
    assert data["agreement_state"] in (
        "ON_RENT", "RETURNED_PENDING_INSPECTION", "CLOSED", "CLOSED_WITH_DAMAGE")
    assert isinstance(data["deposit_held_cents"], int)


def assert_return_inspection(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("rental_agreement_id", ""))
    assert isinstance(data["return_fuel_level_liters"], int)
    assert data["return_fuel_level_liters"] >= 0
    assert data["cleanliness"] in ("CLEAN", "DIRTY")
    assert isinstance(data["damage_assessed_cents"], int)
    assert data["damage_assessed_cents"] >= 0
    assert isinstance(data["fuel_refill_cents"], int)
    assert isinstance(data["net_damage_cents"], int)


def assert_maintenance_ticket(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("equipment_unit_id", ""))
    assert data["reason"] in ("SCHEDULED_SERVICE", "DAMAGE_REPAIR", "INSPECTION")
    assert data["ticket_state"] in ("OPEN", "RESOLVED")


def assert_damage_charge(data: dict):
    _assert_common_append_only(data)
    assert is_valid_uuid(data.get("rental_agreement_id", ""))
    assert is_valid_uuid(data.get("return_inspection_id", ""))
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["waiver_applied"], bool)
    assert isinstance(data["net_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_common_append_only(data)
    assert is_valid_uuid(data.get("contractor_account_id", ""))
    assert data["entry_type"] in (
        "RENTAL_CHARGE", "FUEL_CHARGE", "CLEANING_CHARGE", "LATE_FEE",
        "DAMAGE_CHARGE", "DEPOSIT_HOLD", "DEPOSIT_REFUND", "PAYMENT")
    assert isinstance(data["amount_cents"], int)
