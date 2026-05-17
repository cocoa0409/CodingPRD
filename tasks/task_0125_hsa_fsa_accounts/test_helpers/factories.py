"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.5: monetary fields are integer cents.
PRD §2.5: date arithmetic uses UTC calendar dates.
PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Random id / string helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_full_name(prefix: str = "Test Holder") -> str:
    return f"{prefix} {random_suffix(6)}"


def random_ssn_last4() -> str:
    """PRD §3.1: 'ssn_last4, which must be exactly four numeric digits'.
    Returns a string of 4 random digits."""
    return "".join(random.choices(string.digits, k=4))


def random_expense_code(prefix: str = "MED") -> str:
    return f"{prefix}_{random_suffix(6).upper()}"


# ---------------------------------------------------------------------------
# Date / time helpers — PRD §2.5, §2.7
# ---------------------------------------------------------------------------
def iso_date_str(d: date) -> str:
    """ISO 8601 calendar date in YYYY-MM-DD form."""
    return d.isoformat()


def iso_datetime_utc(year: int, month: int, day: int,
                     hour: int = 0, minute: int = 0,
                     second: int = 0) -> str:
    """ISO 8601 UTC instant in YYYY-MM-DDTHH:MM:SSZ form. PRD §2.7
    accepts this form for clock advance and OpsRun.as_of_date."""
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


def iso_now_utc() -> str:
    """PRD §2.2 ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(tz=timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ===========================================================================
# Clock control — PRD §2.7, §4
# ===========================================================================
def clock_advance_payload(*, to: str) -> Dict[str, Any]:
    """PRD §2.7: 'a write endpoint advances it to a supplied to
    instant'."""
    return {"to": to}


# ===========================================================================
# AccountHolder — PRD §3.1
# ===========================================================================
def create_account_holder_payload(
    *,
    full_name: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    tax_filing_status: str = "SINGLE",
    birth_date: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: full_name, ssn_last4, tax_filing_status,
    birth_date.

    Defaults choose values that satisfy:
    - full_name non-empty string
    - ssn_last4 exactly 4 numeric digits
    - tax_filing_status in {SINGLE, MARRIED_JOINT, MARRIED_SEPARATE,
      HEAD_OF_HOUSEHOLD}
    - birth_date is a real past date
    """
    return {
        "full_name": full_name if full_name is not None else random_full_name(),
        # Use 'is None' so callers can drive ERR_BAD_REQUEST tests by
        # passing an empty string or other falsy invalid value.
        "ssn_last4": ssn_last4 if ssn_last4 is not None else random_ssn_last4(),
        "tax_filing_status": tax_filing_status,
        "birth_date": birth_date if birth_date is not None else iso_date_str(date(1980, 1, 1)),
    }


# ===========================================================================
# Dependent — PRD §3.1
# ===========================================================================
def create_dependent_payload(
    *,
    full_name: Optional[str] = None,
    birth_date: Optional[str] = None,
    relationship: str = "CHILD",
) -> Dict[str, Any]:
    """PRD §3.1: 'Adding a dependent to an account holder accepts the
    dependent's full_name, birth_date, and relationship (one of CHILD,
    SPOUSE, or QUALIFYING_RELATIVE).'"""
    return {
        "full_name": full_name or random_full_name(prefix="Test Dep"),
        "birth_date": birth_date or iso_date_str(date(2010, 6, 1)),
        "relationship": relationship,
    }


