"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3).

Each assert_{entity}(data) validates the response shape of one resource:
server-minted UUID id, ISO 8601 timestamps, enum-typed status, and the
field types the PRD fixes for that resource.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ClientStatus, CartStatus, BaristaStatus, SkillLevel, CatalogStatus,
    PricingModel, PricingVariant, TravelVariant, BookingStatus,
    AssignmentStatus, ReservationStatus, PaymentKind, PaymentStatus,
)


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in _enum_values(ClientStatus)


def assert_cart(data: dict):
    _assert_common(data)
    assert isinstance(data["cart_code"], str) and data["cart_code"]
    assert data["status"] in _enum_values(CartStatus)
    assert isinstance(data["max_drinks_per_hour"], int)
    assert isinstance(data["requires_power_hookup"], bool)
    assert isinstance(data["requires_water_hookup"], bool)
    assert isinstance(data["home_base_lat"], (int, float))
    assert isinstance(data["home_base_lng"], (int, float))
    assert isinstance(data["committed_event_count"], int)


def assert_barista(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in _enum_values(BaristaStatus)
    assert data["skill_level"] in _enum_values(SkillLevel)
    assert isinstance(data["latte_art_certified"], bool)
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["weekly_hour_cap"], int)
    assert isinstance(data["committed_hours_this_week"], int)
    assert data["committed_hours_this_week"] >= 0


def assert_package(data: dict):
    _assert_common(data)
    assert isinstance(data["package_code"], str) and data["package_code"]
    assert data["status"] in _enum_values(CatalogStatus)
    assert data["pricing_model"] in _enum_values(PricingModel)
    for field in ("base_hours", "included_drinks", "flat_price_cents",
                  "per_cup_price_cents", "per_cup_minimum_cents", "max_guests"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_addon(data: dict):
    _assert_common(data)
    assert isinstance(data["addon_code"], str) and data["addon_code"]
    assert data["status"] in _enum_values(CatalogStatus)
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["requires_lead_barista"], bool)
    assert isinstance(data["requires_latte_art_cert"], bool)


def assert_travel_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert data["status"] in _enum_values(CatalogStatus)
    for field in ("max_distance_km", "banded_fee_cents", "per_km_rate_cents",
                  "min_booking_subtotal_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_booking(data: dict):
    _assert_common(data)
    for field in ("client_id", "package_id", "cart_id", "travel_zone_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must be a UUID"
    assert data["status"] in _enum_values(BookingStatus)
    assert is_iso8601_timestamp(data["event_start"])
    assert is_iso8601_timestamp(data["event_end"])
    assert isinstance(data["guest_count"], int)
    assert isinstance(data["venue_provides_power"], bool)
    assert isinstance(data["venue_provides_water"], bool)
    assert isinstance(data["distance_km"], int)
    # Money fields are integer cents (PRD §2.6).
    for field in ("quoted_subtotal_cents", "quoted_travel_fee_cents",
                  "quoted_total_cents", "deposit_due_cents", "deposit_paid_cents",
                  "balance_due_cents", "balance_paid_cents", "refund_paid_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_booking_addon(data: dict):
    # Immutable join record: only id + created_at are system-managed (PRD §2.4).
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "BookingAddOn must not carry updated_at"
    assert "version" not in data, "BookingAddOn must not carry version"
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("addon_id", ""))
    assert isinstance(data["applied_price_cents"], int)


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("barista_id", ""))
    assert data["status"] in _enum_values(AssignmentStatus)
    assert isinstance(data["duration_hours"], int) and data["duration_hours"] >= 1
    assert isinstance(data["is_primary"], bool)


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["status"] in _enum_values(CatalogStatus)
    for field in ("on_hand_units", "reserved_units", "consumed_units_lifetime",
                  "reorder_threshold_units"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["qty_units"], int) and data["qty_units"] >= 1
    assert isinstance(data["qty_consumed"], int) and data["qty_consumed"] >= 0
    assert data["status"] in _enum_values(ReservationStatus)


def assert_payment(data: dict):
    # Payments settle via explicit actions: only id + created_at (PRD §2.4).
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert "version" not in data, "Payment must not carry version"
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data["kind"] in _enum_values(PaymentKind)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in _enum_values(PaymentStatus)
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]


def assert_cancellation_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["tier_code"], str) and data["tier_code"]
    assert isinstance(data["min_notice_hours"], int)
    assert isinstance(data["max_notice_hours"], int)
    assert isinstance(data["deposit_refund_pct"], (int, float))
    assert 0.0 <= data["deposit_refund_pct"] <= 1.0
    assert isinstance(data["balance_waived"], bool)
    assert data["status"] in _enum_values(CatalogStatus)


def assert_inventory_conservation(item_before: dict, item_after: dict):
    """Inventory conservation law (PRD §3.7): units that left the depot equal
    consumed_units_lifetime, and reserved_units tracks live reservations."""
    consumed_delta = item_after["consumed_units_lifetime"] - item_before["consumed_units_lifetime"]
    on_hand_delta = item_before["on_hand_units"] - item_after["on_hand_units"]
    assert on_hand_delta == consumed_delta, (
        f"on_hand delta {on_hand_delta} must equal consumed delta {consumed_delta}"
    )
