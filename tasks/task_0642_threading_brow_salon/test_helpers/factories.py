"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import FAR_FUTURE_EXPIRY

# Monotonic counters so repeated factory calls within one test produce unique
# salon-scoped values (phone, code, sku, license_number).
_phone_seq = itertools.count(1)
_lic_seq = itertools.count(1)
_code_seq = itertools.count(1)
_sku_seq = itertools.count(1)


def create_salon_payload(**overrides) -> dict:
    defaults = {
        "name": "Brow Bar",
        "license_number": f"LIC-{next(_lic_seq)}",
        "license_expiry": FAR_FUTURE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "display_name": "Tara",
        "sanitation_cert_expiry": FAR_FUTURE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_chair_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "label": "Bar 1",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "full_name": "Mia",
        "phone": f"555-{next(_phone_seq):04d}",
    }
    defaults.update(overrides)
    return defaults


def create_service_menu_item_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "code": f"BROW_THREAD_{next(_code_seq)}",
        "name": "Eyebrow Threading",
        "base_price_cents": 2000,
        "est_minutes": 15,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "code": f"TINT_{next(_code_seq)}",
        "name": "Brow Tint",
        "price_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_retail_product_payload(salon_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "sku": f"SERUM_{next(_sku_seq)}",
        "name": "Brow Serum",
        "unit_price_cents": 3000,
        "initial_stock_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(member_id, tier="SILVER", **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "tier": tier,
    }
    defaults.update(overrides)
    return defaults


def create_queue_ticket_payload(salon_id, member_id, service_menu_item_id, **overrides) -> dict:
    defaults = {
        "salon_id": salon_id,
        "member_id": member_id,
        "service_menu_item_id": service_menu_item_id,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(
    salon_id, queue_ticket_id, chair_id, technician_id, expected_salon_version, **overrides
) -> dict:
    defaults = {
        "salon_id": salon_id,
        "queue_ticket_id": queue_ticket_id,
        "chair_id": chair_id,
        "technician_id": technician_id,
        "expected_salon_version": expected_salon_version,
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(line_type, item_ref_id, **overrides) -> dict:
    defaults = {
        "line_type": line_type,
        "item_ref_id": item_ref_id,
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_adjustment_payload(points, **overrides) -> dict:
    defaults = {"points": points}
    defaults.update(overrides)
    return defaults
