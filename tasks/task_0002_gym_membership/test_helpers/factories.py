"""Payload factories — one per entity. Input fields only (PRD §3 + §4)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    """Return an ISO 8601 UTC timestamp with milliseconds and a 'Z' suffix
    (PRD §2.4: ISO 8601 UTC with three fractional digits)."""
    # Strip microseconds beyond millis, add 'Z'.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_email(prefix: str = "user") -> str:
    """Build a lowercase RFC-5322-ish email, unique per call."""
    return f"{prefix}.{_unique_suffix()}@example.com"


# ──────────────────────────────────────────────────────────
# Member registration (PRD §3.1, §4)
# ──────────────────────────────────────────────────────────

def create_member_payload(
    *,
    home_store_id: str,
    state_code: str = "CA",
    email: Optional[str] = None,
    password: str = "TestPassw0rd!",
    referred_by_member_id: Optional[str] = None,
    plan: Optional[str] = None,
    billing_cycle: Optional[str] = None,
    applied_coupon_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /members (PRD §3.1).

    Required: email, password, home_store_id, state_code.
    Optional: referred_by_member_id, and subscription bootstrap params.
    """
    payload: Dict[str, Any] = {
        "email": email or make_email(),
        "password": password,
        "home_store_id": home_store_id,
        "state_code": state_code,
    }
    if referred_by_member_id is not None:
        payload["referred_by_member_id"] = referred_by_member_id
    if plan is not None:
        payload["plan"] = plan
    if billing_cycle is not None:
        payload["billing_cycle"] = billing_cycle
    if applied_coupon_code is not None:
        payload["applied_coupon_code"] = applied_coupon_code
    payload.update(overrides)
    return payload


def login_payload(email: str, password: str = "TestPassw0rd!") -> Dict[str, Any]:
    """Body for POST /members/{memberId}/login (PRD §3.1)."""
    return {"email": email, "password": password}


# ──────────────────────────────────────────────────────────
# Subscription (PRD §3.2, §4)
# ──────────────────────────────────────────────────────────

