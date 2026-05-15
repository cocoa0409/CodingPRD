"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact schema the PRD declares for the request
body (PRD §3.1–§3.9). Tests pass overrides for the values they want
to control.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Utility — ISO 8601 UTC timestamp helper used by /_clock/advance and tests.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ---------------------------------------------------------------------------
# Pricing profile (PRD §3.2)
# ---------------------------------------------------------------------------
def create_pricing_profile_payload(
    size_class: str = "SMALL",
    rental_mode: str = "HOURLY",
    unit_price_cents: int = 500,
    deposit_cents: int = 2000,
    grace_minutes: int = 15,
    overdue_rate_cents_per_hour: int = 200,
    forced_clearance_hours: int = 48,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "size_class": size_class,
        "rental_mode": rental_mode,
        "unit_price_cents": unit_price_cents,
        "deposit_cents": deposit_cents,
        "grace_minutes": grace_minutes,
        "overdue_rate_cents_per_hour": overdue_rate_cents_per_hour,
        "forced_clearance_hours": forced_clearance_hours,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Cabinet (PRD §3.1)
# ---------------------------------------------------------------------------
def create_cabinet_payload(
    location_code: str = "BJ-CHAOYANG-001",
    latitude: float = TEST_DEFAULTS["LATITUDE"],
    longitude: float = TEST_DEFAULTS["LONGITUDE"],
    partner_id: str = "partner-001",
    partner_share_pct: int = TEST_DEFAULTS["PARTNER_SHARE_PCT"],
    firmware_version: str = "1.4.2",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "location_code": location_code,
        "latitude": latitude,
        "longitude": longitude,
        "partner_id": partner_id,
        "partner_share_pct": partner_share_pct,
        "firmware_version": firmware_version,
    }
    payload.update(overrides)
    return payload


def update_cabinet_payload(
    version: int,
    firmware_version: Optional[str] = None,
    partner_id: Optional[str] = None,
    partner_share_pct: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    if firmware_version is not None:
        payload["firmware_version"] = firmware_version
    if partner_id is not None:
        payload["partner_id"] = partner_id
    if partner_share_pct is not None:
        payload["partner_share_pct"] = partner_share_pct
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compartment (PRD §3.2)
# ---------------------------------------------------------------------------
def create_compartment_payload(
    slot_number: int = 1,
    size_class: str = "SMALL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "slot_number": slot_number,
        "size_class": size_class,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rental (PRD §3.2 + §3.4)
# ---------------------------------------------------------------------------
def create_rental_payload(
    rental_mode: str = "HOURLY",
    billing_units: int = 1,
    unlock_channel: str = "QR",
    insurance_tier: str = "NONE",
    declared_value_cents: int = 0,
    # Echoed pricing-profile fields (per PRD §3.2: "the body also echoes
    # the pricing-profile fields ... but the server resolves the active
    # PricingProfile ... and snapshots the canonical values").
    unit_price_cents: int = 500,
    deposit_cents: int = 2000,
    grace_minutes: int = 15,
    overdue_rate_cents_per_hour: int = 200,
    forced_clearance_hours: int = 48,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rental_mode": rental_mode,
        "billing_units": billing_units,
        "unlock_channel": unlock_channel,
        "insurance_tier": insurance_tier,
        "declared_value_cents": declared_value_cents,
        "unit_price_cents": unit_price_cents,
        "deposit_cents": deposit_cents,
        "grace_minutes": grace_minutes,
        "overdue_rate_cents_per_hour": overdue_rate_cents_per_hour,
        "forced_clearance_hours": forced_clearance_hours,
    }
    payload.update(overrides)
    return payload


def renew_rental_payload(
    renewal_billing_units: int = 1,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"renewal_billing_units": renewal_billing_units}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def return_rental_payload(
    unlock_channel: str = "QR",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"unlock_channel": unlock_channel}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def refund_rental_payload(version: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Insurance claim (PRD §3.9)
# ---------------------------------------------------------------------------
def create_insurance_claim_payload(
    rental_id: str,
    claim_type: str = "DAMAGE",
    claimed_amount_cents: int = 100_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rental_id": rental_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def submit_evidence_payload(
    evidence_description: str = "photo of damaged item",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"evidence_description": evidence_description}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def reject_evidence_payload(
    rejection_reason: str = "blurry photo",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def approve_claim_payload(
    payout_cents: int = 50_000,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"payout_cents": payout_cents}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def deny_claim_payload(
    rejection_reason: str = "claim not supported by evidence",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Repair tickets (PRD §3.8)
# ---------------------------------------------------------------------------
def create_repair_ticket_payload(
    compartment_id: str,
    fault_category: str = "DOOR_NOT_CLOSED",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "compartment_id": compartment_id,
        "fault_category": fault_category,
    }
    payload.update(overrides)
    return payload


def dispatch_repair_payload(
    assigned_technician_id: str = "tech-a",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"assigned_technician_id": assigned_technician_id}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def repair_ticket_payload(
    repair_notes: str = "door aligned and tested",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"repair_notes": repair_notes}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def reject_repair_payload(
    rejection_reason: str = "issue persists",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# /_clock/advance (PRD §2.11)
# ---------------------------------------------------------------------------
def clock_advance_payload(to_timestamp: str) -> Dict[str, Any]:
    return {"to_timestamp": to_timestamp}


__all__ = [
    "iso_utc",
    "create_pricing_profile_payload",
    "create_cabinet_payload",
    "update_cabinet_payload",
    "create_compartment_payload",
    "create_rental_payload",
    "renew_rental_payload",
    "return_rental_payload",
    "refund_rental_payload",
    "create_insurance_claim_payload",
    "submit_evidence_payload",
    "reject_evidence_payload",
    "approve_claim_payload",
    "deny_claim_payload",
    "create_repair_ticket_payload",
    "dispatch_repair_payload",
    "repair_ticket_payload",
    "reject_repair_payload",
    "clock_advance_payload",
]
