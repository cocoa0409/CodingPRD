"""Payload factories — one per entity, input fields only.

Defaults mirror PRD-declared required fields; optional fields are omitted unless
overridden so the server applies its own documented defaults.
"""

_counter = {"n": 0}


def _uniq() -> int:
    _counter["n"] += 1
    return _counter["n"]


# --------------------------------------------------------------------------- #
# Salon
# --------------------------------------------------------------------------- #
def create_salon_payload(**overrides) -> dict:
    defaults = {"name": "Test Salon"}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Stylist — compensation_model is required (no PRD default)
# --------------------------------------------------------------------------- #
def create_stylist_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "full_name": "Test Stylist",
        "compensation_model": "COMMISSION",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Resource
# --------------------------------------------------------------------------- #
def create_resource_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "label": "Chair 1",
        "resource_type": "CHAIR",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
def create_service_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "name": "Test Service",
        "duration_minutes": 30,
        "base_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Client — email unique per salon; default keeps each call distinct
# --------------------------------------------------------------------------- #
def create_client_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "full_name": "Test Client",
        "email": f"client{_uniq()}@x.com",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# MembershipPlan — service_discount_pct is required (no PRD default)
# --------------------------------------------------------------------------- #
def create_membership_plan_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "name": "Gold",
        "monthly_fee_cents": 5000,
        "service_discount_pct": 0.20,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Membership
# --------------------------------------------------------------------------- #
def create_membership_payload(client_id, plan_id, **overrides) -> dict:
    defaults = {"client_id": client_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Package
# --------------------------------------------------------------------------- #
def create_package_payload(salon_id, service_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "service_id": service_id,
        "session_count": 4,
        "price_cents": 24000,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# PackagePurchase
# --------------------------------------------------------------------------- #
def create_package_purchase_payload(client_id, package_id, **overrides) -> dict:
    defaults = {"client_id": client_id, "package_id": package_id}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# ProductSku — sku unique per salon
# --------------------------------------------------------------------------- #
def create_product_sku_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "sku": f"SKU-{_uniq()}",
        "name": "Test Product",
        "unit_price_cents": 2000,
        "qty_on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Appointment
# --------------------------------------------------------------------------- #
def create_appointment_payload(
    salon_id, client_id, stylist_id, resource_id, service_id,
    start_utc, expected_stylist_version, **overrides
) -> dict:
    defaults = {
        "salon_id": salon_id,
        "client_id": client_id,
        "stylist_id": stylist_id,
        "resource_id": resource_id,
        "service_id": service_id,
        "start_utc": start_utc,
        "expected_stylist_version": expected_stylist_version,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Checkout — tip_cents and retail_lines optional
# --------------------------------------------------------------------------- #
def create_checkout_payload(appointment_id, **overrides) -> dict:
    defaults = {"appointment_id": appointment_id}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------- #
# Clock advance
# --------------------------------------------------------------------------- #
def clock_advance_payload(to_iso8601, expected_salon_version, **overrides) -> dict:
    defaults = {
        "to_iso8601": to_iso8601,
        "expected_salon_version": expected_salon_version,
    }
    defaults.update(overrides)
    return defaults
