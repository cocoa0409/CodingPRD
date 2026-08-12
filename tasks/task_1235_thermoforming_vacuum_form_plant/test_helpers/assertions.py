"""Entity assertions and domain invariant checkers.

Structure follows PRD §2.4 (common system fields; scrap records and
cleanliness certificates carry only id + created_at) and §3 (per-resource
fields and status vocabularies).
"""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationStatus,
    AllocationSourceType,
    CertSubjectType,
    CleanlinessGrade,
    FormingRunStatus,
    InspectionStatus,
    InspectionType,
    MaterialLotStatus,
    PackagingSpecStatus,
    RegrindBatchStatus,
    ResourceType,
    ScrapRecordStatus,
    SpecType,
    OrderQualityStatus,
    OrderScheduleStatus,
    TaskStatus,
    TaskType,
    ToolStatus,
    ToolType,
)

_RESINS = ["PETG", "HIPS", "ABS", "PP", "PC"]
_GRADES = [g.value for g in CleanlinessGrade]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """PRD §2.4: 'Both `updated_at` and `version` are absent from these two
    resources' (scrap records and cleanliness certificates)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def _assert_mass(value, name):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), \
        f"{name} must be numeric, got {value!r}"


def assert_lot_mass_invariant(data: dict):
    """PRD §3.1: available_kg == quantity_kg - allocated_kg - consumed_kg."""
    assert data["available_kg"] == pytest.approx(
        data["quantity_kg"] - data["allocated_kg"] - data["consumed_kg"], abs=1e-9
    ), f"lot mass invariant violated: {data}"


def assert_batch_mass_invariant(data: dict):
    """PRD §3.2: available_kg == accumulated_kg - reserved_kg - consumed_kg."""
    assert data["available_kg"] == pytest.approx(
        data["accumulated_kg"] - data["reserved_kg"] - data["consumed_kg"], abs=1e-9
    ), f"batch mass invariant violated: {data}"


def assert_shot_conservation(order: dict, completed_runs: list):
    """PRD §3.6: shots_completed + shots_scrapped equals the sum of
    shots_completed over the order's COMPLETED forming runs, integer-exact."""
    run_total = sum(r["shots_completed"] for r in completed_runs)
    assert order["shots_completed"] + order["shots_scrapped"] == run_total, (
        f"shot conservation violated: {order['shots_completed']} + "
        f"{order['shots_scrapped']} != {run_total}"
    )


def assert_material_lot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in MaterialLotStatus]
    assert data["resin_type"] in _RESINS
    assert data["cleanliness_grade_required"] in _GRADES
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    for field in ("gauge_mm", "quantity_kg", "unit_cost_per_kg",
                  "allocated_kg", "consumed_kg", "available_kg"):
        _assert_mass(data[field], field)
    assert_lot_mass_invariant(data)


def assert_regrind_batch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RegrindBatchStatus]
    assert data["resin_type"] in _RESINS
    assert data["source_grade"] in _GRADES
    assert isinstance(data["batch_code"], str) and data["batch_code"]
    for field in ("target_kg", "accumulated_kg", "reserved_kg",
                  "consumed_kg", "available_kg"):
        _assert_mass(data[field], field)
    assert_batch_mass_invariant(data)


def assert_tool(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ToolStatus]
    assert data["tool_type"] in [t.value for t in ToolType]
    assert data["cleanliness_grade"] in _GRADES
    assert isinstance(data["tool_code"], str) and data["tool_code"]
    assert isinstance(data["part_number"], str) and data["part_number"]
    _assert_mass(data["min_gauge_mm"], "min_gauge_mm")
    _assert_mass(data["max_gauge_mm"], "max_gauge_mm")
    _assert_mass(data["prototype_cost"], "prototype_cost")
    assert isinstance(data["shots_used"], int)
    assert isinstance(data["drawing_revision"], int)


def assert_packaging_spec(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in PackagingSpecStatus]
    assert data["spec_type"] in [t.value for t in SpecType]
    assert data["cleanliness_grade"] in _GRADES
    assert isinstance(data["spec_code"], str) and data["spec_code"]
    _assert_mass(data["per_pack_cost"], "per_pack_cost")


