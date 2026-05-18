"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.2: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp / date helpers — PRD §2.2 ISO 8601 with three fractional digits.
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


def iso_instant_utc(year: int, month: int, day: int,
                    hour: int = 12, minute: int = 0, second: int = 0,
                    millis: int = 0) -> str:
    """Build a deterministic ISO 8601 UTC instant."""
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def iso_date(d: date) -> str:
    """PRD §3.1: ISO 8601 calendar date (YYYY-MM-DD)."""
    return d.isoformat()


def date_offset(d: date, *, days: int) -> date:
    return d + timedelta(days=days)


def iso_offset(*, days: int = 0, hours: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(days=days, hours=hours))


def parse_iso(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def bulletin_month_of(d: date) -> str:
    """PRD §3.9: bulletin_month in YYYY-MM form."""
    return f"{d.year:04d}-{d.month:02d}"


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_email(prefix: str = "user") -> str:
    return f"{prefix}.{random_suffix(6).lower()}@example.com"


def random_a_number() -> str:
    """PRD §3.1: 'a capital A followed by exactly nine digits'."""
    digits = "".join(random.choices(string.digits, k=9))
    return f"A{digits}"


# ===========================================================================
# Petitioner — PRD §3.1
# ===========================================================================
def create_petitioner_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    country_of_citizenship: Optional[str] = None,
    email: Optional[str] = None,
    a_number: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /petitioners body = {full_name, date_of_birth,
    country_of_citizenship, email, a_number?}.

    PRD §3.1: "a date_of_birth ... that must fall at least fourteen
    years before today". Default DOB places the petitioner well past
    that boundary.
    """
    body: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"{TEST_DEFAULTS['FULL_NAME']} {random_suffix(4)}"
        ),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None
            else TEST_DEFAULTS["DATE_OF_BIRTH"]
        ),
        "country_of_citizenship": (
            country_of_citizenship if country_of_citizenship is not None
            else TEST_DEFAULTS["COUNTRY_OF_CITIZENSHIP"]
        ),
        "email": email if email is not None else random_email(),
    }
    if a_number is not None:
        body["a_number"] = a_number
    body.update(overrides)
    return body


# ===========================================================================
# Beneficiary — PRD §3.1
# ===========================================================================
def create_beneficiary_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    country_of_chargeability: Optional[str] = None,
    preference_category: Optional[str] = None,
    relationship_to_petitioner: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /petitioners/{id}/beneficiaries body =
    {full_name, date_of_birth, country_of_chargeability,
    preference_category, relationship_to_petitioner}.
    """
    body: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Beneficiary {random_suffix(4)}"
        ),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None
            else TEST_DEFAULTS["DATE_OF_BIRTH"]
        ),
        "country_of_chargeability": (
            country_of_chargeability if country_of_chargeability is not None
            else TEST_DEFAULTS["COUNTRY_OF_CHARGEABILITY"]
        ),
        "preference_category": (
            preference_category if preference_category is not None
            else TEST_DEFAULTS["PREFERENCE_CATEGORY_DEFAULT"]
        ),
        "relationship_to_petitioner": (
            relationship_to_petitioner
            if relationship_to_petitioner is not None
            else TEST_DEFAULTS["RELATIONSHIP_DEFAULT"]
        ),
    }
    body.update(overrides)
    return body


