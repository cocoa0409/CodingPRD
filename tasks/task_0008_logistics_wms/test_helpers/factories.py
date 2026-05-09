"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["WAREHOUSE_NAME"],
        "dock_position_x": TEST_DEFAULTS["DOCK_X"],
        "dock_position_y": TEST_DEFAULTS["DOCK_Y"],
        # putaway_strategy intentionally optional; defaults to DISTANCE_OPTIMIZED on server
    }
    defaults.update(overrides)
    return defaults


def create_bin_payload(**overrides) -> dict:
    defaults = {
        "bin_code": "BIN1",
        "zone": "AMBIENT",
        "position_x": 1,
        "position_y": 0,
        "capacity_volume_cm3": TEST_DEFAULTS["DEFAULT_BIN_CAPACITY_VOLUME_CM3"],
        "capacity_weight_g": TEST_DEFAULTS["DEFAULT_BIN_CAPACITY_WEIGHT_G"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_code": "LOT1",
        "sku": TEST_DEFAULTS["DEFAULT_SKU"],
        "category": "AMBIENT",
        "unit_weight_g": TEST_DEFAULTS["DEFAULT_UNIT_WEIGHT_G"],
        "unit_volume_cm3": TEST_DEFAULTS["DEFAULT_UNIT_VOLUME_CM3"],
        "unit_value_cents": TEST_DEFAULTS["DEFAULT_UNIT_VALUE_CENTS"],
        "manufacture_date": TEST_DEFAULTS["DEFAULT_MANUFACTURE_DATE"],
        "expiry_date": TEST_DEFAULTS["DEFAULT_EXPIRY_DATE"],
        "supplier_lot_ref": TEST_DEFAULTS["DEFAULT_SUPPLIER_LOT_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_inbound_shipment_payload(lot_id: str, declared_units: int = 10,
                                    asn_number: str = "ASN1", **overrides) -> dict:
    defaults = {
        "asn_number": asn_number,
        "supplier_name": TEST_DEFAULTS["DEFAULT_SUPPLIER_NAME"],
        "declared_total_units": declared_units,
        "lines": [{"lot_id": lot_id, "declared_units": declared_units}],
    }
    defaults.update(overrides)
    return defaults


def create_inbound_shipment_multiline_payload(lines: list, asn_number: str = "ASN1",
                                              declared_total_units: int = None,
                                              **overrides) -> dict:
    """`lines` is a list of {lot_id, declared_units} dicts.
    `declared_total_units` may be set explicitly to test ASN match; if None, uses sum.
    """
    if declared_total_units is None:
        declared_total_units = sum(line["declared_units"] for line in lines)
    defaults = {
        "asn_number": asn_number,
        "supplier_name": TEST_DEFAULTS["DEFAULT_SUPPLIER_NAME"],
        "declared_total_units": declared_total_units,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_complete_inspection_payload(lot_id: str, received_units: int,
                                       inspection_defect_count: int = 0,
                                       extra_lines: list = None) -> dict:
    """Build the request body for /complete_inspection.
    `extra_lines` may be a list of additional {lot_id, received_units} dicts.
    """
    lines = [{"lot_id": lot_id, "received_units": received_units}]
    if extra_lines:
        lines.extend(extra_lines)
    return {
        "inspection_defect_count": inspection_defect_count,
        "lines": lines,
    }


def create_order_payload(requested_lines: list, order_number: str = "ORD1",
                         customer_name: str = "Alice", carrier: str = "UPS",
                         pick_strategy: str = None, **overrides) -> dict:
    """`requested_lines` is a list of {sku, qty_units} dicts."""
    defaults = {
        "order_number": order_number,
        "customer_name": customer_name,
        "requested_lines": requested_lines,
        "carrier": carrier,
    }
    if pick_strategy is not None:
        defaults["pick_strategy"] = pick_strategy
    defaults.update(overrides)
    return defaults


def create_wave_payload(order_ids: list, wave_code: str = "WAVE1",
                       strategy: str = "BATCH", **overrides) -> dict:
    defaults = {
        "wave_code": wave_code,
        "strategy": strategy,
        "order_ids": order_ids,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_count_payload(bin_id: str, lot_id: str, **overrides) -> dict:
    defaults = {
        "bin_id": bin_id,
        "lot_id": lot_id,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(recall_reason: str = "SAFETY_ISSUE", **overrides) -> dict:
    defaults = {"recall_reason": recall_reason}
    defaults.update(overrides)
    return defaults


def create_clock_advance_payload(warehouse_id: str, new_time: str) -> dict:
    return {"warehouse_id": warehouse_id, "new_time": new_time}


def create_pack_payload(allow_partial: bool = None) -> dict:
    if allow_partial is None:
        return {}
    return {"allow_partial": allow_partial}


def create_pick_complete_payload(picked_units: int) -> dict:
    return {"picked_units": picked_units}


def create_submit_count_payload(counted_qty: int) -> dict:
    return {"counted_qty": counted_qty}
