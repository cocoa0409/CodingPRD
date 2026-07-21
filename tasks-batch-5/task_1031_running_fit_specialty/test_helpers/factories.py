"""Payload factories — one per entity, input fields only (PRD Section 3)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_member_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "email": f"member{n}@example.com",
        "full_name": f"Test Member {n}",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "category": "SHOE",
        "unit_price_cents": 10000,
        "initial_stock": 3,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(member_id, lines, promo_code=None, **overrides) -> dict:
    payload = {"member_id": member_id, "lines": lines}
    if promo_code is not None:
        payload["promo_code"] = promo_code
    payload.update(overrides)
    return payload


def line(product_id, quantity=1) -> dict:
    return {"product_id": product_id, "quantity": quantity}


def create_subscription_payload(member_id, plan="BASIC", **overrides) -> dict:
    defaults = {"member_id": member_id, "plan": plan}
    defaults.update(overrides)
    return defaults


def create_fitter_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Fitter"}
    defaults.update(overrides)
    return defaults


def create_fitment_session_payload(
    member_id, fitter_id, scheduled_start, scheduled_end, **overrides
) -> dict:
    defaults = {
        "member_id": member_id,
        "fitter_id": fitter_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(
    title="Group Run", start_time=None, end_time=None, capacity=5, **overrides
) -> dict:
    defaults = {
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_training_booking_payload(session_id, member_id, **overrides) -> dict:
    defaults = {"session_id": session_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_return_payload(order_line_id, reason="wear test failed", **overrides) -> dict:
    defaults = {"order_line_id": order_line_id, "reason": reason}
    defaults.update(overrides)
    return defaults
