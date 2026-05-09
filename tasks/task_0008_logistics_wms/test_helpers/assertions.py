"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


_ALL_LOT_STATUSES = {"ACTIVE", "NEAR_EXPIRY", "EXPIRED", "QUARANTINED", "RECALLED", "DISPOSED"}
_ALL_BIN_STATUSES = {"ACTIVE", "FROZEN"}
_ALL_INBOUND_SHIPMENT_STATUSES = {"ASN_RECEIVED", "INSPECTING", "PASSED", "FAILED",
                                  "PUTAWAY", "QUARANTINED", "CLOSED"}
_ALL_INBOUND_LINE_STATUSES = {"PENDING_INSPECTION", "INSPECTED_PASS", "INSPECTED_FAIL",
                              "PUTAWAY", "QUARANTINED"}
_ALL_ORDER_STATUSES = {"CREATED", "ALLOCATED", "PICKING", "PICKED", "SHORT_PICKED",
                       "PACKED", "SHIPPED", "CANCELLED"}
_ALL_PICK_TASK_STATUSES = {"CREATED", "PICKING", "PICKED", "SHORT_PICKED", "FAILED", "CANCELLED"}
_ALL_WAVE_STATUSES = {"PLANNED", "RELEASED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
_ALL_CYCLE_COUNT_STATUSES = {"SCHEDULED", "COUNTING", "RECONCILED", "VARIANCE_FOUND",
                             "ADJUSTED", "DISPUTED"}
_ALL_POSTURES = {"OPEN", "RESTRICTED", "FROZEN"}


def _assert_common_fields(data: dict, name: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{name}.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{name}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{name}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{name}.version must be int >= 1, got {data.get('version')!r}"


def assert_warehouse(data: dict):
    _assert_common_fields(data, "Warehouse")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["dock_position_x"], int)
    assert isinstance(data["dock_position_y"], int)
    assert data["putaway_strategy"] in ("DISTANCE_OPTIMIZED", "CAPACITY_OPTIMIZED")
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    assert is_iso8601_timestamp(data["clock_now"])
    assert isinstance(data["shrinkage_value_30d_cents"], int)
    assert isinstance(data["abnormal_event_count_24h"], int) and data["abnormal_event_count_24h"] >= 0
    assert isinstance(data["recall_count_open"], int) and data["recall_count_open"] >= 0
    assert isinstance(data["risk_score"], (int, float)) and data["risk_score"] >= 0
    assert data["risk_score"] <= 1000.00
    assert data["posture"] in _ALL_POSTURES


def assert_bin(data: dict):
    _assert_common_fields(data, "Bin")
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["bin_code"], str) and data["bin_code"]
    assert data["zone"] in ("AMBIENT", "COLD", "HAZMAT", "RETURNS")
    assert isinstance(data["position_x"], int)
    assert isinstance(data["position_y"], int)
    assert isinstance(data["capacity_volume_cm3"], int)
    assert isinstance(data["capacity_weight_g"], int)
    assert isinstance(data["used_volume_cm3"], int) and data["used_volume_cm3"] >= 0
    assert isinstance(data["used_weight_g"], int) and data["used_weight_g"] >= 0
    assert isinstance(data["remaining_volume_cm3"], int)
    assert isinstance(data["remaining_weight_g"], int)
    assert data["remaining_volume_cm3"] == data["capacity_volume_cm3"] - data["used_volume_cm3"]
    assert data["remaining_weight_g"] == data["capacity_weight_g"] - data["used_weight_g"]
    assert data["status"] in _ALL_BIN_STATUSES
    assert isinstance(data["distance_from_dock"], (int, float))


def assert_lot(data: dict):
    _assert_common_fields(data, "Lot")
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("AMBIENT", "COLD", "HAZMAT", "RETURNS")
    assert isinstance(data["unit_weight_g"], int)
    assert isinstance(data["unit_volume_cm3"], int)
    assert isinstance(data["unit_value_cents"], int)
    assert is_iso8601_timestamp(data["manufacture_date"])
    assert is_iso8601_timestamp(data["expiry_date"])
    assert data["status"] in _ALL_LOT_STATUSES


def assert_inbound_shipment(data: dict):
    _assert_common_fields(data, "InboundShipment")
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["asn_number"], str) and data["asn_number"]
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["declared_total_units"], int) and data["declared_total_units"] >= 0
    assert data["status"] in _ALL_INBOUND_SHIPMENT_STATUSES


def assert_inbound_line(data: dict):
    _assert_common_fields(data, "InboundLine")
    assert is_valid_uuid(data["inbound_shipment_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["declared_units"], int) and data["declared_units"] >= 0
    assert data["status"] in _ALL_INBOUND_LINE_STATUSES


def assert_inventory(data: dict):
    _assert_common_fields(data, "Inventory")
    assert is_valid_uuid(data["warehouse_id"])
    assert is_valid_uuid(data["bin_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["qty_units"], int) and data["qty_units"] >= 0
    assert isinstance(data["reserved_units"], int) and data["reserved_units"] >= 0
    assert isinstance(data["available_units"], int)
    assert data["available_units"] == data["qty_units"] - data["reserved_units"]


def assert_order(data: dict):
    _assert_common_fields(data, "Order")
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["order_number"], str) and data["order_number"]
    assert isinstance(data["customer_name"], str)
    assert isinstance(data["requested_lines"], list) and len(data["requested_lines"]) >= 1
    assert data["pick_strategy"] in ("FEFO", "FIFO")
    assert data["carrier"] in ("UPS", "FEDEX", "USPS")
    assert data["status"] in _ALL_ORDER_STATUSES


def assert_pick_task(data: dict):
    _assert_common_fields(data, "PickTask")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["bin_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 0
    assert isinstance(data["picked_units"], int) and data["picked_units"] >= 0
    assert data["status"] in _ALL_PICK_TASK_STATUSES


def assert_wave(data: dict):
    _assert_common_fields(data, "Wave")
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["wave_code"], str) and data["wave_code"]
    assert data["strategy"] in ("BATCH", "ZONE", "ORDER")
    assert isinstance(data["order_ids"], list)
    assert data["status"] in _ALL_WAVE_STATUSES


def assert_cycle_count(data: dict):
    _assert_common_fields(data, "CycleCount")
    assert is_valid_uuid(data["warehouse_id"])
    assert is_valid_uuid(data["bin_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["book_qty"], int) and data["book_qty"] >= 0
    assert data["status"] in _ALL_CYCLE_COUNT_STATUSES


def assert_posture_consistent_with_score(warehouse: dict):
    """PRD §3.1: posture is FROZEN when risk_score > 200, RESTRICTED when > 100 and ≤ 200,
    OPEN otherwise."""
    score = warehouse["risk_score"]
    if score > 200:
        assert warehouse["posture"] == "FROZEN", \
            f"risk_score={score} > 200 should yield posture=FROZEN, got {warehouse['posture']}"
    elif score > 100:
        assert warehouse["posture"] == "RESTRICTED", \
            f"risk_score={score} (in (100, 200]) should yield posture=RESTRICTED, got {warehouse['posture']}"
    else:
        assert warehouse["posture"] == "OPEN", \
            f"risk_score={score} (≤ 100) should yield posture=OPEN, got {warehouse['posture']}"


def assert_inventory_invariant(inv: dict):
    """available_units = qty_units - reserved_units; both nonneg."""
    assert inv["qty_units"] >= 0
    assert inv["reserved_units"] >= 0
    assert inv["reserved_units"] <= inv["qty_units"], \
        f"reserved_units {inv['reserved_units']} should not exceed qty_units {inv['qty_units']}"
    assert inv["available_units"] == inv["qty_units"] - inv["reserved_units"]