# ===========================================================================
# CaseTypeConfig — PRD §3.3
# ===========================================================================
def case_type_config_payload(
    *,
    case_type: str,
    requires_biometrics: bool,
    requires_interview: bool,
    rfe_response_window_days: int = 87,
    requires_priority_date_current: bool = False,
    receipt_prefix: str = "MSC",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /admin/case-type-config body = {case_type,
    requires_biometrics, requires_interview, rfe_response_window_days,
    requires_priority_date_current, receipt_prefix}.
    """
    body: Dict[str, Any] = {
        "case_type": case_type,
        "requires_biometrics": requires_biometrics,
        "requires_interview": requires_interview,
        "rfe_response_window_days": rfe_response_window_days,
        "requires_priority_date_current": requires_priority_date_current,
        "receipt_prefix": receipt_prefix,
    }
    body.update(overrides)
    return body


# ===========================================================================
# Case — PRD §3.2
# ===========================================================================
def create_case_payload(
    *,
    petitioner_id: str,
    beneficiary_id: str,
    case_type: str,
    linked_i130_case_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /cases body = {petitioner_id, beneficiary_id,
    case_type, linked_i130_case_id?}.
    """
    body: Dict[str, Any] = {
        "petitioner_id": petitioner_id,
        "beneficiary_id": beneficiary_id,
        "case_type": case_type,
    }
    if linked_i130_case_id is not None:
        body["linked_i130_case_id"] = linked_i130_case_id
    body.update(overrides)
    return body


def decide_case_payload(
    *,
    decision: str,
    denial_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /cases/{id}/decide body = {decision,
    denial_reason?}.

    PRD §3.7: "carries a decision value of APPROVE or DENY and an
    optional denial_reason".
    """
    body: Dict[str, Any] = {"decision": decision}
    if denial_reason is not None:
        body["denial_reason"] = denial_reason
    body.update(overrides)
    return body


# ===========================================================================
# Biometrics — PRD §3.4
# ===========================================================================
def schedule_biometrics_payload(
    *,
    scheduled_at: str,
    location_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /cases/{id}/biometrics body = {scheduled_at,
    location_code}.
    """
    body: Dict[str, Any] = {
        "scheduled_at": scheduled_at,
        "location_code": (
            location_code if location_code is not None
            else TEST_DEFAULTS["LOCATION_CODE"]
        ),
    }
    body.update(overrides)
    return body


def reschedule_biometrics_payload(
    *,
    new_scheduled_at: str,
    location_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /biometrics/{id}/reschedule body =
    {new_scheduled_at, location_code}.
    """
    body: Dict[str, Any] = {
        "new_scheduled_at": new_scheduled_at,
        "location_code": (
            location_code if location_code is not None
            else TEST_DEFAULTS["LOCATION_CODE"]
        ),
    }
    body.update(overrides)
    return body


# ===========================================================================
# RFE — PRD §3.5
# ===========================================================================
def issue_rfe_payload(
    *,
    reason_code: str = "MISSING_DOC",
    officer_notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /cases/{id}/rfe body = {reason_code,
    officer_notes}.
    """
    body: Dict[str, Any] = {
        "reason_code": reason_code,
        "officer_notes": (
            officer_notes if officer_notes is not None
            else TEST_DEFAULTS["OFFICER_NOTES"]
        ),
    }
    body.update(overrides)
    return body


# ===========================================================================
# Interview — PRD §3.6
# ===========================================================================
def schedule_interview_payload(
    *,
    scheduled_at: str,
    field_office_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /cases/{id}/interview body = {scheduled_at,
    field_office_code}.
    """
    body: Dict[str, Any] = {
        "scheduled_at": scheduled_at,
        "field_office_code": (
            field_office_code if field_office_code is not None
            else TEST_DEFAULTS["FIELD_OFFICE_CODE"]
        ),
    }
    body.update(overrides)
    return body


def complete_interview_payload(
    *,
    outcome: str = "RECOMMEND_APPROVAL",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /interviews/{id}/complete body = {outcome}."""
    body: Dict[str, Any] = {"outcome": outcome}
    body.update(overrides)
    return body


# ===========================================================================
# VisaBulletin — PRD §3.9
# ===========================================================================
def visa_bulletin_payload(
    *,
    bulletin_month: str,
    chart_type: str = "FINAL_ACTION",
    preference_category: str = "F2A",
    country: str = "MEX",
    cutoff_date: str = "CURRENT",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /admin/visa-bulletin body = {bulletin_month,
    chart_type, preference_category, country, cutoff_date}.
    """
    body: Dict[str, Any] = {
        "bulletin_month": bulletin_month,
        "chart_type": chart_type,
        "preference_category": preference_category,
        "country": country,
        "cutoff_date": cutoff_date,
    }
    body.update(overrides)
    return body


def chart_in_effect_payload(*, chart_type: str = "FINAL_ACTION",
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §4: POST /admin/visa-bulletin/chart-in-effect body =
    {chart_type}.
    """
    body: Dict[str, Any] = {"chart_type": chart_type}
    body.update(overrides)
    return body


# ===========================================================================
# Clock — PRD §3.10
# ===========================================================================
def clock_advance_payload(*, to: str,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.10: 'advance the logical server clock to a supplied to
    instant, expressed as an ISO 8601 UTC timestamp'.
    """
    body: Dict[str, Any] = {"to": to}
    body.update(overrides)
    return body


__all__ = [
    # Time helpers
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "iso_date",
    "date_offset",
    "iso_offset",
    "parse_iso",
    "bulletin_month_of",
    "random_suffix",
    "random_email",
    "random_a_number",
    # Payload factories
    "create_petitioner_payload",
    "create_beneficiary_payload",
    "case_type_config_payload",
    "create_case_payload",
    "decide_case_payload",
    "schedule_biometrics_payload",
    "reschedule_biometrics_payload",
    "issue_rfe_payload",
    "schedule_interview_payload",
    "complete_interview_payload",
    "visa_bulletin_payload",
    "chart_in_effect_payload",
    "clock_advance_payload",
]
