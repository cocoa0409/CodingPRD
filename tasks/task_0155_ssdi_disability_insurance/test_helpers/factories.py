"""Payload factories — one per endpoint that accepts a body.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are omitted so the
implementation cannot accidentally accept them.

PRD §2.4: ISO 8601 UTC timestamps with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets.

    Also accepts date-only strings (YYYY-MM-DD), returning a UTC-aware
    datetime at 00:00:00 on that day. Fields like CDRReview.review_due_date
    and Application.next_cdr_due_date are serialized as YYYY-MM-DD per
    PRD §2.8 (whole-month diary intervals) and must compare cleanly with
    UTC-aware datetimes elsewhere in the helpers.
    """
    s = iso_ts.replace("Z", "+00:00")
    # Date-only form: attach UTC midnight so comparisons with tz-aware
    # datetimes succeed.
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return datetime.fromisoformat(s + "T00:00:00+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


def date_to_iso(d: date) -> str:
    """YYYY-MM-DD."""
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_ssn_last4() -> str:
    return "".join(random.choices(string.digits, k=4))


def random_claimant_name() -> str:
    return f"{TEST_DEFAULTS['claimant_full_name']} {random_suffix(4)}"


# ---------------------------------------------------------------------------
# Clock — PRD §2.10
# ---------------------------------------------------------------------------
def clock_advance_payload(target_iso: str) -> Dict[str, Any]:
    """PRD §2.10: 'advances the logical clock to a supplied to instant'.
    The body field is named `to` per PRD §4 endpoint table.
    """
    return {"to": target_iso}


# ---------------------------------------------------------------------------
# Claimant — PRD §3.1
# ---------------------------------------------------------------------------
def create_claimant_payload(
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    filing_date: Optional[str] = None,
    alleged_onset_date: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'A claimant joins the system by registering with their
    legal name, date of birth, the date on which they are filing the
    initial SSDI claim, the date they allege their disability began, and
    the last four digits of their Social Security number.'
    """
    today = utcnow().date()
    defaults: Dict[str, Any] = {
        "full_name": full_name or random_claimant_name(),
        "date_of_birth": date_of_birth or "1985-06-15",
        "filing_date": filing_date or date_to_iso(today),
        "alleged_onset_date": (
            alleged_onset_date or date_to_iso(today - timedelta(days=30))
        ),
        "ssn_last4": ssn_last4 or random_ssn_last4(),
    }
    defaults.update(overrides)
    return defaults


def patch_claimant_payload(
    full_name: Optional[str] = None,
    alleged_onset_date: Optional[str] = None,
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'A patch against the claimant — which may update
    full_name, alleged_onset_date, or version — re-runs the QC
    requirement lookup whenever alleged_onset_date changes.'
    """
    payload: Dict[str, Any] = {}
    if full_name is not None:
        payload["full_name"] = full_name
    if alleged_onset_date is not None:
        payload["alleged_onset_date"] = alleged_onset_date
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# QuarterCredit — PRD §3.1
# ---------------------------------------------------------------------------
def create_quarter_credit_payload(
    year: int,
    quarter: int,
    earnings_cents: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'The row carries the parent claimant_id, the calendar
    year (which must lie between 1978 and 2100 inclusive), the integer
    quarter from 1 through 4, and the quarter's earnings_cents
    (non-negative).'"""
    payload: Dict[str, Any] = {
        "year": year,
        "quarter": quarter,
        "earnings_cents": earnings_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MedicalEvidence — PRD §3.3
# ---------------------------------------------------------------------------
def create_listing_match_evidence_payload(
    listing_code: str = "1.15",
    medical_findings: Optional[str] = None,
    evidence_date: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'a LISTING_MATCH carries a listing_code (for example,
    "1.15" for musculoskeletal disorders) and leaves rfc_exertional_level,
    rfc_skill_level, age_category_at_decision, and education_level null.'
    """
    payload: Dict[str, Any] = {
        "source_type": "LISTING_MATCH",
        "listing_code": listing_code,
        "medical_findings": (
            medical_findings
            or "Documented impairment with sustained clinical findings."
        ),
        "evidence_date": evidence_date or date_to_iso(utcnow().date()),
    }
    payload.update(overrides)
    return payload


def create_rfc_assessment_evidence_payload(
    rfc_exertional_level: str = "SEDENTARY",
    rfc_skill_level: str = "UNSKILLED",
    age_category_at_decision: str = "YOUNGER",
    education_level: str = "HIGH_SCHOOL_OR_MORE",
    medical_findings: Optional[str] = None,
    evidence_date: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'an RFC_ASSESSMENT is the opposite — listing_code is null
    while rfc_exertional_level (one of SEDENTARY, LIGHT, MEDIUM, or
    HEAVY), rfc_skill_level (one of UNSKILLED, SEMI_SKILLED, or SKILLED),
    age_category_at_decision (one of YOUNGER, CLOSELY_APPROACHING, or
    ADVANCED), and education_level (one of ILLITERATE, LIMITED, or
    HIGH_SCHOOL_OR_MORE) must all be supplied.'
    """
    payload: Dict[str, Any] = {
        "source_type": "RFC_ASSESSMENT",
        "rfc_exertional_level": rfc_exertional_level,
        "rfc_skill_level": rfc_skill_level,
        "age_category_at_decision": age_category_at_decision,
        "education_level": education_level,
        "medical_findings": (
            medical_findings
            or "RFC limitations meet sedentary-only grid-rule criteria."
        ),
        "evidence_date": evidence_date or date_to_iso(utcnow().date()),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Application — PRD §3.3, §3.4
# ---------------------------------------------------------------------------
def create_application_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3: 'A new Application is created by the claimant against
    their claimant record and arrives in DRAFT status; the claimant_id
    is bound from the URL path and the row carries no other input fields
    at creation.'"""
    return dict(overrides)


def create_determination_payload(
    level: str,
    decision: str,
    medical_basis: Optional[str] = None,
    established_onset_date: Optional[str] = None,
    rationale: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.4: 'The body of the request supplies the determination's
    level (here INITIAL), the decision (one of ALLOW, DENY, or REMAND,
    though REMAND is valid only at APPEALS_COUNCIL), an optional
    medical_basis ... an optional established_onset_date, and a free-text
    rationale of at least fifty characters.'"""
    payload: Dict[str, Any] = {
        "level": level,
        "decision": decision,
        "rationale": rationale or TEST_DEFAULTS["rationale_text"],
    }
    if medical_basis is not None:
        payload["medical_basis"] = medical_basis
    if established_onset_date is not None:
        payload["established_onset_date"] = established_onset_date
    payload.update(overrides)
    return payload


def appeal_payload(target_level: str, **overrides) -> Dict[str, Any]:
    """PRD §3.6: 'an appeal request supplies target_level in the body'."""
    payload: Dict[str, Any] = {"target_level": target_level}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# HearingSlot — PRD §3.7
# ---------------------------------------------------------------------------
def create_hearing_slot_payload(
    alj_id: str,
    start_at: str,
    end_at: str,
    hearing_office: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.7: 'An ALJ ... creates a slot in OPEN status by supplying
    the responsible alj_id, the hearing_office code (for example,
    OHO_BOSTON), and the slot's start_at and end_at ISO 8601 UTC
    datetimes. end_at must equal start_at plus exactly sixty minutes.'
    """
    payload: Dict[str, Any] = {
        "alj_id": alj_id,
        "hearing_office": hearing_office or TEST_DEFAULTS["hearing_office"],
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def book_hearing_slot_payload(application_id: str,
                              **overrides) -> Dict[str, Any]:
    """PRD §3.7: 'Booking moves a slot from OPEN to BOOKED and binds the
    slot to an application via the request body's application_id.'"""
    payload: Dict[str, Any] = {"application_id": application_id}
    payload.update(overrides)
    return payload


def reschedule_hearing_slot_payload(new_slot_id: str,
                                    **overrides) -> Dict[str, Any]:
    """PRD §3.7: 'the request body's new_slot_id must refer to an OPEN
    slot'."""
    payload: Dict[str, Any] = {"new_slot_id": new_slot_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ChildAuxiliary — PRD §3.5
# ---------------------------------------------------------------------------
def create_child_auxiliary_payload(
    application_id: str,
    child_name: Optional[str] = None,
    child_date_of_birth: Optional[str] = None,
    child_relationship: str = "BIOLOGICAL",
    is_full_time_student: Optional[bool] = None,
    is_disabled_before_22: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: 'the body carries application_id, child_name,
    child_date_of_birth, child_relationship (one of BIOLOGICAL, ADOPTED,
    STEPCHILD, or DEPENDENT_GRANDCHILD), an optional is_full_time_student
    flag (required when the child is between 18 and 19 years old in
    secondary school), and an optional is_disabled_before_22 flag.'"""
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "child_name": child_name or f"Test Child {random_suffix(4)}",
        "child_date_of_birth": (
            child_date_of_birth
            or date_to_iso(utcnow().date() - timedelta(days=365 * 10))
        ),
        "child_relationship": child_relationship,
    }
    if is_full_time_student is not None:
        payload["is_full_time_student"] = is_full_time_student
    if is_disabled_before_22 is not None:
        payload["is_disabled_before_22"] = is_disabled_before_22
    payload.update(overrides)
    return payload


def terminate_child_auxiliary_payload(termination_reason: str,
                                      **overrides) -> Dict[str, Any]:
    """PRD §3.5: 'Termination is a system-emitted transition that
    supplies a termination_reason (one of AGE_OUT, NO_LONGER_DISABLED, or
    PARENT_BENEFIT_ENDED)'."""
    payload: Dict[str, Any] = {"termination_reason": termination_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SSI supplement — PRD §3.5
# ---------------------------------------------------------------------------
def create_ssi_supplement_payload(
    claimant_id: str,
    countable_income_cents: int = 0,
    countable_resources_cents: int = 0,
    living_arrangement: str = "OWN_HOUSEHOLD",
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: 'its body carries claimant_id, countable_income_cents,
    countable_resources_cents, and living_arrangement'."""
    payload: Dict[str, Any] = {
        "claimant_id": claimant_id,
        "countable_income_cents": countable_income_cents,
        "countable_resources_cents": countable_resources_cents,
        "living_arrangement": living_arrangement,
    }
    payload.update(overrides)
    return payload


def patch_ssi_supplement_payload(
    countable_income_cents: Optional[int] = None,
    countable_resources_cents: Optional[int] = None,
    living_arrangement: Optional[str] = None,
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §2.5: 'Mutating endpoints that take a request body —
    primarily the PATCH endpoints on Claimant and SSISupplement — accept
    an optional version field.'"""
    payload: Dict[str, Any] = {}
    if countable_income_cents is not None:
        payload["countable_income_cents"] = countable_income_cents
    if countable_resources_cents is not None:
        payload["countable_resources_cents"] = countable_resources_cents
    if living_arrangement is not None:
        payload["living_arrangement"] = living_arrangement
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CDRReview — PRD §3.8
# ---------------------------------------------------------------------------
def complete_cdr_payload(
    medical_improvement_found: bool,
    working_at_sga: bool,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.8: 'The body supplies medical_improvement_found and
    working_at_sga.'"""
    payload: Dict[str, Any] = {
        "medical_improvement_found": medical_improvement_found,
        "working_at_sga": working_at_sga,
    }
    payload.update(overrides)
    return payload


__all__ = [
    # Time
    "iso_utc", "iso_now", "utcnow", "parse_iso",
    "add_minutes", "add_hours", "add_days", "add_seconds", "date_to_iso",
    # Random
    "random_suffix", "random_ssn_last4", "random_claimant_name",
    # Clock
    "clock_advance_payload",
    # Claimant
    "create_claimant_payload", "patch_claimant_payload",
    # QuarterCredit
    "create_quarter_credit_payload",
    # MedicalEvidence
    "create_listing_match_evidence_payload",
    "create_rfc_assessment_evidence_payload",
    # Application
    "create_application_payload",
    "create_determination_payload",
    "appeal_payload",
    # HearingSlot
    "create_hearing_slot_payload",
    "book_hearing_slot_payload",
    "reschedule_hearing_slot_payload",
    # ChildAuxiliary
    "create_child_auxiliary_payload",
    "terminate_child_auxiliary_payload",
    # SSI
    "create_ssi_supplement_payload",
    "patch_ssi_supplement_payload",
    # CDR
    "complete_cdr_payload",
]
