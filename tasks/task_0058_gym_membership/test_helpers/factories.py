"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 declares as input (source: input)
for the relevant endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-name helpers
# ---------------------------------------------------------------------------
def unique_suffix(length: int = 10) -> str:
    return uuid.uuid4().hex[:length]


def unique_code(prefix: str = "CT") -> str:
    return f"{prefix}_{unique_suffix(8).upper()}"


def unique_email(prefix: str = "member") -> str:
    return f"{prefix}-{unique_suffix()}@example.com"


def unique_phone() -> str:
    """E.164-style: leading + with country code, digits only after.

    PRD §3.1: "phone (unique E.164 digits only)".
    """
    # Use uuid integer + namespace to ensure uniqueness with digits only.
    return "+1" + f"{uuid.uuid4().int % 10_000_000_000:010d}"


def unique_full_name(prefix: str = "Member") -> str:
    return f"{prefix} {unique_suffix(6)}"


# ---------------------------------------------------------------------------
# CardType  POST /card-types  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_card_type_payload(
    *,
    code: Optional[str] = None,
    category: str = "MONTHLY",
    price_cents: int = 30_000,
    validity_days: int = 30,
    visit_quota: int = 0,
    family_shareable: bool = False,
    max_freeze_days: int = 14,
    transfer_fee_pct_bp: int = 1_000,
    renewal_discount_pct_bp: int = 0,
    refund_eligibility_days: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1 card-type fields. Per PRD §3.1 these are: code, category,
    price_cents, validity_days, visit_quota, family_shareable,
    max_freeze_days, transfer_fee_pct_bp, renewal_discount_pct_bp,
    refund_eligibility_days."""
    payload: Dict[str, Any] = {
        "code": code or unique_code("CT"),
        "category": category,
        "price_cents": price_cents,
        "validity_days": validity_days,
        "visit_quota": visit_quota,
        "family_shareable": family_shareable,
        "max_freeze_days": max_freeze_days,
        "transfer_fee_pct_bp": transfer_fee_pct_bp,
        "renewal_discount_pct_bp": renewal_discount_pct_bp,
        "refund_eligibility_days": refund_eligibility_days,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Member  POST /members  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_member_payload(
    *,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    family_group_id: Optional[str] = None,
    notification_channels: Optional[List[str]] = None,
    auto_renew_authorized: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Member registration captures full_name (1 to 120
    characters), phone (unique E.164 digits only), email (unique),
    optional family_group_id ..., optional notification_channels ...,
    and optional auto_renew_authorized (defaulting to false).'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_full_name(),
        "phone": phone or unique_phone(),
        "email": email or unique_email(),
    }
    if family_group_id is not None:
        payload["family_group_id"] = family_group_id
    if notification_channels is not None:
        payload["notification_channels"] = notification_channels
    if auto_renew_authorized is not None:
        payload["auto_renew_authorized"] = auto_renew_authorized
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Wallet recharge  POST /members/{id}/wallet/recharge  (PRD §3.3)
# ---------------------------------------------------------------------------
def recharge_payload(*, amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'The request body carries a single amount_cents field.'"""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Card  POST /cards  (PRD §3.2)
# ---------------------------------------------------------------------------
def issue_card_payload(
    *,
    card_type_id: str,
    holder_member_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'Issuing a card produces a Card whose card_type_id and
    holder_member_id are taken from the request body.'"""
    payload: Dict[str, Any] = {
        "card_type_id": card_type_id,
        "holder_member_id": holder_member_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Freeze  POST /cards/{id}/freeze  (PRD §3.5)
# ---------------------------------------------------------------------------
def freeze_payload(
    *,
    reason: str = "ILLNESS",
    requested_days: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'takes a reason of either ILLNESS or BUSINESS_TRIP and a
    requested_days that is at least 1.'"""
    payload: Dict[str, Any] = {
        "reason": reason,
        "requested_days": requested_days,
    }
    payload.update(overrides)
    return payload


def unfreeze_payload(
    *,
    freeze_episode_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'supplying the target episode as freeze_episode_id in the
    body.'"""
    payload: Dict[str, Any] = {"freeze_episode_id": freeze_episode_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transfer  POST /cards/{id}/transfer  (PRD §3.6)
# ---------------------------------------------------------------------------
def transfer_payload(*, to_member_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'The request body carries the destination as
    to_member_id.'"""
    payload: Dict[str, Any] = {"to_member_id": to_member_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Send reminder  POST /cards/{id}/send-reminder  (PRD §3.7)
# ---------------------------------------------------------------------------
def send_reminder_payload(*, tier: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'the body carries the tier value.'"""
    payload: Dict[str, Any] = {"tier": tier}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Trainer  POST /trainers  (PRD §3.8)
# ---------------------------------------------------------------------------
def create_trainer_payload(
    *,
    full_name: Optional[str] = None,
    specialties: Optional[List[str]] = None,
    session_commission_pct_bp: int = 1_500,
    package_commission_pct_bp: int = 800,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'A Trainer record carries full_name, a non-empty
    specialties array of specialty codes ... a per-session commission
    rate in basis points (session_commission_pct_bp, between 0 and
    10,000), a package-sales commission rate in basis points
    (package_commission_pct_bp, between 0 and 10,000).'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_full_name("Trainer"),
        "specialties": specialties or ["STRENGTH"],
        "session_commission_pct_bp": session_commission_pct_bp,
        "package_commission_pct_bp": package_commission_pct_bp,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TrainerSlot  POST /trainer-slots  (PRD §3.8)
# ---------------------------------------------------------------------------
def create_trainer_slot_payload(
    *,
    trainer_id: str,
    starts_at: str,
    ends_at: str,
    specialty_code: str = "STRENGTH",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'Slots are published against a specific trainer with
    starts_at, ends_at, and specialty_code.'"""
    payload: Dict[str, Any] = {
        "trainer_id": trainer_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "specialty_code": specialty_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PTBooking  POST /pt-bookings  (PRD §3.8)
# ---------------------------------------------------------------------------
def create_pt_booking_payload(
    *,
    member_id: str,
    slot_id: str,
    billing_mode: str = "SINGLE",
    package_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'The body carries member_id, slot_id, billing_mode, and
    optional package_id.'"""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "slot_id": slot_id,
        "billing_mode": billing_mode,
    }
    if package_id is not None:
        payload["package_id"] = package_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PTPackage  POST /pt-packages  (PRD §3.8)
# ---------------------------------------------------------------------------
def create_pt_package_payload(
    *,
    member_id: str,
    trainer_id: str,
    total_sessions: int = 5,
    gross_price_cents: int = 50_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'The body carries member_id, trainer_id, total_sessions
    (at least 1), and gross_price_cents (at least 0).'"""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "trainer_id": trainer_id,
        "total_sessions": total_sessions,
        "gross_price_cents": gross_price_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# GroupClass  POST /group-classes  (PRD §3.9)
# ---------------------------------------------------------------------------
def create_group_class_payload(
    *,
    class_code: Optional[str] = None,
    instructor_trainer_id: str,
    starts_at: str,
    ends_at: str,
    capacity: int = 5,
    recurrence_series_id: Optional[str] = None,
    deduction_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: 'The body carries class_code, instructor_trainer_id,
    starts_at, ends_at, capacity (at least 1), an optional
    recurrence_series_id ..., and an optional deduction_cents (default
    zero) ...'"""
    payload: Dict[str, Any] = {
        "class_code": class_code or unique_code("GC"),
        "instructor_trainer_id": instructor_trainer_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }
    if recurrence_series_id is not None:
        payload["recurrence_series_id"] = recurrence_series_id
    if deduction_cents is not None:
        payload["deduction_cents"] = deduction_cents
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# GroupBooking  POST /group-bookings  (PRD §3.9)
# ---------------------------------------------------------------------------
def create_group_booking_payload(
    *,
    class_id: str,
    member_id: str,
    card_id: Optional[str] = None,
    accept_waitlist: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: 'Booking a class submits class_id, member_id, an optional
    card_id ..., and an optional accept_waitlist flag.'"""
    payload: Dict[str, Any] = {
        "class_id": class_id,
        "member_id": member_id,
    }
    if card_id is not None:
        payload["card_id"] = card_id
    if accept_waitlist is not None:
        payload["accept_waitlist"] = accept_waitlist
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Access event  POST /access-events  (PRD §3.10)
# ---------------------------------------------------------------------------
def access_event_payload(
    *,
    card_id: str,
    member_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10: 'The body carries card_id and member_id.'"""
    payload: Dict[str, Any] = {"card_id": card_id, "member_id": member_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payout cycle  POST /payouts  (PRD §3.11)
# ---------------------------------------------------------------------------
def open_payout_payload(
    *,
    cycle_start: str,
    cycle_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.11: 'Opening a payout cycle takes cycle_start and cycle_end
    (both ISO 8601 UTC).'"""
    payload: Dict[str, Any] = {
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance  POST /_clock/advance  (PRD §2.10)
# ---------------------------------------------------------------------------
def clock_payload(*, to: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.10: 'The clock-advance capability ... nudges the logical
    clock to a supplied instant.'"""
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Emit event  POST /_events/emit  (PRD §4)
# ---------------------------------------------------------------------------
def emit_event_payload(
    *,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"event_type": event_type, "payload": payload or {}}
    body.update(overrides)
    return body


__all__ = [
    "unique_suffix",
    "unique_code",
    "unique_email",
    "unique_phone",
    "unique_full_name",
    "create_card_type_payload",
    "create_member_payload",
    "recharge_payload",
    "issue_card_payload",
    "freeze_payload",
    "unfreeze_payload",
    "transfer_payload",
    "send_reminder_payload",
    "create_trainer_payload",
    "create_trainer_slot_payload",
    "create_pt_booking_payload",
    "create_pt_package_payload",
    "create_group_class_payload",
    "create_group_booking_payload",
    "access_event_payload",
    "open_payout_payload",
    "clock_payload",
    "emit_event_payload",
]
