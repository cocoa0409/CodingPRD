"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable_fields(data: dict):
    """PRD §2.4: mutable resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"


def _assert_event_record_fields(data: dict):
    """PRD §2.4: event records carry ONLY id + created_at among system fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "event records must not carry updated_at"
    assert "version" not in data, "event records must not carry version"


def assert_customer(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_coating_spec(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["color_code"], str) and len(data["color_code"]) > 0
    assert isinstance(data["film_build_min_um"], (int, float))
    assert isinstance(data["film_build_max_um"], (int, float))
    assert isinstance(data["cure_metal_temp_c"], (int, float))
    assert isinstance(data["cure_minutes_at_temp"], int)
    assert isinstance(data["adhesion_class_min"], int)
    assert isinstance(data["impact_joules_min"], (int, float))
    assert isinstance(data["voc_g_per_l"], (int, float))
    assert isinstance(data["area_dm2_per_part"], (int, float))
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_paint_line(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["current_color_code"], str)
    assert isinstance(data["line_speed_fpm"], (int, float))
    assert isinstance(data["hanger_capacity_parts"], int)
    assert data["allocation_policy"] in ("FULL_TO_NEXT_LOT", "PRO_RATA_BY_PARTS")
    assert data["posture"] in ("RUNNING", "CHEM_HOLD")


def assert_cure_oven(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["max_loads"], int) and data["max_loads"] > 0


def assert_pretreatment_stage(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["paint_line_id"], str)
    assert isinstance(data["stage_name"], str) and len(data["stage_name"]) > 0
    assert isinstance(data["sequence_no"], int)
    assert isinstance(data["chemical_family"], str)
    assert isinstance(data["conc_min_gpl"], (int, float))
    assert isinstance(data["conc_max_gpl"], (int, float))
    assert data["status"] in ("IN_RANGE", "OUT_OF_RANGE", "ADJUSTING")


def assert_titration_reading(data: dict):
    _assert_event_record_fields(data)
    assert isinstance(data["stage_id"], str)
    assert isinstance(data["measured_conc_gpl"], (int, float))
    assert isinstance(data["in_range"], bool)


def assert_lot(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["spec_id"], str)
    assert isinstance(data["part_quantity"], int) and data["part_quantity"] > 0
    assert isinstance(data["scrapped_quantity"], int) and data["scrapped_quantity"] >= 0
    assert isinstance(data["passed_quantity"], int) and data["passed_quantity"] >= 0
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert data["status"] in (
        "RECEIVED", "QUEUED", "SCHEDULED", "ON_LINE", "CURING", "CURE_FAILED",
        "QC_PENDING", "QC_HOLD", "STRIPPING", "RELEASED", "SCRAPPED", "CANCELLED",
    )
    assert isinstance(data["base_charge_cents"], int)
    assert isinstance(data["purge_alloc_cents"], int)
    assert isinstance(data["rework_charge_cents"], int)
    assert isinstance(data["total_charge_cents"], int)


def assert_lot_part_accountability(data: dict):
    """PRD §3.6 invariant: part_quantity == passed + scrapped + outstanding, always."""
    total = data["passed_quantity"] + data["scrapped_quantity"] + data["outstanding_quantity"]
    assert total == data["part_quantity"], (
        f"part accountability violated: {data['passed_quantity']} + "
        f"{data['scrapped_quantity']} + {data['outstanding_quantity']} != {data['part_quantity']}"
    )


def assert_run_slot(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["paint_line_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["start_utc"], str)
    assert isinstance(data["end_utc"], str)
    assert isinstance(data["parts_per_hanger"], int) and data["parts_per_hanger"] >= 1
    assert isinstance(data["planned_line_speed_fpm"], (int, float))
    assert isinstance(data["predicted_film_build_um"], (int, float))
    assert isinstance(data["voc_projected_kg"], (int, float))
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "CANCELLED")


def assert_oven_cycle(data: dict):
    _assert_event_record_fields(data)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["oven_id"], str)
    assert isinstance(data["entered_at"], str)
    assert isinstance(data["exited_at"], str)
    assert isinstance(data["min_metal_temp_c"], (int, float))
    assert isinstance(data["minutes_at_or_above_temp"], int)
    assert data["verdict"] in ("PASS", "FAIL")


def assert_quality_test(data: dict):
    _assert_event_record_fields(data)
    assert isinstance(data["lot_id"], str)
    assert data["test_type"] in ("ADHESION", "IMPACT")
    assert isinstance(data["measured_value"], (int, float))
    assert data["verdict"] in ("PASS", "FAIL")


def assert_rework_order(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["parts_to_rework"], int) and data["parts_to_rework"] >= 0
    assert data["status"] in ("DRAFT", "APPROVED", "COMPLETED")


def assert_color_change(data: dict):
    _assert_event_record_fields(data)
    assert isinstance(data["paint_line_id"], str)
    assert isinstance(data["from_color_code"], str)
    assert isinstance(data["to_color_code"], str)
    assert isinstance(data["window_start_utc"], str)
    assert isinstance(data["window_end_utc"], str)
    assert isinstance(data["purge_solvent_liters"], (int, float))
    assert isinstance(data["purge_cost_cents"], int)
    assert isinstance(data["purge_voc_kg"], (int, float))
    assert data["allocation_method"] in ("FULL_TO_NEXT_LOT", "PRO_RATA_BY_PARTS")


def assert_voc_permit(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["cap_kg"], (int, float))
    assert isinstance(data["used_kg"], (int, float))
    assert isinstance(data["reserved_kg"], (int, float))
    assert data["status"] in ("ACTIVE", "EXCEEDED", "CLOSED")


def assert_emission_entry(data: dict):
    _assert_event_record_fields(data)
    assert isinstance(data["permit_id"], str)
    assert data["source_type"] in (
        "PAINT_USAGE_METERED", "PURGE_SOLVENT", "STRIP_SOLVENT", "CLOSEOUT_ADJUSTMENT",
    )
    assert isinstance(data["voc_kg"], (int, float))
    assert data["entry_variant"] in ("METERED", "THEORETICAL", "ADJUSTMENT")
