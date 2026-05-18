"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted so
the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.9: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp produced by iso_utc."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def iso_instant_utc(year: int, month: int, day: int, hour: int = 0,
                    minute: int = 0, second: int = 0) -> str:
    """Build an ISO 8601 UTC instant with .000Z millis."""
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Random-id helpers — random string suffixes for unique labels/names.
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


# ---------------------------------------------------------------------------
# Debtor — PRD §3.1
# ---------------------------------------------------------------------------
def create_debtor_payload(
    *,
    full_name: Optional[str] = None,
    household_size: Optional[int] = None,
    state_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /debtors — Debtor only.

    PRD §3.1: "registers a Debtor profile by supplying their full_name,
    their household_size (which must be at least 1 ...), and a state_code
    consisting of exactly two uppercase letters identifying the state".
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Debtor {random_suffix(4)}"
        ),
        "household_size": (
            household_size if household_size is not None
            else TEST_DEFAULTS["HOUSEHOLD_SIZE"]
        ),
        "state_code": state_code or TEST_DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Creditor — PRD §3.1
# ---------------------------------------------------------------------------
def create_creditor_payload(
    *,
    name: Optional[str] = None,
    creditor_type: str = "GENERAL_UNSECURED",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /creditors — Creditor only.

    PRD §3.1: "registers a Creditor profile by supplying a name and a
    creditor_type of SECURED, PRIORITY, or GENERAL_UNSECURED".
    """
    payload: Dict[str, Any] = {
        "name": name if name is not None
        else f"Creditor {random_suffix(4)}",
        "creditor_type": creditor_type,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Case — PRD §3.1
# ---------------------------------------------------------------------------
def create_case_payload(
    *,
    debtor_id: str,
    chapter_requested: str = "CHAPTER_7",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cases — Debtor only.

    PRD §3.1: "A debtor opens a Case by submitting debtor_id and the
    desired chapter_requested (either CHAPTER_7 or CHAPTER_13)."
    """
    payload: Dict[str, Any] = {
        "debtor_id": debtor_id,
        "chapter_requested": chapter_requested,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Schedule — PRD §3.2
# ---------------------------------------------------------------------------
def create_schedule_payload(
    *,
    schedule_type: str,
    line_items: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/schedules — Debtor only.

    PRD §3.2: "identified by schedule_type (taking exactly one of the
    ten enumerated values A, B, C, D, E, F, G, H, I, or J) and a
    line_items array, where each entry carries a label and an
    amount_cents integer".
    """
    payload: Dict[str, Any] = {
        "schedule_type": schedule_type,
        "line_items": line_items if line_items is not None else [],
    }
    payload.update(overrides)
    return payload


def income_line(amount_cents: int, label: str = "wages") -> Dict[str, Any]:
    """Helper to build a single Schedule line_items entry. PRD §3.2:
    'each entry carries a label and an amount_cents integer'."""
    return {"label": label, "amount_cents": amount_cents}


def six_month_income_lines(
    *, per_month_cents: int, label: str = "wages",
) -> List[Dict[str, Any]]:
    """Build a Schedule I payload with six identical monthly entries.

    PRD §3.3: means test "takes the income line items and sums the
    amount_cents over the most recent six months of those line items".
    """
    return [income_line(per_month_cents, label) for _ in range(6)]


# ---------------------------------------------------------------------------
# Schedule-341 — PRD §3.5
# ---------------------------------------------------------------------------
def schedule_341_payload(
    *,
    meeting_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/schedule-341 — Trustee only.

    PRD §3.5: "the trustee supplies a meeting_date value and the server
    records it on the case as meeting_341_date".
    """
    payload: Dict[str, Any] = {"meeting_date": meeting_date}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claim — PRD §3.6
# ---------------------------------------------------------------------------
def create_claim_payload(
    *,
    creditor_id: str,
    claim_class: str,
    amount_cents: int,
    is_dischargeable: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/claims — Creditor only.

    PRD §3.6: "Creditors file Claim rows against an open case by
    submitting creditor_id, claim_class, amount_cents, and
    is_dischargeable."
    """
    payload: Dict[str, Any] = {
        "creditor_id": creditor_id,
        "claim_class": claim_class,
        "amount_cents": amount_cents,
        "is_dischargeable": is_dischargeable,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plan — PRD §3.8
# ---------------------------------------------------------------------------
def create_plan_payload(
    *,
    proposed_monthly_payment_cents: int,
    plan_months: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/plans — Debtor only.

    PRD §3.8: "The plan payload carries the debtor's
    proposed_monthly_payment_cents (the amount the debtor commits to pay
    the trustee each month) and plan_months (the duration of the plan)."
    """
    payload: Dict[str, Any] = {
        "proposed_monthly_payment_cents": proposed_monthly_payment_cents,
        "plan_months": plan_months,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TrusteePayment — PRD §3.9
# ---------------------------------------------------------------------------
def create_payment_payload(
    *,
    sequence_number: int,
    amount_cents: int,
    status: str = "APPLIED",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cases/{case_id}/plans/{plan_id}/payments — Debtor or
    Trustee.

    PRD §3.9: "Each payment carries a sequence_number (the monthly
    index, unique per plan and in the range from 1 to the plan's
    plan_months inclusive), an amount_cents, and a status of either
    APPLIED (paid) or MISSED (recorded missed month)."
    """
    payload: Dict[str, Any] = {
        "sequence_number": sequence_number,
        "amount_cents": amount_cents,
        "status": status,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CollectionAction — PRD §2.7 / §4
# ---------------------------------------------------------------------------
def create_collection_action_payload(
    *,
    creditor_id: str,
    case_id: str,
    action_kind: str = "GARNISH",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /collection-actions — Creditor only.

    PRD §2.7: "every collection attempt — whether of action_kind
    GARNISH, LIEN, LAWSUIT, or DUNNING_LETTER — is recorded but
    blocked".
    """
    payload: Dict[str, Any] = {
        "creditor_id": creditor_id,
        "case_id": case_id,
        "action_kind": action_kind,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock — PRD §3.5 (test-only)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to_iso8601: str,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance — Trustee.

    PRD §3.5: "the system exposes an admin-only clock-advancement
    capability that accepts a to_iso8601 parameter and sets the server
    clock to that instant".
    """
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OCC version body — PRD §2.8
# ---------------------------------------------------------------------------
def version_body(version: Optional[int]) -> Dict[str, Any]:
    """Build an action payload carrying an optional version field per
    PRD §2.8 OCC contract."""
    return {} if version is None else {"version": version}


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "iso_instant_utc",
    "random_suffix",
    "create_debtor_payload",
    "create_creditor_payload",
    "create_case_payload",
    "create_schedule_payload",
    "income_line",
    "six_month_income_lines",
    "schedule_341_payload",
    "create_claim_payload",
    "create_plan_payload",
    "create_payment_payload",
    "create_collection_action_payload",
    "clock_advance_payload",
    "version_body",
]
