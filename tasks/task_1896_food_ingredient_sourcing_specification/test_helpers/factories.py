"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import (
    CONTRACT_WINDOW_END,
    CONTRACT_WINDOW_START,
    COA_RECEIVED_AT,
    DECLARATION_VALID_FROM,
    DECLARATION_VALID_UNTIL,
    SPEC_EFFECTIVE_DATE,
)


def create_ingredient_payload(**overrides) -> dict:
    defaults = {
        "ingredient_code": "ENZ-1",
        "name": "Enzyme One",
        "allergen_profile": ["NONE"],
        "requires_dual_source": False,
    }
    defaults.update(overrides)
    return defaults


def create_spec_payload(expected_ingredient_version, **overrides) -> dict:
    defaults = {
        "spec_version_label": "v1",
        "effective_date": SPEC_EFFECTIVE_DATE,
        "version_note": "initial spec version",
        "expected_ingredient_version": expected_ingredient_version,
    }
    defaults.update(overrides)
    return defaults


def create_parameter_payload(**overrides) -> dict:
    defaults = {
        "parameter_name": "moisture",
        "criticality": "MINOR",
        "uom": "percent",
        "target_value": 5,
        "min_value": 0,
        "max_value": 10,
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": "SUP-1",
        "legal_name": "Supplier One",
        "risk_tier": "TIER_A",
        "country_of_operation": "US",
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(**overrides) -> dict:
    defaults = {
        "questionnaire_score": 90,
        "document_pack_complete": True,
    }
    defaults.update(overrides)
    return defaults


def create_approved_source_payload(supplier_id, pinned_spec_id, expected_ingredient_version, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "pinned_spec_id": pinned_spec_id,
        "expected_ingredient_version": expected_ingredient_version,
    }
    defaults.update(overrides)
    return defaults


def create_allergen_declaration_payload(**overrides) -> dict:
    defaults = {
        "declaration_type": "ALLERGEN",
        "payload": {"allergen_tags": ["NONE"]},
        "valid_from": DECLARATION_VALID_FROM,
        "valid_until": DECLARATION_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_coo_declaration_payload(**overrides) -> dict:
    defaults = {
        "declaration_type": "COUNTRY_OF_ORIGIN",
        "payload": {"country_codes": ["US"], "primary_country": "US"},
        "valid_from": DECLARATION_VALID_FROM,
        "valid_until": DECLARATION_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(expected_approved_source_version, **overrides) -> dict:
    defaults = {
        "annual_committed_volume_kg": 10000,
        "index_base_value": 100,
        "index_pass_through_pct": 0.5,
        "window_start": CONTRACT_WINDOW_START,
        "window_end": CONTRACT_WINDOW_END,
        "expected_approved_source_version": expected_approved_source_version,
    }
    defaults.update(overrides)
    return defaults


def create_price_index_payload(**overrides) -> dict:
    defaults = {
        "index_name": "INGREDIENT-SPOT",
        "observed_at": "2026-06-01T00:00:00Z",
        "index_value": 100,
    }
    defaults.update(overrides)
    return defaults


def create_coa_payload(contract_id, measured_values, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "lot_number": "L1",
        "shipped_qty_kg": 100,
        "received_at": COA_RECEIVED_AT,
        "measured_values": measured_values,
    }
    defaults.update(overrides)
    return defaults


def create_substitution_request_payload(from_source_id, to_source_id, **overrides) -> dict:
    defaults = {
        "from_approved_source_id": from_source_id,
        "to_approved_source_id": to_source_id,
        "reason_code": "COST_REDUCTION",
        "formula_unit_cost_sensitivities": [
            {"parameter_name": "moisture", "cost_per_unit_delta": 0.10},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "scheduled_window_start": "2026-08-01T00:00:00Z",
        "scheduled_window_end": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_capa_payload(**overrides) -> dict:
    defaults = {
        "description": "corrective action description",
        "due_date": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
