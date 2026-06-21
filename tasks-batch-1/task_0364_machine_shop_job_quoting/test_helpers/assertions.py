"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact. The InspectionStation assertion omits
updated_at/version because that configuration entity carries only id +
created_at (PRD §2.5).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_quartet(data: dict):
    """id + created_at + updated_at + version, for full first-class resources."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_rfq(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["customer_name"], str) and len(data["customer_name"]) > 0
    assert isinstance(data["customer_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "QUOTED", "CLOSED", "CANCELLED"]
    assert data["incoterm"] in ["EXW", "FOB", "DDP"]
    assert isinstance(data["part_line_count"], int) and data["part_line_count"] >= 0


def assert_part_line(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("rfq_id", "")), "rfq_id must be a valid UUID"
    assert isinstance(data["part_number"], str)
    assert isinstance(data["drawing_rev"], str)
    assert data["material_spec"] in ["AL_6061", "SS_304", "TI_6AL4V", "BRASS_360"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["tolerance_class"] in ["STANDARD", "PRECISION", "CRITICAL"]


def assert_quote(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("rfq_id", "")), "rfq_id must be a valid UUID"
    assert is_valid_uuid(data.get("part_line_id", "")), "part_line_id must be a valid UUID"
    assert data["status"] in ["DRAFT", "PRICED", "APPROVED", "REJECTED"]
    assert isinstance(data["material_unit_cost_cents"], int)
    assert isinstance(data["scrap_allowance_pct"], int)
    assert isinstance(data["extended_cost_cents"], int)
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["quoted_unit_price_cents"], int)


def assert_routing_op(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("quote_id", "")), "quote_id must be a valid UUID"
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert data["machine_class"] in ["MILL_3AX", "MILL_5AX", "LATHE"]
    assert isinstance(data["estimated_cycle_min"], (int, float))
    assert data["status"] in ["PLANNED", "SCHEDULED", "COMPLETED"]


def assert_work_order(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("quote_id", "")), "quote_id must be a valid UUID"
    assert is_valid_uuid(data.get("part_line_id", "")), "part_line_id must be a valid UUID"
    assert isinstance(data["qty_ordered"], int) and data["qty_ordered"] >= 1
    assert isinstance(data["qty_started"], int)
    assert isinstance(data["qty_in_process"], int)
    assert isinstance(data["qty_accepted"], int)
    assert isinstance(data["qty_rework_pending"], int)
    assert isinstance(data["qty_scrapped"], int)
    assert isinstance(data["qty_shipped"], int)
    assert data["status"] in [
        "PLANNED", "RELEASED", "IN_PROCESS", "COMPLETED", "SHIPPED", "CLOSED", "CANCELLED"
    ]
    assert isinstance(data["material_allocated"], bool)
    assert isinstance(data["actual_cost_cents"], int)


def assert_material_lot(data: dict):
    _assert_common_quartet(data)
    assert data["material_spec"] in ["AL_6061", "SS_304", "TI_6AL4V", "BRASS_360"]
    assert isinstance(data["heat_number"], str)
    assert isinstance(data["qty_received"], int) and data["qty_received"] >= 1
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["qty_remaining"], int) and data["qty_remaining"] >= 0
    assert data["status"] in ["AVAILABLE", "DEPLETED"]


def assert_lot_allocation(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a valid UUID"
    assert is_valid_uuid(data.get("material_lot_id", "")), "material_lot_id must be a valid UUID"
    assert isinstance(data["qty_allocated"], int) and data["qty_allocated"] >= 1
    assert data["status"] in ["ACTIVE", "VOIDED"]


def assert_machine_slot(data: dict):
    _assert_common_quartet(data)
    assert data["machine_class"] in ["MILL_3AX", "MILL_5AX", "LATHE"]
    assert isinstance(data["machine_code"], str)
    assert is_valid_uuid(data.get("routing_op_id", "")), "routing_op_id must be a valid UUID"
    assert isinstance(data["start_min"], int)
    assert isinstance(data["end_min"], int) and data["end_min"] > data["start_min"]
    assert data["status"] in ["BOOKED", "RELEASED"]


def assert_inspection(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a valid UUID"
    assert is_valid_uuid(data.get("inspection_station_id", "")), "inspection_station_id must be a valid UUID"
    assert data["mode"] in ["FAI", "IN_PROCESS", "FINAL"]
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert data["status"] in ["OPEN", "DISPOSITIONED"]


def assert_shipment(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a valid UUID"
    assert isinstance(data["qty_shipped"], int) and data["qty_shipped"] >= 1
    assert isinstance(data["on_time"], bool)
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert isinstance(data["late_penalty_cents"], int) and data["late_penalty_cents"] >= 0
    assert data["status"] in ["SHIPPED", "VOIDED"]


def assert_invoice(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("shipment_id", "")), "shipment_id must be a valid UUID"
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a valid UUID"
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["penalty_credit_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["ISSUED", "PAID", "VOIDED"]


def assert_inspection_station(data: dict):
    """Configuration entity: only id + created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["supports_mode"] in ["FAI", "IN_PROCESS", "FINAL", "ALL"]


def assert_material_conservation(lot: dict, active_allocations_qty: int):
    """Invariant: sum(ACTIVE allocations) + qty_remaining == qty_received."""
    assert active_allocations_qty + lot["qty_remaining"] == lot["qty_received"], (
        f"Material units must be conserved: {active_allocations_qty} allocated + "
        f"{lot['qty_remaining']} remaining != {lot['qty_received']} received"
    )
