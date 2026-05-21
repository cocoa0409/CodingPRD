"""Payload factories — one per endpoint that accepts a body.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for values they want to control. Only PRD-declared input
fields are produced; computed/system fields are omitted so the
implementation cannot accidentally accept them.

PRD §2.2: API responses use ISO 8601 UTC with three fractional digits.
Input fields that take datetimes accept the same format.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.2 ISO 8601 UTC with three fractional digits
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


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def date_to_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Quarter/Saturday helpers — PRD §3.2, §3.3
# ---------------------------------------------------------------------------
def quarter_of(d: date) -> int:
    """Calendar quarter (1..4) containing date d."""
    return (d.month - 1) // 3 + 1


def quarter_start(year: int, quarter: int) -> date:
    """First day of the (year, quarter) calendar quarter."""
    month = (quarter - 1) * 3 + 1
    return date(year, month, 1)


def add_quarters(year: int, quarter: int, delta: int) -> tuple[int, int]:
    """Add `delta` calendar quarters to (year, quarter), returning the
    resulting (year, quarter)."""
    total = year * 4 + (quarter - 1) + delta
    new_year, new_q = divmod(total, 4)
    return new_year, new_q + 1


def previous_saturday_on_or_before(d: date) -> date:
    """Return the Saturday on or before d. ISO weekday: Mon=1..Sun=7."""
    # We want Saturday (weekday() == 5).
    delta = (d.weekday() - 5) % 7
    return d - timedelta(days=delta)


def next_saturday_strictly_after(d: date) -> date:
    """Return the first Saturday strictly after d."""
    sat = previous_saturday_on_or_before(d)
    if sat <= d:
        return sat + timedelta(days=7)
    return sat


def first_sunday_on_or_before(d: date) -> date:
    """First Sunday on or before d. weekday(): Mon=0..Sun=6."""
    delta = (d.weekday() + 1) % 7  # how many days back to last Sunday
    return d - timedelta(days=delta)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=length)
    )


def random_ssn_last4() -> str:
    return "".join(random.choices(string.digits, k=4))


def random_ein() -> str:
    return "".join(random.choices(string.digits, k=9))


def random_full_name() -> str:
    return f"Test Claimant {random_suffix(4)}"


def random_legal_name() -> str:
    return f"Test Employer {random_suffix(4)} LLC"


def random_program_name() -> str:
    return f"Test-PEUC-{random_suffix(4)}"


# ---------------------------------------------------------------------------
# Claimant — PRD §3.1
# ---------------------------------------------------------------------------
def create_claimant_payload(
    ssn_last4: Optional[str] = None,
    full_name: Optional[str] = None,
    state_residence: str = "CA",
    date_of_birth: str = "1985-06-15",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A claimant identity is created with a payload supplying
    ssn_last4 (exactly four digits, used only for identification),
    full_name, state_residence (a two-letter US state code matching the
    pattern of two uppercase letters), and date_of_birth (an ISO 8601
    calendar date).'"""
    payload: Dict[str, Any] = {
        "ssn_last4": ssn_last4 if ssn_last4 is not None else random_ssn_last4(),
        "full_name": full_name if full_name is not None else random_full_name(),
        "state_residence": state_residence,
        "date_of_birth": date_of_birth,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Employer — PRD §3.1
# ---------------------------------------------------------------------------
def create_employer_payload(
    ein: Optional[str] = None,
    legal_name: Optional[str] = None,
    reserve_ratio_basis_cents: int = 1_000_000,
    taxable_payroll_cents: int = 10_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'The payload supplies ein (exactly nine digits, unique
    across the system), legal_name, reserve_ratio_basis_cents (the
    long-run reserve dollars in the employer's account; must be strictly
    greater than zero), and taxable_payroll_cents (the preceding calendar
    year's total taxable wages; must be zero or positive).'"""
    payload: Dict[str, Any] = {
        "ein": ein if ein is not None else random_ein(),
        "legal_name": (
            legal_name if legal_name is not None else random_legal_name()
        ),
        "reserve_ratio_basis_cents": reserve_ratio_basis_cents,
        "taxable_payroll_cents": taxable_payroll_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WageRecord — PRD §3.1
# ---------------------------------------------------------------------------
def create_wage_record_payload(
    employer_id: str,
    quarter_year: int,
    quarter_index: int,
    wages_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'the body supplies employer_id, quarter_year (an integer
    at least 2000 and at most the current calendar year on the server
    clock), quarter_index (1 for January–March through 4 for
    October–December), and wages_cents (zero or positive).'"""
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "quarter_year": quarter_year,
        "quarter_index": quarter_index,
        "wages_cents": wages_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claim — PRD §3.2
# ---------------------------------------------------------------------------
def create_claim_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'A claimant opens a new claim by posting under their own
    claimant resource.'"""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def adjudicate_claim_payload(
    decision: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'The request body carries a decision of either ELIGIBLE
    or DENIED together with an optional version for the OCC check.'"""
    payload: Dict[str, Any] = {"decision": decision}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def apply_extension_payload(
    extension_id: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'a claimant whose claim has reached EXHAUSTED may request
    application of an active extension by posting an apply-extension
    action with an extension_id in the body and an optional version for
    OCC.'"""
    payload: Dict[str, Any] = {"extension_id": extension_id}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WeeklyCertification — PRD §3.3
# ---------------------------------------------------------------------------
def work_search_entry(
    contact_date: Optional[str] = None,
    employer_name: Optional[str] = None,
    contact_method: str = "ONLINE_APPLICATION",
) -> Dict[str, Any]:
    """PRD §3.3: 'each element of work_search_entries produces an
    immutable WorkSearchEntry row whose ... contact_date, employer_name,
    and contact_method (one of ONLINE_APPLICATION, IN_PERSON, PHONE,
    EMAIL, or REFERRAL) come from the submitted element.'"""
    return {
        "contact_date": (
            contact_date if contact_date is not None
            else date_to_iso(utcnow().date())
        ),
        "employer_name": (
            employer_name if employer_name is not None
            else f"Acme {random_suffix(4)}"
        ),
        "contact_method": contact_method,
    }


def n_work_search_entries(
    n: int,
    base_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Generate n distinct work-search entries with varied employer names."""
    if base_date is None:
        base_date = utcnow().date()
    return [
        work_search_entry(
            contact_date=date_to_iso(base_date - timedelta(days=i)),
            employer_name=f"Acme {i}-{random_suffix(3)}",
        )
        for i in range(n)
    ]


def create_weekly_certification_payload(
    week_ending_date: str,
    earnings_reported_cents: int = 0,
    able_and_available: bool = True,
    work_search_entries: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'The certification payload, posted under the parent claim,
    carries four pieces of evidence: week_ending_date (the ISO date
    marking the end of the calendar week being certified, which must be
    a Saturday); earnings_reported_cents (zero or positive);
    able_and_available (a boolean affirming the claimant was able to and
    available for work all week); and work_search_entries, an array of
    work-search contacts.'"""
    if work_search_entries is None:
        work_search_entries = n_work_search_entries(3)
    payload: Dict[str, Any] = {
        "week_ending_date": week_ending_date,
        "earnings_reported_cents": earnings_reported_cents,
        "able_and_available": able_and_available,
        "work_search_entries": work_search_entries,
    }
    payload.update(overrides)
    return payload


def audit_weekly_certification_payload(
    classification: str,
    reason: str = "Audit reason",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'An Adjudicator initiates an audit against an APPROVED
    certification, supplying a classification (one of AGENCY_ERROR,
    NON_FRAUD, or FRAUD), a free-text reason, and an optional version
    for OCC.'"""
    payload: Dict[str, Any] = {
        "classification": classification,
        "reason": reason,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Overpayment — PRD §3.5
# ---------------------------------------------------------------------------
def repay_overpayment_payload(
    amount_cents: int,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'A claimant who owes an outstanding overpayment recovers
    it by posting a repayment with amount_cents (and optional version).'"""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def waive_overpayment_payload(
    reason: str = "Waived per agency policy",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'An Adjudicator may waive an outstanding overpayment whose
    classification is in the set of AGENCY_ERROR or NON_FRAUD.'"""
    payload: Dict[str, Any] = {"reason": reason}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def write_off_payload(
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'An Adjudicator may also write off an outstanding
    overpayment, but only after the statute of limitations has elapsed.'"""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appeal — PRD §3.6
# ---------------------------------------------------------------------------
def create_appeal_payload(
    claim_id: str,
    subject_type: str,
    subject_id: str,
    assigned_appeal_officer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'A claimant files an appeal with a claim_id, a
    subject_type ..., a subject_id ..., and an
    assigned_appeal_officer_id naming the AppealOfficer who will
    hear it.'"""
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "assigned_appeal_officer_id": assigned_appeal_officer_id,
    }
    payload.update(overrides)
    return payload


def decide_appeal_payload(
    decision: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'An IN_HEARING appeal is decided by the same officer with
    a decision of either SUSTAINED or REVERSED (and optional version).'"""
    payload: Dict[str, Any] = {"decision": decision}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PandemicExtension — PRD §3.4
# ---------------------------------------------------------------------------
def create_pandemic_extension_payload(
    program_name: Optional[str] = None,
    effective_start: Optional[str] = None,
    effective_end: Optional[str] = None,
    extra_weeks: int = 13,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'A SystemAdmin can provision a pandemic emergency
    extension program — assigning a program_name (for example, a human
    label such as "PEUC-2026"), an effective_start and effective_end
    date pair, and an extra_weeks count between 1 and 26 inclusive.'"""
    payload: Dict[str, Any] = {
        "program_name": (
            program_name if program_name is not None
            else random_program_name()
        ),
        "effective_start": (
            effective_start if effective_start is not None
            else date_to_iso(utcnow().date())
        ),
        "effective_end": (
            effective_end if effective_end is not None
            else date_to_iso(utcnow().date() + timedelta(days=90))
        ),
        "extra_weeks": extra_weeks,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EmployerCharge relief — PRD §3.7
# ---------------------------------------------------------------------------
def relieve_charge_payload(
    reason: str = "Separation not employer's fault",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'the agent submits a charge-relief request, identifying
    the targeted charge via the charge_id path segment and supplying a
    reason in the body.'"""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SystemClock — PRD §2.9
# ---------------------------------------------------------------------------
def clock_advance_payload(seconds: int) -> Dict[str, Any]:
    """PRD §2.9: 'An admin-only test-driving capability advances the clock
    by a supplied number of seconds.'"""
    return {"seconds": seconds}


__all__ = [
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_hours", "add_days",
    "date_to_iso",
    "quarter_of", "quarter_start", "add_quarters",
    "previous_saturday_on_or_before", "next_saturday_strictly_after",
    "first_sunday_on_or_before",
    "random_suffix", "random_ssn_last4", "random_ein",
    "random_full_name", "random_legal_name", "random_program_name",
    "create_claimant_payload",
    "create_employer_payload",
    "create_wage_record_payload",
    "create_claim_payload",
    "adjudicate_claim_payload",
    "apply_extension_payload",
    "work_search_entry",
    "n_work_search_entries",
    "create_weekly_certification_payload",
    "audit_weekly_certification_payload",
    "repay_overpayment_payload",
    "waive_overpayment_payload",
    "write_off_payload",
    "create_appeal_payload",
    "decide_appeal_payload",
    "create_pandemic_extension_payload",
    "relieve_charge_payload",
    "clock_advance_payload",
]
