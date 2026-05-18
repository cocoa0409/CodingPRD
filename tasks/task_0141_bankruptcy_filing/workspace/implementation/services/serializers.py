"""Serializers — convert stored dict rows to API JSON, omitting internal fields.

PRD §2.4 — mutable entities (Debtor, Case, Creditor, Claim, Plan) carry
created_at + updated_at + version; immutable/append-only entities (Schedule,
MeansTestResult, TrusteePayment, CollectionAction) carry only id + created_at.

The serializers project the in-memory rows to wire format, hiding
implementation-internal fields like _id_seq or other private keys.
"""

from services.calculations import compute_schedule_completeness, compute_total_unsecured_pool
from db import store


# ---------------------------------------------------------------------------
# Debtor
# ---------------------------------------------------------------------------
def serialize_debtor(debtor: dict) -> dict:
    # total_cases_filed is computed: count of cases for this debtor where
    # status != WITHDRAWN_PRE_FILE.
    total_cases_filed = 0
    for case in store.cases.values():
        if case["debtor_id"] == debtor["id"] and case["status"] != "WITHDRAWN_PRE_FILE":
            total_cases_filed += 1
    return {
        "id": debtor["id"],
        "full_name": debtor["full_name"],
        "household_size": debtor["household_size"],
        "state_code": debtor["state_code"],
        "total_cases_filed": total_cases_filed,
        "created_at": debtor["created_at"],
        "updated_at": debtor["updated_at"],
        "version": debtor["version"],
    }


# ---------------------------------------------------------------------------
# Creditor
# ---------------------------------------------------------------------------
def serialize_creditor(creditor: dict) -> dict:
    return {
        "id": creditor["id"],
        "name": creditor["name"],
        "creditor_type": creditor["creditor_type"],
        "created_at": creditor["created_at"],
        "updated_at": creditor["updated_at"],
        "version": creditor["version"],
    }


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------
_STAY_ACTIVE_STATES = {
    "FILED",
    "MEETING_SCHEDULED",
    "MEETING_HELD",
    "PLAN_PROPOSED",
    "PLAN_CONFIRMED",
    "IN_REPAYMENT",
}


def serialize_case(case: dict) -> dict:
    stay = case["status"] in _STAY_ACTIVE_STATES
    return {
        "id": case["id"],
        "debtor_id": case["debtor_id"],
        "chapter_requested": case["chapter_requested"],
        "chapter_effective": case.get("chapter_effective"),
        "status": case["status"],
        "automatic_stay_active": stay,
        "filing_date": case.get("filing_date"),
        "meeting_341_date": case.get("meeting_341_date"),
        "schedule_completeness": compute_schedule_completeness(case["id"]),
        "means_test_result_id": case.get("means_test_result_id"),
        "total_unsecured_pool_cents": compute_total_unsecured_pool(case["id"]),
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "version": case["version"],
    }


# ---------------------------------------------------------------------------
# Schedule (immutable snapshot: id + created_at only)
# ---------------------------------------------------------------------------
def serialize_schedule(schedule: dict) -> dict:
    return {
        "id": schedule["id"],
        "case_id": schedule["case_id"],
        "schedule_type": schedule["schedule_type"],
        "line_items": schedule["line_items"],
        "total_cents": schedule["total_cents"],
        "superseded_by_id": schedule.get("superseded_by_id"),
        "created_at": schedule["created_at"],
    }


# ---------------------------------------------------------------------------
# MeansTestResult (immutable snapshot)
# ---------------------------------------------------------------------------
def serialize_means_test_result(mtr: dict) -> dict:
    return {
        "id": mtr["id"],
        "case_id": mtr["case_id"],
        "current_monthly_income_cents": mtr["current_monthly_income_cents"],
        "cmi_annualized_cents": mtr["cmi_annualized_cents"],
        "state_median_annual_cents": mtr["state_median_annual_cents"],
        "presumption_of_abuse": mtr["presumption_of_abuse"],
        "allowed_monthly_expenses_cents": mtr["allowed_monthly_expenses_cents"],
        "disposable_monthly_income_cents": mtr["disposable_monthly_income_cents"],
        "required_plan_months": mtr["required_plan_months"],
        "minimum_plan_total_cents": mtr["minimum_plan_total_cents"],
        "created_at": mtr["created_at"],
    }


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------
def serialize_claim(claim: dict) -> dict:
    return {
        "id": claim["id"],
        "case_id": claim["case_id"],
        "creditor_id": claim["creditor_id"],
        "claim_class": claim["claim_class"],
        "amount_cents": claim["amount_cents"],
        "is_dischargeable": claim["is_dischargeable"],
        "status": claim["status"],
        "created_at": claim["created_at"],
        "updated_at": claim["updated_at"],
        "version": claim["version"],
    }


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
def _plan_paid_to_date(plan_id: str) -> int:
    total = 0
    for pmt in store.trustee_payments.values():
        if pmt["plan_id"] == plan_id and pmt["status"] == "APPLIED":
            total += pmt["amount_cents"]
    return total


def _plan_missed_count(plan_id: str) -> int:
    return sum(
        1
        for pmt in store.trustee_payments.values()
        if pmt["plan_id"] == plan_id and pmt["status"] == "MISSED"
    )


def serialize_plan(plan: dict) -> dict:
    return {
        "id": plan["id"],
        "case_id": plan["case_id"],
        "proposed_monthly_payment_cents": plan["proposed_monthly_payment_cents"],
        "plan_months": plan["plan_months"],
        "planned_total_cents": plan["planned_total_cents"],
        "paid_to_date_cents": _plan_paid_to_date(plan["id"]),
        "status": plan["status"],
        "missed_payment_count": _plan_missed_count(plan["id"]),
        "created_at": plan["created_at"],
        "updated_at": plan["updated_at"],
        "version": plan["version"],
    }


# ---------------------------------------------------------------------------
# TrusteePayment (append-only ledger)
# ---------------------------------------------------------------------------
def serialize_trustee_payment(pmt: dict) -> dict:
    return {
        "id": pmt["id"],
        "plan_id": pmt["plan_id"],
        "sequence_number": pmt["sequence_number"],
        "amount_cents": pmt["amount_cents"],
        "status": pmt["status"],
        "applied_at": pmt["applied_at"],
        "created_at": pmt["created_at"],
    }


# ---------------------------------------------------------------------------
# CollectionAction (immutable attempt log)
# ---------------------------------------------------------------------------
def serialize_collection_action(ca: dict) -> dict:
    return {
        "id": ca["id"],
        "creditor_id": ca["creditor_id"],
        "case_id": ca["case_id"],
        "action_kind": ca["action_kind"],
        "outcome": ca["outcome"],
        "rejected_reason": ca["rejected_reason"],
        "created_at": ca["created_at"],
    }
