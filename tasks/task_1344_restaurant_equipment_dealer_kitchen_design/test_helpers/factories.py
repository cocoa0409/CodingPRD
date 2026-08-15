"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "CUSTOMER_LEGAL_NAME": "Test Customer LLC",
    "CUSTOMER_EMAIL": "ops@test.example",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "PROJECT_NAME": "Test Kitchen Build",
    "SITE_ADDRESS": "1 Main St",
    "HEALTH_JURISDICTION": "CITY_HEALTH",
    "LAYOUT_LABEL": "Rev-A",
    "DRAWING_REF": "DWG-001",
    "MODEL_NO": "RANGE-36",
    "QUANTITY": 1,
    "UNIT_PRICE_CENTS": 100_000,
    "LEAD_TIME_DAYS": 7,
    "SHOP_DRAWING_REF": "SD-001",
    "QUOTED_FAB_COST_CENTS": 500_000,
    "TECHNICIAN_NAME": "Factory Tech",
    "DEMO_MINUTES": 30,
    "AGENCY_NAME": "A1 Authorized Service",
    "AGENCY_CAPACITY": 5,
    "PUNCH_DESCRIPTION": "Adjust door hinge",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["CUSTOMER_LEGAL_NAME"],
        "contact_email": DEFAULTS["CUSTOMER_EMAIL"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "project_name": DEFAULTS["PROJECT_NAME"],
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "health_jurisdiction": DEFAULTS["HEALTH_JURISDICTION"],
    }
    defaults.update(overrides)
    return defaults


def create_layout_payload(**overrides) -> dict:
    defaults = {
        "layout_label": DEFAULTS["LAYOUT_LABEL"],
        "drawing_ref": DEFAULTS["DRAWING_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_item_payload(**overrides) -> dict:
    defaults = {
        "model_no": DEFAULTS["MODEL_NO"],
        "item_kind": "STOCK",
        "quantity": DEFAULTS["QUANTITY"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "lead_time_days": DEFAULTS["LEAD_TIME_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_job_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-08-05T08:00:00Z",
        "scheduled_end": "2026-08-05T12:00:00Z",
        "rigging_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_startup_session_payload(equipment_item_id, **overrides) -> dict:
    defaults = {
        "equipment_item_id": equipment_item_id,
        "technician_name": DEFAULTS["TECHNICIAN_NAME"],
        "demo_minutes": DEFAULTS["DEMO_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_service_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_name": DEFAULTS["AGENCY_NAME"],
        "covered_jurisdictions": ["CITY_HEALTH"],
        "capacity": DEFAULTS["AGENCY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_punch_list_item_payload(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["PUNCH_DESCRIPTION"],
        "severity": "COSMETIC",
    }
    defaults.update(overrides)
    return defaults
