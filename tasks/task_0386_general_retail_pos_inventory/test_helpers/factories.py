"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STORE_NAME": "Test Store",
    "TAX_RATE_BPS": 0,
    "PRODUCT_NAME": "Test Product",
    "LIST_PRICE_CENTS": 1000,
    "CUSTOMER_NAME": "Test Customer",
}


def create_store_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["STORE_NAME"],
        "code": "STORE1",
        "tax_rate_bps": DEFAULTS["TAX_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "SKU1",
        "barcode": "BARCODE1",
        "name": DEFAULTS["PRODUCT_NAME"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(store_id, product_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "product_id": product_id,
        "reorder_point": 0,
        "reorder_qty": 0,
    }
    defaults.update(overrides)
    return defaults


def create_count_sheet_payload(inventory_item_id, counted_qty, **overrides) -> dict:
    defaults = {"inventory_item_id": inventory_item_id, "counted_qty": counted_qty}
    defaults.update(overrides)
    return defaults


def create_loyalty_account_payload(**overrides) -> dict:
    defaults = {"customer_name": DEFAULTS["CUSTOMER_NAME"], "phone": "555-0000"}
    defaults.update(overrides)
    return defaults


def grant_loyalty_payload(loyalty_account_id, add_points, **overrides) -> dict:
    defaults = {"loyalty_account_id": loyalty_account_id, "add_points": add_points}
    defaults.update(overrides)
    return defaults


def create_promotion_payload(code, kind, value, **overrides) -> dict:
    defaults = {"code": code, "kind": kind, "value": value}
    defaults.update(overrides)
    return defaults


def create_cash_session_payload(store_id, opening_float_cents=0, **overrides) -> dict:
    defaults = {"store_id": store_id, "opening_float_cents": opening_float_cents}
    defaults.update(overrides)
    return defaults


def create_sale_payload(store_id, kind, lines, **overrides) -> dict:
    defaults = {"store_id": store_id, "kind": kind, "lines": lines}
    defaults.update(overrides)
    return defaults


def create_tender_payload(method, amount_cents, expected_sale_version, **overrides) -> dict:
    defaults = {
        "method": method,
        "amount_cents": amount_cents,
        "expected_sale_version": expected_sale_version,
    }
    defaults.update(overrides)
    return defaults


def create_layaway_payload(store_id, product_id, customer_id, quantity, due_date, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "product_id": product_id,
        "customer_id": customer_id,
        "quantity": quantity,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_layaway_payment_payload(amount_cents, expected_layaway_version, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "expected_layaway_version": expected_layaway_version}
    defaults.update(overrides)
    return defaults


def create_transfer_payload(from_store_id, to_store_id, product_id, quantity, **overrides) -> dict:
    defaults = {
        "from_store_id": from_store_id,
        "to_store_id": to_store_id,
        "product_id": product_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def dispatch_transfer_payload(expected_transfer_version, **overrides) -> dict:
    defaults = {"expected_transfer_version": expected_transfer_version}
    defaults.update(overrides)
    return defaults


def receive_transfer_payload(received_qty, **overrides) -> dict:
    defaults = {"received_qty": received_qty}
    defaults.update(overrides)
    return defaults


def reconcile_payload(counted_cash_cents, **overrides) -> dict:
    defaults = {"counted_cash_cents": counted_cash_cents}
    defaults.update(overrides)
    return defaults


def advance_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
