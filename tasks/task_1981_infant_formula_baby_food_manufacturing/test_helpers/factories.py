"""Payload factories — one per creatable resource, input fields only (PRD §3).

Formulas require an `ingredients` array of at least two entries whose
percentages sum to 100.000 (PRD §3.3); every formula fixture therefore takes
two ingredient ids.
"""

DEFAULT_NUTRIENT_SPECS = [
    {
        "nutrient_code": "PROTEIN",
        "unit": "g",
        "min_per_100kcal": 1.80,
        "max_per_100kcal": 3.50,
        "target_per_100kcal": 2.50,
    }
]


def create_nutrient_profile_payload(**overrides) -> dict:
    defaults = {
        "profile_code": "INF-0-6M",
        "nutrient_specs": [dict(s) for s in DEFAULT_NUTRIENT_SPECS],
        "regulation_ref": "21 CFR 107.100",
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_system_user_payload(**overrides) -> dict:
    defaults = {
        "username": "user-01",
        "full_name": "Test User One",
        "role": "QA_MANAGER",
        "department": "Quality Assurance",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": "SUP-001",
        "legal_name": "Test Supplier Ltd",
        "ingredient_categories": ["DAIRY_BASE"],
        "audit_frequency_days": 180,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "audit_type": "INITIAL",
        "audit_date": "2026-07-01T00:00:00Z",
        "auditor_name": "Jane Auditor",
        "score": 90.00,
        "findings": [],
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_payload(**overrides) -> dict:
    defaults = {
        "ingredient_code": "WPC-80",
        "ingredient_name": "Whey Protein Concentrate 80%",
        "category": "DAIRY_BASE",
        "pathogen_risk_class": "LOW_RISK",
        "storage_condition": "REFRIGERATED",
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_lot_payload(**overrides) -> dict:
    defaults = {
        "ingredient_id": "",
        "supplier_id": "",
        "lot_number": "LOT-001",
        "quantity_kg": 500.000,
        "received_date": "2026-07-15T00:00:00Z",
        "expiry_date": "2027-07-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(**overrides) -> dict:
    defaults = {
        "formula_code": "IF-START-1",
        "product_name": "InfStart Stage 1",
        "nutrient_profile_id": "",
        "ingredients": [],
        "process_type": "DRY_BLEND",
    }
    defaults.update(overrides)
    return defaults


def create_process_validation_payload(**overrides) -> dict:
    defaults = {
        "formula_id": "",
        "validation_type": "DRY_BLEND_HOMOGENEITY",
        "protocol_version": "PV-2026-001",
        "validation_validity_days": 365,
    }
    defaults.update(overrides)
    return defaults


def passing_test_results() -> list:
    return [
        {
            "test_name": "homogeneity_cv",
            "measured_value": 4.0,
            "acceptance_criteria": "<= 5.0",
            "pass": True,
        }
    ]


def create_production_batch_payload(**overrides) -> dict:
    defaults = {
        "formula_id": "",
        "batch_size_kg": 100.000,
        "production_date": "2026-08-01T00:00:00Z",
        "expected_formula_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_label_submission_payload(**overrides) -> dict:
    defaults = {
        "formula_id": "",
        "submission_type": "NEW_PRODUCT_REGISTRATION",
        "label_text": "Complete nutrition label",
        "claims": [],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    defaults = {
        "complainant_name": "Jane Doe",
        "complainant_contact": "jane@example.com",
        "product_formula_id": "",
        "complaint_type": "QUALITY_DEFECT",
        "severity": "LOW",
        "description": "Product clumping observed",
    }
    defaults.update(overrides)
    return defaults


def create_recall_campaign_payload(**overrides) -> dict:
    defaults = {
        "reason": "PRECAUTIONARY",
        "recall_class": "CLASS_III",
        "scope_description": "Precautionary recall",
    }
    defaults.update(overrides)
    return defaults


def create_recall_scope_payload(**overrides) -> dict:
    defaults = {
        "batch_id": "",
        "withdrawal_level": "RETAIL",
        "quantity_shipped_kg": 100.000,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_plan_payload(**overrides) -> dict:
    defaults = {
        "formula_id": "",
        "total_available_kg": 300.000,
        "allocation_method": "PRO_RATA",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_entry_payload(**overrides) -> dict:
    defaults = {
        "customer_code": "CUST-A",
        "customer_name": "Retailer Alpha",
        "requested_kg": 100.000,
    }
    defaults.update(overrides)
    return defaults
