"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates the response shape against the PRD contract.
Invariant checkers cover the two conserved quantities the PRD calls out:
the member wallet ledger and storage-unit slot conservation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert data["plan_tier"] in ("STANDARD", "PREMIUM")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["wallet_balance_cents"], int)
    assert isinstance(data["lifetime_loaded_cents"], int)
    assert isinstance(data["lifetime_charged_cents"], int)
    assert_wallet_conservation(data)


def assert_wallet_conservation(data: dict):
    """PRD 2.7 invariant: wallet_balance == lifetime_loaded - lifetime_charged."""
    assert data["wallet_balance_cents"] == (
        data["lifetime_loaded_cents"] - data["lifetime_charged_cents"]
    ), (
        f"wallet conservation broken: balance={data['wallet_balance_cents']} "
        f"loaded={data['lifetime_loaded_cents']} charged={data['lifetime_charged_cents']}"
    )


def assert_station(data: dict):
    _assert_common(data)
    assert data["station_class"] in ("PREP_TABLE", "CONVECTION_OVEN", "BLAST_CHILLER")
    assert data["status"] in ("OPEN", "OUT_OF_SERVICE")
    assert isinstance(data["turnover_buffer_minutes"], int)


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["is_peak"], bool)
    assert isinstance(data["turnover_applied"], bool)
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("CONFIRMED", "CANCELLED", "COMPLETED")


def assert_storage_unit(data: dict):
    _assert_common(data)
    assert data["temp_class"] in ("DRY", "COLD", "FROZEN")
    assert isinstance(data["total_slots"], int)
    assert isinstance(data["used_slots"], int)
    assert data["used_slots"] >= 0
    assert data["used_slots"] <= data["total_slots"], "used_slots must never exceed total_slots"
    assert data["compliance_status"] in ("COMPLIANT", "EXCURSION", "QUARANTINED")
    assert isinstance(data["excursion_minutes"], int)


def assert_storage_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["temp_class"] in ("DRY", "COLD", "FROZEN")
    assert isinstance(data["requested_slots"], int)
    assert isinstance(data["allocation_plan"], list)
    assert isinstance(data["monthly_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "RELEASED", "QUARANTINED")


def assert_ingredient(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["on_hand_qty"], (int, float))
    assert isinstance(data["allergen_tags"], list)


def assert_recipe(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["version"], int)
    assert isinstance(data["batch_yield_units"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_recipe_component(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["recipe_id"])
    assert is_valid_uuid(data["ingredient_id"])
    assert isinstance(data["planned_qty"], (int, float))


def assert_production_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["recipe_id"])
    assert isinstance(data["planned_yield_units"], int)
    assert data["status"] in ("PLANNED", "IN_PRODUCTION", "COMPLETED", "SCRAPPED")


def assert_temp_log(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["storage_unit_id"])
    assert isinstance(data["reading_c"], (int, float))
    assert isinstance(data["in_range"], bool)
    assert isinstance(data["certified"], bool)


def assert_ingredient_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["ingredient_id"])
    assert isinstance(data["order_qty"], (int, float))
    assert isinstance(data["unit_cost_cents"], int)
    assert data["status"] in ("PLACED", "RECEIVED", "CANCELLED")


def assert_event_packout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["batch_ids"], list)
    assert isinstance(data["combined_allergen_tags"], list)
    assert isinstance(data["packed_unit_count"], int)
    assert data["status"] in ("DRAFT", "SEALED", "SHIPPED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID")
