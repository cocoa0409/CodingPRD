"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "APP_FULL_NAME": "Test Applicant",
    "APP_DOB": "1990-01-01",
    "APP_EMAIL": "applicant@x.org",
    "APP_PHONE": "555-0001",
    "DEPT_NAME": "Emergency",
    "DEPT_HEAD": "dh-1",
    "ROLE_NAME": "ED Greeter",
    "ROLE_CATEGORY": "PATIENT_FACING",
    "ROLE_MIN_AGE": 18,
    "SLOTS_NEEDED": 1,
    "DOCUMENT_REF": "doc-1",
    "TRAINING_CODE": "ORIENTATION",
    "TRAINING_RECURRENCE": "ONE_TIME",
    "SHIFT_START": "2026-08-10T08:00:00Z",
    "SHIFT_END": "2026-08-10T12:00:00Z",
    "SHIFT_CAPACITY": 5,
    "ENTRY_MINUTES": 60,
    "ENTRY_CATEGORY": "CLERICAL",
    "ENTRY_DATE": "2026-08-01",
    "CAMPAIGN_NAME": "Scanner Fund",
    "CAMPAIGN_GOAL": 50000,
    "CAMPAIGN_START": "2026-08-01T00:00:00Z",
    "CAMPAIGN_END": "2026-08-05T00:00:00Z",
    "ITEM_SKU": "SKU-1",
    "ITEM_NAME": "Plush Bear",
    "ITEM_PRICE": 1000,
    "ITEM_COST": 300,
    "ITEM_STOCK": 10,
}


def create_application_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["APP_FULL_NAME"],
        "date_of_birth": DEFAULTS["APP_DOB"],
        "email": DEFAULTS["APP_EMAIL"],
        "phone": DEFAULTS["APP_PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(**overrides) -> dict:
    defaults = {
        "volunteer_id": None,
        "clearance_type": "BACKGROUND",
        "document_ref": DEFAULTS["DOCUMENT_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DEPT_NAME"],
        "head_user_id": DEFAULTS["DEPT_HEAD"],
    }
    defaults.update(overrides)
    return defaults


def create_role_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROLE_NAME"],
        "category": DEFAULTS["ROLE_CATEGORY"],
        "minimum_age": DEFAULTS["ROLE_MIN_AGE"],
    }
    defaults.update(overrides)
    return defaults


def create_request_payload(**overrides) -> dict:
    defaults = {
        "department_id": None,
        "role_id": None,
        "slots_needed": DEFAULTS["SLOTS_NEEDED"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(**overrides) -> dict:
    defaults = {"request_id": None, "volunteer_id": None}
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "volunteer_id": None,
        "training_code": DEFAULTS["TRAINING_CODE"],
        "recurrence": DEFAULTS["TRAINING_RECURRENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "department_id": None,
        "role_id": None,
        "start_at": DEFAULTS["SHIFT_START"],
        "end_at": DEFAULTS["SHIFT_END"],
        "capacity": DEFAULTS["SHIFT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {"shift_id": None, "volunteer_id": None}
    defaults.update(overrides)
    return defaults


def create_hour_entry_payload(**overrides) -> dict:
    defaults = {
        "volunteer_id": None,
        "service_date": DEFAULTS["ENTRY_DATE"],
        "minutes": DEFAULTS["ENTRY_MINUTES"],
        "service_category": DEFAULTS["ENTRY_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAMPAIGN_NAME"],
        "goal_cents": DEFAULTS["CAMPAIGN_GOAL"],
        "start_at": DEFAULTS["CAMPAIGN_START"],
        "end_at": DEFAULTS["CAMPAIGN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["ITEM_SKU"],
        "name": DEFAULTS["ITEM_NAME"],
        "unit_price_cents": DEFAULTS["ITEM_PRICE"],
        "unit_cost_cents": DEFAULTS["ITEM_COST"],
        "stock_on_hand": DEFAULTS["ITEM_STOCK"],
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(**overrides) -> dict:
    defaults = {
        "cashier_volunteer_id": None,
        "lines": [],
        "tendered_cents": 0,
    }
    defaults.update(overrides)
    return defaults
