"""Payload factories — one per entity, input fields only.

Each factory accepts **overrides so a test can control just the values it cares
about. Only fields the client supplies (source: input) appear here.
"""
import itertools

_email_counter = itertools.count(1)
_style_code_counter = itertools.count(1)


def unique_email(prefix="cust"):
    return f"{prefix}-{next(_email_counter)}@example.com"


def unique_style_code(prefix="SK"):
    return f"{prefix}-{next(_style_code_counter)}"


def create_boutique_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Boutique",
        "state_code": "CA",
        "tax_rate_bps": 875,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(boutique_id: str, **overrides) -> dict:
    defaults = {
        "boutique_id": boutique_id,
        "full_name": "Test Customer",
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_style_payload(boutique_id: str, **overrides) -> dict:
    defaults = {
        "boutique_id": boutique_id,
        "style_code": unique_style_code(),
        "name": "Test Style",
        "category": "TOPS",
        "season": "SPRING",
        "list_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_sku_variant_payload(**overrides) -> dict:
    defaults = {
        "size": "M",
        "color": "Blue",
        "on_hand": 5,
    }
    defaults.update(overrides)
    return defaults


def restock_payload(units: int, **overrides) -> dict:
    defaults = {"units": units}
    defaults.update(overrides)
    return defaults


def create_markdown_schedule_payload(style_id: str, expected_style_version: int, **overrides) -> dict:
    defaults = {
        "style_id": style_id,
        "phase": "SEASONAL",
        "markdown_pct": 25,
        "effective_date": 0,
        "expected_style_version": expected_style_version,
    }
    defaults.update(overrides)
    return defaults


def create_fitting_room_payload(boutique_id: str, **overrides) -> dict:
    defaults = {
        "boutique_id": boutique_id,
        "label": "Room 1",
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(fitting_room_id: str, customer_id: str, sku_variant_id: str, **overrides) -> dict:
    defaults = {
        "fitting_room_id": fitting_room_id,
        "customer_id": customer_id,
        "sku_variant_id": sku_variant_id,
        "start_minute": 600,
        "end_minute": 660,
    }
    defaults.update(overrides)
    return defaults


def create_stylist_payload(boutique_id: str, **overrides) -> dict:
    defaults = {
        "boutique_id": boutique_id,
        "full_name": "Test Stylist",
        "buffer_minutes": 15,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(stylist_id: str, customer_id: str, **overrides) -> dict:
    defaults = {
        "stylist_id": stylist_id,
        "customer_id": customer_id,
        "start_minute": 600,
        "end_minute": 660,
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(sku_variant_id: str, qty: int = 1, **overrides) -> dict:
    defaults = {
        "sku_variant_id": sku_variant_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(sales_order_id: str, order_line_id: str, resolution: str = "REFUND", **overrides) -> dict:
    defaults = {
        "sales_order_id": sales_order_id,
        "order_line_id": order_line_id,
        "resolution": resolution,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id: str, source_sku_variant_id: str, qty: int = 1, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "source_sku_variant_id": source_sku_variant_id,
        "qty": qty,
        "ship_to_state_code": "WA",
    }
    defaults.update(overrides)
    return defaults


def create_lookbook_payload(boutique_id: str, **overrides) -> dict:
    defaults = {
        "boutique_id": boutique_id,
        "title": "Test Lookbook",
        "season": "SPRING",
    }
    defaults.update(overrides)
    return defaults


def store_credit_grant_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def clock_advance_payload(boutique_id: str, to_business_date: int, **overrides) -> dict:
    defaults = {
        "boutique_id": boutique_id,
        "to_business_date": to_business_date,
    }
    defaults.update(overrides)
    return defaults
