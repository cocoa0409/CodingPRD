"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC strings with three fractional
digits. PRD §3.1: dates of birth are ISO calendar dates (YYYY-MM-DD).
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ===========================================================================
# Timestamp helpers — PRD §2.4 ISO 8601 UTC, three fractional digits.
# ===========================================================================
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime.

    Accepts both Z-suffixed and offset-tagged strings, with or without
    fractional seconds.
    """
    s = iso_ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def iso_date(d: date) -> str:
    """ISO calendar date (YYYY-MM-DD)."""
    return d.isoformat()


def parse_anchor() -> datetime:
    """Return the clock anchor as a timezone-aware datetime."""
    return parse_iso(TEST_DEFAULTS["CLOCK_ANCHOR"])


def iso_anchor_offset(*, days: int = 0, hours: int = 0,
                      minutes: int = 0, seconds: int = 0,
                      milliseconds: int = 0) -> str:
    """Return an ISO 8601 UTC timestamp offset from the clock anchor."""
    return iso_utc(
        parse_anchor() + timedelta(
            days=days, hours=hours, minutes=minutes,
            seconds=seconds, milliseconds=milliseconds,
        ),
    )


# ===========================================================================
# Random helpers for unique identifiers.
# ===========================================================================
_DIGITS = string.digits
_UPPER = string.ascii_uppercase


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(_UPPER + _DIGITS, k=n))


def random_mrn() -> str:
    """PRD §3.1: 'two uppercase letters followed by eight digits'."""
    return (
        "".join(random.choices(_UPPER, k=2))
        + "".join(random.choices(_DIGITS, k=8))
    )


def random_npi() -> str:
    """PRD §3.1: 'ten digits, unique across clinicians'."""
    return "".join(random.choices(_DIGITS, k=10))


def random_panel_code(prefix: Optional[str] = None) -> str:
    """PRD §3.1: 'a LOINC-style identifier 3 to 20 characters drawn
    from uppercase letters, digits, and underscores'."""
    base = prefix or TEST_DEFAULTS["DEFAULT_PANEL_CODE_PREFIX"]
    # Keep within [3, 20] inclusive.
    suffix = random_suffix(8)
    code = (base + suffix)[:20]
    return code


def random_phone_e164() -> str:
    """PRD §3.1: leading '+', leading non-zero digit, 6 to 14 further
    digits."""
    body_len = random.randint(7, 10)
    digits = "".join(random.choices(_DIGITS, k=body_len))
    return "+1" + digits


def random_courier_id() -> str:
    return "courier-" + random_suffix(8)


def random_location_code(prefix: str = "LOC") -> str:
    return f"{prefix}_{random_suffix(6)}"


# ===========================================================================
# Patient — PRD §3.1.
# ===========================================================================
def create_patient_payload(
    *,
    mrn: Optional[str] = None,
    full_name: str = "Test Patient",
    date_of_birth: str = "1980-01-15",
    primary_phone_e164: Optional[str] = None,
    backup_phone_e164: Optional[str] = None,
    notification_consent: Optional[str] = None,
    include_backup_phone: bool = False,
    include_notification_consent: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mrn": mrn if mrn is not None else random_mrn(),
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "primary_phone_e164": (
            primary_phone_e164
            if primary_phone_e164 is not None
            else random_phone_e164()
        ),
    }
    if include_backup_phone or backup_phone_e164 is not None:
        payload["backup_phone_e164"] = backup_phone_e164
    if include_notification_consent or notification_consent is not None:
        payload["notification_consent"] = notification_consent
    return payload


# ===========================================================================
# Clinician — PRD §3.1.
# ===========================================================================
def create_clinician_payload(
    *,
    npi: Optional[str] = None,
    full_name: str = "Test Clinician",
    role_kind: str = "LAB_TECH",
    phone_e164: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "npi": npi if npi is not None else random_npi(),
        "full_name": full_name,
        "role_kind": role_kind,
        "phone_e164": (
            phone_e164 if phone_e164 is not None else random_phone_e164()
        ),
    }


