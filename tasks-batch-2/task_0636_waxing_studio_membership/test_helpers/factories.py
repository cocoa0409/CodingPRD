"""Payload factories — one per entity, input fields only."""
import itertools

_email_seq = itertools.count(1)


def unique_email(prefix="member") -> str:
    """Generate a unique email so duplicate-email checks never collide accidentally."""
    return f"{prefix}-{next(_email_seq)}@example.com"


def create_location_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Studio",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_service_type_payload(**overrides) -> dict:
    defaults = {
        "name": "Brazilian",
        "duration_minutes": 30,
        "list_price_cents": 4500,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "name": "Smooth Body Wash",
        "unit_price_cents": 1299,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(location_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "label": "Room 1",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(location_id, certified_service_ids=None, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "full_name": "Tia Tech",
        "certified_service_ids": certified_service_ids if certified_service_ids is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(home_location_id, **overrides) -> dict:
    defaults = {
        "home_location_id": home_location_id,
        "full_name": "Dora Member",
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "tier": "PLUS",
        "monthly_credit_grant": 4,
        "monthly_fee_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(member_id, location_id, room_id, technician_id,
                               service_type_id, start_utc, payment_method,
                               expected_room_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "location_id": location_id,
        "room_id": room_id,
        "technician_id": technician_id,
        "service_type_id": service_type_id,
        "start_utc": start_utc,
        "payment_method": payment_method,
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_retail_sale_payload(member_id, reservation_id, product_id, quantity, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "reservation_id": reservation_id,
        "product_id": product_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults
