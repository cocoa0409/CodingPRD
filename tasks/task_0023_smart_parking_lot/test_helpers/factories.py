"""Payload factories — one factory per entity, input fields only.

Field names match PRD §3 verbatim. Every factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_lot_name(prefix: str = "Lot") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_zone_code(prefix: str = "Z") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def unique_space_label(prefix: str = "S") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def unique_plate(prefix: str = "AAA") -> str:
    """Build a normalized plate (uppercase, [A-Z0-9-]{1,12})."""
    suffix = uuid.uuid4().hex[:6].upper()
    plate = f"{prefix}{suffix}"
    return plate[:12]


def unique_holder_ref(prefix: str = "HOLDER") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def unique_external_ref(prefix: str = "EXT") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_officer_id(prefix: str = "OFF") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# ParkingLot payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_lot_payload(
    *,
    name: Optional[str] = None,
    timezone: str = "UTC",
    hourly_rate_cents: int = 400,
    daily_cap_cents: int = 2000,
    free_minutes: Optional[int] = None,
    tow_grace_minutes: Optional[int] = None,
    reservation_hold_minutes: Optional[int] = None,
    no_show_penalty_cents: Optional[int] = None,
    partner_share_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_lot_name(),
        "timezone": timezone,
        "hourly_rate_cents": hourly_rate_cents,
        "daily_cap_cents": daily_cap_cents,
    }
    if free_minutes is not None:
        payload["free_minutes"] = free_minutes
    if tow_grace_minutes is not None:
        payload["tow_grace_minutes"] = tow_grace_minutes
    if reservation_hold_minutes is not None:
        payload["reservation_hold_minutes"] = reservation_hold_minutes
    if no_show_penalty_cents is not None:
        payload["no_show_penalty_cents"] = no_show_penalty_cents
    if partner_share_bps is not None:
        payload["partner_share_bps"] = partner_share_bps
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Zone / Space (PRD §3.1)
# ---------------------------------------------------------------------------
def create_zone_payload(
    *,
    code: Optional[str] = None,
    zone_type: str = "STANDARD",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_zone_code(),
        "zone_type": zone_type,
    }
    payload.update(overrides)
    return payload


def create_space_payload(
    *,
    label: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label": label or unique_space_label(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vehicle (PRD §3.2)
# ---------------------------------------------------------------------------
def create_vehicle_payload(
    *,
    plate: Optional[str] = None,
    kind: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    # Treat plate=None as "auto-generate a unique plate" but pass through
    # explicit "" (empty string) so plate-validation tests that exercise
    # the regex-rejection path can do so.
    if plate is None:
        plate = unique_plate()
    payload: Dict[str, Any] = {
        "plate": plate,
    }
    if kind is not None:
        payload["kind"] = kind
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Card (PRD §3.3)
# ---------------------------------------------------------------------------
def create_card_payload(
    *,
    card_type: str = "STORED_VALUE",
    holder_ref: Optional[str] = None,
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2027-01-01T00:00:00.000Z",
    monthly_fee_cents: Optional[int] = None,
    auto_pay_enabled: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "card_type": card_type,
        "holder_ref": holder_ref or unique_holder_ref(),
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    if monthly_fee_cents is not None:
        payload["monthly_fee_cents"] = monthly_fee_cents
    if auto_pay_enabled is not None:
        payload["auto_pay_enabled"] = auto_pay_enabled
    payload.update(overrides)
    return payload


def recharge_card_payload(
    *,
    amount_cents: int,
    external_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if external_ref is not None:
        payload["external_ref"] = external_ref
    payload.update(overrides)
    return payload


def bind_card_payload(*, vehicle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"vehicle_id": vehicle_id}
    payload.update(overrides)
    return payload


def unbind_card_payload(*, vehicle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"vehicle_id": vehicle_id}
    payload.update(overrides)
    return payload


def transfer_card_payload(
    *,
    target_card_id: str,
    reason: str = "transfer to new card",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_card_id": target_card_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reservation (PRD §3.4)
# ---------------------------------------------------------------------------
def create_reservation_payload(
    *,
    zone_id: str,
    vehicle_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    card_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "zone_id": zone_id,
        "vehicle_id": vehicle_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    if card_id is not None:
        payload["card_id"] = card_id
    payload.update(overrides)
    return payload


def patch_reservation_payload(
    *,
    reason: str = "schedule update",
    scheduled_start_at: Optional[str] = None,
    scheduled_end_at: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    if scheduled_start_at is not None:
        payload["scheduled_start_at"] = scheduled_start_at
    if scheduled_end_at is not None:
        payload["scheduled_end_at"] = scheduled_end_at
    if vehicle_id is not None:
        payload["vehicle_id"] = vehicle_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Session (PRD §3.5)
# ---------------------------------------------------------------------------
def create_session_payload(
    *,
    vehicle_id: Optional[str] = None,
    plate: Optional[str] = None,
    space_id: Optional[str] = None,
    card_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if vehicle_id is not None:
        payload["vehicle_id"] = vehicle_id
    if plate is not None:
        payload["plate"] = plate
    if space_id is not None:
        payload["space_id"] = space_id
    if card_id is not None:
        payload["card_id"] = card_id
    payload.update(overrides)
    return payload


def pay_session_payload(
    *,
    card_id: Optional[str] = None,
    external_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if card_id is not None:
        payload["card_id"] = card_id
    if external_ref is not None:
        payload["external_ref"] = external_ref
    payload.update(overrides)
    return payload


def waive_session_payload(
    *,
    reason: str = "operator goodwill",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Violation (PRD §3.6)
# ---------------------------------------------------------------------------
def create_violation_payload(
    *,
    lot_id: str,
    vehicle_id: str,
    violation_type: str,
    space_id: str,
    detected_at: str,
    officer_id: Optional[str] = None,
    session_id: Optional[str] = None,
    photo_uri: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_id": lot_id,
        "vehicle_id": vehicle_id,
        "violation_type": violation_type,
        "space_id": space_id,
        "detected_at": detected_at,
        "officer_id": officer_id or unique_officer_id(),
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if photo_uri is not None:
        payload["photo_uri"] = photo_uri
    payload.update(overrides)
    return payload


def patch_violation_payload(
    *,
    status: str,
    reason: str = "violation status change",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status, "reason": reason}
    payload.update(overrides)
    return payload


def pay_violation_payload(
    *,
    amount_cents: int,
    card_id: Optional[str] = None,
    external_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if card_id is not None:
        payload["card_id"] = card_id
    if external_ref is not None:
        payload["external_ref"] = external_ref
    payload.update(overrides)
    return payload


def tow_violation_payload(
    *,
    reason: str = "vehicle towed; unpaid 24h+",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Refund (PRD §3.7)
# ---------------------------------------------------------------------------
def refund_payload(
    *,
    reason: str = "dispute resolved",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_lot_name",
    "unique_zone_code",
    "unique_space_label",
    "unique_plate",
    "unique_holder_ref",
    "unique_external_ref",
    "unique_officer_id",
    "create_lot_payload",
    "create_zone_payload",
    "create_space_payload",
    "create_vehicle_payload",
    "create_card_payload",
    "recharge_card_payload",
    "bind_card_payload",
    "unbind_card_payload",
    "transfer_card_payload",
    "create_reservation_payload",
    "patch_reservation_payload",
    "create_session_payload",
    "pay_session_payload",
    "waive_session_payload",
    "create_violation_payload",
    "patch_violation_payload",
    "pay_violation_payload",
    "tow_violation_payload",
    "refund_payload",
]
