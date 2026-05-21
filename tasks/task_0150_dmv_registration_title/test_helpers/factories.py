"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS

# Characters legal in a VIN per PRD §3.2 — uppercase A-Z and digits 0-9
# excluding I, O, Q.
_VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
# Characters legal in a plate_number per PRD §3.8 — uppercase A-Z, digits 0-9.
_PLATE_CHARS = string.ascii_uppercase + string.digits


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits
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


def iso_instant_utc(
    year: int, month: int, day: int,
    hour: int = 12, minute: int = 0, second: int = 0,
    millis: int = 0,
) -> str:
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_vin() -> str:
    """Generate a globally-unique 17-character VIN per PRD §3.2 regex
    ^[A-HJ-NPR-Z0-9]{17}$ — uppercase alphanumeric excluding I, O, Q.
    """
    return "".join(random.choices(_VIN_CHARS, k=17))


def random_plate_number(length: int = 6) -> str:
    """Generate a plate_number matching PRD §3.8 regex
    ^[A-Z0-9]{2,8}$.
    """
    return "".join(random.choices(_PLATE_CHARS, k=length))


def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_station_id() -> str:
    return f"STATION-{random_suffix(6)}"


def date_for_age(age_years: int, reference: Optional[datetime] = None) -> str:
    """Return a YYYY-MM-DD date_of_birth that yields the requested age in
    years as of `reference` (or utcnow()). Anchors at noon UTC to dodge
    DST quirks. PRD §3.10 uses floor((now - dob) / 365.25d) for age.
    """
    if reference is None:
        reference = utcnow()
    target = reference - timedelta(days=int(age_years * 365.25) + 1)
    return target.date().isoformat()


# ---------------------------------------------------------------------------
# Vehicle — PRD §3.2
# ---------------------------------------------------------------------------
def create_vehicle_payload(
    vin: Optional[str] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    model_year: int = TEST_DEFAULTS["model_year"],
    curb_weight_lbs: int = TEST_DEFAULTS["curb_weight_lbs"],
    fuel_type: str = TEST_DEFAULTS["fuel_type"],
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: vin, make, model, model_year, curb_weight_lbs, fuel_type."""
    payload: Dict[str, Any] = {
        "vin": vin or random_vin(),
        "make": make or TEST_DEFAULTS["make"],
        "model": model or TEST_DEFAULTS["model"],
        "model_year": model_year,
        "curb_weight_lbs": curb_weight_lbs,
        "fuel_type": fuel_type,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Owner — PRD §3.1
# ---------------------------------------------------------------------------
def create_owner_payload(
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    residency_state: str = TEST_DEFAULTS["residency_state_resident"],
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: full_name (1..100), date_of_birth (YYYY-MM-DD),
    residency_state (ISO 3166-2:US two-char)."""
    payload: Dict[str, Any] = {
        "full_name": full_name if full_name is not None
        else f"{TEST_DEFAULTS['owner_full_name']} {random_suffix(4)}",
        "date_of_birth": date_of_birth if date_of_birth is not None
        else TEST_DEFAULTS["date_of_birth_adult"],
        "residency_state": residency_state,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Salvage event — PRD §3.3
# ---------------------------------------------------------------------------
def salvage_event_payload(severity: str = "PARTIAL", **overrides) -> Dict[str, Any]:
    """PRD §3.3: severity is PARTIAL or TOTAL."""
    payload: Dict[str, Any] = {"severity": severity}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# REAL ID — PRD §3.10
# ---------------------------------------------------------------------------
def create_real_id_application_payload(
    documents_proof_of_identity: bool = True,
    documents_proof_of_residency: bool = True,
    documents_proof_of_ssn: bool = True,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.10: three booleans documents_proof_of_identity,
    documents_proof_of_residency, documents_proof_of_ssn."""
    payload: Dict[str, Any] = {
        "documents_proof_of_identity": documents_proof_of_identity,
        "documents_proof_of_residency": documents_proof_of_residency,
        "documents_proof_of_ssn": documents_proof_of_ssn,
    }
    payload.update(overrides)
    return payload


def resubmit_real_id_payload(
    documents_proof_of_identity: bool = True,
    documents_proof_of_residency: bool = True,
    documents_proof_of_ssn: bool = True,
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.10 + §2.5: same three booleans plus optional version for OCC."""
    payload: Dict[str, Any] = {
        "documents_proof_of_identity": documents_proof_of_identity,
        "documents_proof_of_residency": documents_proof_of_residency,
        "documents_proof_of_ssn": documents_proof_of_ssn,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transfer application — PRD §3.4
# ---------------------------------------------------------------------------
def create_transfer_application_payload(
    application_type: str,
    applicant_owner_id: str,
    declared_sale_price: float = TEST_DEFAULTS["declared_sale_price"],
    trade_in_value: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.4: application_type (INITIAL_REGISTRATION | TITLE_TRANSFER),
    applicant_owner_id, declared_sale_price (0.01..2000000.00),
    optional trade_in_value (default 0.00)."""
    payload: Dict[str, Any] = {
        "application_type": application_type,
        "applicant_owner_id": applicant_owner_id,
        "declared_sale_price": declared_sale_price,
    }
    if trade_in_value is not None:
        payload["trade_in_value"] = trade_in_value
    payload.update(overrides)
    return payload


def approve_salvage_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    """PRD §3.5: decision (APPROVE | DENY)."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def issue_plate_payload(plate_number: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    """PRD §3.8: plate_number — uppercase A-Z or digit 0-9, 2..8 chars."""
    payload: Dict[str, Any] = {
        "plate_number": plate_number or random_plate_number(6),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Emissions inspection — PRD §3.5
# ---------------------------------------------------------------------------
def create_emissions_inspection_payload(
    vehicle_id: str,
    station_id: str,
    scheduled_start: str,
    scheduled_end: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: vehicle_id, station_id (1..40 char opaque), scheduled_start,
    scheduled_end (end > start)."""
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "station_id": station_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def record_emissions_result_payload(
    outcome: str = "PASSED",
    odometer_reading: int = 10000,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: outcome (PASSED|FAILED), odometer_reading
    (integer 0..2000000)."""
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "odometer_reading": odometer_reading,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lien record — PRD §3.6
# ---------------------------------------------------------------------------
def create_lien_record_payload(
    lienholder_name: str = TEST_DEFAULTS["lienholder_name"],
    principal_amount: float = TEST_DEFAULTS["principal_amount"],
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.6: lienholder_name (1..120), principal_amount
    (0.01..2000000.00, 2dp)."""
    payload: Dict[str, Any] = {
        "lienholder_name": lienholder_name,
        "principal_amount": principal_amount,
    }
    payload.update(overrides)
    return payload


def release_lien_payload(
    release_reference: str = "REL-12345",
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.6: release_reference (non-empty string), optional version."""
    payload: Dict[str, Any] = {"release_reference": release_reference}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plate lifecycle — PRD §3.9
# ---------------------------------------------------------------------------
def surrender_plate_payload(surrender_reason: str = "OWNER_REQUEST",
                            **overrides) -> Dict[str, Any]:
    """PRD §3.9: surrender_reason in {SALVAGE_TRIGGERED, OWNER_REQUEST,
    LIEN_DEFAULT, TRANSFER_COMPLETE}."""
    payload: Dict[str, Any] = {"surrender_reason": surrender_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock — PRD §3.8
# ---------------------------------------------------------------------------
def clock_advance_payload(to_dt: Any) -> Dict[str, Any]:
    """PRD §3.8: 'to' (ISO 8601 datetime)."""
    if isinstance(to_dt, datetime):
        return {"to": iso_utc(to_dt)}
    return {"to": str(to_dt)}


__all__ = [
    # time
    "iso_utc", "utcnow", "iso_now", "iso_instant_utc", "parse_iso",
    "add_days", "add_seconds", "add_minutes",
    # random
    "random_vin", "random_plate_number", "random_suffix",
    "random_station_id", "date_for_age",
    # vehicle
    "create_vehicle_payload",
    "salvage_event_payload",
    # owner
    "create_owner_payload",
    # real id
    "create_real_id_application_payload",
    "resubmit_real_id_payload",
    # transfer
    "create_transfer_application_payload",
    "approve_salvage_payload",
    "issue_plate_payload",
    # emissions
    "create_emissions_inspection_payload",
    "record_emissions_result_payload",
    # lien
    "create_lien_record_payload",
    "release_lien_payload",
    # plate
    "surrender_plate_payload",
    # clock
    "clock_advance_payload",
]
