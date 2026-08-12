"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):05d}"


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Dealer",
        "dealer_code": _seq("DLR"),
        "price_level": "L3",
        "credit_limit_cents": TEST_DEFAULTS["DEALER_CREDIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def update_dealer_payload(**overrides) -> dict:
    return dict(overrides)


def create_door_style_payload(**overrides) -> dict:
    defaults = {
        "style_code": _seq("DS"),
        "name": "Test Style",
        "construction": "SHAKER",
        "base_list_price_cents": TEST_DEFAULTS["DOOR_UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_finish_spec_payload(**overrides) -> dict:
    defaults = {
        "finish_code": _seq("FS"),
        "color_name": "Natural",
        "sheen": "MATTE",
        "upcharge_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {
        "sku": _seq("SKU"),
        "description": "Plywood sheet",
        "kind": "SHEET_GOODS",
        "sheet_width_in": TEST_DEFAULTS["SHEET_WIDTH_IN"],
        "sheet_height_in": TEST_DEFAULTS["SHEET_HEIGHT_IN"],
        "on_hand_qty": 100,
    }
    defaults.update(overrides)
    return defaults


def create_box_line_payload(finish_id: str, **overrides) -> dict:
    defaults = {
        "line_type": "BOX",
        "finish_id": finish_id,
        "width_in": 24,
        "height_in": 30,
        "depth_in": 12,
        "qty": 1,
        "unit_list_price_cents": TEST_DEFAULTS["BOX_UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_door_line_payload(door_style_id: str, finish_id: str, **overrides) -> dict:
    defaults = {
        "line_type": "DOOR",
        "door_style_id": door_style_id,
        "finish_id": finish_id,
        "width_in": 15,
        "height_in": 30,
        "depth_in": 1,
        "qty": 1,
        "unit_list_price_cents": TEST_DEFAULTS["DOOR_UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_modification_payload(**overrides) -> dict:
    defaults = {
        "mod_code": "TOE_KICK_NOTCH",
        "new_dimension_in": 4,
    }
    defaults.update(overrides)
    return defaults


def create_finish_batch_payload(finish_id: str, **overrides) -> dict:
    defaults = {
        "finish_id": finish_id,
        "sheen_lot_no": _seq("LOT"),
        "capacity_doors": TEST_DEFAULTS["BATCH_CAPACITY_DOORS"],
    }
    defaults.update(overrides)
    return defaults


def create_nesting_station_payload(**overrides) -> dict:
    defaults = {
        "station_code": _seq("ST"),
        "changeover_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_nesting_run_payload(station_id: str, sheet_component_id: str, door_line_ids, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "sheet_component_id": sheet_component_id,
        "door_line_ids": list(door_line_ids),
        "scheduled_date": "2026-05-02",
        "start_minute": 60,
        "end_minute": 240,
    }
    defaults.update(overrides)
    return defaults


def create_assembly_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": _seq("AL"),
        "capacity_minutes_per_day": TEST_DEFAULTS["LINE_CAPACITY_MINUTES"],
        "standard_minutes_per_box": TEST_DEFAULTS["MINUTES_PER_BOX"],
        "setup_minutes_per_sub_lot": TEST_DEFAULTS["SETUP_MINUTES_PER_SUB_LOT"],
    }
    defaults.update(overrides)
    return defaults


def create_sub_lot_payload(order_line_id: str, assembly_line_id: str, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "assembly_line_id": assembly_line_id,
        "scheduled_date": "2026-05-03",
        "start_minute": 60,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_claim_payload(original_order_line_id: str, **overrides) -> dict:
    defaults = {
        "original_order_line_id": original_order_line_id,
        "claim_type": "FREIGHT_DAMAGE",
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": _seq("RT"),
        "route_date": "2026-05-06",
        "capacity_cu_ft": TEST_DEFAULTS["ROUTE_CAPACITY_CU_FT"],
    }
    defaults.update(overrides)
    return defaults
