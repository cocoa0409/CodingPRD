"""Payload factories — one per entity, input fields only."""
import uuid

DEFAULTS = {
    "SURGEON_NAME": "Dr. Test",
    "SPECIALTY": "ORTHO",
    "ITEM_NAME": "Test item",
    "UNIT_COST_CENTS": 250,
    "PROCEDURE_NAME": "TKA",
    "DURATION_MIN": 60,
    "ROOM": "OR-1",
    "RATIONALE": "clinically justified request",
    "REJECTION_REASON": "insufficient clinical evidence",
}


def _unique_sku() -> str:
    return "SKU-" + uuid.uuid4().hex[:12].upper()


def create_surgeon_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["SURGEON_NAME"],
        "specialty": DEFAULTS["SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_item_payload(**overrides) -> dict:
    defaults = {
        "sku": _unique_sku(),
        "name": DEFAULTS["ITEM_NAME"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_preference_card_payload(**overrides) -> dict:
    defaults = {
        "procedure_name": DEFAULTS["PROCEDURE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_preference_card_line_payload(**overrides) -> dict:
    defaults = {
        "quantity": 1,
        "designation": "OPEN",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-09-05T08:00:00Z",
        "expected_duration_min": DEFAULTS["DURATION_MIN"],
        "room": DEFAULTS["ROOM"],
    }
    defaults.update(overrides)
    return defaults


def create_product_request_payload(**overrides) -> dict:
    defaults = {
        "proposed_item_name": "Valve introducer",
        "proposed_sku": _unique_sku(),
        "estimated_unit_cost_cents": 4000,
        "rationale": DEFAULTS["RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_consignment_count_payload(**overrides) -> dict:
    defaults = {
        "counted_qty": 0,
    }
    defaults.update(overrides)
    return defaults