def patch_clinician_payload(
    *,
    active: Optional[bool] = None,
    phone_e164: Optional[str] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if active is not None:
        payload["active"] = active
    if phone_e164 is not None:
        payload["phone_e164"] = phone_e164
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# TestPanel — PRD §3.1.
# ===========================================================================
def analyte_spec(
    *,
    analyte_code: str,
    unit: str = "mg/dL",
    critical_low: Optional[float] = None,
    critical_high: Optional[float] = None,
) -> Dict[str, Any]:
    """One analyte entry. PRD §3.1: 'each element of which carries an
    analyte_code, a unit, and two nullable bounds critical_low and
    critical_high.'"""
    return {
        "analyte_code": analyte_code,
        "unit": unit,
        "critical_low": critical_low,
        "critical_high": critical_high,
    }


def create_test_panel_payload(
    *,
    code: Optional[str] = None,
    name: str = "Test Panel",
    clia_complexity: str = "MODERATE",
    specimen_type: str = "BLOOD",
    stability_minutes: int = 120,
    analytes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if analytes is None:
        analytes = [
            analyte_spec(
                analyte_code="A1",
                unit="mg/dL",
                critical_low=None,
                critical_high=300,
            ),
            analyte_spec(
                analyte_code="A2",
                unit="mg/dL",
                critical_low=None,
                critical_high=300,
            ),
        ]
    return {
        "code": code if code is not None else random_panel_code(),
        "name": name,
        "clia_complexity": clia_complexity,
        "specimen_type": specimen_type,
        "stability_minutes": stability_minutes,
        "analytes": analytes,
    }


# ===========================================================================
# LabOrder — PRD §3.2.
# ===========================================================================
def create_lab_order_payload(
    *,
    patient_id: str,
    ordering_provider_id: str,
    panel_id: str,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "ordering_provider_id": ordering_provider_id,
        "panel_id": panel_id,
    }
    if priority is not None:
        payload["priority"] = priority
    return payload


def cancel_lab_order_payload(
    *, version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Specimen — PRD §3.3.
# ===========================================================================
def create_specimen_payload(
    *,
    collected_by_id: str,
    collected_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "collected_by_id": collected_by_id,
        "collected_at": (
            collected_at if collected_at is not None
            else iso_anchor_offset(minutes=-5)
        ),
    }


# ===========================================================================
# TransportLeg — PRD §3.3.
# ===========================================================================
def create_transport_leg_payload(
    *,
    from_location: str,
    to_location: str,
    departed_at: Optional[str] = None,
    courier_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "from_location": from_location,
        "to_location": to_location,
        "departed_at": (
            departed_at if departed_at is not None
            else iso_anchor_offset(minutes=0)
        ),
        "courier_id": (
            courier_id if courier_id is not None else random_courier_id()
        ),
    }


def arrive_transport_leg_payload(*, arrived_at: str) -> Dict[str, Any]:
    return {"arrived_at": arrived_at}


# ===========================================================================
# LabResult — PRD §3.4.
# ===========================================================================
def measurement(
    *, analyte_code: str, value: float, unit: str = "mg/dL",
) -> Dict[str, Any]:
    return {"analyte_code": analyte_code, "value": value, "unit": unit}


def create_result_payload(
    *,
    resulted_by_id: str,
    measurements: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "resulted_by_id": resulted_by_id,
        "measurements": measurements,
    }


def release_result_payload(
    *,
    released_by_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"released_by_id": released_by_id}
    if version is not None:
        payload["version"] = version
    return payload


def amend_result_payload(
    *,
    measurements: List[Dict[str, Any]],
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"measurements": measurements}
    if version is not None:
        payload["version"] = version
    return payload


def retract_result_payload(
    *, version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Acknowledgement — PRD §3.5.
# ===========================================================================
def acknowledge_payload(
    *,
    acknowledged_by_id: str,
    read_back_text: str,
) -> Dict[str, Any]:
    return {
        "acknowledged_by_id": acknowledged_by_id,
        "read_back_text": read_back_text,
    }


# ===========================================================================
# Clock — PRD §3.8.
# ===========================================================================
def clock_advance_payload(*, to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


__all__ = [
    # Timestamp helpers
    "iso_utc",
    "parse_iso",
    "iso_date",
    "parse_anchor",
    "iso_anchor_offset",
    # Random helpers
    "random_suffix",
    "random_mrn",
    "random_npi",
    "random_panel_code",
    "random_phone_e164",
    "random_courier_id",
    "random_location_code",
    # Patient
    "create_patient_payload",
    # Clinician
    "create_clinician_payload",
    "patch_clinician_payload",
    # TestPanel
    "analyte_spec",
    "create_test_panel_payload",
    # LabOrder
    "create_lab_order_payload",
    "cancel_lab_order_payload",
    # Specimen / transport
    "create_specimen_payload",
    "create_transport_leg_payload",
    "arrive_transport_leg_payload",
    # Result
    "measurement",
    "create_result_payload",
    "release_result_payload",
    "amend_result_payload",
    "retract_result_payload",
    # Ack
    "acknowledge_payload",
    # Clock
    "clock_advance_payload",
]
