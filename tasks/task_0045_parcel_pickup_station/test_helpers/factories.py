"""Payload factories -- one per endpoint payload defined in the PRD.

Only `source: input` fields appear here. Fields the server mints (ids,
timestamps, computed derivations) are intentionally absent so factories
never invite implementations to skip server-side derivations.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


# ===========================================================================
# Unique id / value generators
# ===========================================================================
def unique_id() -> str:
    """Short unique suffix used inside factory defaults."""
    return uuid.uuid4().hex[:8]


def unique_station_name(prefix: str = "Station") -> str:
    return f"{prefix}-{unique_id()}"


def unique_zone_code(prefix: str = "Z") -> str:
    # PRD §3.1: zone_code is 1..16 chars; suffix keeps it short and unique.
    return f"{prefix}-{unique_id()}"[:16]


def unique_tracking_number(prefix: str = "TRK") -> str:
    return f"{prefix}-{unique_id()}"


def unique_courier_company_id(prefix: str = "courier") -> str:
    return f"{prefix}-{unique_id()}"


def unique_recipient_phone() -> str:
    # PRD: 6..15 digit phone; use 11 digits.
    n = uuid.uuid4().int % (10 ** 11)
    return str(n).zfill(11)


def unique_idempotency_key(prefix: str = "idem") -> str:
    return f"{prefix}-{unique_id()}"


# ===========================================================================
# Station (PRD §3.1)
# ===========================================================================
def create_station_payload(**overrides: Any) -> Dict[str, Any]:
    """Payload for POST /stations.

    PRD §3.1: name 1..100 chars, address free-form, hours in HH:MM 24h
    pattern, storage_capacity >= 1, optional free_storage_hours defaults
    to 72.
    """
    defaults: Dict[str, Any] = {
        "name": unique_station_name(),
        "address": "123 Test Street",
        "business_hours_open": "08:00",
        "business_hours_close": "20:00",
        "storage_capacity": 50,
        "free_storage_hours": 72,
    }
    defaults.update(overrides)
    return defaults


def patch_station_payload(**overrides: Any) -> Dict[str, Any]:
    """Payload for PATCH /stations/{id}. All keys optional."""
    return dict(overrides)


# ===========================================================================
# ShelfZone (PRD §3.1)
# ===========================================================================
def create_shelf_zone_payload(**overrides: Any) -> Dict[str, Any]:
    """Payload for POST /stations/{id}/shelf-zones.

    PRD §3.1: zone_code unique per station 1..16 chars; row_count and
    column_count each at least one; zone_type defaults to STANDARD.
    """
    defaults: Dict[str, Any] = {
        "zone_code": unique_zone_code(),
        "row_count": 2,
        "column_count": 2,
        "zone_type": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Staff (PRD §3.1)
# ===========================================================================
def create_staff_payload(**overrides: Any) -> Dict[str, Any]:
    """Payload for POST /stations/{id}/staff.

    PRD §3.1: staff_id, station_id, full_name, phone (6..15 digit),
    role_kind in {CLERK, MANAGER}.
    """
    defaults: Dict[str, Any] = {
        "full_name": f"Test Staff {unique_id()}",
        "phone": unique_recipient_phone(),
        "role_kind": "CLERK",
    }
    defaults.update(overrides)
    return defaults


def patch_staff_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# ===========================================================================
# Parcel (PRD §3.2)
# ===========================================================================
def register_parcel_payload(
    courier_company_id: Optional[str] = None,
    tracking_number: Optional[str] = None,
    recipient_phone: Optional[str] = None,
    weight_grams: int = 500,
    size_class: str = "M",
    shelf_zone_id: Optional[str] = None,
    shelf_position: Optional[str] = None,
    exception_type: Optional[str] = None,
    recipient_name: Optional[str] = None,
    include_recipient_name: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /stations/{id}/parcels.

    PRD §3.2 explicitly names: courier_company_id, tracking_number,
    recipient_phone (6..15 digits), optional recipient_name (defaults
    null), weight_grams >= 1, size_class in {S,M,L,XL}. shelf_zone_id /
    shelf_position are present on the accept-and-shelve path;
    exception_type is present (DAMAGED or WRONG_DELIVERY) on the
    rejection path. Default exception_type is NONE.
    """
    payload: Dict[str, Any] = {
        "courier_company_id": courier_company_id or unique_courier_company_id(),
        "tracking_number": tracking_number or unique_tracking_number(),
        "recipient_phone": recipient_phone or unique_recipient_phone(),
        "weight_grams": weight_grams,
        "size_class": size_class,
    }
    if include_recipient_name or recipient_name is not None:
        payload["recipient_name"] = recipient_name
    if shelf_zone_id is not None:
        payload["shelf_zone_id"] = shelf_zone_id
    if shelf_position is not None:
        payload["shelf_position"] = shelf_position
    if exception_type is not None:
        payload["exception_type"] = exception_type
    payload.update(overrides)
    return payload


