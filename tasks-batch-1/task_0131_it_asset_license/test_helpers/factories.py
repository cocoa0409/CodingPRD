"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the client-supplied input fields for a create
(or action) call. Optional fields with PRD-declared defaults are omitted unless
overridden, so tests can exercise the default-application behavior.
"""

DEFAULTS = {
    "VENDOR_NAME": "Acme Supplier",
    "SUPPORT_EMAIL": "support@example.com",
    "EMPLOYEE_NAME": "Test Employee",
    "DEPARTMENT": "ENG",
    "PRODUCT_NAME": "EditorPro",
    "TERM_START": "2025-01-01T00:00:00.000Z",
    "TERM_END": "2025-12-31T00:00:00.000Z",
    "IN_SERVICE_DATE": "2025-01-01T00:00:00.000Z",
    "PURCHASE_COST_CENTS": 100000,
    "UNIT_PRICE_CENTS": 1000,
}


def create_vendor_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["VENDOR_NAME"],
        "vendor_type": "HARDWARE",
        "support_email": DEFAULTS["SUPPORT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_employee_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["EMPLOYEE_NAME"],
        "email": "employee@example.com",
        "department": DEFAULTS["DEPARTMENT"],
    }
    payload.update(overrides)
    return payload


def create_software_product_payload(**overrides) -> dict:
    payload = {
        "vendor_id": None,
        "name": DEFAULTS["PRODUCT_NAME"],
        "license_model": "PER_SEAT",
    }
    payload.update(overrides)
    return payload


def create_entitlement_payload(**overrides) -> dict:
    payload = {
        "software_product_id": None,
        "vendor_id": None,
        "entitled_units": 5,
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
    }
    payload.update(overrides)
    return payload


def create_hardware_payload(**overrides) -> dict:
    payload = {
        "vendor_id": None,
        "asset_tag": "TAG-001",
        "category": "LAPTOP",
        "purchase_cost_cents": DEFAULTS["PURCHASE_COST_CENTS"],
        "in_service_date": DEFAULTS["IN_SERVICE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_coverage_payload(**overrides) -> dict:
    payload = {
        "hardware_asset_id": None,
        "vendor_id": None,
        "coverage_type": "WARRANTY",
        "coverage_start": DEFAULTS["TERM_START"],
        "coverage_end": DEFAULTS["TERM_END"],
    }
    payload.update(overrides)
    return payload


def create_installation_payload(**overrides) -> dict:
    payload = {
        "software_product_id": None,
        "hardware_asset_id": None,
        "license_entitlement_id": None,
        "expected_entitlement_version": None,
    }
    payload.update(overrides)
    return payload


def create_checkout_payload(**overrides) -> dict:
    payload = {
        "employee_id": None,
        "checkout_at": "2025-02-01T00:00:00.000Z",
        "expected_return_at": "2025-02-10T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_disposal_request_payload(**overrides) -> dict:
    payload = {
        "hardware_asset_id": None,
        "reason": "END_OF_LIFE",
    }
    payload.update(overrides)
    return payload


def create_renewal_order_payload(**overrides) -> dict:
    payload = {
        "target_type": "ENTITLEMENT",
        "extend_months": 6,
    }
    payload.update(overrides)
    return payload


def create_true_up_payload(**overrides) -> dict:
    payload = {
        "software_product_id": None,
        "variant": "LIVE",
    }
    payload.update(overrides)
    return payload
