"""Payload factories — one per endpoint that accepts a body.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are omitted.

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
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


def utc_midnight(d: date) -> datetime:
    """UTC midnight for a given calendar date (used for term boundaries)."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def date_iso_midnight(d: date) -> str:
    """ISO 8601 UTC string at midnight on the given date — used for
    Enrollment.term_start / term_end (PRD §2.6: 'UTC midnights bounding
    a half-open interval')."""
    return iso_utc(utc_midnight(d))


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_lowercase_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits,
                                  k=length))


def random_veteran_name() -> str:
    return f"{TEST_DEFAULTS['veteran_full_name']} {random_suffix(4)}"


def random_facility_code() -> str:
    """PRD §3.5: 'an 8-character facility_code unique across all schools'."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def random_condition_code(prefix: str = "5237") -> str:
    """PRD §3.3: 'a lowercase-alphanumeric-and-underscore identifier of 1
    to 32 characters identifying the VA diagnostic code, for example
    5237_lumbar'."""
    return f"{prefix}_{random_lowercase_suffix(6)}"


# ---------------------------------------------------------------------------
# Clock — PRD §3.8
# ---------------------------------------------------------------------------
def clock_advance_to_payload(target_iso: str) -> Dict[str, Any]:
    """PRD §3.8: 'accepting a body with either a to timestamp (an ISO
    8601 instant the clock jumps to) or a seconds integer (the clock
    advances by that many seconds)'."""
    return {"to": target_iso}


def clock_advance_seconds_payload(seconds: int) -> Dict[str, Any]:
    """PRD §3.8: 'or a seconds integer (the clock advances by that many
    seconds)'."""
    return {"seconds": seconds}


# ---------------------------------------------------------------------------
# Veteran — PRD §3.1
# ---------------------------------------------------------------------------
def create_veteran_payload(
    full_name: Optional[str] = None,
    branch: Optional[str] = None,
    aggregate_active_duty_days: Optional[int] = None,
    discharge_status: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'a Veteran record that captures the legal full_name (1
    to 120 characters), the service branch ... the
    aggregate_active_duty_days count ... and the discharge_status'."""
    payload: Dict[str, Any] = {
        "full_name": full_name or random_veteran_name(),
        "branch": branch or TEST_DEFAULTS["branch"],
        "aggregate_active_duty_days": (
            aggregate_active_duty_days
            if aggregate_active_duty_days is not None
            else 1100  # default to tier 100
        ),
        "discharge_status": (
            discharge_status or TEST_DEFAULTS["discharge_status"]
        ),
    }
    payload.update(overrides)
    return payload


