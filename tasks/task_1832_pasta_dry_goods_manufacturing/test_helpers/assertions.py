"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only kinds carry only id + created_at: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only resource must not carry updated_at"
    assert "version" not in data, "append-only resource must not carry version"


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_code"], str) and data["contract_code"]
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert data["ingredient_type"] in ("SEMOLINA", "DURUM_SEMOLINA", "RICE_FLOUR")
    assert isinstance(data["base_price_cents_per_kg"], int)
    assert data["reference_index_value"] > 0
    assert data["pricing_method"] in ("INDEX_LAGGED", "SPOT_BLEND")
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)
    assert data["cumulative_delivered_kg"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "EXPIRED")
    assert isinstance(data["created_by_user_id"], str)


def assert_index_reading(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["effective_date"], str)
    assert data["index_value"] > 0


def assert_semolina_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["delivery_date"], str)
    assert data["received_weight_kg"] > 0
    assert data["status"] in ("QUARANTINED", "ACCEPTED", "REJECTED", "DEPLETED")
    assert data["cert_grade"] in ("GRADE_A", "GRADE_B", "GRADE_REJECT")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["created_by_user_id"], str)


def assert_lot_mass_invariant(data: dict):
    """received == remaining + consumed must hold at every step."""
    assert data["received_weight_kg"] == pytest.approx(
        data["remaining_weight_kg"] + data["consumed_kg"]
    ), (
        f"mass drift: received {data['received_weight_kg']} != "
        f"remaining {data['remaining_weight_kg']} + consumed {data['consumed_kg']}"
    )


def assert_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["recipe_name"], str) and data["recipe_name"]
    assert data["brand_type"] in ("BRANDED", "PRIVATE_LABEL")
    assert data["shape_family"] in ("LONG_CUT", "SHORT_CUT", "SPECIALTY")
    assert isinstance(data["gluten_free"], bool)
    assert data["drying_curve"] in ("STANDARD", "HIGH_TEMP", "LOW_TEMP")
    assert data["shelf_life_days"] > 0
    assert data["unit_weight_g"] > 0
    assert data["units_per_case"] > 0
    assert data["case_weight_limit_kg"] > 0
    assert data["cases_per_pallet"] > 0
    assert data["status"] in ("DRAFT", "APPROVED", "RETIRED")
    assert isinstance(data["created_by_user_id"], str)


def assert_recipe_ingredient(data: dict):
    _assert_append_only_fields(data)
    assert data["ingredient_type"] in ("SEMOLINA", "DURUM_SEMOLINA", "RICE_FLOUR")
    assert data["percentage"] > 0


def assert_production_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_name"], str) and data["line_name"]
    assert data["gluten_posture"] in (
        "GLUTEN_EXPOSED", "CLEANING_IN_PROGRESS", "AWAITING_SWAB", "GF_VALIDATED"
    )


def assert_extrusion_die(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["die_code"], str) and data["die_code"]
    assert data["shape_family"] in ("LONG_CUT", "SHORT_CUT", "SPECIALTY")
    assert data["rated_capacity_kg"] > 0
    assert data["extruded_kg"] >= 0
    assert data["status"] in ("AVAILABLE", "MOUNTED", "IN_CLEANING", "RETIRED")


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("semolina_lot_id", ""))
    assert isinstance(data["pinned_recipe_version"], int)
    assert data["planned_input_kg"] > 0
    assert isinstance(data["changeover_minutes"], int)
    assert isinstance(data["gluten_free"], bool)
    assert data["brand_type"] in ("BRANDED", "PRIVATE_LABEL")
    assert data["production_status"] in (
        "SCHEDULED", "MIXING", "EXTRUDING", "DRYING", "PACKAGING", "COMPLETED", "ABORTED"
    )
    assert data["quality_disposition"] in ("PENDING_QA", "RELEASED", "HELD", "REJECTED")


def assert_drying_session(data: dict):
    _assert_common_fields(data)
    assert data["drying_curve"] in ("STANDARD", "HIGH_TEMP", "LOW_TEMP")
    assert data["initial_moisture_pct"] > 0
    assert data["target_moisture_pct"] > 0
    assert isinstance(data["redry_count"], int) and data["redry_count"] >= 0
    assert isinstance(data["required_hours"], int) and data["required_hours"] > 0
    assert data["status"] in ("IN_PROGRESS", "AWAITING_LAB", "CONFIRMED", "FAILED")


def assert_packaging_job(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("CREATED", "LABEL_VERIFIED", "COMPLETED", "BLOCKED", "CANCELLED")
    assert data["actual_yield_kg"] > 0
    for field in ("total_units", "units_per_case", "full_case_count",
                  "partial_case_count", "scrapped_units", "case_count", "pallet_count"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative int, got {data[field]!r}"
        )


def assert_case_plan_invariant(data: dict):
    """total_units == cased units + scrapped units."""
    remainder = data["total_units"] - data["full_case_count"] * data["units_per_case"]
    cased = data["full_case_count"] * data["units_per_case"] + (
        remainder if data["partial_case_count"] == 1 else 0
    )
    assert data["total_units"] == cased + data["scrapped_units"], (
        f"case plan drift: {data['total_units']} != {cased} + {data['scrapped_units']}"
    )
    assert data["case_count"] == data["full_case_count"] + data["partial_case_count"]


def assert_finished_goods_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("packaging_job_id", ""))
    assert is_valid_uuid(data.get("run_id", ""))
    assert data["status"] in ("CREATED", "STORED", "RELEASED", "BLOCKED", "EXPIRED", "REJECTED")
    assert isinstance(data["case_count"], int) and data["case_count"] >= 0
    assert isinstance(data["pallet_count"], int) and data["pallet_count"] >= 0
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 0
    assert isinstance(data["gluten_free"], bool)
    assert data["brand_type"] in ("BRANDED", "PRIVATE_LABEL")


def assert_warehouse_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_name"], str) and data["zone_name"]
    assert data["zone_type"] in ("GLUTEN_FREE", "CONVENTIONAL")
    assert data["capacity_pallets"] > 0
    assert data["pest_posture"] in ("CLEAR", "MONITORING", "QUARANTINED")
    assert isinstance(data["occupied_pallets"], int) and data["occupied_pallets"] >= 0


def assert_pest_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", ""))
    assert data["severity"] in ("NONE", "MINOR", "CRITICAL")
    assert isinstance(data["recorded_by_user_id"], str)
    assert data["status"] in ("RECORDED", "VERIFIED")


def assert_gluten_test(data: dict):
    _assert_common_fields(data)
    assert data["test_type"] in ("LINE_SWAB", "PRODUCT_TEST")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["recorded_by_user_id"], str)
    assert data["status"] in ("RECORDED", "VERIFIED")
