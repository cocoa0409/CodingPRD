"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally
omitted.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §3.1: SSN is exactly 9 digits; legal_name is 1..200 chars after
trimming; date_of_birth and start_date are ISO 8601 dates YYYY-MM-DD.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def date_str(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


# ---------------------------------------------------------------------------
# Random suffix — for cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_ssn() -> str:
    """Generate a 9-digit SSN unique per call.

    PRD §3.1: "`ssn` as exactly nine digits and unique across active
    employees".
    """
    return "".join(random.choices(string.digits, k=9))


def unique_document_number(prefix: str = "X") -> str:
    return prefix + "".join(
        random.choices(string.digits, k=8)
    )


def unique_idempotency_key(prefix: str = "k") -> str:
    return f"{prefix}-{random_suffix(10)}"


# ---------------------------------------------------------------------------
# Employee — POST /employees
# PRD §3.1: legal_name, date_of_birth, ssn, citizenship_status, start_date
# (required); work_authorization_expiry, visa_class (optional).
# ---------------------------------------------------------------------------
def create_employee_payload(
    *,
    legal_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    ssn: Optional[str] = None,
    citizenship_status: str = "US_CITIZEN",
    start_date: Optional[str] = None,
    work_authorization_expiry: Optional[str] = None,
    visa_class: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or TEST_DEFAULTS["EMPLOYEE_LEGAL_NAME"],
        "date_of_birth": date_of_birth or TEST_DEFAULTS["EMPLOYEE_DOB"],
        "ssn": ssn or unique_ssn(),
        "citizenship_status": citizenship_status,
        "start_date": start_date or TEST_DEFAULTS["EMPLOYEE_START_DATE"],
    }
    if work_authorization_expiry is not None:
        payload["work_authorization_expiry"] = work_authorization_expiry
    if visa_class is not None:
        payload["visa_class"] = visa_class
    payload.update(extra)
    return payload


def update_employee_payload(
    *,
    version: Optional[int] = None,
    start_date: Optional[str] = None,
    visa_class: Optional[str] = None,
    work_authorization_expiry: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """PRD §3.1: PATCH carries `version` for OCC plus the fields being
    updated (start_date, visa_class, work_authorization_expiry)."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if start_date is not None:
        payload["start_date"] = start_date
    if visa_class is not None:
        payload["visa_class"] = visa_class
    if work_authorization_expiry is not None:
        payload["work_authorization_expiry"] = work_authorization_expiry
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# I9Document — POST /employees/{employee_id}/i9-documents
# PRD §3.2: category, document_title, document_number, issuing_authority,
# expiration_date?, receipt?.
# ---------------------------------------------------------------------------
def create_i9_document_payload(
    *,
    category: str,
    document_title: Optional[str] = None,
    document_number: Optional[str] = None,
    issuing_authority: Optional[str] = None,
    expiration_date: Optional[str] = None,
    receipt: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category": category,
        "document_title": document_title or _default_title_for(category),
        "document_number": document_number or unique_document_number(),
        "issuing_authority": (
            issuing_authority or _default_issuing_authority_for(category)
        ),
    }
    if expiration_date is not None:
        payload["expiration_date"] = expiration_date
    if receipt is not None:
        payload["receipt"] = receipt
    payload.update(extra)
    return payload


def _default_title_for(category: str) -> str:
    if category == "LIST_A":
        return TEST_DEFAULTS["DOCUMENT_TITLE_PASSPORT"]
    if category == "LIST_B":
        return TEST_DEFAULTS["DOCUMENT_TITLE_DL"]
    if category == "LIST_C":
        return TEST_DEFAULTS["DOCUMENT_TITLE_SSN_CARD"]
    return "Document"


def _default_issuing_authority_for(category: str) -> str:
    if category == "LIST_A":
        return TEST_DEFAULTS["DOCUMENT_ISSUING_AUTHORITY_FED"]
    if category == "LIST_B":
        return TEST_DEFAULTS["DOCUMENT_ISSUING_AUTHORITY_STATE"]
    if category == "LIST_C":
        return TEST_DEFAULTS["DOCUMENT_ISSUING_AUTHORITY_USCIS"]
    return "Authority"


# ---------------------------------------------------------------------------
# I9Form — POST /employees/{employee_id}/i9-forms
# PRD §3.3: form_kind, supersedes_form_id? (required for REVERIFICATION/REHIRE).
# ---------------------------------------------------------------------------
def create_i9_form_payload(
    *,
    form_kind: str = "INITIAL",
    supersedes_form_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"form_kind": form_kind}
    if supersedes_form_id is not None:
        payload["supersedes_form_id"] = supersedes_form_id
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Section 1 — POST .../section1
# PRD §3.3: "The request body carries only `version` for the OCC check."
# ---------------------------------------------------------------------------
def section1_payload(
    *,
    version: Optional[int] = None,
    **extra: Any,
) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload if payload else None


# ---------------------------------------------------------------------------
# Section 2 — POST .../section2
# PRD §3.3: version, list_a_document_id?, list_b_document_id?,
# list_c_document_id?, enforce_deadline?.
# ---------------------------------------------------------------------------
def section2_payload(
    *,
    version: Optional[int] = None,
    list_a_document_id: Optional[str] = None,
    list_b_document_id: Optional[str] = None,
    list_c_document_id: Optional[str] = None,
    enforce_deadline: Optional[bool] = None,
    include_empty_lists: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a Section 2 sign payload.

    If `include_empty_lists=True`, all three list_*_document_id keys are
    sent as null — useful to confirm the empty-document-set edge case
    (PRD §3.3: "any other combination ... is rejected").
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if list_a_document_id is not None or include_empty_lists:
        payload["list_a_document_id"] = list_a_document_id
    if list_b_document_id is not None or include_empty_lists:
        payload["list_b_document_id"] = list_b_document_id
    if list_c_document_id is not None or include_empty_lists:
        payload["list_c_document_id"] = list_c_document_id
    if enforce_deadline is not None:
        payload["enforce_deadline"] = enforce_deadline
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Void form — POST /i9-forms/{form_id}/void
# PRD §3.3: "Voiding requires `version` in the request body."
# ---------------------------------------------------------------------------
def void_form_payload(
    *,
    version: Optional[int] = None,
    **extra: Any,
) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload if payload else None


# ---------------------------------------------------------------------------
# EVerifyCase — POST /employees/{employee_id}/everify-cases
# PRD §3.5: i9_form_id + idempotency_key.
# ---------------------------------------------------------------------------
def submit_everify_payload(
    *,
    i9_form_id: str,
    idempotency_key: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "i9_form_id": i9_form_id,
        "idempotency_key": idempotency_key or unique_idempotency_key(),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Deliver result — POST /everify-cases/{case_id}/result
# PRD §3.5: result + tnc_kind?.
# ---------------------------------------------------------------------------
def deliver_result_payload(
    *,
    result: str,
    tnc_kind: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": result}
    if tnc_kind is not None:
        payload["tnc_kind"] = tnc_kind
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# TNC decision — POST /everify-cases/{case_id}/tnc-decision
# PRD §3.5: decision in {CONTEST, NO_CONTEST}.
# ---------------------------------------------------------------------------
def tnc_decision_payload(
    *,
    decision: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Close case — POST /everify-cases/{case_id}/close
# PRD §3.6: body is empty per §4 input table.
# ---------------------------------------------------------------------------
def close_case_payload(**extra: Any) -> Optional[Dict[str, Any]]:
    if not extra:
        return None
    return dict(extra)


# ---------------------------------------------------------------------------
# Clock — POST /_clock/advance
# PRD §2.6: "advanced only via an admin-only test-driving capability
# that accepts a target instant in the `to` field."
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(extra)
    return payload


__all__ = [
    # Time helpers
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_days",
    "date_str",
    # Randomness
    "random_suffix",
    "unique_ssn", "unique_document_number", "unique_idempotency_key",
    # Payload factories
    "create_employee_payload",
    "update_employee_payload",
    "create_i9_document_payload",
    "create_i9_form_payload",
    "section1_payload",
    "section2_payload",
    "void_form_payload",
    "submit_everify_payload",
    "deliver_result_payload",
    "tnc_decision_payload",
    "close_case_payload",
    "clock_advance_payload",
]
