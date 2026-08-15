"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def brand_owner_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "legal_name": f"Test Brand {i}",
        "fein": f"559{i:06d}"[:9],
        "contact_email": f"ra{i}@brand.example",
    }
    defaults.update(overrides)
    return defaults


def supplier_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "supplier_name": f"Test Supplier {i}",
        "fsma_facility_id": f"FSMA-{i:06d}",
        "country_code": "US",
        "risk_tier": "LOW",
    }
    defaults.update(overrides)
    return defaults


def ingredient_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "aafco_name": f"Test Meal {i}",
        "ingredient_code": f"ING{i:05d}"[:8].upper(),
        "nutrient_matrix": {"CRUDE_PROTEIN": 0.60, "CRUDE_FAT": 0.12, "MOISTURE": 0.08},
        "allergen_class": "NONE",
    }
    defaults.update(overrides)
    return defaults


def pairing_payload(supplier_id: str, ingredient_id: str, **overrides) -> dict:
    i = _n()
    defaults = {
        "supplier_id": supplier_id,
        "ingredient_id": ingredient_id,
        "coa_document_ref": f"COA-{i:05d}",
    }
    defaults.update(overrides)
    return defaults


def formula_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "formula_code": f"F-{i:05d}",
        "product_name": f"Test Product {i}",
        "species": "DOG",
        "life_stage": "ADULT_MAINTENANCE",
        "adequacy_basis": "FORMULATION",
    }
    defaults.update(overrides)
    return defaults


def formula_ingredient_payload(ingredient_id: str, **overrides) -> dict:
    defaults = {"ingredient_id": ingredient_id, "inclusion_pct": 100.0}
    defaults.update(overrides)
    return defaults


def nutrient_profile_payload(**overrides) -> dict:
    """Defaults satisfy the DOG / ADULT_MAINTENANCE AAFCO floors (PRD §3.3)."""
    defaults = {
        "profile_basis": "FORMULATION_CALC",
        "crude_protein_min_pct": 26.0,
        "crude_fat_min_pct": 9.0,
        "crude_fiber_max_pct": 3.0,
        "moisture_max_pct": 10.0,
        "calcium_min_pct": 1.0,
        "phosphorus_min_pct": 0.8,
    }
    defaults.update(overrides)
    return defaults


def trial_protocol_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "protocol_code": f"AAFCO-P-{i:04d}",
        "animal_count": 8,
        "duration_days": 26,
    }
    defaults.update(overrides)
    return defaults


def batch_payload(expected_formula_version: int, **overrides) -> dict:
    defaults = {
        "planned_kg": 500.0,
        "line_id": "LINE-1",
        "scheduled_start": "2026-08-10T08:00:00Z",
        "expected_formula_version": expected_formula_version,
    }
    defaults.update(overrides)
    return defaults


def lot_payload(**overrides) -> dict:
    defaults = {"packaged_units": 100, "best_by_date": "2027-08-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def lab_sample_payload(**overrides) -> dict:
    defaults = {
        "sample_type": "FIRST",
        "measured_protein_pct": 27.0,
        "measured_fat_pct": 12.0,
        "measured_fiber_pct": 2.0,
        "measured_moisture_pct": 9.0,
    }
    defaults.update(overrides)
    return defaults


def state_registration_payload(**overrides) -> dict:
    # tonnage_tier declares the brand's prior-year tonnage in the state
    # (PRD §3.7); below 5 tons pays the base fee.
    defaults = {"state_code": "CA", "label_revision_ref": 1, "tonnage_tier": 3.0}
    defaults.update(overrides)
    return defaults


def complaint_case_payload(brand_owner_id: str, formula_id: str, **overrides) -> dict:
    defaults = {
        "brand_owner_id": brand_owner_id,
        "formula_id": formula_id,
        "severity": "MINOR",
        "category": "PALATABILITY",
    }
    defaults.update(overrides)
    return defaults


def recall_action_payload(formula_id: str, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "scope_batch_ids": [],
        "recall_class": "CLASS_III",
        "reason": "Test recall",
    }
    defaults.update(overrides)
    return defaults
