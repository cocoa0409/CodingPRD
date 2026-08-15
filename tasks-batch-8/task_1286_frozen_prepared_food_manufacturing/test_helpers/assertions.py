"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["product_style"] in ("ENTREE", "BOWL", "SKILLET")
    assert isinstance(data["base_batch_yield_units"], int) and data["base_batch_yield_units"] > 0
    assert data["portion_weight_g"] > 0
    assert isinstance(data["shelf_life_days"], int) and data["shelf_life_days"] > 0
    assert data["status"] in ("DRAFT", "APPROVED", "RETIRED")


def assert_component(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert isinstance(data["component_name"], str) and data["component_name"]
    assert data["component_type"] in ("RAW_INGREDIENT", "SUB_ASSEMBLY", "PACKAGING")
    assert data["quantity_per_base_batch"] > 0
    assert data["unit_of_measure"] in ("KG", "L", "EACH", "M")
    assert 0 < data["scale_exponent"] <= 1.5


def assert_copack_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["billing_method"] in ("PER_CASE", "PER_KG")


def assert_production_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert data["pack_format"] in ("RETAIL", "FOODSERVICE")
    assert isinstance(data["units_planned"], int) and data["units_planned"] > 0
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["units_planned"], int) and data["units_planned"] > 0
    assert data["status"] in (
        "CREATED", "KITTED", "COOKED", "FROZEN", "PACKED",
        "COMPLETED", "ON_HOLD", "REWORK", "CANCELLED",
    )


def assert_freezer_cell(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cell_code"], str) and data["cell_code"]
    assert isinstance(data["capacity_kg"], int) and data["capacity_kg"] > 0
    assert isinstance(data["min_load_kg"], int) and 0 < data["min_load_kg"] <= data["capacity_kg"]
    assert isinstance(data["pull_down_kg_per_hour"], int) and data["pull_down_kg_per_hour"] > 0
    assert isinstance(data["sanitation_minutes"], int) and data["sanitation_minutes"] >= 0
    assert data["status"] in ("IDLE", "IN_USE")


def assert_freezing_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    assert isinstance(data["load_kg"], int) and data["load_kg"] > 0
    assert isinstance(data["required_hours"], int) and data["required_hours"] >= 4
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    assert data["status"] in ("RESERVED", "IN_PROGRESS", "VERIFIED", "FAILED", "VOIDED")


def assert_packaging_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["line_type"] in ("TRAY", "POUCH")
    assert isinstance(data["rate_units_per_minute"], int) and data["rate_units_per_minute"] > 0
    assert data["supported_film_type"] in ("TRAY_FILM", "POUCH_FILM")


def assert_line_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("batch_id", ""))
    assert is_valid_uuid(data.get("film_lot_id", ""))
    assert isinstance(data["units_planned"], int) and data["units_planned"] > 0
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["reserved_film_m"], int) and data["reserved_film_m"] > 0
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_film_lot(data: dict):
    _assert_common_fields(data)
    assert data["film_type"] in ("TRAY_FILM", "POUCH_FILM")
    assert isinstance(data["rolls_received"], int) and data["rolls_received"] > 0
    assert isinstance(data["meters_per_roll"], int) and data["meters_per_roll"] > 0
    assert data["status"] in ("AVAILABLE", "QUARANTINED")


def assert_ccp_check(data: dict):
    """Append-only check record (PRD §2.5): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only check must not carry updated_at"
    assert "version" not in data, "append-only check must not carry version"
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["check_type"] in ("METAL_DETECTOR", "XRAY")
    assert isinstance(data["test_piece_detected"], bool)
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    assert is_iso8601_timestamp(data.get("performed_at", ""))


def assert_storage_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["slot_code"], str) and data["slot_code"]
    assert data["zone"] in ("FREEZER_A", "FREEZER_B", "DEEP_FREEZE")
    assert data["temperature_class"] in ("STANDARD", "DEEP")
    assert isinstance(data["capacity_cases"], int) and data["capacity_cases"] > 0
    assert isinstance(data["occupied_cases"], int) and data["occupied_cases"] >= 0


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["pack_format"] in ("RETAIL", "FOODSERVICE")
    assert isinstance(data["cases_produced"], int) and data["cases_produced"] > 0
    assert isinstance(data["valid_complaint_count"], int) and data["valid_complaint_count"] >= 0
    assert data["release_status"] in (
        "QA_PENDING", "RELEASED", "REJECTED", "QUARANTINED", "RECALLED", "DEPLETED",
    )


def assert_complaint(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["complaint_type"] in ("FREEZER_BURN", "TEXTURE", "FOREIGN_MATERIAL", "OFF_ODOR")
    assert isinstance(data["units_affected"], int) and data["units_affected"] > 0
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert data["status"] in ("OPEN", "UNDER_INVESTIGATION", "RESOLVED_VALID", "RESOLVED_INVALID")


def assert_film_conservation(lot: dict):
    """PRD §3.5: reserved + consumed + available == received at every moment."""
    total = lot["meters_reserved"] + lot["meters_consumed"] + lot["meters_available"]
    assert total == lot["meters_received"], (
        f"film conservation violated: {lot['meters_reserved']} + {lot['meters_consumed']} "
        f"+ {lot['meters_available']} != {lot['meters_received']}"
    )


def assert_storage_invariant(slot: dict):
    """PRD §3.7: occupied_cases never exceeds capacity; occupancy is the sum of stored lots."""
    assert 0 <= slot["occupied_cases"] <= slot["capacity_cases"], (
        f"occupied_cases {slot['occupied_cases']} outside [0, {slot['capacity_cases']}]"
    )
