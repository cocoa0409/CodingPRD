"""Payload factories — one per entity, input fields only (PRD §3 workflows)."""
from .constants import TEST_DEFAULTS


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["CLIENT_NAME"],
        "contact_email": TEST_DEFAULTS["CLIENT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "retailer_name": TEST_DEFAULTS["RETAILER_NAME"],
        "program_name": TEST_DEFAULTS["PROGRAM_NAME"],
        "store_count": TEST_DEFAULTS["STORE_COUNT"],
        "program_revenue_cents": TEST_DEFAULTS["PROGRAM_REVENUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_compliance_rule_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "dimension": TEST_DEFAULTS["RULE_DIMENSION"],
        "limit_value": TEST_DEFAULTS["RULE_LIMIT_VALUE"],
    }
    defaults.update(overrides)
    return defaults


def create_design_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "design_code": TEST_DEFAULTS["DESIGN_CODE"],
        "width_in": TEST_DEFAULTS["WIDTH_IN"],
        "height_in": TEST_DEFAULTS["HEIGHT_IN"],
        "depth_in": TEST_DEFAULTS["DEPTH_IN"],
        "weight_lb": TEST_DEFAULTS["WEIGHT_LB"],
        "material": TEST_DEFAULTS["MATERIAL"],
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(program_id: str, design_id: str,
                                  expected_program_version: int,
                                  **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "design_id": design_id,
        "overage_pct": 0,
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(program_id: str, store_number: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "store_number": store_number,
        "address": f"{store_number} Main St",
    }
    defaults.update(overrides)
    return defaults


def create_kit_payload(production_run_id: str, store_id: str, **overrides) -> dict:
    defaults = {
        "production_run_id": production_run_id,
        "store_id": store_id,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(kit_id: str, **overrides) -> dict:
    defaults = {
        "kit_id": kit_id,
        "ship_window_start": "2026-08-10T00:00:00Z",
        "ship_window_end": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(kit_id: str, **overrides) -> dict:
    defaults = {
        "kit_id": kit_id,
        "reported_by": TEST_DEFAULTS["REPORTED_BY"],
        "replacement_quantity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_field_service_request_payload(store_id: str, program_id: str,
                                         **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "program_id": program_id,
        "issue_type": "ASSEMBLY_HELP",
    }
    defaults.update(overrides)
    return defaults