# ===========================================================================
# Account — PRD §3.1
# ===========================================================================
def create_account_payload(
    *,
    account_holder_id: str,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    account_holder_birth_date: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: account_holder_id, account_type
    (HSA|HEALTH_FSA|DEPENDENT_CARE_FSA), coverage_tier (required iff
    HSA), year_end_policy, account_holder_birth_date.

    Defaults to an HSA SELF_ONLY account with NONE policy. The caller
    is responsible for choosing valid combinations:
    - HSA: coverage_tier in {SELF_ONLY, FAMILY}; year_end_policy == NONE
    - HEALTH_FSA: coverage_tier null; year_end_policy in
      {GRACE_PERIOD, CARRYOVER, NONE}
    - DEPENDENT_CARE_FSA: coverage_tier null; year_end_policy in
      {GRACE_PERIOD, NONE}
    """
    payload: Dict[str, Any] = {
        "account_holder_id": account_holder_id,
        "account_type": account_type,
        "year_end_policy": year_end_policy,
        "account_holder_birth_date": (
            account_holder_birth_date or iso_date_str(date(1980, 1, 1))
        ),
    }
    if account_type == "HSA":
        payload["coverage_tier"] = coverage_tier or "SELF_ONLY"
    else:
        # PRD §3.1: 'for either FSA type, coverage_tier must be null'.
        payload["coverage_tier"] = None
    return payload


# ===========================================================================
# PlanYear — PRD §3.2
# ===========================================================================
def create_plan_year_payload(*, calendar_year: int) -> Dict[str, Any]:
    """PRD §3.2: 'A PlanYear is opened by a PlanAdministrator against
    an account by supplying a calendar_year — a four-digit integer
    such as 2025.'"""
    return {"calendar_year": calendar_year}


# ===========================================================================
# Contribution — PRD §3.3
# ===========================================================================
def create_contribution_payload(
    *,
    amount_cents: int,
    source: str = "PAYROLL",
) -> Dict[str, Any]:
    """PRD §3.3 inputs: amount_cents (positive integer >= 1) and
    source in {PAYROLL, DIRECT, EMPLOYER_MATCH}."""
    return {
        "amount_cents": amount_cents,
        "source": source,
    }


# ===========================================================================
# QualifiedExpense — PRD §3.4
# ===========================================================================
def create_qualified_expense_payload(
    *,
    code: Optional[str] = None,
    category: str = "MEDICAL",
    eligible_account_types: Optional[List[str]] = None,
    requires_dependent: bool = False,
) -> Dict[str, Any]:
    """PRD §3.4 inputs: code (unique IRS-style code), category, an
    eligible_account_types array listing the subset of
    {HSA, HEALTH_FSA, DEPENDENT_CARE_FSA} that may file against this
    code, and requires_dependent (boolean)."""
    return {
        "code": code or random_expense_code(),
        "category": category,
        "eligible_account_types": (
            eligible_account_types
            if eligible_account_types is not None
            else ["HSA", "HEALTH_FSA"]
        ),
        "requires_dependent": requires_dependent,
    }


# ===========================================================================
# Claim — PRD §3.5
# ===========================================================================
def create_claim_payload(
    *,
    service_date: str,
    expense_code: str,
    amount_cents: int,
    dependent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.5: 'An AccountHolder creates a claim against their own
    account by posting service_date, expense_code, amount_cents, and
    optionally dependent_id.'"""
    payload: Dict[str, Any] = {
        "service_date": service_date,
        "expense_code": expense_code,
        "amount_cents": amount_cents,
    }
    if dependent_id is not None:
        payload["dependent_id"] = dependent_id
    return payload


def deny_claim_payload(*, denial_reason: str) -> Dict[str, Any]:
    """PRD §3.5: 'The request body must include a denial_reason;
    absence of a denial reason returns ERR_DENIAL_REASON_REQUIRED.'"""
    return {"denial_reason": denial_reason}


# ===========================================================================
# OpsRun — PRD §3.7
# ===========================================================================
def create_ops_run_payload(*, kind: str, as_of_date: str) -> Dict[str, Any]:
    """PRD §3.7: 'An ops run accepts a kind (either YEAR_END_CLOSE or
    GRACE_PERIOD_EXPIRY) and an as_of_date — the logical date the run
    treats as today.'"""
    return {
        "kind": kind,
        "as_of_date": as_of_date,
    }


# ===========================================================================
# Optional-version helper — PRD §2.4
# ===========================================================================
def version_body(version: Optional[int]) -> Dict[str, Any]:
    """Build an OCC body fragment carrying `version` only when supplied.

    PRD §2.4: 'Any mutating request body may optionally include a
    version field. If supplied, the server compares it to the current
    version of the target resource: a mismatch is rejected with
    ERR_INVALID_STATE (the system's optimistic-concurrency error). If
    version is omitted from the body, the check is skipped and the
    operation proceeds against whatever the current state is.'
    """
    return {"version": version} if version is not None else {}


__all__ = [
    "random_suffix",
    "random_full_name",
    "random_ssn_last4",
    "random_expense_code",
    "iso_date_str",
    "iso_datetime_utc",
    "iso_now_utc",
    "clock_advance_payload",
    "create_account_holder_payload",
    "create_dependent_payload",
    "create_account_payload",
    "create_plan_year_payload",
    "create_contribution_payload",
    "create_qualified_expense_payload",
    "create_claim_payload",
    "deny_claim_payload",
    "create_ops_run_payload",
    "version_body",
]
