"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed and system fields are intentionally
omitted so the implementation cannot accidentally accept them as inputs.

PRD §2.4 / §2.8: timestamps are ISO 8601 UTC with three fractional
digits.
PRD §2.5: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    GRADE_LEVEL_MAX,
    GRADE_LEVEL_MIN,
    HOUSEHOLD_SIZE_MAX,
    HOUSEHOLD_SIZE_MIN,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
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


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def date_midnight_iso(year: int, month: int, day: int) -> str:
    """ISO 8601 UTC midnight for a calendar day."""
    return iso_utc(datetime(year, month, day, tzinfo=timezone.utc))


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_email(prefix: str = "parent") -> str:
    return f"{prefix}-{random_suffix(6).lower()}@example.test"


# ---------------------------------------------------------------------------
# District — PRD §3.1
# ---------------------------------------------------------------------------
def create_district_payload(
    *,
    name: Optional[str] = None,
    school_year_start: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts — AuditOfficer only per PRD §3.1.

    PRD §3.1: required input fields are name and school_year_start.
    """
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"District {random_suffix(4)}",
        "school_year_start": (
            school_year_start
            if school_year_start is not None
            else TEST_DEFAULTS["DEFAULT_SCHOOL_YEAR_START"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ParentAccount — PRD §3.1
# ---------------------------------------------------------------------------
def create_parent_account_payload(
    *,
    parent_email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/parent-accounts — AuditOfficer only per
    PRD §3.1.

    PRD §3.1: required input field is parent_email.
    """
    payload: Dict[str, Any] = {
        "parent_email": (
            parent_email if parent_email is not None else random_email()
        ),
    }
    payload.update(overrides)
    return payload


def top_up_payload(*, amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """POST /districts/{id}/parent-accounts/{id}/top-up — Parent only
    per PRD §3.1.

    PRD §3.1: required input field is amount_cents (positive integer).
    """
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def refund_payload(*, serving_record_id: str,
                   **overrides: Any) -> Dict[str, Any]:
    """POST /districts/{id}/parent-accounts/{id}/refund — AuditOfficer
    only per PRD §3.6.

    PRD §3.6: required input field is serving_record_id naming the
    original CHARGE.
    """
    payload: Dict[str, Any] = {"serving_record_id": serving_record_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Student — PRD §3.1
# ---------------------------------------------------------------------------
def create_student_payload(
    *,
    parent_account_id: str,
    full_name: Optional[str] = None,
    grade_level: int = TEST_DEFAULTS["DEFAULT_GRADE_LEVEL"],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/students — Parent or AuditOfficer per
    PRD §3.1.

    PRD §3.1: required input fields are parent_account_id, full_name,
    grade_level (integer 0..12).
    """
    payload: Dict[str, Any] = {
        "parent_account_id": parent_account_id,
        "full_name": (
            full_name if full_name is not None
            else f"Student {random_suffix(4)}"
        ),
        "grade_level": grade_level,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AllergyProfileEntry — PRD §3.2
# ---------------------------------------------------------------------------
def create_allergy_entry_payload(
    *,
    allergen: str = "PEANUT",
    severity: str = "MODERATE",
    doctor_note_attached: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/students/{id}/allergy-entries — Parent only
    per PRD §3.2.

    PRD §3.2: required input fields are allergen, severity,
    doctor_note_attached.
    """
    payload: Dict[str, Any] = {
        "allergen": allergen,
        "severity": severity,
        "doctor_note_attached": doctor_note_attached,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FrlApplication — PRD §3.4, §3.5
# ---------------------------------------------------------------------------
def create_frl_application_payload(
    *,
    student_id: str,
    household_size: int = TEST_DEFAULTS["DEFAULT_HOUSEHOLD_SIZE"],
    declared_annual_income_cents: int = TEST_DEFAULTS[
        "DEFAULT_INCOME_REDUCED_CENTS"
    ],
    documents_attached_count: Optional[int] = None,
    prior_year_application_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/frl-applications — Parent only per PRD §3.4.

    PRD §3.4: required input fields are student_id, household_size,
    declared_annual_income_cents; optional documents_attached_count
    (defaulting to 0) and prior_year_application_id.
    """
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "household_size": household_size,
        "declared_annual_income_cents": declared_annual_income_cents,
    }
    if documents_attached_count is not None:
        payload["documents_attached_count"] = documents_attached_count
    if prior_year_application_id is not None:
        payload["prior_year_application_id"] = prior_year_application_id
    payload.update(overrides)
    return payload


def request_info_payload(*, review_note: str,
                         **overrides: Any) -> Dict[str, Any]:
    """POST /frl-applications/{id}/request-info — DistrictReviewer only
    per PRD §3.4.

    PRD §3.4: required input field is review_note (non-empty string).
    """
    payload: Dict[str, Any] = {"review_note": review_note}
    payload.update(overrides)
    return payload


def resubmit_payload(*, documents_attached_count: int,
                     **overrides: Any) -> Dict[str, Any]:
    """POST /frl-applications/{id}/resubmit — Parent only per PRD §3.4.

    PRD §3.4: required input field is documents_attached_count.
    """
    payload: Dict[str, Any] = {
        "documents_attached_count": documents_attached_count,
    }
    payload.update(overrides)
    return payload


def deny_payload(*, review_note: str,
                 **overrides: Any) -> Dict[str, Any]:
    """POST /frl-applications/{id}/deny — DistrictReviewer only per
    PRD §3.4.

    PRD §3.4: "the request body to carry a non-empty review_note".
    """
    payload: Dict[str, Any] = {"review_note": review_note}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MenuItem — PRD §3.3
# ---------------------------------------------------------------------------
def create_menu_item_payload(
    *,
    name: Optional[str] = None,
    contains_allergens: Optional[List[str]] = None,
    calories: int = TEST_DEFAULTS["DEFAULT_CALORIES"],
    sodium_mg: int = TEST_DEFAULTS["DEFAULT_SODIUM_MG"],
    full_price_cents: int = TEST_DEFAULTS["DEFAULT_FULL_PRICE_CENTS"],
    reimbursable: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/menu-items — CafeteriaManager only per
    PRD §3.3.

    PRD §3.3: required input fields are name, contains_allergens (array,
    may be empty), calories, sodium_mg, full_price_cents, reimbursable.
    """
    payload: Dict[str, Any] = {
        "name": (
            name if name is not None else f"MenuItem {random_suffix(4)}"
        ),
        "contains_allergens": (
            list(contains_allergens)
            if contains_allergens is not None else []
        ),
        "calories": calories,
        "sodium_mg": sodium_mg,
        "full_price_cents": full_price_cents,
        "reimbursable": reimbursable,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MealServingRecord — PRD §3.6
# ---------------------------------------------------------------------------
def create_meal_serving_payload(
    *,
    student_id: str,
    menu_item_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/meal-servings — CafeteriaManager only per
    PRD §3.6.

    PRD §3.6: required input fields are student_id and menu_item_id;
    serving_date is server-stamped from the logical clock.
    """
    payload: Dict[str, Any] = {
        "student_id": student_id,
        "menu_item_id": menu_item_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# UsdaReimbursementClaim — PRD §3.7
# ---------------------------------------------------------------------------
def create_usda_claim_payload(
    *,
    period_start: str,
    period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/usda-claims — AuditOfficer only per PRD §3.7.

    PRD §3.7: required input fields are period_start and period_end
    (both UTC-midnight instants; period_end >= period_start).
    """
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.8
# ---------------------------------------------------------------------------
def clock_advance_payload(*, target_instant: str,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance — AuditOfficer only per PRD §2.8.

    PRD §2.8: required input field is target_instant (ISO 8601 UTC).
    """
    payload: Dict[str, Any] = {"target_instant": target_instant}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "date_midnight_iso",
    "random_suffix",
    "random_email",
    "create_district_payload",
    "create_parent_account_payload",
    "top_up_payload",
    "refund_payload",
    "create_student_payload",
    "create_allergy_entry_payload",
    "create_frl_application_payload",
    "request_info_payload",
    "resubmit_payload",
    "deny_payload",
    "create_menu_item_payload",
    "create_meal_serving_payload",
    "create_usda_claim_payload",
    "clock_advance_payload",
]
