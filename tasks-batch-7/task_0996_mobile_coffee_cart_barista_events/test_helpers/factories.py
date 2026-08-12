"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""
import uuid

from .constants import STANDARD


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_client_payload(**overrides) -> dict:
    defaults = {
        "company_name": f"Acme-{_suffix()}",
        "contact_email": f"acme-{_suffix()}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_cart_payload(**overrides) -> dict:
    defaults = {
        "cart_code": f"CART-{_suffix()}",
        "max_drinks_per_hour": 200,
        "requires_power_hookup": False,
        "requires_water_hookup": False,
        "home_base_lat": 37.0,
        "home_base_lng": -122.0,
    }
    defaults.update(overrides)
    return defaults


def create_barista_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Bia-{_suffix()}",
        "skill_level": "LEAD",
        "latte_art_certified": True,
        "hourly_rate_cents": STANDARD["HOURLY_RATE_CENTS"],
        "weekly_hour_cap": STANDARD["WEEKLY_HOUR_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_flat_package_payload(**overrides) -> dict:
    defaults = {
        "package_code": f"PKG-FLAT-{_suffix()}",
        "pricing_model": "FLAT",
        "base_hours": 2,
        "included_drinks": 100,
        "flat_price_cents": STANDARD["FLAT_PRICE_CENTS"],
        "per_cup_price_cents": 0,
        "per_cup_minimum_cents": 0,
        "max_guests": 80,
    }
    defaults.update(overrides)
    return defaults


def create_per_cup_package_payload(**overrides) -> dict:
    defaults = {
        "package_code": f"PKG-CUP-{_suffix()}",
        "pricing_model": "PER_CUP",
        "base_hours": 3,
        "included_drinks": 0,
        "flat_price_cents": 0,
        "per_cup_price_cents": STANDARD["PER_CUP_PRICE_CENTS"],
        "per_cup_minimum_cents": STANDARD["PER_CUP_MINIMUM_CENTS"],
        "max_guests": 200,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {
        "addon_code": f"LATTE_ART-{_suffix()}",
        "price_cents": 8000,
        "requires_lead_barista": False,
        "requires_latte_art_cert": True,
    }
    defaults.update(overrides)
    return defaults


def create_travel_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": f"ZONE-{_suffix()}",
        "max_distance_km": 25,
        "banded_fee_cents": STANDARD["ZONE1_BANDED_FEE_CENTS"],
        "per_km_rate_cents": STANDARD["ZONE1_PER_KM_RATE_CENTS"],
        "min_booking_subtotal_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(**overrides) -> dict:
    defaults = {
        "sku": f"BEAN-{_suffix()}",
        "on_hand_units": 100,
        "reorder_threshold_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_tier_payload(**overrides) -> dict:
    defaults = {
        "tier_code": f"T-{_suffix()}",
        "min_notice_hours": 0,
        "max_notice_hours": -1,
        "deposit_refund_pct": 1.0,
        "balance_waived": True,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(client_id, package_id, cart_id, travel_zone_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "package_id": package_id,
        "cart_id": cart_id,
        "travel_zone_id": travel_zone_id,
        "event_start": "2026-05-10T10:00:00Z",
        "event_end": "2026-05-10T12:00:00Z",
        "guest_count": 40,
        "venue_provides_power": True,
        "venue_provides_water": True,
        "distance_km": 10,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_offer_payload(barista_id, **overrides) -> dict:
    defaults = {
        "barista_id": barista_id,
        "is_primary": True,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(item_id, qty_units, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "qty_units": qty_units,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(kind, amount_cents, idempotency_key=None, **overrides) -> dict:
    defaults = {
        "kind": kind,
        "amount_cents": amount_cents,
        "idempotency_key": idempotency_key or f"pay-{_suffix()}",
    }
    defaults.update(overrides)
    return defaults
