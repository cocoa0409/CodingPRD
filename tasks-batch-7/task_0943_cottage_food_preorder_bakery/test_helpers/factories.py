"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import (
    COOKIE_DOZEN_PRICE_CENTS,
    COOKIE_UNIT_PRICE_CENTS,
    LOAF_DOZEN_PRICE_CENTS,
    LOAF_OVEN_HOURS_PER_BATCH,
    LOAF_UNIT_PRICE_CENTS,
    LOAF_YIELD_UNITS_PER_SLOT,
    LOT_EXPIRES_AT,
    LOT_RECEIVED_AT,
    SCONE_DOZEN_PRICE_CENTS,
    SCONE_UNIT_PRICE_CENTS,
    WINDOW_CUTOFF_AT,
    WINDOW_HANDOFF_DATE,
    WINDOW_HANDOFF_END_AT,
    WINDOW_OPENS_AT,
    WINDOW_PRODUCTION_DATE,
)

_counter = itertools.count(1)


def unique_email(stem="buyer"):
    return f"{stem}{next(_counter)}@example.com"


def create_baker_payload(**overrides):
    payload = {
        "display_name": "Hearth and Crumb",
        "jurisdiction_code": "CA-ALAMEDA",
        "payout_period_start": "2026-05-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_customer_payload(baker_id, **overrides):
    payload = {
        "baker_id": baker_id,
        "display_name": "Ada Byron",
        "email": "ada@example.com",
        "delivery_distance_km": 6.0,
    }
    payload.update(overrides)
    return payload


def create_recipe_payload(baker_id, **overrides):
    payload = {"baker_id": baker_id, "name": "Brown Butter Cookie"}
    payload.update(overrides)
    return payload


def create_recipe_component_payload(**overrides):
    payload = {
        "component_name": "flour and butter",
        "quantity_grams": 500,
        "declared_allergens": ["wheat", "milk"],
    }
    payload.update(overrides)
    return payload


def create_ingredient_lot_payload(baker_id, **overrides):
    payload = {
        "baker_id": baker_id,
        "lot_code": "FLR-2026-11",
        "received_at": LOT_RECEIVED_AT,
        "expires_at": LOT_EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


def create_cookie_payload(baker_id, recipe_id, **overrides):
    """A PER_DOZEN_BAKERS, STANDARD-profile cookie at unit 450 / dozen 4600."""
    payload = {
        "baker_id": baker_id,
        "recipe_id": recipe_id,
        "name": "Brown Butter Cookie",
        "product_class": "SHELF_STABLE",
        "pricing_basis": "PER_DOZEN_BAKERS",
        "unit_price_cents": COOKIE_UNIT_PRICE_CENTS,
        "dozen_price_cents": COOKIE_DOZEN_PRICE_CENTS,
    }
    payload.update(overrides)
    return payload


def create_loaf_payload(baker_id, recipe_id, **overrides):
    """A PER_UNIT, LONG_BAKE loaf at 900 a unit, 3.0 oven hours, 12 units a slot."""
    payload = {
        "baker_id": baker_id,
        "recipe_id": recipe_id,
        "name": "Country Loaf",
        "product_class": "SHELF_STABLE",
        "pricing_basis": "PER_UNIT",
        "unit_price_cents": LOAF_UNIT_PRICE_CENTS,
        "dozen_price_cents": LOAF_DOZEN_PRICE_CENTS,
        "oven_profile": "LONG_BAKE",
        "oven_hours_per_batch": LOAF_OVEN_HOURS_PER_BATCH,
        "yield_units_per_slot": LOAF_YIELD_UNITS_PER_SLOT,
    }
    payload.update(overrides)
    return payload


def create_scone_payload(baker_id, recipe_id, **overrides):
    """A PER_UNIT, STANDARD-profile scone at 400 a unit."""
    payload = {
        "baker_id": baker_id,
        "recipe_id": recipe_id,
        "name": "Cream Scone",
        "product_class": "SHELF_STABLE",
        "pricing_basis": "PER_UNIT",
        "unit_price_cents": SCONE_UNIT_PRICE_CENTS,
        "dozen_price_cents": SCONE_DOZEN_PRICE_CENTS,
        "oven_profile": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_menu_item_payload(baker_id, recipe_id, **overrides):
    return create_cookie_payload(baker_id, recipe_id, **overrides)


def create_offer_window_payload(baker_id, **overrides):
    payload = {
        "baker_id": baker_id,
        "label": "Wed 6 May",
        "opens_at": WINDOW_OPENS_AT,
        "order_cutoff_at": WINDOW_CUTOFF_AT,
        "production_date": WINDOW_PRODUCTION_DATE,
        "handoff_date": WINDOW_HANDOFF_DATE,
        "handoff_window_end_at": WINDOW_HANDOFF_END_AT,
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, offer_window_id, **overrides):
    payload = {
        "customer_id": customer_id,
        "offer_window_id": offer_window_id,
        "handoff_mode": "PICKUP_COUNTER",
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(menu_item_id, quantity, expected_offer_window_version,
                              **overrides):
    payload = {
        "menu_item_id": menu_item_id,
        "quantity": quantity,
        "expected_offer_window_version": expected_offer_window_version,
    }
    payload.update(overrides)
    return payload


def patch_order_line_payload(quantity, expected_offer_window_version, **overrides):
    payload = {
        "quantity": quantity,
        "expected_offer_window_version": expected_offer_window_version,
    }
    payload.update(overrides)
    return payload


def create_label_payload(order_line_id, recipe_id, expected_recipe_version, **overrides):
    payload = {
        "order_line_id": order_line_id,
        "recipe_id": recipe_id,
        "net_weight_grams": 320.0,
        "expected_recipe_version": expected_recipe_version,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(customer_id, menu_item_id, **overrides):
    payload = {
        "customer_id": customer_id,
        "menu_item_id": menu_item_id,
        "cadence": "WEEKLY",
        "units_per_cycle": 24,
        "billing_mode": "PAY_PER_CYCLE",
        "handoff_mode": "PICKUP_COUNTER",
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(offer_window_id, sequence_number=1, **overrides):
    payload = {"offer_window_id": offer_window_id, "sequence_number": sequence_number}
    payload.update(overrides)
    return payload


def create_payment_payload(order_id, **overrides):
    payload = {"order_id": order_id, "tip_mode": "FIXED", "tip_fixed_cents": 0}
    payload.update(overrides)
    return payload


def create_refund_payload(amount_cents, expected_order_version, **overrides):
    payload = {
        "amount_cents": amount_cents,
        "refund_reason": "goodwill",
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_delivery_route_payload(baker_id, offer_window_id, **overrides):
    payload = {"baker_id": baker_id, "offer_window_id": offer_window_id}
    payload.update(overrides)
    return payload


def create_review_payload(order_id, menu_item_id, rating=5, **overrides):
    payload = {
        "order_id": order_id,
        "menu_item_id": menu_item_id,
        "rating": rating,
        "body": "Perfect crumb.",
    }
    payload.update(overrides)
    return payload
