"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid


def _uniq() -> str:
    return uuid.uuid4().hex[:10]


def create_product_payload(**overrides) -> dict:
    payload = {
        "sku": f"SKU-{_uniq()}",
        "name": "Test Product",
        "category": "DECK",
        "unit_price_cents": 6000,
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {
        "email": f"member-{_uniq()}@example.com",
        "full_name": "Test Member",
    }
    payload.update(overrides)
    return payload


def create_instructor_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Instructor",
        "discipline": "SKATE",
    }
    payload.update(overrides)
    return payload


def create_service_bay_payload(**overrides) -> dict:
    payload = {
        "name": f"Bay-{_uniq()}",
    }
    payload.update(overrides)
    return payload


def create_rental_unit_payload(**overrides) -> dict:
    payload = {
        "name": f"Unit-{_uniq()}",
        "kind": "SURFBOARD",
        "daily_rate_cents": 2500,
    }
    payload.update(overrides)
    return payload


def create_board_build_payload(member_id, component_lines, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "component_lines": component_lines,
    }
    payload.update(overrides)
    return payload


def create_service_order_payload(member_id, bay_id, service_type,
                                 slot_start, slot_end, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "bay_id": bay_id,
        "service_type": service_type,
        "slot_start": slot_start,
        "slot_end": slot_end,
    }
    payload.update(overrides)
    return payload


def create_rental_payload(member_id, unit_id, start_date, end_date, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "unit_id": unit_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def create_lesson_payload(member_id, instructor_id, discipline,
                          start_at, end_at, fee_cents, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "instructor_id": instructor_id,
        "discipline": discipline,
        "start_at": start_at,
        "end_at": end_at,
        "fee_cents": fee_cents,
    }
    payload.update(overrides)
    return payload


def create_trade_in_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "description": "Used gear",
    }
    payload.update(overrides)
    return payload


def create_special_order_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "product_name": "Custom item",
        "qty": 1,
    }
    payload.update(overrides)
    return payload


def create_event_payload(**overrides) -> dict:
    payload = {
        "name": f"Event-{_uniq()}",
        "capacity": 5,
    }
    payload.update(overrides)
    return payload
