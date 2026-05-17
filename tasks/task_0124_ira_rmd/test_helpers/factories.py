"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.8: monetary fields are integer cents.
PRD §3.1: dates are ISO 8601 YYYY-MM-DD.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Random id / string helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_full_name() -> str:
    return f"Test Participant {random_suffix(6)}"


# ---------------------------------------------------------------------------
# Date / time helpers — PRD §3.1 (date-only) and §2.4 (timestamps)
# ---------------------------------------------------------------------------
def iso_date_str(d: date) -> str:
    """PRD §3.1: ISO 8601 calendar date in YYYY-MM-DD form."""
    return d.isoformat()


def date_n_years_ago(years: int, *, base: Optional[date] = None) -> date:
    base = base or date(2026, 1, 2)
    # Anchor to a fixed reference date to avoid clock drift across tests;
    # subtract `years` years preserving month/day, clamping Feb 29.
    try:
        return date(base.year - years, base.month, base.day)
    except ValueError:
        # Feb 29 in a non-leap year — back off one day.
        return date(base.year - years, base.month, base.day - 1)


def iso_now_utc() -> str:
    """PRD §2.4 ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(tz=timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ===========================================================================
# Clock control — PRD §2.10
# ===========================================================================
def clock_advance_payload(*, days: int) -> Dict[str, Any]:
    """PRD §2.10: 'Advancing the clock by a given number of days'.
    The body field is `days` (integer)."""
    return {"days": days}


# ===========================================================================
# Participant — PRD §3.1
# ===========================================================================
def create_participant_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    tax_status: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: full_name, date_of_birth, tax_status.

    Defaults choose values that satisfy:
    - full_name 1..120 chars non-empty after trim
    - date_of_birth a real past date placing age >= 18 on creation
    - tax_status in {SINGLE, MARRIED_JOINT, MARRIED_SEPARATE, HEAD_OF_HOUSEHOLD}
    """
    payload: Dict[str, Any] = {
        "full_name": full_name or random_full_name(),
        "date_of_birth": date_of_birth or iso_date_str(
            date_n_years_ago(40),
        ),
        "tax_status": tax_status or "SINGLE",
    }
    return payload


def update_participant_payload(
    *,
    full_name: Optional[str] = None,
    tax_status: Optional[str] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.1: 'A custodian may later amend a participant's full_name
    and tax_status; these are the only two fields the update operation
    accepts.' PRD §2.5: optional `version` for OCC."""
    payload: Dict[str, Any] = {}
    if full_name is not None:
        payload["full_name"] = full_name
    if tax_status is not None:
        payload["tax_status"] = tax_status
    if version is not None:
        payload["version"] = version
    return payload


def decease_participant_payload(*, date_of_death: str) -> Dict[str, Any]:
    """PRD §3.1: 'a custodian records the death by submitting a
    date_of_death (ISO 8601 date)'."""
    return {"date_of_death": date_of_death}


# ===========================================================================
# Account — PRD §3.2
# ===========================================================================
def create_account_payload(
    *,
    account_type: str = "TRADITIONAL",
    inherited_from_participant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.2 inputs: account_type (TRADITIONAL|ROTH) and optional
    inherited_from_participant_id."""
    payload: Dict[str, Any] = {"account_type": account_type}
    if inherited_from_participant_id is not None:
        payload["inherited_from_participant_id"] = (
            inherited_from_participant_id
        )
    return payload


# ===========================================================================
# Contribution — PRD §3.3
# ===========================================================================
def create_contribution_payload(
    *,
    amount_cents: int,
    contribution_type: str = "REGULAR",
) -> Dict[str, Any]:
    """PRD §3.3 inputs: amount_cents (positive int) and contribution_type
    in {REGULAR, CATCHUP, BACKDOOR_NONDEDUCTIBLE}."""
    return {
        "amount_cents": amount_cents,
        "contribution_type": contribution_type,
    }


# ===========================================================================
# Distribution — PRD §3.4
# ===========================================================================
def create_distribution_payload(
    *,
    gross_amount_cents: int,
    distribution_reason: str = "NORMAL",
) -> Dict[str, Any]:
    """PRD §3.4 inputs: gross_amount_cents (positive int) and
    distribution_reason in {NORMAL, EARLY, RMD, DEATH, CONVERSION,
    EXCESS_REMOVAL}."""
    return {
        "gross_amount_cents": gross_amount_cents,
        "distribution_reason": distribution_reason,
    }


# ===========================================================================
# Conversion request — PRD §3.7
# ===========================================================================
def create_conversion_request_payload(
    *,
    source_account_id: str,
    destination_account_id: str,
    amount_cents: int,
    backdoor_flag: Optional[bool] = None,
) -> Dict[str, Any]:
    """PRD §3.7 inputs: source_account_id, destination_account_id,
    amount_cents (positive int), optional backdoor_flag (default false)."""
    payload: Dict[str, Any] = {
        "source_account_id": source_account_id,
        "destination_account_id": destination_account_id,
        "amount_cents": amount_cents,
    }
    if backdoor_flag is not None:
        payload["backdoor_flag"] = backdoor_flag
    return payload


# ===========================================================================
# Optional-version helper — PRD §2.5
# ===========================================================================
def version_body(version: Optional[int]) -> Dict[str, Any]:
    """Build an OCC body fragment carrying `version` only when supplied.

    PRD §2.5: "If version is omitted from the request body, the server
    skips the concurrency check and processes the mutation
    unconditionally."
    """
    return {"version": version} if version is not None else {}


__all__ = [
    "random_suffix",
    "random_full_name",
    "iso_date_str",
    "date_n_years_ago",
    "iso_now_utc",
    "clock_advance_payload",
    "create_participant_payload",
    "update_participant_payload",
    "decease_participant_payload",
    "create_account_payload",
    "create_contribution_payload",
    "create_distribution_payload",
    "create_conversion_request_payload",
    "version_body",
]
