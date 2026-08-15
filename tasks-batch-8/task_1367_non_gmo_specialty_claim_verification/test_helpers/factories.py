"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CLAIM_CODE": "NGMO",
    "STANDARD_NAME": "Non-GMO",
    "INGREDIENT_THRESHOLD_PCT": 0.9,
    "EXEMPTION_MAX_WEIGHT_PCT": 0.5,
    "BRAND_NAME": "Test Brand",
    "CONTACT_EMAIL": "brand@example.com",
    "PRODUCT_NAME": "Test Product",
    "GTIN": "G-TEST",
    "ANNUAL_VOLUME_UNITS": 100,
    "INGREDIENT_NAME": "Soy",
    "CROP_TYPE": "HIGH_RISK",
    "DECLARED_WEIGHT_PCT": 100.00,
    "SUPPLIER_NAME": "Supplier Co",
    "AFFIDAVIT_VALID_FROM": "2026-01-01T00:00:00Z",
    "AFFIDAVIT_VALID_UNTIL": "2028-01-01T00:00:00Z",
    "RISK_POINT": "INGREDIENT_INTAKE",
    "FACILITY_NAME": "Facility One",
    "AUDITOR_ID": "aud-1",
    "SCHEDULED_DATE": "2026-08-05T00:00:00Z",
    "CASE_SOURCE": "CONSUMER_COMPLAINT",
    "CASE_DESCRIPTION": "allegation details",
}


def create_claim_standard_payload(**overrides) -> dict:
    defaults = {
        "claim_code": DEFAULTS["CLAIM_CODE"],
        "name": DEFAULTS["STANDARD_NAME"],
        "ingredient_threshold_pct": DEFAULTS["INGREDIENT_THRESHOLD_PCT"],
        "exemption_max_weight_pct": DEFAULTS["EXEMPTION_MAX_WEIGHT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_brand_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BRAND_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(brand_id: str, standard_id: str, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "standard_id": standard_id,
        "name": DEFAULTS["PRODUCT_NAME"],
        "gtin": DEFAULTS["GTIN"],
        "annual_volume_units": DEFAULTS["ANNUAL_VOLUME_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "name": DEFAULTS["INGREDIENT_NAME"],
        "crop_type": DEFAULTS["CROP_TYPE"],
        "declared_weight_pct": DEFAULTS["DECLARED_WEIGHT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_affidavit_payload(ingredient_id: str, **overrides) -> dict:
    defaults = {
        "ingredient_id": ingredient_id,
        "supplier_name": DEFAULTS["SUPPLIER_NAME"],
        "valid_from": DEFAULTS["AFFIDAVIT_VALID_FROM"],
        "valid_until": DEFAULTS["AFFIDAVIT_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_sampling_plan_payload(product_id: str, expected_product_version, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "risk_point": DEFAULTS["RISK_POINT"],
        "expected_product_version": expected_product_version,
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(sampling_plan_id: str, ingredient_id: str, **overrides) -> dict:
    defaults = {
        "sampling_plan_id": sampling_plan_id,
        "ingredient_id": ingredient_id,
    }
    defaults.update(overrides)
    return defaults


def create_record_result_payload(**overrides) -> dict:
    defaults = {"result_gmo_pct": 0.10}
    defaults.update(overrides)
    return defaults


def create_facility_audit_payload(brand_id: str, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "facility_name": DEFAULTS["FACILITY_NAME"],
        "auditor_id": DEFAULTS["AUDITOR_ID"],
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_report_payload(**overrides) -> dict:
    defaults = {
        "lots": [{"lot_code": "L1", "input_qty": 200, "recovered_qty": 190}],
    }
    defaults.update(overrides)
    return defaults


def create_enforcement_case_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "source": DEFAULTS["CASE_SOURCE"],
        "description": DEFAULTS["CASE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults
