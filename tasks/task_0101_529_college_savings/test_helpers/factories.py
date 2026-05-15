"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed fields are intentionally omitted so the
implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.8: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import CADENCE_MONTHLY_DAYS, TEST_DEFAULTS


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


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_ssn_last_four() -> str:
    return "".join(random.choices(string.digits, k=4))


def date_in_year(year: int, month: int = 6, day: int = 15) -> str:
    """ISO 8601 date string YYYY-MM-DD for use as `incurred_on` or
    `date_of_birth`."""
    return date(year, month, day).isoformat()


# ---------------------------------------------------------------------------
# Donor — PRD §3.1
# ---------------------------------------------------------------------------
def create_donor_payload(
    *,
    full_name: Optional[str] = None,
    state_of_residence: str = "NY",
    ssn_last_four: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /donors — PlanAdministrator only.

    PRD §3.1: required input fields are full_name, state_of_residence,
    ssn_last_four.
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Donor {random_suffix(4)}"
        ),
        "state_of_residence": state_of_residence,
        "ssn_last_four": ssn_last_four or random_ssn_last_four(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Beneficiary — PRD §3.1
# ---------------------------------------------------------------------------
def create_beneficiary_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    ssn_last_four: Optional[str] = None,
    relationship_family_code: str = "CHILD",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /beneficiaries — Donor or PlanAdministrator.

    PRD §3.1: required input fields are full_name, date_of_birth,
    ssn_last_four, relationship_family_code (one of SELF, CHILD,
    SIBLING, NIECE_NEPHEW, PARENT, COUSIN, SPOUSE, IN_LAW,
    FIRST_COUSIN_ONCE_REMOVED).
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Beneficiary {random_suffix(4)}"
        ),
        "date_of_birth": date_of_birth or TEST_DEFAULTS[
            "DEFAULT_BENEFICIARY_DOB"
        ],
        "ssn_last_four": ssn_last_four or random_ssn_last_four(),
        "relationship_family_code": relationship_family_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Account — PRD §3.2
