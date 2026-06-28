"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "EMAIL_DOMAIN": "homeowner.example",
    "FULL_NAME": "Test Homeowner",
    "STATE_CODE": "CA",
    "ANNUAL_INCOME_CENTS": 9_000_000,
    "ADDRESS_LINE": "1 Kitchen Way",
    "SCHEDULED_FOR": "2026-04-02T15:00:00Z",
    "LINEAR_FEET": 25,
    "DOOR_COUNT": 18,
    "DOOR_STYLE": "SHAKER",
    "FINISH_CODE": "WOOD_VENEER",
    "SCOPE": "REFACE",
}

_email_counter = [0]


def unique_email() -> str:
    _email_counter[0] += 1
    return f"customer-{_email_counter[0]}@{DEFAULTS['EMAIL_DOMAIN']}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": DEFAULTS["FULL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "address_line": DEFAULTS["ADDRESS_LINE"],
    }
    defaults.update(overrides)
    return defaults


def create_measure_payload(**overrides) -> dict:
    defaults = {"scheduled_for": DEFAULTS["SCHEDULED_FOR"]}
    defaults.update(overrides)
    return defaults


def complete_measure_payload(**overrides) -> dict:
    defaults = {
        "linear_feet": DEFAULTS["LINEAR_FEET"],
        "door_count": DEFAULTS["DOOR_COUNT"],
        "door_style": DEFAULTS["DOOR_STYLE"],
        "finish_code": DEFAULTS["FINISH_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(measure_id, **overrides) -> dict:
    defaults = {"measure_id": measure_id, "scope": DEFAULTS["SCOPE"]}
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {"kind": "HARDWARE", "unit_price_cents": 850, "quantity": 24}
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {"delta_linear_feet": 0, "delta_door_count": 0, "rush": False}
    defaults.update(overrides)
    return defaults


def create_material_order_payload(quote_id, **overrides) -> dict:
    defaults = {"quote_id": quote_id}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Crew",
        "daily_job_capacity": 2,
        "skill_finishes": ["WOOD_VENEER", "LAMINATE"],
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(material_order_id, crew_id, **overrides) -> dict:
    defaults = {
        "material_order_id": material_order_id,
        "crew_id": crew_id,
        "window_start": "2026-05-06T08:00:00Z",
        "window_end": "2026-05-06T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {"description": "drawer misaligned"}
    defaults.update(overrides)
    return defaults


def create_financing_application_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "amount_cents": 2_000_000,
        "term_months": 36,
    }
    defaults.update(overrides)
    return defaults