def create_subscription_payload(
    *,
    plan: str = "PLUS",
    billing_cycle: str = "MONTHLY",
    auto_renew: Optional[bool] = None,
    applied_coupon_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /members/{memberId}/subscriptions (PRD §3.2).

    Required: plan, billing_cycle. Optional: auto_renew (defaults true), applied_coupon_code.
    """
    payload: Dict[str, Any] = {"plan": plan, "billing_cycle": billing_cycle}
    if auto_renew is not None:
        payload["auto_renew"] = auto_renew
    if applied_coupon_code is not None:
        payload["applied_coupon_code"] = applied_coupon_code
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# PaymentAttempt (PRD §3.3, §4)
# ──────────────────────────────────────────────────────────

def create_payment_attempt_payload(
    *,
    outcome: str = "SUCCESS",
    gateway_txn_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    failure_reason: Optional[str] = None,
    amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /members/{memberId}/subscriptions/{subId}/payment-attempts (PRD §3.3).

    Required: gateway_txn_id, idempotency_key, outcome.
    Optional: failure_reason. amount_cents is included only when overriding for tamper tests.
    """
    payload: Dict[str, Any] = {
        "gateway_txn_id": gateway_txn_id or f"txn_{_unique_suffix()}",
        "idempotency_key": idempotency_key or str(uuid.uuid4()),
        "outcome": outcome,
    }
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Store / ClassSession / EquipmentPool / Trainer (PRD §3.5, §3.9, §4)
# ──────────────────────────────────────────────────────────

# Note: PRD §4 lists no POST /stores endpoint — Stores are pre-seeded by the
# implementation. Fixtures discover Store ids via GET /stores; there is no
# create_store_payload.


def create_class_session_payload(
    *,
    class_type: str = "YOGA",
    trainer_id: str,
    starts_at: str,
    ends_at: str,
    capacity: int = 10,
    minimum_tier: Optional[str] = None,
    equipment_pool_id: Optional[str] = None,
    equipment_units_required: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /stores/{storeId}/class-sessions (PRD §3.5)."""
    payload: Dict[str, Any] = {
        "class_type": class_type,
        "trainer_id": trainer_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }
    if minimum_tier is not None:
        payload["minimum_tier"] = minimum_tier
    if equipment_pool_id is not None:
        payload["equipment_pool_id"] = equipment_pool_id
    if equipment_units_required is not None:
        payload["equipment_units_required"] = equipment_units_required
    payload.update(overrides)
    return payload


def create_equipment_pool_payload(
    *,
    equipment_type: str = "SPIN_BIKE",
    total_units: int = 10,
    maintenance_window_start: Optional[str] = None,
    maintenance_window_end: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /stores/{storeId}/equipment-pools (PRD §3.5)."""
    payload: Dict[str, Any] = {
        "equipment_type": equipment_type,
        "total_units": total_units,
    }
    if maintenance_window_start is not None:
        payload["maintenance_window_start"] = maintenance_window_start
    if maintenance_window_end is not None:
        payload["maintenance_window_end"] = maintenance_window_end
    payload.update(overrides)
    return payload


def create_trainer_payload(
    *,
    home_store_id: str,
    full_name: str = "Test Trainer",
    certifications: Optional[List[str]] = None,
    hourly_rate_cents: int = 8000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /trainers (PRD §3.5)."""
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "home_store_id": home_store_id,
        "certifications": list(certifications) if certifications else ["YOGA", "SPIN"],
        "hourly_rate_cents": hourly_rate_cents,
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Booking (PRD §3.6, §4)
# ──────────────────────────────────────────────────────────

def create_booking_payload(
    *,
    booking_kind: str,
    class_session_id: Optional[str] = None,
    trainer_id: Optional[str] = None,
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    applied_coupon_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /members/{memberId}/bookings (PRD §3.6).

    Required: booking_kind, and exactly one of {class_session_id, trainer_id} per
    the PRD's "class_session_id is required when booking_kind is GROUP_CLASS
    (and trainer_id is null), while trainer_id is required when booking_kind is
    PERSONAL_TRAINING (and class_session_id is null)".
    """
    payload: Dict[str, Any] = {"booking_kind": booking_kind}
    if class_session_id is not None:
        payload["class_session_id"] = class_session_id
    if trainer_id is not None:
        payload["trainer_id"] = trainer_id
    if starts_at is not None:
        payload["starts_at"] = starts_at
    if ends_at is not None:
        payload["ends_at"] = ends_at
    if applied_coupon_id is not None:
        payload["applied_coupon_id"] = applied_coupon_id
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Coupon (PRD §3.8, §4)
# ──────────────────────────────────────────────────────────

def create_coupon_payload(
    *,
    code: Optional[str] = None,
    kind: str = "PERCENT_OFF",
    value: int = 10,
    applicable_to: str = "BOTH",
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    max_redemptions: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /coupons (PRD §3.8). Code must be 6–12 uppercase A–Z/0–9."""
    now = _now_utc()
    payload: Dict[str, Any] = {
        "code": code or ("TEST" + _unique_suffix()[:8].upper()),
        "kind": kind,
        "value": value,
        "applicable_to": applicable_to,
        "valid_from": valid_from or iso_utc(now - timedelta(days=1)),
        "valid_until": valid_until or iso_utc(now + timedelta(days=365)),
        "max_redemptions": max_redemptions,
    }
    payload.update(overrides)
    return payload


def verify_coupon_payload(
    context_kind: str, context_id: Optional[str] = None
) -> Dict[str, Any]:
    """Body for POST /coupons/{couponId}/verify (PRD §3.8)."""
    payload: Dict[str, Any] = {"context_kind": context_kind}
    if context_id is not None:
        payload["context_id"] = context_id
    return payload


# ──────────────────────────────────────────────────────────
# Gate-vendor check-in (PRD §3.7) — webhook role=system
# ──────────────────────────────────────────────────────────

def check_in_payload(gate_device_id: str) -> Dict[str, Any]:
    """Body for POST /members/{memberId}/bookings/{bookingId}/check-in (PRD §3.7)."""
    return {"gate_device_id": gate_device_id}
