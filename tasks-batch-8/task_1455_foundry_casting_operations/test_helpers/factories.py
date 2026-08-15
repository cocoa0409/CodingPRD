"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import SIMPLE_SPEC, TEST_DEFAULTS


def create_foundry_payload(**overrides) -> dict:
    defaults = {"name": "F1"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(foundry_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "company_name": "Acme",
        "credit_limit_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_pattern_payload(foundry_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "part_number": "PN-1",
        "alloy_shrink_class": "FERROUS",
        "mold_process": "SAND",
        "finish_dimensions_mm": [100.0, 50.0, 25.0],
        "machining_allowance_mm": 8.0,
        "impressions": 1,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(foundry_id: str, customer_id: str, pattern_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "customer_id": customer_id,
        "pattern_id": pattern_id,
        "quantity": 1,
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "machining_allowance_pct": TEST_DEFAULTS["MACHINING_ALLOWANCE_PCT"],
        "warranty_months": TEST_DEFAULTS["WARRANTY_MONTHS"],
        "warranty_budget_cents": TEST_DEFAULTS["WARRANTY_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_furnace_payload(foundry_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "kind": "FURNACE",
        "label": "Cupola-1",
        "daily_tap_capacity_kg": TEST_DEFAULTS["FURNACE_TAP_CAPACITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_molding_line_payload(foundry_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "kind": "MOLDING_LINE",
        "label": "Line-A",
        "daily_minute_capacity": TEST_DEFAULTS["LINE_MINUTE_CAPACITY"],
        "cleanup_buffer_minutes": TEST_DEFAULTS["CLEANUP_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_heat_payload(foundry_id: str, furnace_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "furnace_id": furnace_id,
        "alloy_grade": TEST_DEFAULTS["ALLOY_GRADE"],
        "chemistry_spec": SIMPLE_SPEC,
    }
    defaults.update(overrides)
    return defaults


def virgin_addition(weight_kg: float, composition: dict) -> dict:
    return {"source": "VIRGIN", "weight_kg": weight_kg, "composition": composition}


def return_lot_addition(return_lot_id: str, weight_kg: float) -> dict:
    return {"source": "RETURN_LOT", "return_lot_id": return_lot_id, "weight_kg": weight_kg}


def create_pour_slot_payload(molding_line_id: str, heat_id: str, mold_ids: list,
                             start_at: str, end_at: str, **overrides) -> dict:
    defaults = {
        "molding_line_id": molding_line_id,
        "heat_id": heat_id,
        "mold_ids": mold_ids,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_mold_payload(pattern_id: str, sand_batch_id: str, order_id: str, **overrides) -> dict:
    defaults = {
        "pattern_id": pattern_id,
        "sand_batch_id": sand_batch_id,
        "order_id": order_id,
        "sand_weight_kg": 50,
        "metal_weight_kg": 200,
        "cooling_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(casting_id: str, **overrides) -> dict:
    defaults = {
        "casting_id": casting_id,
        "porosity_grade": 1,
        "defect_type": "NONE",
        "zone": "C",
    }
    defaults.update(overrides)
    return defaults


def create_return_lot_payload(foundry_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "alloy_grade": TEST_DEFAULTS["ALLOY_GRADE"],
        "collected_weight_kg": 500.0,
    }
    defaults.update(overrides)
    return defaults


def create_sand_batch_payload(foundry_id: str, **overrides) -> dict:
    defaults = {
        "foundry_id": foundry_id,
        "virgin_weight_kg": TEST_DEFAULTS["SAND_VIRGIN_KG"],
        "max_loi_pct": TEST_DEFAULTS["MAX_LOI_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "claim_type": "DEFECT",
        "claim_qty": 1,
        "claimed_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults
