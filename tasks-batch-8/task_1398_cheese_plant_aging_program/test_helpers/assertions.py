"""Entity assertions: shape checks for each resource in the PRD."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_plant(data):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["export_listed"], bool)
    assert isinstance(data["total_aging_capacity_wheels"], int)
    assert data["total_aging_capacity_wheels"] >= 0


def assert_milk_intake(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert isinstance(data["hauler_ticket"], str) and data["hauler_ticket"]
    assert isinstance(data["volume_liters"], (int, float)) and data["volume_liters"] > 0
    assert isinstance(data["fat_pct"], (int, float))
    assert isinstance(data["protein_pct"], (int, float))
    assert isinstance(data["somatic_cell_count"], int)
    assert isinstance(data["antibiotics_detected"], bool)
    assert data["status"] in ["RECEIVED", "ACCEPTED", "REJECTED", "CONSUMED"]
    assert isinstance(data["consumed_liters"], (int, float))


def assert_vat(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["capacity_liters"], int) and data["capacity_liters"] > 0
    assert isinstance(data["cip_clean"], bool)
    assert data["status"] in ["IDLE", "BOOKED", "IN_MAKE", "CLEANING", "DECOMMISSIONED"]


def assert_make_sheet(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("vat_id", ""))
    assert is_valid_uuid(data.get("milk_intake_id", ""))
    assert data["variety"] in ["CHEDDAR", "COLBY", "BRICK", "MUENSTER"]
    assert isinstance(data["liters_committed"], (int, float)) and data["liters_committed"] > 0
    assert is_valid_uuid(data.get("culture_lot_id", ""))
    assert is_valid_uuid(data.get("coagulant_lot_id", ""))
    assert isinstance(data["culture_units_planned"], (int, float))
    assert isinstance(data["coagulant_ml_planned"], (int, float))
    assert isinstance(data["make_steps_completed"], int)
    assert isinstance(data["make_steps_required"], int)
    assert isinstance(data["step_signer_ids"], list)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "CURD_READY", "COMPLETED", "CANCELLED"]


def assert_additive_lot(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert data["kind"] in ["CULTURE", "COAGULANT"]
    assert isinstance(data["supplier_lot_no"], str) and data["supplier_lot_no"]
    assert isinstance(data["quantity_on_hand"], (int, float))
    assert isinstance(data["quantity_initial"], (int, float))
    assert data["status"] in ["QUARANTINE", "RELEASED", "DEPLETED", "EXPIRED", "RECALLED"]


def assert_cheese_batch(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("make_sheet_id", ""))
    assert data["variety"] in ["CHEDDAR", "COLBY", "BRICK", "MUENSTER"]
    assert isinstance(data["green_weight_kg"], (int, float))
    assert isinstance(data["yield_provisional_pct"], (int, float))
    assert isinstance(data["yield_actual_pct"], (int, float))
    assert isinstance(data["wheels_produced"], int) and data["wheels_produced"] >= 1
    assert isinstance(data["wheels_placed"], int)
    assert data["current_grade"] in ["UNGRADED", "GRADE_A", "GRADE_B", "DOWNGRADE", "CONDEMNED"]
    assert data["release_decision"] in ["PENDING", "RELEASED", "REJECTED"]
    assert isinstance(data["min_age_days"], int)
    assert data["status"] in ["GREEN", "AGING", "GRADED", "RELEASED", "ALLOCATED", "CONDEMNED"]


def assert_whey_stream(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("make_sheet_id", ""))
    assert isinstance(data["total_whey_kg"], (int, float))
    assert isinstance(data["valorized_kg"], (int, float))
    assert isinstance(data["disposed_kg"], (int, float))
    assert isinstance(data["valorization_rate_pct"], (int, float))


def assert_aging_room(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["capacity_wheels"], int) and data["capacity_wheels"] > 0
    assert isinstance(data["wheels_present"], int)
    assert isinstance(data["temp_c"], (int, float))
    assert isinstance(data["humidity_pct"], (int, float))
    assert data["posture"] in ["AVAILABLE", "FULL", "DEVIATION"]
    assert data["status"] in ["ACTIVE", "DECOMMISSIONED"]


def assert_aging_unit(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("cheese_batch_id", ""))
    assert is_valid_uuid(data.get("aging_room_id", ""))
    assert isinstance(data["wheel_count"], int) and data["wheel_count"] >= 1
    assert is_iso8601_timestamp(data.get("entered_at", ""))
    assert isinstance(data["age_days"], int) and data["age_days"] >= 0
    assert is_iso8601_timestamp(data.get("last_turned_at", ""))
    assert isinstance(data["turns_due"], bool)
    assert data["status"] in ["IN_ROOM", "MOVED", "REMOVED"]


def assert_grading_event(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("cheese_batch_id", ""))
    assert isinstance(data["grader_user_id"], str) and data["grader_user_id"]
    assert isinstance(data["moisture_pct"], (int, float))
    assert isinstance(data["fat_dry_basis_pct"], (int, float))
    assert isinstance(data["body_score"], int)
    assert isinstance(data["flavor_score"], int)
    assert data["assigned_grade"] in ["GRADE_A", "GRADE_B", "DOWNGRADE", "CONDEMNED"]
    assert is_iso8601_timestamp(data.get("graded_at", ""))


def assert_allocation_order(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("cheese_batch_id", ""))
    assert data["channel"] in ["PRIVATE_LABEL", "BRANDED"]
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["wheels_requested"], int) and data["wheels_requested"] >= 1
    assert isinstance(data["wheels_cut"], int) and data["wheels_cut"] >= 0
    assert isinstance(data["priority"], int)
    assert data["status"] in ["OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED"]


def assert_cut_wrap_run(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("allocation_order_id", ""))
    assert isinstance(data["wheels_in"], int) and data["wheels_in"] >= 1
    assert isinstance(data["finished_case_weight_kg"], (int, float))
    assert isinstance(data["trim_waste_kg"], (int, float))
    assert isinstance(data["input_weight_kg"], (int, float))
    assert isinstance(data["reconciliation_gap_kg"], (int, float))
    assert data["status"] in ["DRAFT", "RECONCILED", "VOIDED"]


def assert_export_certificate(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("cut_wrap_run_id", ""))
    assert isinstance(data["destination_country"], str) and data["destination_country"]
    assert isinstance(data["consignee"], str) and data["consignee"]
    assert data["status"] in ["REQUESTED", "ISSUED", "DENIED", "REVOKED"]
