"""Entity assertions and domain invariant checkers for the MES API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """id (UUID), created_at, updated_at (ISO8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert data["product_type"] in ("FINISHED_GOOD", "SUBASSEMBLY", "RAW_MATERIAL")
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["lot_controlled"], bool)


def assert_bom_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["parent_product_id"])
    assert is_valid_uuid(data["component_product_id"])
    assert data["quantity_per"] > 0
    assert 0 <= data["scrap_factor_pct"] < 100


def assert_routing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["routing_code"], str)
    assert data["status"] in ("DRAFT", "RELEASED", "ARCHIVED")
    assert isinstance(data["operation_count"], int) and data["operation_count"] >= 0


def assert_operation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["routing_id"])
    assert is_valid_uuid(data["machine_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] > 0
    assert data["ideal_cycle_time_secs"] > 0
    assert isinstance(data["setup_buffer_secs"], int) and data["setup_buffer_secs"] >= 0


def assert_machine(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_code"], str)
    assert isinstance(data["work_center"], str)
    assert data["status"] in ("AVAILABLE", "RUNNING", "DOWN")
    assert isinstance(data["planned_production_secs"], int) and data["planned_production_secs"] > 0
    for ratio_field in ("oee_availability", "oee_performance", "oee_quality", "oee_overall"):
        assert 0 <= data[ratio_field] <= 1, f"{ratio_field} must be in [0,1]"
    assert isinstance(data["quality_flagged"], bool)


def assert_machine_run_log(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["machine_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["run_time_secs"], int) and data["run_time_secs"] >= 0
    assert isinstance(data["total_units"], int) and data["total_units"] >= 0
    assert isinstance(data["good_units"], int) and 0 <= data["good_units"] <= data["total_units"]


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["routing_id"])
    assert isinstance(data["order_qty"], int) and data["order_qty"] > 0
    assert data["status"] in (
        "PLANNED", "RELEASED", "IN_PROCESS", "COMPLETED", "CLOSED", "CANCELLED"
    )
    for q in ("started_qty", "completed_qty", "scrapped_qty", "wip_qty"):
        assert isinstance(data[q], int), f"{q} must be int"
    assert isinstance(data["material_variance_cents"], int)


def assert_component_demand(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["component_product_id"])
    assert data["required_qty"] >= 0
    assert data["issued_qty"] >= 0
    assert isinstance(data["standard_cost_cents"], int)


def assert_work_order_operation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["operation_id"])
    assert is_valid_uuid(data["machine_id"])
    assert isinstance(data["sequence_no"], int)
    assert data["status"] in ("QUEUED", "IN_PROGRESS", "PAUSED", "COMPLETED", "REWORK")
    assert isinstance(data["units_in"], int) and data["units_in"] >= 0
    assert isinstance(data["good_qty"], int) and data["good_qty"] >= 0
    assert isinstance(data["scrap_qty"], int) and data["scrap_qty"] >= 0


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["lot_code"], str)
    assert data["on_hand_qty"] >= 0
    assert data["issued_qty"] >= 0
    assert data["received_qty"] > 0


def assert_lot_issue(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["component_demand_id"])
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["work_order_operation_id"])
    assert data["issued_qty"] > 0
    assert isinstance(data["reversed"], bool)


def assert_scrap_disposition(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["work_order_operation_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["defect_code"], str)
    assert data["status"] in ("PENDING", "SCRAPPED", "REWORKED")
    assert isinstance(data["scrap_cost_cents"], int) and data["scrap_cost_cents"] >= 0


def assert_traveler_signoff(data: dict):
    """Append-only record: id + created_at only; no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["result"] in ("PASS", "FAIL")
    assert is_valid_uuid(data["work_order_operation_id"])


# ─── Domain invariant checkers ────────────────────────

def assert_lot_conservation(lot: dict):
    """PRD §3.8: on_hand_qty + issued_qty == received_qty held at all times."""
    assert lot["on_hand_qty"] + lot["issued_qty"] == lot["received_qty"], (
        f"Lot conservation violated: {lot['on_hand_qty']} + {lot['issued_qty']} "
        f"!= {lot['received_qty']}"
    )


def assert_wip_conservation(wo: dict):
    """PRD §3.4: wip_qty always equals started_qty - completed_qty - scrapped_qty."""
    assert wo["wip_qty"] == wo["started_qty"] - wo["completed_qty"] - wo["scrapped_qty"], (
        f"WIP conservation violated: wip {wo['wip_qty']} != "
        f"{wo['started_qty']} - {wo['completed_qty']} - {wo['scrapped_qty']}"
    )
