"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PRODUCT_MODEL": "Bernina 770",
    "PRODUCT_BRAND": "Bernina",
    "PRODUCT_MSRP": 120000,
    "CUSTOMER_NAME": "Test Customer",
    "CUSTOMER_EMAIL": "customer@example.com",
    "ACQUISITION_COST": 80000,
    "LIST_PRICE": 120000,
    "SALE_PRICE": 100000,
    "DAILY_RATE": 2000,
    "DEPOSIT": 5000,
    "CLASS_TITLE": "Intro to Sewing",
    "CLASS_FEE": 5000,
    "MONTHLY_FEE": 3100,
    "UNIT_PRICE": 80000,
}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "model_name": DEFAULTS["PRODUCT_MODEL"],
        "category": "SEWING_MACHINE",
        "brand": DEFAULTS["PRODUCT_BRAND"],
        "msrp_cents": DEFAULTS["PRODUCT_MSRP"],
        # warranty_months omitted by default (PRD default is 12).
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "serial_number": "SN-DEFAULT",
        "condition": "NEW",
        "acquisition_cost_cents": DEFAULTS["ACQUISITION_COST"],
        "list_price_cents": DEFAULTS["LIST_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(customer_id: str, inventory_item_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "sale_price_cents": DEFAULTS["SALE_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_repair_ticket_payload(customer_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(customer_id: str, inventory_item_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "start_at": "2026-07-02T00:00:00Z",
        "due_at": "2026-07-06T00:00:00Z",
        "daily_rate_cents": DEFAULTS["DAILY_RATE"],
        "deposit_cents": DEFAULTS["DEPOSIT"],
    }
    defaults.update(overrides)
    return defaults


def create_class_session_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["CLASS_TITLE"],
        "machine_type": "SEWING",
        "start_at": "2026-08-01T10:00:00Z",
        "end_at": "2026-08-01T12:00:00Z",
        "capacity": 5,
        "fee_cents": DEFAULTS["CLASS_FEE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plan_tier": "BASIC",
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE"],
        "tune_ups_included": 2,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "quantity": 2,
        "unit_price_cents": DEFAULTS["UNIT_PRICE"],
        "deposit_cents": 20000,
    }
    defaults.update(overrides)
    return defaults