def reassign_shelf_payload(
    shelf_zone_id: str,
    shelf_position: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """Payload for PATCH /parcels/{id}/shelf."""
    payload: Dict[str, Any] = {
        "shelf_zone_id": shelf_zone_id,
        "shelf_position": shelf_position,
    }
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Pickup (PRD §3.6)
# ===========================================================================
def pickup_by_code_payload(code: str) -> Dict[str, Any]:
    return {"verification_method": "code", "code": code}


def pickup_by_authorization_payload(
    authorization_id: str, delegate_id_number: str
) -> Dict[str, Any]:
    return {
        "verification_method": "authorization",
        "authorization_id": authorization_id,
        "delegate_id_number": delegate_id_number,
    }


def pickup_by_face_match_payload(face_match: bool = True) -> Dict[str, Any]:
    return {"verification_method": "face_match", "face_match": face_match}


def dispose_payload(reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ===========================================================================
# Pickup Codes (PRD §3.3)
# ===========================================================================
def reissue_pickup_code_payload(reason: str = "LOST") -> Dict[str, Any]:
    return {"reason": reason}


# ===========================================================================
# Pickup Authorizations (PRD §3.4)
# ===========================================================================
def create_authorization_payload(
    expires_at: str,
    delegate_name: Optional[str] = None,
    delegate_id_number: Optional[str] = None,
    delegate_phone: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "delegate_name": delegate_name or f"Delegate-{unique_id()}",
        "delegate_id_number": delegate_id_number or f"ID-{unique_id()}",
        "delegate_phone": delegate_phone or unique_recipient_phone(),
        "expires_at": expires_at,
    }


def revoke_authorization_payload() -> Dict[str, Any]:
    return {"status": "REVOKED"}


# ===========================================================================
# Returns (PRD §3.7)
# ===========================================================================
def request_return_payload(
    courier_tracking_return: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if courier_tracking_return is not None:
        payload["courier_tracking_return"] = courier_tracking_return
    return payload


def courier_response_payload(decision: str) -> Dict[str, Any]:
    return {"decision": decision}


def ship_return_payload(
    courier_tracking_return: Optional[str] = None,
) -> Dict[str, Any]:
    if courier_tracking_return is None:
        courier_tracking_return = f"RTN-{unique_id()}"
    return {"courier_tracking_return": courier_tracking_return}


# ===========================================================================
# Billing (PRD §3.9)
# ===========================================================================
def create_billing_period_payload(period_yyyymm: str) -> Dict[str, Any]:
    return {"period_yyyymm": period_yyyymm}


def pay_bill_payload(
    amount: float,
    idempotency_key: Optional[str] = None,
    include_idempotency_key: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount": amount}
    if include_idempotency_key:
        payload["idempotency_key"] = idempotency_key or unique_idempotency_key()
    return payload


def dispute_bill_payload(reason: str = "wrong fee") -> Dict[str, Any]:
    return {"reason": reason}


def resolve_dispute_payload(
    adjustment_amount: Optional[float] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if adjustment_amount is not None:
        payload["adjustment_amount"] = adjustment_amount
    if note is not None:
        payload["note"] = note
    return payload


def write_off_payload(note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if note is not None:
        payload["note"] = note
    return payload


# ===========================================================================
# Quality assessments (PRD §3.10)
# ===========================================================================
def create_quality_assessment_payload(period_yyyymm: str) -> Dict[str, Any]:
    return {"period_yyyymm": period_yyyymm}


# ===========================================================================
# Clock + sweep + courier handshake (PRD §3.5)
# ===========================================================================
def clock_advance_payload(seconds: int) -> Dict[str, Any]:
    return {"seconds": seconds}


def sweep_payload(station_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if station_id is not None:
        payload["station_id"] = station_id
    return payload


def courier_inbound_handshake_payload(
    courier_company_id: str,
    tracking_number: str,
    station_id: str,
    recipient_phone: str,
    weight_grams: int = 500,
    size_class: str = "M",
) -> Dict[str, Any]:
    return {
        "courier_company_id": courier_company_id,
        "tracking_number": tracking_number,
        "station_id": station_id,
        "recipient_phone": recipient_phone,
        "weight_grams": weight_grams,
        "size_class": size_class,
    }


__all__ = [
    "unique_id",
    "unique_station_name",
    "unique_zone_code",
    "unique_tracking_number",
    "unique_courier_company_id",
    "unique_recipient_phone",
    "unique_idempotency_key",
    "create_station_payload",
    "patch_station_payload",
    "create_shelf_zone_payload",
    "create_staff_payload",
    "patch_staff_payload",
    "register_parcel_payload",
    "reassign_shelf_payload",
    "pickup_by_code_payload",
    "pickup_by_authorization_payload",
    "pickup_by_face_match_payload",
    "dispose_payload",
    "reissue_pickup_code_payload",
    "create_authorization_payload",
    "revoke_authorization_payload",
    "request_return_payload",
    "courier_response_payload",
    "ship_return_payload",
    "create_billing_period_payload",
    "pay_bill_payload",
    "dispute_bill_payload",
    "resolve_dispute_payload",
    "write_off_payload",
    "create_quality_assessment_payload",
    "clock_advance_payload",
    "sweep_payload",
    "courier_inbound_handshake_payload",
]
