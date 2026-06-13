"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STORE_NAME": "Test Store",
    "STATE_CODE": "CA",
    "CURBSIDE_SPACES": 2,
    "PRODUCT_NAME": "Test Product",
    "UNIT_PRICE_CENTS": 1000,
    "VEHICLE_DESCRIPTION": "blue sedan",
    "CUSTOMER_NAME": "Test Customer",
    "CUSTOMER_PHONE": "555-0100",
}

_email_counter = [0]


def unique_email(prefix: str = "cust") -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "phone": DEFAULTS["CUSTOMER_PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["STORE_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "curbside_spaces": DEFAULTS["CURBSIDE_SPACES"],
    }
    defaults.update(overrides)
    return defaults


_sku_counter = [0]


def unique_sku(prefix: str = "SKU") -> str:
    _sku_counter[0] += 1
    return f"{prefix}-{_sku_counter[0]}"


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": unique_sku(),
        "name": DEFAULTS["PRODUCT_NAME"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_store_inventory_payload(store_id: str, product_id: str, on_hand: int = 5, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "product_id": product_id,
        "on_hand": on_hand,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_slot_payload(store_id: str, window_start: str, window_end: str,
                               capacity: int = 5, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "window_start": window_start,
        "window_end": window_end,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, store_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "store_id": store_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id: str, qty_ordered: int = 1, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "qty_ordered": qty_ordered,
    }
    defaults.update(overrides)
    return defaults


def submit_order_payload(slot_id: str, expected_slot_version: int, **overrides) -> dict:
    defaults = {
        "slot_id": slot_id,
        "expected_slot_version": expected_slot_version,
    }
    defaults.update(overrides)
    return defaults


def restock_payload(delta_on_hand: int, expected_inventory_version: int, **overrides) -> dict:
    defaults = {
        "delta_on_hand": delta_on_hand,
        "expected_inventory_version": expected_inventory_version,
    }
    defaults.update(overrides)
    return defaults


def verify_payload(presented_name: str = DEFAULTS["CUSTOMER_NAME"],
                   presented_phone: str = DEFAULTS["CUSTOMER_PHONE"], **overrides) -> dict:
    defaults = {
        "presented_name": presented_name,
        "presented_phone": presented_phone,
    }
    defaults.update(overrides)
    return defaults


def pickup_payload(handovers: list, **overrides) -> dict:
    defaults = {"handovers": handovers}
    defaults.update(overrides)
    return defaults


def handover(order_line_id: str, qty_handed_over: int) -> dict:
    return {"order_line_id": order_line_id, "qty_handed_over": qty_handed_over}


def create_substitution_payload(order_line_id: str, substitute_product_id: str,
                                substitute_qty: int, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "substitute_product_id": substitute_product_id,
        "substitute_qty": substitute_qty,
    }
    defaults.update(overrides)
    return defaults


def create_curbside_checkin_payload(order_id: str, store_id: str,
                                    vehicle_description: str = DEFAULTS["VEHICLE_DESCRIPTION"],
                                    **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "store_id": store_id,
        "vehicle_description": vehicle_description,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
