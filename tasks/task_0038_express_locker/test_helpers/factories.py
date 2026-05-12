"""Payload factories — one per request schema named in PRD §3.

Field names match PRD prose verbatim. Each factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Unique-id helpers
# ---------------------------------------------------------------------------
def unique_suffix(n: int = 8) -> str:
    return uuid.uuid4().hex[:n]


def unique_site_code(prefix: str = "BJ-CY") -> str:
    return f"{prefix}-{unique_suffix(6)}"


def unique_partner_id(prefix: str = "partner") -> str:
    return f"{prefix}-{unique_suffix(8)}"


def unique_company_id(prefix: str = "company") -> str:
    return f"{prefix}-{unique_suffix(8)}"


def unique_phone() -> str:
    """Return an E.164 phone-shaped string."""
    return "+1" + "".join(str((uuid.uuid4().int >> i) & 0xF % 10) for i in range(10))[:10]


def unique_tracking_no(prefix: str = "TRK") -> str:
    return f"{prefix}-{unique_suffix(10).upper()}"


def unique_slot_label(prefix: str = "A") -> str:
    return f"{prefix}-{unique_suffix(4).upper()}"


def unique_external_id(prefix: str = "ext") -> str:
    return f"{prefix}-{unique_suffix(12)}"


# ---------------------------------------------------------------------------
# LockerMachine (PRD §3.1)
# ---------------------------------------------------------------------------
def create_locker_machine_payload(
    *,
    site_code: Optional[str] = None,
    partner_id: Optional[str] = None,
    firmware_version: str = "9.9.9",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_code": site_code or unique_site_code(),
        "partner_id": partner_id or unique_partner_id(),
        "firmware_version": firmware_version,
    }
    payload.update(overrides)
    return payload


def heartbeat_payload(
    *,
    firmware_version: str = "9.9.9",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"firmware_version": firmware_version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compartment (PRD §3.1)
# ---------------------------------------------------------------------------
def create_compartment_payload(
    *,
    slot_label: Optional[str] = None,
    size: str = "MEDIUM",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "slot_label": slot_label or unique_slot_label(),
        "size": size,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Courier (PRD §3.10)
# ---------------------------------------------------------------------------
def create_courier_payload(
    *,
    phone: Optional[str] = None,
    company_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "phone": phone or unique_phone(),
        "company_id": company_id or unique_company_id(),
    }
    payload.update(overrides)
    return payload


def restrict_courier_payload(*, reason: str = "test-restrict",
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def blacklist_courier_payload(*, reason: str = "test-blacklist",
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Parcel (PRD §3.3, §3.6)
# ---------------------------------------------------------------------------
def create_parcel_payload(
    *,
    locker_machine_id: str,
    tracking_no: Optional[str] = None,
    recipient_phone: Optional[str] = None,
    required_size: str = "MEDIUM",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tracking_no": tracking_no or unique_tracking_no(),
        "locker_machine_id": locker_machine_id,
        "recipient_phone": recipient_phone or unique_phone(),
        "required_size": required_size,
    }
    payload.update(overrides)
    return payload


def correct_wrong_deposit_payload(
    *,
    new_tracking_no: Optional[str] = None,
    new_recipient_phone: Optional[str] = None,
    new_required_size: str = "MEDIUM",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "new_tracking_no": new_tracking_no or unique_tracking_no("TRK2"),
        "new_recipient_phone": new_recipient_phone or unique_phone(),
        "new_required_size": new_required_size,
    }
    payload.update(overrides)
    return payload


def initiate_pickup_payload(
    *,
    method: str = "CODE",
    code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"method": method}
    if method == "CODE" and code is not None:
        payload["code"] = code
    payload.update(overrides)
    return payload


def dispose_parcel_payload(*, reason: str = "abandoned",
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def waive_fee_payload(*, reason: str = "MANUAL_DISPUTE",
                      **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: reason ∈ {SYSTEM_FAULT, COURIER_WRONG_DEPOSIT, MANUAL_DISPUTE}."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Disputes (PRD §3.9)
# ---------------------------------------------------------------------------
def open_dispute_payload(*, claim_type: str = "OVERTIME_DISPUTE",
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"claim_type": claim_type}
    payload.update(overrides)
    return payload


def resolve_dispute_payload(*, resolution: str,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: resolution ∈ {WAIVE, REJECT, COURIER_AT_FAULT}."""
    payload: Dict[str, Any] = {"resolution": resolution}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Settlement (PRD §3.11)
# ---------------------------------------------------------------------------
def create_settlement_payload(
    *,
    partner_id: str,
    period_start: str,
    period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driving (PRD §3.12)
# ---------------------------------------------------------------------------
def advance_clock_payload(*, seconds: int,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"seconds": seconds}
    payload.update(overrides)
    return payload


def emit_event_payload(
    *,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.12: event_type ∈ {payment_succeeded, payment_refunded,
    im_delivered, courier_company_ack}."""
    body: Dict[str, Any] = {
        "event_type": event_type,
        "payload": payload or {},
    }
    body.update(overrides)
    return body


def payment_succeeded_payload(
    *,
    fee_record_id: str,
    payment_external_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.8: payment_succeeded references an OvertimeFeeRecord.id and
    captures payment_external_id as the idempotency key."""
    return emit_event_payload(
        event_type="payment_succeeded",
        payload={
            "fee_record_id": fee_record_id,
            "payment_external_id": payment_external_id or unique_external_id(),
        },
    )


def payment_refunded_payload(
    *,
    fee_record_id: str,
    payment_external_id: str,
) -> Dict[str, Any]:
    """PRD §3.8: payment_refunded matches an existing payment_external_id."""
    return emit_event_payload(
        event_type="payment_refunded",
        payload={
            "fee_record_id": fee_record_id,
            "payment_external_id": payment_external_id,
        },
    )


__all__ = [
    "unique_suffix",
    "unique_site_code",
    "unique_partner_id",
    "unique_company_id",
    "unique_phone",
    "unique_tracking_no",
    "unique_slot_label",
    "unique_external_id",
    "create_locker_machine_payload",
    "heartbeat_payload",
    "create_compartment_payload",
    "create_courier_payload",
    "restrict_courier_payload",
    "blacklist_courier_payload",
    "create_parcel_payload",
    "correct_wrong_deposit_payload",
    "initiate_pickup_payload",
    "dispose_parcel_payload",
    "waive_fee_payload",
    "open_dispute_payload",
    "resolve_dispute_payload",
    "create_settlement_payload",
    "advance_clock_payload",
    "emit_event_payload",
    "payment_succeeded_payload",
    "payment_refunded_payload",
]
