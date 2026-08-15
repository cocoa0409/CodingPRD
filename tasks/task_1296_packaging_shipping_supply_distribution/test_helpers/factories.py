"""Payload factories — one per creatable resource, input fields only (PRD sections 3 and 4)."""

DEFAULTS = {
    "COMPANY_NAME": "Acme Corp",
    "ACCOUNT_TYPE": "CORPORATE",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "DEFAULT_WAREHOUSE_CODE": "ATL",
    "WAREHOUSE_CODE": "ATL",
    "WAREHOUSE_NAME": "Atlanta DC",
    "WAREHOUSE_ZONE": 2,
    "SHIP_CUTOFF": "15:00",
    "TIMEZONE": "America/New_York",
    "SKU": "BX-100",
    "PRODUCT_NAME": "12x12x12 Box",
    "CATEGORY": "BOXES",
    "BASE_PRICE_CENTS": 1000,
    "UOM": "EACH",
    "CASE_QTY": 1,
    "PALLET_QTY": 500,
    "WEIGHT_LBS_PER_UNIT": 10,
    "DENSITY_PCF": 20,
    "SHIP_ZONE": 5,
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "account_type": DEFAULTS["ACCOUNT_TYPE"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "default_warehouse_code": DEFAULTS["DEFAULT_WAREHOUSE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "category": DEFAULTS["CATEGORY"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "uom": DEFAULTS["UOM"],
        "case_qty": DEFAULTS["CASE_QTY"],
        "pallet_qty": DEFAULTS["PALLET_QTY"],
        "weight_lbs_per_unit": DEFAULTS["WEIGHT_LBS_PER_UNIT"],
        "density_pcf": DEFAULTS["DENSITY_PCF"],
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["WAREHOUSE_CODE"],
        "name": DEFAULTS["WAREHOUSE_NAME"],
        "zone": DEFAULTS["WAREHOUSE_ZONE"],
        "ship_cutoff_time": DEFAULTS["SHIP_CUTOFF"],
        "timezone": DEFAULTS["TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_inventory_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "warehouse_id": None,
        "on_hand_qty": 0,
    }
    defaults.update(overrides)
    return defaults


def create_quantity_break_payload(**overrides) -> dict:
    defaults = {
        "min_qty": 10,
        "unit_price_cents": 900,
        "sort_seq": 1,
        "effective_from": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "account_id": None,
        "ship_zone": DEFAULTS["SHIP_ZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "return_type": "STOCK",
        "reason_code": "CHANGED_MIND",
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_restock_notification_payload(**overrides) -> dict:
    defaults = {
        "account_id": None,
        "product_id": None,
    }
    defaults.update(overrides)
    return defaults