# ---------------------------------------------------------------------------
def create_account_payload(
    *,
    primary_donor_id: str,
    beneficiary_id: str,
    state_plan_code: str = "NY",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /accounts — Donor only.

    PRD §3.2: required input fields are primary_donor_id, beneficiary_id,
    state_plan_code.
    """
    payload: Dict[str, Any] = {
        "primary_donor_id": primary_donor_id,
        "beneficiary_id": beneficiary_id,
        "state_plan_code": state_plan_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contribution — PRD §3.3
# ---------------------------------------------------------------------------
def create_contribution_payload(
    *,
    donor_id: str,
    amount_cents: int = 100_000,
    contribution_kind: str = "LUMP_SUM",
    recurring_plan_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /accounts/{id}/contributions — Donor only.

    PRD §3.3: input fields are donor_id, amount_cents, contribution_kind,
    optional recurring_plan_id (null when LUMP_SUM).
    """
    payload: Dict[str, Any] = {
        "donor_id": donor_id,
        "amount_cents": amount_cents,
        "contribution_kind": contribution_kind,
        "recurring_plan_id": recurring_plan_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RecurringPlan — PRD §3.3, §3.4
# ---------------------------------------------------------------------------
def create_recurring_plan_payload(
    *,
    donor_id: str,
    amount_cents: int = 50_000,
    cadence_days: int = CADENCE_MONTHLY_DAYS,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /accounts/{id}/recurring-plans — Donor only.

    PRD §3.3: required input fields are donor_id, amount_cents,
    cadence_days (one of 7, 14, 30, 90, 365).
    """
    payload: Dict[str, Any] = {
        "donor_id": donor_id,
        "amount_cents": amount_cents,
        "cadence_days": cadence_days,
    }
    payload.update(overrides)
    return payload


def patch_recurring_plan_payload(
    *,
    amount_cents: Optional[int] = None,
    cadence_days: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /recurring-plans/{id} — Donor only.

    PRD §2.5 + §3.4: optional amount_cents, cadence_days, and `version`.
    Omitting `version` skips the OCC check; supplying a stale value
    yields ERR_VERSION_CONFLICT.
    """
    payload: Dict[str, Any] = {}
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    if cadence_days is not None:
        payload["cadence_days"] = cadence_days
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Withdrawal — PRD §3.5
# ---------------------------------------------------------------------------
def create_withdrawal_payload(
    *,
    requested_amount_cents: int,
    expense_category: str = "POST_SECONDARY_TUITION",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /accounts/{id}/withdrawals — Donor only.

    PRD §3.5: required input fields are requested_amount_cents (strictly
    > 0) and expense_category (POST_SECONDARY_TUITION, ROOM_AND_BOARD,
    BOOKS_SUPPLIES, K_12, NON_QUALIFIED).
    """
    payload: Dict[str, Any] = {
        "requested_amount_cents": requested_amount_cents,
        "expense_category": expense_category,
    }
    payload.update(overrides)
    return payload


def reject_withdrawal_payload(
    *,
    rejected_reason: str = "INSUFFICIENT_BALANCE",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /withdrawals/{id}/reject — PlanAdministrator only.

    PRD §3.5: required input field is rejected_reason, one of
    INSUFFICIENT_BALANCE, ACCOUNT_RESTRICTED, K12_CAP_WOULD_EXCEED,
    EXPENSE_RECEIPT_MISSING.
    """
    payload: Dict[str, Any] = {"rejected_reason": rejected_reason}
    payload.update(overrides)
    return payload


def attach_education_expense_payload(
    *,
    institution_name: Optional[str] = None,
    category: str = "POST_SECONDARY_TUITION",
    amount_cents: int = 100_000,
    incurred_on: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /withdrawals/{id}/expenses — Donor only.

    PRD §3.5: required input fields are institution_name (non-empty, at
    most 200 chars), category, amount_cents (> 0), incurred_on (ISO 8601
    date in the same calendar year as the disbursement).
    """
    payload: Dict[str, Any] = {
        "institution_name": institution_name
        or f"School {random_suffix(4)}",
        "category": category,
        "amount_cents": amount_cents,
        "incurred_on": incurred_on or date.today().isoformat(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# BeneficiaryChangeRequest — PRD §3.6
# ---------------------------------------------------------------------------
def create_beneficiary_change_request_payload(
    *,
    proposed_beneficiary_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /accounts/{id}/beneficiary-change-requests — Donor only.

    PRD §3.6: required input field is proposed_beneficiary_id. The
    current_beneficiary_id snapshot is captured by the server from
    Account.beneficiary_id at submit time and is NOT an input.
    """
    payload: Dict[str, Any] = {
        "proposed_beneficiary_id": proposed_beneficiary_id,
    }
    payload.update(overrides)
    return payload


def reject_beneficiary_change_request_payload(
    *,
    rejection_reason: str = "RELATIONSHIP_NOT_PERMITTED",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /beneficiary-change-requests/{id}/reject — PlanAdministrator.

    PRD §3.6: required input field is rejection_reason, one of
    RELATIONSHIP_NOT_PERMITTED, GENERATION_SKIP, ACCOUNT_NOT_OPEN,
    IDENTICAL_TO_CURRENT.
    """
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TaxReport — PRD §3.7
# ---------------------------------------------------------------------------
def create_tax_report_payload(
    *,
    account_id: str,
    tax_year: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-reports — PlanAdministrator only.

    PRD §3.7: required input fields are account_id and tax_year (>= 2000).
    """
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "tax_year": tax_year,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# StateRule — PRD §3.1
# ---------------------------------------------------------------------------
def create_state_rule_payload(
    *,
    state_code: str,
    deduction_cap_cents: int = 500_000,
    parity: str = "PARITY",
    lifetime_aggregate_cap_cents: int = 500_000_000,
    k12_qualified: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /state-rules — PlanAdministrator only.

    PRD §3.1: required input fields are state_code, deduction_cap_cents,
    parity (IN_STATE_ONLY or PARITY), lifetime_aggregate_cap_cents
    (> 0), k12_qualified.
    """
    payload: Dict[str, Any] = {
        "state_code": state_code,
        "deduction_cap_cents": deduction_cap_cents,
        "parity": parity,
        "lifetime_aggregate_cap_cents": lifetime_aggregate_cap_cents,
        "k12_qualified": k12_qualified,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §3.8
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    to_iso8601: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — PlanAdministrator only.

    PRD §3.8: required input field is to_iso8601. Time only moves
    forward; advancing backward returns ERR_CLOCK_NOT_MOVING_FORWARD.
    """
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "random_suffix",
    "random_ssn_last_four",
    "date_in_year",
    "create_donor_payload",
    "create_beneficiary_payload",
    "create_account_payload",
    "create_contribution_payload",
    "create_recurring_plan_payload",
    "patch_recurring_plan_payload",
    "create_withdrawal_payload",
    "reject_withdrawal_payload",
    "attach_education_expense_payload",
    "create_beneficiary_change_request_payload",
    "reject_beneficiary_change_request_payload",
    "create_tax_report_payload",
    "create_state_rule_payload",
    "clock_advance_payload",
]