def assert_production_order(data: dict):
    _assert_common_fields(data)
    assert data["schedule_status"] in [s.value for s in OrderScheduleStatus]
    assert data["quality_status"] in [s.value for s in OrderQualityStatus]
    assert data["resin_type"] in _RESINS
    assert data["cleanliness_grade"] in _GRADES
    assert isinstance(data["order_code"], str) and data["order_code"]
    assert isinstance(data["ordered_qty"], int) and data["ordered_qty"] > 0
    assert isinstance(data["shots_completed"], int) and data["shots_completed"] >= 0
    assert isinstance(data["shots_scrapped"], int) and data["shots_scrapped"] >= 0
    assert isinstance(data["is_prototype_order"], bool)
    _assert_mass(data["required_gauge_mm"], "required_gauge_mm")
    _assert_mass(data["spec_nominal_wall_mm"], "spec_nominal_wall_mm")
    _assert_mass(data["spec_min_wall_mm"], "spec_min_wall_mm")
    _assert_mass(data["nominal_part_weight_kg"], "nominal_part_weight_kg")
    _assert_mass(data["required_material_kg"], "required_material_kg")


def assert_material_allocation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in AllocationStatus]
    assert data["source_type"] in [s.value for s in AllocationSourceType]
    _assert_mass(data["qty_kg"], "qty_kg")
    assert is_valid_uuid(data.get("production_order_id", ""))


def assert_machine_resource(data: dict):
    _assert_common_fields(data)
    assert data["resource_type"] in [t.value for t in ResourceType]
    assert data["cleanliness_grade"] in _GRADES
    assert isinstance(data["resource_code"], str) and data["resource_code"]
    _assert_mass(data["machine_rate_per_hour"], "machine_rate_per_hour")


def assert_forming_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in FormingRunStatus]
    assert is_valid_uuid(data.get("production_order_id", ""))
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    _assert_mass(data["oven_temp_c"], "oven_temp_c")
    assert isinstance(data["cycle_time_s"], int) and data["cycle_time_s"] > 0
    assert isinstance(data["shots_planned"], int) and data["shots_planned"] > 0


def assert_scrap_record(data: dict):
    _assert_append_only_fields(data)
    assert data["status"] in [s.value for s in ScrapRecordStatus]
    assert data["resin_type"] in _RESINS
    assert is_valid_uuid(data.get("forming_run_id", ""))
    _assert_mass(data["weight_kg"], "weight_kg")


def assert_quality_inspection(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in InspectionStatus]
    assert data["inspection_type"] in [t.value for t in InspectionType]
    assert is_valid_uuid(data.get("production_order_id", ""))
    assert is_valid_uuid(data.get("booth_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["wall_measurements_mm"], list) and data["wall_measurements_mm"]
    _assert_mass(data["min_wall_mm"], "min_wall_mm")
    _assert_mass(data["avg_wall_mm"], "avg_wall_mm")
    _assert_mass(data["deviation_pct"], "deviation_pct")


def assert_assembly_task(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in TaskStatus]
    assert data["task_type"] in [t.value for t in TaskType]
    assert is_valid_uuid(data.get("production_order_id", ""))
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] > 0


def assert_cleanliness_certificate(data: dict):
    _assert_append_only_fields(data)
    assert data["subject_type"] in [s.value for s in CertSubjectType]
    assert data["grade"] in _GRADES
    assert is_valid_uuid(data.get("subject_id", ""))
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert isinstance(data["cert_body"], str) and data["cert_body"]


__all__ = [
    "assert_lot_mass_invariant",
    "assert_batch_mass_invariant",
    "assert_shot_conservation",
    "assert_material_lot",
    "assert_regrind_batch",
    "assert_tool",
    "assert_packaging_spec",
    "assert_production_order",
    "assert_material_allocation",
    "assert_machine_resource",
    "assert_forming_run",
    "assert_scrap_record",
    "assert_quality_inspection",
    "assert_assembly_task",
    "assert_cleanliness_certificate",
]
