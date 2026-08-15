"""Payload factories — one per creatable entity, input fields only."""
from .constants import DEFAULT_PROPERTY, TEST_DEFAULTS


def create_property_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_PROPERTY)
    defaults.update(overrides)
    return defaults


def create_unit_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "unit_number": TEST_DEFAULTS["UNIT_NUMBER"],
        "square_feet": TEST_DEFAULTS["SQUARE_FEET"],
    }
    defaults.update(overrides)
    return defaults


def create_turn_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "notice_date": TEST_DEFAULTS["NOTICE_DATE"],
        "move_out_date": TEST_DEFAULTS["MOVE_OUT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_scope_item_payload(turn_id, category="REPAIR", **overrides) -> dict:
    defaults = {
        "turn_id": turn_id,
        "category": category,
        "description": f"{category.lower()} work",
        "estimated_cost_cents": TEST_DEFAULTS["ITEM_ESTIMATE"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(name="FixCo", trade="REPAIR", **overrides) -> dict:
    defaults = {"name": name, "trade": trade}
    defaults.update(overrides)
    return defaults


def create_vendor_assignment_payload(scope_item_id, vendor_id,
                                     start_date="2026-08-01",
                                     end_date="2026-08-03",
                                     **overrides) -> dict:
    defaults = {
        "scope_item_id": scope_item_id,
        "vendor_id": vendor_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(result="PASS", **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_replacement_decision_payload(scope_item_id, **overrides) -> dict:
    defaults = {
        "scope_item_id": scope_item_id,
        "repair_estimate_cents": 30000,
        "replace_estimate_cents": 60000,
        "repair_life_years": 2,
        "remaining_life_years": 8,
        "decision": "REPLACE",
    }
    defaults.update(overrides)
    return defaults


def create_lease_commitment_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "applicant_name": TEST_DEFAULTS["APPLICANT_NAME"],
        "committed_delivery_date": "2026-08-10",
    }
    defaults.update(overrides)
    return defaults
