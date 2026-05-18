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
# Timestamp / date helpers — PRD §2.2 ISO 8601 UTC with three fractional
# digits for full instants; calendar dates for marriage_date /
# separation_date in YYYY-MM-DD.
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
                    hour: int = 0, minute: int = 0, second: int = 0,
                    millis: int = 0) -> str:
    """Build a deterministic ISO 8601 UTC instant."""
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0, millis: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(days=days, hours=hours,
                                    minutes=minutes, seconds=seconds,
                                    milliseconds=millis))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 instant (with trailing Z) to a UTC datetime."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def iso_calendar(d: date) -> str:
    """PRD §3.1 marriage_date / separation_date — calendar date in
    YYYY-MM-DD."""
    return d.isoformat()


def midnight_iso(d: date) -> str:
    """Midnight UTC instant for a calendar date — for any field PRD
    declares as a datetime that the scaffold pins to UTC midnight."""
    return iso_utc(datetime(d.year, d.month, d.day, 0, 0, 0,
                            tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


# ===========================================================================
# Clock — PRD §2.6
# ===========================================================================
def clock_advance_payload(*, to: str) -> Dict[str, Any]:
    """PRD §2.6: 'submitting a target instant in the to_timestamp
    field'."""
    return {"to_timestamp": to}


# ===========================================================================
# Case (POST /cases) — PRD §3.1
# ===========================================================================
def party_payload(
    *,
    full_name: str = "Test Party",
    date_of_birth: str = "1985-01-01",
    gross_monthly_income_cents: int = 300_000,
    counsel_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Nested party record on POST /cases.

    PRD §3.1: "each carrying full_name, date_of_birth,
    gross_monthly_income_cents ... and an optional counsel_user_id for
    an attorney of record."
    """
    body: Dict[str, Any] = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "gross_monthly_income_cents": gross_monthly_income_cents,
    }
    if counsel_user_id is not None:
        body["counsel_user_id"] = counsel_user_id
    return body


def create_case_payload(
    *,
    jurisdiction_state: str = "CA",
    marriage_date: str = TEST_DEFAULTS["DEFAULT_MARRIAGE_DATE"],
    separation_date: str = TEST_DEFAULTS["DEFAULT_SEPARATION_DATE"],
    has_minor_children: bool = True,
    petitioner: Optional[Dict[str, Any]] = None,
    respondent: Optional[Dict[str, Any]] = None,
    petitioner_full_name: str = "Alice Petitioner",
    petitioner_dob: str = "1985-01-01",
    petitioner_gross_cents: int = 300_000,
    petitioner_counsel_user_id: Optional[str] = None,
    respondent_full_name: str = "Bob Respondent",
    respondent_dob: str = "1984-01-01",
    respondent_gross_cents: int = 600_000,
    respondent_counsel_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cases. PRD §3.1: 'jurisdiction_state, marriage_date,
    separation_date, has_minor_children, and two nested party
    records — one petitioner and one respondent'."""
    if petitioner is None:
        petitioner = party_payload(
            full_name=petitioner_full_name,
            date_of_birth=petitioner_dob,
            gross_monthly_income_cents=petitioner_gross_cents,
            counsel_user_id=petitioner_counsel_user_id,
        )
    if respondent is None:
        respondent = party_payload(
            full_name=respondent_full_name,
            date_of_birth=respondent_dob,
            gross_monthly_income_cents=respondent_gross_cents,
            counsel_user_id=respondent_counsel_user_id,
        )
    return {
        "jurisdiction_state": jurisdiction_state,
        "marriage_date": marriage_date,
        "separation_date": separation_date,
        "has_minor_children": has_minor_children,
        "petitioner": petitioner,
        "respondent": respondent,
    }


# ===========================================================================
# FinancialDisclosure — PRD §3.2
# ===========================================================================
def create_disclosure_payload(
    *,
    party_id: str,
    gross_monthly_income_cents: int = 300_000,
    deductible_taxes_cents: int = 0,
    monthly_health_insurance_cents: int = 0,
    monthly_childcare_cents: int = 0,
    assets_total_cents: int = 0,
    debts_total_cents: int = 0,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/disclosures. PRD §3.2 names the seven input
    fields: 'party_id, gross_monthly_income_cents, deductible_taxes_cents,
    monthly_health_insurance_cents, monthly_childcare_cents,
    assets_total_cents, and debts_total_cents'."""
    return {
        "party_id": party_id,
        "gross_monthly_income_cents": gross_monthly_income_cents,
        "deductible_taxes_cents": deductible_taxes_cents,
        "monthly_health_insurance_cents": monthly_health_insurance_cents,
        "monthly_childcare_cents": monthly_childcare_cents,
        "assets_total_cents": assets_total_cents,
        "debts_total_cents": debts_total_cents,
    }


def patch_disclosure_payload(
    *,
    version: int,
    gross_monthly_income_cents: Optional[int] = None,
    deductible_taxes_cents: Optional[int] = None,
    monthly_health_insurance_cents: Optional[int] = None,
    monthly_childcare_cents: Optional[int] = None,
    assets_total_cents: Optional[int] = None,
    debts_total_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """PATCH /cases/{caseId}/disclosures/{disclosureId}.

    PRD §2.8: 'PATCH /cases/{caseId}/disclosures/{disclosureId} (which
    carries version plus any subset of the editable monetary fields)'.
    """
    body: Dict[str, Any] = {"version": version}
    if gross_monthly_income_cents is not None:
        body["gross_monthly_income_cents"] = gross_monthly_income_cents
    if deductible_taxes_cents is not None:
        body["deductible_taxes_cents"] = deductible_taxes_cents
    if monthly_health_insurance_cents is not None:
        body["monthly_health_insurance_cents"] = monthly_health_insurance_cents
    if monthly_childcare_cents is not None:
        body["monthly_childcare_cents"] = monthly_childcare_cents
    if assets_total_cents is not None:
        body["assets_total_cents"] = assets_total_cents
    if debts_total_cents is not None:
        body["debts_total_cents"] = debts_total_cents
    return body


def reject_disclosure_payload(
    *, rejection_reason: str = "incomplete documentation",
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/disclosures/{id}/reject. PRD §3.2: 'Rejecting
    it requires a rejection_reason in the request body'."""
    body: Dict[str, Any] = {"rejection_reason": rejection_reason}
    if version is not None:
        body["version"] = version
    return body


# ===========================================================================
# ParentingPlan — PRD §3.3
# ===========================================================================
def create_parenting_plan_payload(
    *,
    proposing_party_id: str,
    legal_custody: str = "JOINT",
    physical_custody: str = "JOINT",
    petitioner_overnights_per_year: int = 100,
    respondent_overnights_per_year: int = 265,
    countered_plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/parenting-plans.

    PRD §3.3: 'supplying the proposing_party_id ..., the legal_custody
    choice ..., the physical_custody choice ..., and the two overnight
    counts petitioner_overnights_per_year and
    respondent_overnights_per_year.'

    PRD §3.3: 'A plan can be countered by the other party by submitting
    a new plan whose body includes countered_plan_id pointing back at
    the plan being countered.'
    """
    body: Dict[str, Any] = {
        "proposing_party_id": proposing_party_id,
        "legal_custody": legal_custody,
        "physical_custody": physical_custody,
        "petitioner_overnights_per_year": petitioner_overnights_per_year,
        "respondent_overnights_per_year": respondent_overnights_per_year,
    }
    if countered_plan_id is not None:
        body["countered_plan_id"] = countered_plan_id
    return body


# ===========================================================================
# MediationSession — PRD §3.4
# ===========================================================================
def schedule_mediation_session_payload(
    *,
    mediator_user_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/mediation-sessions. PRD §3.4:
    'supplying mediator_user_id, scheduled_start_at, and
    scheduled_end_at'."""
    return {
        "mediator_user_id": mediator_user_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }


def complete_mediation_session_payload(
    *,
    outcome: str,
    parenting_plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/mediation-sessions/{id}/complete.

    PRD §3.4: 'Completion requires an outcome in the request
    (AGREEMENT, PARTIAL, or IMPASSE)'.
    PRD §3.4: 'When outcome is AGREEMENT or PARTIAL, the request must
    also carry a parenting_plan_id referring to a plan that belongs to
    the case.'
    """
    body: Dict[str, Any] = {"outcome": outcome}
    if parenting_plan_id is not None:
        body["parenting_plan_id"] = parenting_plan_id
    return body


# ===========================================================================
# SupportOrder — PRD §3.5
# ===========================================================================
def create_support_order_payload(
    *,
    support_type: str,
    order_kind: str,
    parenting_plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/support-orders.

    PRD §3.5: 'A SupportOrder is created by a Judge via a request
    carrying support_type (either CHILD or SPOUSAL), order_kind (either
    TEMPORARY or FINAL), and — only for CHILD orders —
    parenting_plan_id.'
    """
    body: Dict[str, Any] = {
        "support_type": support_type,
        "order_kind": order_kind,
    }
    if parenting_plan_id is not None:
        body["parenting_plan_id"] = parenting_plan_id
    return body


def terminate_support_order_payload(
    *,
    obligee_remarried: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/support-orders/{id}/terminate.

    PRD §3.5: 'For a SPOUSAL order, termination is permitted when the
    request body's obligee_remarried flag is true.'
    """
    body: Dict[str, Any] = {}
    if obligee_remarried is not None:
        body["obligee_remarried"] = obligee_remarried
    return body


# ===========================================================================
# TemporaryOrder — PRD §3.6
# ===========================================================================
def create_temp_order_payload(
    *,
    parenting_plan_id: Optional[str] = None,
    child_support_order_id: Optional[str] = None,
    spousal_support_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/temp-orders.

    PRD §3.6: 'when has_minor_children is true, the body must carry
    both parenting_plan_id and child_support_order_id, and may
    optionally carry spousal_support_order_id; when has_minor_children
    is false, both parenting_plan_id and child_support_order_id must be
    null, and only spousal_support_order_id (if any) is supplied.'
    """
    body: Dict[str, Any] = {}
    # PRD declares all three fields as part of the body; we include them
    # explicitly (using null for absence) so the field-combination
    # validator can be exercised faithfully.
    body["parenting_plan_id"] = parenting_plan_id
    body["child_support_order_id"] = child_support_order_id
    body["spousal_support_order_id"] = spousal_support_order_id
    return body


def issue_temp_order_payload(*, temporary_order_id: str) -> Dict[str, Any]:
    """POST /cases/{caseId}/issue-temp-order."""
    return {"temporary_order_id": temporary_order_id}


# ===========================================================================
# FinalJudgment — PRD §3.6
# ===========================================================================
def create_final_judgment_payload(
    *,
    parenting_plan_id: Optional[str] = None,
    child_support_order_id: Optional[str] = None,
    spousal_support_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/final-judgments.

    PRD §3.6: 'A Judge creates a FinalJudgment in DRAFT, with the same
    field-combination rules on parenting_plan_id, child_support_order_id,
    and spousal_support_order_id as the temporary order (governed by
    has_minor_children).'
    """
    body: Dict[str, Any] = {}
    body["parenting_plan_id"] = parenting_plan_id
    body["child_support_order_id"] = child_support_order_id
    body["spousal_support_order_id"] = spousal_support_order_id
    return body


def issue_final_judgment_payload(
    *, final_judgment_id: str,
) -> Dict[str, Any]:
    """POST /cases/{caseId}/issue-final-judgment."""
    return {"final_judgment_id": final_judgment_id}


# ===========================================================================
# Dismiss — PRD §3.1
# ===========================================================================
def dismiss_case_payload(*, reason: str = "settled out of court") -> Dict[str, Any]:
    """POST /cases/{caseId}/dismiss. PRD §3.1: 'A Judge may also dismiss
    the case while it is in FILED or AWAITING_ANSWER, supplying a
    free-text reason'."""
    return {"reason": reason}


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "iso_offset",
    "parse_iso",
    "iso_calendar",
    "midnight_iso",
    "random_suffix",
    "clock_advance_payload",
    "party_payload",
    "create_case_payload",
    "create_disclosure_payload",
    "patch_disclosure_payload",
    "reject_disclosure_payload",
    "create_parenting_plan_payload",
    "schedule_mediation_session_payload",
    "complete_mediation_session_payload",
    "create_support_order_payload",
    "terminate_support_order_payload",
    "create_temp_order_payload",
    "issue_temp_order_payload",
    "create_final_judgment_payload",
    "issue_final_judgment_payload",
    "dismiss_case_payload",
]