def patch_veteran_payload(
    aggregate_active_duty_days: Optional[int] = None,
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'The aggregate_active_duty_days value is the sole field
    a clerk or admin may modify after onboarding. The patch endpoint
    accepts the new value and an optional version for the OCC check'."""
    payload: Dict[str, Any] = {}
    if aggregate_active_duty_days is not None:
        payload["aggregate_active_duty_days"] = aggregate_active_duty_days
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Dependent — PRD §3.2
# ---------------------------------------------------------------------------
def create_dependent_payload(
    veteran_id: str,
    relationship: str,
    date_of_birth: Optional[str] = None,
    school_enrolled: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: 'requires the owning veteran_id, the relationship
    (SPOUSE, CHILD, or PARENT), the date_of_birth, and — for the CHILD
    case only — an optional school_enrolled boolean that defaults to
    false.'"""
    today = utcnow().date()
    payload: Dict[str, Any] = {
        "veteran_id": veteran_id,
        "relationship": relationship,
        "date_of_birth": (
            date_of_birth
            # default DOB: 10 years ago (clearly under 18 for CHILD)
            or iso_utc(utc_midnight(today - timedelta(days=365 * 10)))
        ),
    }
    if school_enrolled is not None:
        payload["school_enrolled"] = school_enrolled
    payload.update(overrides)
    return payload


def patch_dependent_payload(
    school_enrolled: Optional[bool] = None,
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: 'The only mutable field on a dependent is the
    school_enrolled flag; the patch endpoint accepts that boolean and an
    optional version.'"""
    payload: Dict[str, Any] = {}
    if school_enrolled is not None:
        payload["school_enrolled"] = school_enrolled
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claim — PRD §3.3
# ---------------------------------------------------------------------------
def create_claim_payload(
    veteran_id: str,
    condition_code: Optional[str] = None,
    claim_type: str = "ORIGINAL",
    original_claim_id: Optional[str] = None,
    proposed_rating: int = 30,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'Filing a claim requires the veteran_id, the
    condition_code ... the claim_type (ORIGINAL or SUPPLEMENTAL), the
    proposed_rating ... and — required only when claim_type is
    SUPPLEMENTAL — the original_claim_id referencing a prior claim.'"""
    payload: Dict[str, Any] = {
        "veteran_id": veteran_id,
        "condition_code": condition_code or random_condition_code(),
        "claim_type": claim_type,
        "proposed_rating": proposed_rating,
    }
    if original_claim_id is not None:
        payload["original_claim_id"] = original_claim_id
    payload.update(overrides)
    return payload


def grant_claim_payload(granted_rating: int,
                        **overrides) -> Dict[str, Any]:
    """PRD §3.3: 'Granting the claim requires a granted_rating in the
    request body, which must be an integer in {0, 10, 20, 30, 40, 50,
    60, 70, 80, 90, 100}'."""
    payload: Dict[str, Any] = {"granted_rating": granted_rating}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# School — PRD §3.5
# ---------------------------------------------------------------------------
def create_school_payload(
    name: Optional[str] = None,
    facility_code: Optional[str] = None,
    program_type: str = "PUBLIC_IN_STATE",
    yellow_ribbon_enrolled: bool = False,
    yellow_ribbon_max_per_year: Optional[float] = None,
    zip_bah_code: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: 'A School ... carries an institutional name (1 to 200
    characters), an 8-character facility_code unique across all schools,
    a program_type ... a yellow_ribbon_enrolled boolean flag, an
    optional yellow_ribbon_max_per_year ... and a 5-digit numeric
    zip_bah_code'."""
    payload: Dict[str, Any] = {
        "name": name or f"{TEST_DEFAULTS['school_name']} {random_suffix(4)}",
        "facility_code": facility_code or random_facility_code(),
        "program_type": program_type,
        "yellow_ribbon_enrolled": yellow_ribbon_enrolled,
        "zip_bah_code": zip_bah_code or TEST_DEFAULTS["zip_bah_code"],
    }
    if yellow_ribbon_max_per_year is not None:
        payload["yellow_ribbon_max_per_year"] = yellow_ribbon_max_per_year
    elif yellow_ribbon_enrolled:
        # PRD §3.5: "required when yellow_ribbon_enrolled is true"
        payload["yellow_ribbon_max_per_year"] = 2000.00
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.6
# ---------------------------------------------------------------------------
def create_enrollment_payload(
    veteran_id: str,
    school_id: str,
    term_start: str,
    term_end: str,
    tuition_charged: float = 10000.00,
    training_time: str = "FULL_TIME",
    delivery_mode: str = "IN_PERSON",
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.6: 'Submitting an enrollment requires the veteran_id ...
    the school_id, the term_start and term_end (UTC midnights bounding a
    half-open interval), the gross tuition_charged ... the training_time
    ... and the delivery_mode'."""
    payload: Dict[str, Any] = {
        "veteran_id": veteran_id,
        "school_id": school_id,
        "term_start": term_start,
        "term_end": term_end,
        "tuition_charged": tuition_charged,
        "training_time": training_time,
        "delivery_mode": delivery_mode,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Housing payment — PRD §3.10
# ---------------------------------------------------------------------------
def create_housing_payment_payload(
    month_year: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.10: 'supplying a month_year (a "YYYY-MM" string matching
    the regex of a four-digit year followed by a two-digit month in
    01–12)'."""
    payload: Dict[str, Any] = {"month_year": month_year}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Voc Rehab plan — PRD §3.11
# ---------------------------------------------------------------------------
def create_voc_rehab_plan_payload(
    veteran_id: str,
    training_mode: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.11: 'A Counselor may create a Voc Rehab plan for a
    veteran by submitting the owning veteran_id and the training_mode'."""
    payload: Dict[str, Any] = {
        "veteran_id": veteran_id,
        "training_mode": training_mode or TEST_DEFAULTS["training_mode"],
    }
    payload.update(overrides)
    return payload


__all__ = [
    # Time
    "iso_utc", "iso_now", "utcnow", "parse_iso",
    "add_minutes", "add_hours", "add_days", "add_seconds",
    "utc_midnight", "date_iso_midnight",
    # Random
    "random_suffix", "random_lowercase_suffix",
    "random_veteran_name", "random_facility_code",
    "random_condition_code",
    # Clock
    "clock_advance_to_payload", "clock_advance_seconds_payload",
    # Veteran
    "create_veteran_payload", "patch_veteran_payload",
    # Dependent
    "create_dependent_payload", "patch_dependent_payload",
    # Claim
    "create_claim_payload", "grant_claim_payload",
    # School
    "create_school_payload",
    # Enrollment
    "create_enrollment_payload",
    # Housing payment
    "create_housing_payment_payload",
    # Voc Rehab plan
    "create_voc_rehab_plan_payload",
]
