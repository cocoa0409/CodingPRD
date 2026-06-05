"""Payload factories — one per entity, input fields only.

Each factory supplies sensible required-field defaults and accepts **overrides
so a test can control exactly the field under examination.
"""

DEFAULTS = {
    "STATE_CODE": "CA",
    "EXPIRES_ON": "2027-01-01T00:00:00Z",
    "PLANTED_AT": "2026-01-01T00:00:00Z",
    "TESTED_AT": "2026-05-01T00:00:00Z",
    "ADULT_BIRTHDATE": "1990-01-01T00:00:00Z",
}


def create_license_payload(**overrides) -> dict:
    """Required: license_number, license_type, state_code, expires_on.
    Optional: daily_purchase_limit_grams (defaults to 28.5 server-side for RETAIL)."""
    defaults = {
        "license_number": "LIC-DEFAULT",
        "license_type": "RETAIL",
        "state_code": DEFAULTS["STATE_CODE"],
        "expires_on": DEFAULTS["EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_plant_batch_payload(**overrides) -> dict:
    """Required: license_id, lot_tag, strain, plant_count, planted_at."""
    defaults = {
        "license_id": None,
        "lot_tag": "LOT-DEFAULT",
        "strain": "Kush",
        "plant_count": 10,
        "planted_at": DEFAULTS["PLANTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_harvest_payload(**overrides) -> dict:
    """Required: plant_batch_id, harvest_name, wet_weight_grams."""
    defaults = {
        "plant_batch_id": None,
        "harvest_name": "H-DEFAULT",
        "wet_weight_grams": 1000,
    }
    defaults.update(overrides)
    return defaults


def cure_harvest_payload(**overrides) -> dict:
    """Required: dry_weight_grams."""
    defaults = {"dry_weight_grams": 500}
    defaults.update(overrides)
    return defaults


def create_package_payload(**overrides) -> dict:
    """Required: harvest_id, package_tag, product_category, quantity_grams."""
    defaults = {
        "harvest_id": None,
        "package_tag": "PKG-DEFAULT",
        "product_category": "FLOWER",
        "quantity_grams": 100,
    }
    defaults.update(overrides)
    return defaults


def create_lab_result_payload(**overrides) -> dict:
    """Required: package_id, testing_license_id, thc_pct, pesticide_pass, tested_at."""
    defaults = {
        "package_id": None,
        "testing_license_id": None,
        "thc_pct": 18.0,
        "pesticide_pass": True,
        "tested_at": DEFAULTS["TESTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(**overrides) -> dict:
    """Required: origin_license_id, destination_license_id."""
    defaults = {
        "origin_license_id": None,
        "destination_license_id": None,
    }
    defaults.update(overrides)
    return defaults


def manifest_line_payload(**overrides) -> dict:
    """Required: package_id, grams."""
    defaults = {"package_id": None, "grams": 50}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Required: birthdate. Optional: is_medical (default false),
    medical_card_number (default null)."""
    defaults = {"birthdate": DEFAULTS["ADULT_BIRTHDATE"]}
    defaults.update(overrides)
    return defaults


def create_sale_payload(**overrides) -> dict:
    """Required: retail_license_id, customer_id, sale_date."""
    defaults = {
        "retail_license_id": None,
        "customer_id": None,
        "sale_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def sale_line_payload(**overrides) -> dict:
    """Required: package_id, grams."""
    defaults = {"package_id": None, "grams": 5.0}
    defaults.update(overrides)
    return defaults


def reconciliation_count_payload(**overrides) -> dict:
    """Required: package_id, counted_by_user_id, counted_grams, counted_at."""
    defaults = {
        "package_id": None,
        "counted_by_user_id": "audit-1",
        "counted_grams": 100.0,
        "counted_at": "2026-06-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def waste_event_payload(**overrides) -> dict:
    """Required: source_type, reason, destroyed_at.
    Conditional: plant_batch_id/destroyed_plant_count (PLANT_BATCH),
    package_id/destroyed_grams (PACKAGE)."""
    defaults = {
        "source_type": "PACKAGE",
        "reason": "OTHER",
        "destroyed_at": "2026-06-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
