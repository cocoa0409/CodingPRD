"""Payload factories — one per entity, input fields only.

Only fields the PRD marks as client-supplied input are produced. Computed and
system-managed fields (prices, statuses, points, credits) are never sent.
"""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def unique_email() -> str:
    return f"cust{next(_seq)}@example.com"


def unique_sku_code() -> str:
    return _uniq("SKU")


# ─── Customer ─────────────────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    payload = {"full_name": "Test Customer", "email": unique_email()}
    payload.update(overrides)
    return payload


def create_loyalty_adjustment_payload(points_delta: int, reason: str = "PROMOTION", **overrides) -> dict:
    payload = {"points_delta": points_delta, "reason": reason}
    payload.update(overrides)
    return payload


# ─── Fitter ───────────────────────────────────────────────────────────────
def create_fitter_payload(**overrides) -> dict:
    payload = {"full_name": "Test Fitter"}
    payload.update(overrides)
    return payload


# ─── FittingRoom ──────────────────────────────────────────────────────────
def create_room_payload(**overrides) -> dict:
    payload = {"room_name": "Test Room", "capacity": 5}
    payload.update(overrides)
    return payload


# ─── FittingAppointment ───────────────────────────────────────────────────
def create_appointment_payload(customer_id, fitter_id, room_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "fitter_id": fitter_id,
        "room_id": room_id,
        "fitting_type": "STANDARD",
        "scheduled_start": "2026-07-02T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_fit_payload(underbust_cm, bust_cm, expected_appointment_version, **overrides) -> dict:
    payload = {
        "underbust_cm": underbust_cm,
        "bust_cm": bust_cm,
        "expected_appointment_version": expected_appointment_version,
    }
    payload.update(overrides)
    return payload


# ─── Product & SKU ────────────────────────────────────────────────────────
def create_product_payload(**overrides) -> dict:
    payload = {
        "style_name": "Test Style",
        "brand": "Test Brand",
        "category": "EVERYDAY_BRA",
        "base_price_cents": 4000,
    }
    payload.update(overrides)
    return payload


def create_sku_payload(product_id, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "band_size": 34,
        "cup_size": "C",
        "sku_code": unique_sku_code(),
        "initial_stock": 5,
    }
    payload.update(overrides)
    return payload


# ─── Order / OrderLine ────────────────────────────────────────────────────
def create_order_payload(customer_id, **overrides) -> dict:
    payload = {"customer_id": customer_id}
    payload.update(overrides)
    return payload


def create_order_line_payload(sku_id, quantity: int = 1, **overrides) -> dict:
    payload = {"sku_id": sku_id, "quantity": quantity}
    payload.update(overrides)
    return payload


# ─── Exchange ─────────────────────────────────────────────────────────────
def create_exchange_payload(order_id, order_line_id, item_condition: str = "SEALED", **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "item_condition": item_condition,
    }
    payload.update(overrides)
    return payload


# ─── InsuranceClaim ───────────────────────────────────────────────────────
def create_insurance_claim_payload(order_id, **overrides) -> dict:
    payload = {"order_id": order_id}
    payload.update(overrides)
    return payload


def adjudicate_payload(decision: str, adjudicated_amount_cents=None, **overrides) -> dict:
    payload = {"decision": decision}
    if adjudicated_amount_cents is not None:
        payload["adjudicated_amount_cents"] = adjudicated_amount_cents
    payload.update(overrides)
    return payload


# ─── Logical clock ────────────────────────────────────────────────────────
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
