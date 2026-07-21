"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BUSINESS_NAME": "Test Trade Co",
    "CONTACT_EMAIL": "trade@example.com",
    "CUSTOMER_NAME": "Test Customer",
    "SKU_BASE": "F-TEST",
    "CATEGORY": "SCONCE",
    "BASE_PRICE_CENTS": 5000,
    "BASE_WATTAGE": 40,
}


def create_trade_account_payload(**overrides) -> dict:
    defaults = {
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_fixture_model_payload(**overrides) -> dict:
    defaults = {
        "sku_base": DEFAULTS["SKU_BASE"],
        "category": DEFAULTS["CATEGORY"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "base_wattage": DEFAULTS["BASE_WATTAGE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {"customer_name": DEFAULTS["CUSTOMER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    # fixture_model_id must be supplied via overrides.
    defaults = {"quantity": 1}
    defaults.update(overrides)
    return defaults


def create_installer_payload(**overrides) -> dict:
    defaults = {"name": "Test Installer", "service_area": "NORTH"}
    defaults.update(overrides)
    return defaults


def create_delivery_truck_payload(**overrides) -> dict:
    defaults = {"name": "Test Truck"}
    defaults.update(overrides)
    return defaults


def create_rebate_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Rebate",
        "rebate_rate": 0.075,
        "wattage_ceiling": 100,
        "budget_total_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(**overrides) -> dict:
    # order_id, order_line_id, supplier_lead_days supplied via overrides.
    defaults = {"supplier_lead_days": 30}
    defaults.update(overrides)
    return defaults


def create_design_consult_payload(**overrides) -> dict:
    # trade_account_id supplied via overrides.
    defaults = {"room_type": "KITCHEN"}
    defaults.update(overrides)
    return defaults


def create_delivery_job_payload(**overrides) -> dict:
    # order_id, delivery_truck_id, window_start, window_end supplied via overrides.
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_install_referral_payload(**overrides) -> dict:
    # order_id, installer_id, delivery_job_id supplied via overrides.
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_return_request_payload(**overrides) -> dict:
    # order_id, order_line_id, reason supplied via overrides.
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_rebate_claim_payload(**overrides) -> dict:
    # order_id, rebate_program_id supplied via overrides.
    defaults = {}
    defaults.update(overrides)
    return defaults
