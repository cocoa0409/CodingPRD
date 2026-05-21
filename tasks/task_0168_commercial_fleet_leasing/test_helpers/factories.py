"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally
omitted.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.7: all monetary values are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_hours(iso_ts: str, hours: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(hours=hours))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def month_first_iso(year: int, month: int) -> str:
    """First instant of a calendar month at midnight UTC."""
    return iso_utc(datetime(year, month, 1, 0, 0, 0, 0, tzinfo=timezone.utc))


def month_last_iso(year: int, month: int) -> str:
    """Last instant of a calendar month: 23:59:59.999 UTC."""
    if month == 12:
        nx = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nx = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last = nx - timedelta(milliseconds=1)
    return iso_utc(last)


def quarter_first_iso(year: int, quarter: int) -> str:
    """First instant of a calendar quarter at midnight UTC."""
    month = {1: 1, 2: 4, 3: 7, 4: 10}[quarter]
    return month_first_iso(year, month)


def quarter_last_iso(year: int, quarter: int) -> str:
    """Last instant of a calendar quarter: 23:59:59.999 UTC."""
    month = {1: 3, 2: 6, 3: 9, 4: 12}[quarter]
    return month_last_iso(year, month)


# ---------------------------------------------------------------------------
# Random suffix — for cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_dot_number() -> str:
    """Generate a DOT number — 6-8 digits, unique across runs."""
    # 8 random digits.
    return "".join(random.choices(string.digits, k=8))


def unique_vin() -> str:
    """Generate a 17-char VIN — uppercase letters (no I/O/Q) + digits."""
    alphabet = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"  # A-HJ-NPR-Z plus digits
    return "".join(random.choices(alphabet, k=17))


def unique_pan_last4() -> str:
    return "".join(random.choices(string.digits, k=4))


# ---------------------------------------------------------------------------
# Lessee — POST /lessees
# ---------------------------------------------------------------------------
def create_lessee_payload(
    *,
    legal_name: Optional[str] = None,
    dot_number: Optional[str] = None,
    base_jurisdiction: str = "CA",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or TEST_DEFAULTS["LESSEE_LEGAL_NAME"],
        "dot_number": dot_number or unique_dot_number(),
        "base_jurisdiction": base_jurisdiction,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Vehicle — POST /vehicles
# ---------------------------------------------------------------------------
def create_vehicle_payload(
    *,
    vin: Optional[str] = None,
    vehicle_class: str = "CLASS_5",
    model_year: int = 2024,
    odometer_baseline_miles: int = 0,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vin": vin or unique_vin(),
        "vehicle_class": vehicle_class,
        "model_year": model_year,
        "odometer_baseline_miles": odometer_baseline_miles,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# TelematicsEvent — POST /vehicles/{id}/telematics-events
# ---------------------------------------------------------------------------
def create_telematics_event_payload(
    *,
    event_ts: str,
    odometer_reading: int,
    harsh_event_count: Optional[int] = None,
    fault_code: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_ts": event_ts,
        "odometer_reading": odometer_reading,
    }
    if harsh_event_count is not None:
        payload["harsh_event_count"] = harsh_event_count
    if fault_code is not None:
        payload["fault_code"] = fault_code
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# LeaseAgreement — POST /lease-agreements
# ---------------------------------------------------------------------------
def create_lease_agreement_payload(
    *,
    lessee_id: str,
    vehicle_id: str,
    term_start_date: str = "2026-03-01T00:00:00.000Z",
    term_end_date: str = "2027-03-01T00:00:00.000Z",
    monthly_mileage_allowance: int = 1000,
    overage_rate_cents_per_mile: int = 25,
    tiered_overage_enabled: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lessee_id": lessee_id,
        "vehicle_id": vehicle_id,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "monthly_mileage_allowance": monthly_mileage_allowance,
        "overage_rate_cents_per_mile": overage_rate_cents_per_mile,
    }
    if tiered_overage_enabled is not None:
        payload["tiered_overage_enabled"] = tiered_overage_enabled
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# FuelCard — POST /lease-agreements/{lease_id}/fuel-cards
# ---------------------------------------------------------------------------
def create_fuel_card_payload(
    *,
    card_pan_last4: Optional[str] = None,
    monthly_limit_cents: int = 100_000,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "card_pan_last4": card_pan_last4 or unique_pan_last4(),
        "monthly_limit_cents": monthly_limit_cents,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# FuelCardTransaction — POST /fuel-card-transactions
# ---------------------------------------------------------------------------
def create_fuel_card_transaction_payload(
    *,
    fuel_card_id: str,
    posted_at: str,
    jurisdiction: str = "CA",
    gallons: float = 10.0,
    amount_cents: int = 4000,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fuel_card_id": fuel_card_id,
        "posted_at": posted_at,
        "jurisdiction": jurisdiction,
        "gallons": gallons,
        "amount_cents": amount_cents,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# MaintenanceTicket — POST /vehicles/{vehicle_id}/maintenance-tickets
# ---------------------------------------------------------------------------
def create_maintenance_ticket_payload(
    *,
    ticket_kind: str = "REPAIR",
    estimate_cents: int = 0,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ticket_kind": ticket_kind,
        "estimate_cents": estimate_cents,
    }
    payload.update(extra)
    return payload


def close_maintenance_ticket_payload(
    *,
    actual_cents: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_cents": actual_cents}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# CollisionClaim — POST /lease-agreements/{lease_id}/collision-claims
# ---------------------------------------------------------------------------
def create_collision_claim_payload(
    *,
    incident_ts: str,
    estimate_cents: int = 100_000,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "incident_ts": incident_ts,
        "estimate_cents": estimate_cents,
    }
    payload.update(extra)
    return payload


def patch_collision_claim_payload(
    *,
    revised_estimate_cents: int,
    version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "revised_estimate_cents": revised_estimate_cents,
    }
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# OverageSettlement — POST /overage-settlements
# ---------------------------------------------------------------------------
def create_overage_settlement_payload(
    *,
    lease_agreement_id: str,
    period_year: int,
    period_month: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lease_agreement_id": lease_agreement_id,
        "period_year": period_year,
        "period_month": period_month,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# IFTAQuarter — POST /lessees/{lessee_id}/ifta-quarters
# ---------------------------------------------------------------------------
def create_ifta_quarter_payload(
    *,
    year: int,
    quarter: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "year": year,
        "quarter": quarter,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Clock — POST /_clock/advance
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# version-only payload — when supplying an optional OCC version for
# PATCH /collision-claims/{id}.
# ---------------------------------------------------------------------------
def version_payload(version: Optional[int] = None,
                    **extra: Any) -> Optional[Dict[str, Any]]:
    if version is None and not extra:
        return None
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


__all__ = [
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_hours", "add_days",
    "month_first_iso", "month_last_iso",
    "quarter_first_iso", "quarter_last_iso",
    "random_suffix", "unique_dot_number",
    "unique_vin", "unique_pan_last4",
    "create_lessee_payload",
    "create_vehicle_payload",
    "create_telematics_event_payload",
    "create_lease_agreement_payload",
    "create_fuel_card_payload",
    "create_fuel_card_transaction_payload",
    "create_maintenance_ticket_payload",
    "close_maintenance_ticket_payload",
    "create_collision_claim_payload",
    "patch_collision_claim_payload",
    "create_overage_settlement_payload",
    "create_ifta_quarter_payload",
    "clock_advance_payload",
    "version_payload",
]
