"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Each factory accepts **overrides so individual tests can
control the values relevant to their assertion while everything else gets a sensible
default. Optional fields with server-side defaults are omitted unless overridden.
"""
import itertools

# Counter to keep emails / SKUs unique within a single test process where a factory
# is called repeatedly without an explicit override.
_seq = itertools.count(1)


def create_style_service_payload(**overrides) -> dict:
    defaults = {
        "name": "Classic Blowout",
        "base_duration_minutes": 45,
        "base_price_cents": 6000,
        "blowout_credit_cost": 1,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(**overrides) -> dict:
    defaults = {
        "name": "Updo",
        "category": "UPDO",
        "extra_duration_minutes": 30,
        "price_cents": 3300,
    }
    defaults.update(overrides)
    return defaults


def create_membership_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "VIP",
        "monthly_fee_cents": 9900,
        "included_blowout_credits": 5,
        "member_discount_pct": 0.25,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = next(_seq)
    defaults = {
        "full_name": "Test Member",
        "email": f"member{n}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_stylist_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Stylist",
        "commission_tier": "SENIOR",
        "shift_start_minute": 480,
        "shift_end_minute": 1200,
    }
    defaults.update(overrides)
    return defaults


def create_chair_payload(**overrides) -> dict:
    defaults = {
        "label": "Chair 1",
        "open_minute": 480,
        "close_minute": 1200,
        "turnover_buffer_minutes": 10,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(member_id, chair_id, stylist_id, style_service_id,
                               start_minute=600, payment_method="CREDIT", **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "chair_id": chair_id,
        "stylist_id": stylist_id,
        "style_service_id": style_service_id,
        "start_minute": start_minute,
        "payment_method": payment_method,
    }
    defaults.update(overrides)
    return defaults


def create_event_block_payload(organizer_member_id, reserved_chair_ids,
                               block_type="GROUP", window_start_minute=540,
                               window_end_minute=900, party_size=2, **overrides) -> dict:
    defaults = {
        "organizer_member_id": organizer_member_id,
        "block_type": block_type,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
        "reserved_chair_ids": reserved_chair_ids,
        "party_size": party_size,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    n = next(_seq)
    defaults = {
        "sku": f"SKU-{n:04d}",
        "name": "Shampoo",
        "unit_price_cents": 2500,
        "initial_stock": 10,
    }
    defaults.update(overrides)
    return defaults


def create_retail_sale_payload(product_id, member_id, quantity=1, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "member_id": member_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_package_purchase_payload(member_id, expected_member_version,
                                    credits_purchased=2, price_cents=10000,
                                    **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "credits_purchased": credits_purchased,
        "price_cents": price_cents,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults
