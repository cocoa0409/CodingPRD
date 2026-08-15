"""Payload factories — one per entity, input fields only (PRD §4)."""
import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:8].upper()


def unique_model_code(prefix: str = "SRT") -> str:
    return f"{prefix}-{_suffix()}"


def create_retailer_payload(**overrides) -> dict:
    defaults = {
        "retailer_name": "SleepCo",
        "drop_ship_enabled": True,
        "recycling_enrolled": True,
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_credit_adjustment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 5000,
        "reason": "promo",
        "expected_retailer_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": unique_model_code(),
        "quilt_pattern": "DIAMOND",
    }
    defaults.update(overrides)
    return defaults


def create_bom_line_payload(**overrides) -> dict:
    defaults = {
        "component_type": "FOAM_CORE",
        "material_code": f"MAT-{_suffix()}",
        "quantity_per_unit": 2.0,
        "unit_cost_cents": 500,
        "filling_content_code": TEST_DEFAULTS["FILLING_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "cert_type": "FLAMMABILITY_16CFR1633",
        "jurisdiction_state_code": "US",
        "issued_on": TEST_DEFAULTS["CERT_ISSUED_ON"],
        "expires_on": TEST_DEFAULTS["CERT_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_law_label_spec_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "filling_content_codes": [TEST_DEFAULTS["FILLING_CODE"]],
        "required_phrases": [TEST_DEFAULTS["STATUTORY_PHRASE"]],
        "prop65_warning_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_law_label_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "expected_model_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_foam_batch_payload(**overrides) -> dict:
    defaults = {
        "foam_density_class": "STANDARD",
        "poured_mass_kg": TEST_DEFAULTS["FOAM_POURED_KG"],
        "chamber_id": "CH-1",
    }
    defaults.update(overrides)
    return defaults


def create_start_cure_payload(**overrides) -> dict:
    defaults = {"ambient_temp_c": 20}
    defaults.update(overrides)
    return defaults


def create_quilt_run_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "machine_id": "M1",
        "size": "QUEEN",
        "start_at": "2026-08-03T08:00:00Z",
        "end_at": "2026-08-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_production_order_payload(**overrides) -> dict:
    defaults = {
        "model_id": None,
        "retailer_id": None,
        "destination_state_code": "CA",
        "quantity": 1,
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "foam_mass_required_kg": 10,
        "ship_method": "WAREHOUSE",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "unit_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {
        "unit_id": None,
        "retailer_id": None,
        "reason": "COMFORT_EXCHANGE",
    }
    defaults.update(overrides)
    return defaults


def create_inspect_payload(**overrides) -> dict:
    defaults = {"measured_sag_inches": 0.8}
    defaults.update(overrides)
    return defaults


def create_resolve_payload(**overrides) -> dict:
    defaults = {"resolution": "REJECT"}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "unit_id": None,
        "retailer_id": None,
        "claim_type": "WORKMANSHIP",
        "measured_sag_inches": 0.5,
    }
    defaults.update(overrides)
    return defaults


def create_recycling_intake_payload(**overrides) -> dict:
    defaults = {
        "retailer_id": None,
        "declared_weight_kg": 100,
    }
    defaults.update(overrides)
    return defaults


def create_finalize_intake_payload(**overrides) -> dict:
    defaults = {
        "actual_steel_kg": 40,
        "actual_foam_kg": 30,
        "actual_fiber_kg": 20,
        "actual_wood_kg": 10,
    }
    defaults.update(overrides)
    return defaults
