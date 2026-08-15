"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Foods Inc",
    "CONTACT_EMAIL": "ops@test-foods.example",
    "SCHEME": "KOSHER",
    "FACILITY_NAME": "Main Plant",
    "FACILITY_ADDRESS": "1 Industrial Way",
    "DESIGNATION": "LINE-1",
    "INGREDIENT_NAME": "Citric Acid",
    "MANUFACTURER": "Acme Ingredients",
    "SOURCE_CATEGORY": "PLANT",
    "BRAND": "TestBrand",
    "PRODUCT_NAME": "Test Product",
    "VISIT_START": "2026-08-02T09:00:00Z",
    "VISIT_END": "2026-08-02T12:00:00Z",
    "INSPECTOR": "sup-1",
    "TERM_START": "2026-04-01",
    "PER_PRODUCT_FEE_CENTS": 73000,
    "BILLING_CYCLE": "ANNIVERSARY",
    "FINDING_DESCRIPTION": "observation",
    "REMEDIATION_DEADLINE": "2026-12-31T00:00:00Z",
    "CHANGE_SUMMARY": "supplier change",
    "HOLIDAY_CODE": "PASSOVER",
    "WINDOW_START": "2026-09-20T00:00:00Z",
    "WINDOW_END": "2026-09-30T00:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "certification_scheme": DEFAULTS["SCHEME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "name": DEFAULTS["FACILITY_NAME"],
        "address": DEFAULTS["FACILITY_ADDRESS"],
        "facility_role": "OWNED",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_line_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "designation": DEFAULTS["DESIGNATION"],
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "name": DEFAULTS["INGREDIENT_NAME"],
        "manufacturer": DEFAULTS["MANUFACTURER"],
        "source_category": DEFAULTS["SOURCE_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(client_id, ingredient_ids=None, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "brand": DEFAULTS["BRAND"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "ingredient_ids": list(ingredient_ids or []),
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "visit_type": "ROUTINE",
        "inspector_user_id": DEFAULTS["INSPECTOR"],
        "scheduled_start": DEFAULTS["VISIT_START"],
        "scheduled_end": DEFAULTS["VISIT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "severity": "MINOR",
        "description": DEFAULTS["FINDING_DESCRIPTION"],
        "remediation_deadline": DEFAULTS["REMEDIATION_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(client_id, expected_client_version, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "scheme": DEFAULTS["SCHEME"],
        "billing_cycle": DEFAULTS["BILLING_CYCLE"],
        "term_start_date": DEFAULTS["TERM_START"],
        "per_product_fee_cents": DEFAULTS["PER_PRODUCT_FEE_CENTS"],
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(client_id, invoice_type, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "invoice_type": invoice_type,
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(client_id, facility_ids, product_ids,
                               **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "scheme": DEFAULTS["SCHEME"],
        "term_type": "ANNUAL",
        "facility_ids": list(facility_ids),
        "product_ids": list(product_ids),
    }
    defaults.update(overrides)
    return defaults


def create_holiday_window_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "holiday_code": DEFAULTS["HOLIDAY_CODE"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults
