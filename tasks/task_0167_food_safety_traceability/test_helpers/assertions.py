"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_LOT_STATUSES = ["RECEIVED", "RELEASED", "REJECTED", "CONSUMED", "EXPIRED", "DESTROYED"]
_LOT_HOLD_STATUSES = ["FREE", "HELD"]
_LOT_COA_STATUSES = ["NOT_REQUIRED", "PENDING", "ACCEPTED", "REJECTED"]
_COA_STATUSES = ["PENDING", "ACCEPTED", "REJECTED"]
_RUN_STATUSES = ["OPEN", "FINALIZED", "ABORTED"]
_HOLD_STATUSES = ["ACTIVE", "RELEASED", "DISPOSED"]
_CLASSIFICATIONS = ["IN_SPEC", "DEVIATION"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["gln"], str) and len(data["gln"]) > 0
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"


def assert_supplier(data: dict):
    _assert_common(data)
    assert data["approval_status"] in ["APPROVED", "SUSPENDED"]
    assert isinstance(data["coa_required"], bool)
    assert isinstance(data["failed_coa_streak"], int)
    assert data["failed_coa_streak"] >= 0


def assert_ingredient(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["storage_target_c"], (int, float))
    assert isinstance(data["storage_tolerance_c"], (int, float))
    assert isinstance(data["shelf_life_days"], int)
    assert isinstance(data["declared_allergen_codes"], list)


def assert_allergen_profile(data: dict):
    # common_fields:false — only id + created_at; NO updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["severity_rank"], int)
    assert 1 <= data["severity_rank"] <= 5


def assert_lot(data: dict):
    _assert_common(data)
    assert data["status"] in _LOT_STATUSES, f"unexpected lot status {data['status']}"
    assert data["hold_status"] in _LOT_HOLD_STATUSES
    assert data["coa_status"] in _LOT_COA_STATUSES
    assert data["lot_kind"] in ["RAW_MATERIAL", "FINISHED"]
    assert isinstance(data["received_qty"], (int, float))
    assert isinstance(data["available_qty"], (int, float))
    assert data["available_qty"] >= 0, "available_qty floored at 0"
    assert is_iso8601_timestamp(data["effective_expiration_date"])
    assert isinstance(data["cumulative_excursion_minutes"], int)
    assert data["cumulative_excursion_minutes"] >= 0
    assert isinstance(data["effective_allergen_codes"], list)


def assert_coa(data: dict):
    _assert_common(data)
    assert data["status"] in _COA_STATUSES
    assert isinstance(data["measured_allergen_codes"], list)
    assert isinstance(data["pathogen_pass"], bool)
    assert isinstance(data["declared_shelf_life_days"], int)


def assert_production_run(data: dict):
    _assert_common(data)
    assert data["status"] in _RUN_STATUSES
    assert isinstance(data["planned_output_qty"], (int, float))


def assert_consumed_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], (int, float))
    assert data["quantity"] > 0


def assert_ccp_reading(data: dict):
    _assert_common(data)
    assert data["classification"] in _CLASSIFICATIONS
    assert isinstance(data["excursion_minutes"], int)
    assert data["excursion_minutes"] >= 0
    assert isinstance(data["measured_value_c"], (int, float))


def assert_hold_order(data: dict):
    _assert_common(data)
    assert data["status"] in _HOLD_STATUSES
    assert isinstance(data["held_lot_count"], int)
    assert data["held_lot_count"] >= 0


def assert_storage_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_units"], (int, float))
    assert data["capacity_units"] > 0


def assert_storage_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_units"], (int, float))
    assert data["capacity_units"] > 0
