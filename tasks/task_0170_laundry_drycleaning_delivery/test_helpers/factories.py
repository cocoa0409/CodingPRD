"""Payload factories — one per entity, input fields only.

Each factory takes **overrides so a test can control the few values it cares
about while inheriting sensible defaults for everything else.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="cust") -> str:
    """Customer email must be unique across customers (PRD §3.1)."""
    return f"{prefix}_{next(_email_counter)}@example.com"


def create_subscription_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "PLUS",
        "monthly_fee_cents": 6000,
        "included_wash_fold_grams": 5000,
        "overage_rate_cents_per_kg": 350,
        "dryclean_discount_pct": 0.25,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "email": overrides.pop("email", unique_email()),
        "full_name": "Test Customer",
        "default_address": "1 Test St",
        "zone_code": "Z1",
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(customer_id, plan_id, **overrides) -> dict:
    payload = {"customer_id": customer_id, "plan_id": plan_id}
    payload.update(overrides)
    return payload


def create_route_window_payload(**overrides) -> dict:
    payload = {
        "zone_code": "Z1",
        "window_kind": "PICKUP",
        "start_utc": "2026-06-01T09:00:00Z",
        "end_utc": "2026-06-01T11:00:00Z",
        "stop_capacity": 5,
    }
    payload.update(overrides)
    return payload


def create_locker_payload(**overrides) -> dict:
    payload = {
        "zone_code": "Z1",
        "location_label": "Test Bank",
        "compartment_count": 4,
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, pickup_window_id, delivery_window_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "pickup_window_id": pickup_window_id,
        "delivery_window_id": delivery_window_id,
        "handoff_method": "DOORSTEP",
    }
    payload.update(overrides)
    return payload


def create_garment_payload(service_type="WASH_FOLD", **overrides) -> dict:
    """Build a garment line consistent with the service type by default."""
    if service_type == "WASH_FOLD":
        payload = {"service_type": "WASH_FOLD", "declared_weight_grams": 2000}
    elif service_type == "DRY_CLEAN":
        payload = {"service_type": "DRY_CLEAN", "declared_piece_count": 1}
    elif service_type == "ALTERATION":
        payload = {"service_type": "ALTERATION", "declared_piece_count": 1, "alteration_fee_cents": 500}
    else:
        payload = {"service_type": service_type}
    payload.update(overrides)
    return payload


def create_locker_assignment_payload(order_id, locker_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "locker_id": locker_id,
        "compartment_index": 1,
        "hold_start_utc": "2026-06-03T09:00:00Z",
        "hold_end_utc": "2026-06-03T18:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_claim_payload(order_id, subject_kind, declared_value_cents, expected_order_version, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "subject_kind": subject_kind,
        "declared_value_cents": declared_value_cents,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_note_payload(note_kind="STAIN", severity=3, description="spot", **overrides) -> dict:
    payload = {"note_kind": note_kind, "severity": severity, "description": description}
    payload.update(overrides)
    return payload
