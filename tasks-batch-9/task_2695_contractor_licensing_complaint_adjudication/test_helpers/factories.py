"""Request-payload factories.

Every factory returns a valid payload built from PRD-declared field names, with
keyword overrides for the field a test wants to vary. Money is always emitted
as a JSON integer of cents, never as a string.
"""

from typing import Any, Optional

from . import constants as K
from .types import (
    ApplicationType,
    ClaimBasis,
    CoverageType,
    EducationCredential,
    EntityType,
    ExamType,
    RelationshipType,
)

Json = dict[str, Any]


def _merge(base: Json, overrides: Json) -> Json:
    payload = dict(base)
    payload.update(overrides)
    return payload


# --------------------------------------------------------- reference data ----
def trade_classification_payload(**overrides: Any) -> Json:
    """A tier-3 classification requiring mediation before enforcement."""
    return _merge(dict(K.C10), overrides)


def fund_account_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "fiscal_year": 2027,
            "initial_balance_cents": 5000000,
            "per_claim_cap_cents": 1500000,
            "per_license_aggregate_cap_cents": 2000000,
        },
        overrides,
    )


# -------------------------------------------------------------- parties ------
def licensee_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "legal_name": "Northgate Electric LLC",
            "entity_type": EntityType.LLC,
            "contact_email": "office@northgate-electric.example",
        },
        overrides,
    )


def qualifying_individual_payload(**overrides: Any) -> Json:
    return _merge(
        {"full_name": "Dana Ruiz", "verified_experience_months": 60}, overrides
    )


def consumer_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "full_name": "Priya Raman",
            "contact_email": "priya.raman@example.com",
            "mailing_state": "WA",
        },
        overrides,
    )


def exam_result_payload(
    exam_type: str = ExamType.LAW_AND_BUSINESS, **overrides: Any
) -> Json:
    """A passing sitting. ``trade_code`` is required only for a TRADE exam."""
    payload: Json = {
        "exam_type": exam_type,
        "score": K.EXAM_PASS_SCORE,
        "taken_on": "2025-03-01",
    }
    if exam_type == ExamType.TRADE:
        payload["trade_code"] = K.C10["code"]
    return _merge(payload, overrides)


def trade_exam_payload(trade_code: str, **overrides: Any) -> Json:
    return exam_result_payload(
        ExamType.TRADE, **_merge({"trade_code": trade_code}, overrides)
    )


def law_and_business_exam_payload(**overrides: Any) -> Json:
    return exam_result_payload(ExamType.LAW_AND_BUSINESS, **overrides)


# --------------------------------------------------------- applications ------
def application_payload(
    licensee_id: str,
    classification_id: str,
    qualifying_individual_id: str,
    **overrides: Any,
) -> Json:
    return _merge(
        {
            "licensee_id": licensee_id,
            "classification_id": classification_id,
            "qualifying_individual_id": qualifying_individual_id,
            "application_type": ApplicationType.ORIGINAL,
            "declared_net_worth_cents": 500000,
            "education_credential": EducationCredential.NONE,
        },
        overrides,
    )


def decision_payload(outcome: str, **overrides: Any) -> Json:
    return _merge({"outcome": outcome}, overrides)


# ------------------------------------------------------ coverage records -----
def coverage_record_payload(license_id: str, **overrides: Any) -> Json:
    """A conforming contractor bond opening on the default clock date."""
    return _merge(
        {
            "license_id": license_id,
            "coverage_type": CoverageType.BOND,
            "carrier_name": "Cascade Surety Company",
            "policy_number": "BND-40021",
            "amount_cents": K.C10["required_bond_amount_cents"],
            "effective_date": "2026-08-01",
            "expiration_date": "2027-08-01",
        },
        overrides,
    )


def general_liability_payload(license_id: str, **overrides: Any) -> Json:
    return _merge(
        {
            "license_id": license_id,
            "coverage_type": CoverageType.GENERAL_LIABILITY,
            "carrier_name": "Cascade Mutual Insurance",
            "policy_number": "GL-88110",
            "amount_cents": 100000,
            "effective_date": "2026-08-01",
            "expiration_date": "2027-08-01",
        },
        overrides,
    )


def verification_payload(outcome: str, **overrides: Any) -> Json:
    return _merge({"outcome": outcome}, overrides)


def cancellation_payload(cancellation_date: str) -> Json:
    return {"cancellation_date": cancellation_date}


# -------------------------------------------------- qualifier assignments ----
def qualifier_assignment_payload(
    license_id: str,
    qualifying_individual_id: str,
    expected_license_version: int,
    **overrides: Any,
) -> Json:
    return _merge(
        {
            "license_id": license_id,
            "qualifying_individual_id": qualifying_individual_id,
            "relationship_type": RelationshipType.RESPONSIBLE_MANAGING_EMPLOYEE,
            "effective_from": "2026-08-01",
            "expected_license_version": expected_license_version,
            "ownership_pct": 0,
        },
        overrides,
    )


# ------------------------------------------------------------ complaints -----
def complaint_payload(consumer_id: str, **overrides: Any) -> Json:
    """A complaint against a licensed contractor."""
    return _merge(
        {
            "consumer_id": consumer_id,
            "alleged_loss_cents": 800000,
            "contract_date": "2026-08-10",
            "work_completed_on": "2026-08-20",
            "description": "Panel upgrade abandoned after partial demolition.",
        },
        overrides,
    )


def unlicensed_complaint_payload(
    consumer_id: str, subject_business_name: str, **overrides: Any
) -> Json:
    return _merge(
        {
            "consumer_id": consumer_id,
            "subject_business_name": subject_business_name,
            "alleged_loss_cents": 600000,
            "contract_date": "2026-08-12",
            "work_completed_on": "2026-08-25",
            "description": "Unlicensed operator took a deposit and never returned.",
        },
        overrides,
    )


def screening_payload(jurisdiction_finding: str, **overrides: Any) -> Json:
    return _merge({"jurisdiction_finding": jurisdiction_finding}, overrides)


def mediation_outcome_payload(outcome: str, **overrides: Any) -> Json:
    return _merge({"outcome": outcome}, overrides)


# --------------------------------------------------------- enforcement -------
def investigation_payload(origin: str, **overrides: Any) -> Json:
    return _merge({"origin": origin}, overrides)


def close_investigation_payload(finding: str, **overrides: Any) -> Json:
    return _merge(
        {
            "finding": finding,
            "evidence_summary": "Field inspection and carrier records reviewed.",
        },
        overrides,
    )


def citation_payload(
    investigation_id: str, classification_id: str, **overrides: Any
) -> Json:
    return _merge(
        {
            "investigation_id": investigation_id,
            "classification_id": classification_id,
            "violation_code": "B-7109",
            "correction_due_date": "2026-09-30",
        },
        overrides,
    )


def appeal_payload(**overrides: Any) -> Json:
    return _merge(
        {"appeal_grounds": "The board misread the permit history."}, overrides
    )


def comply_payload(penalty_payment_cents: int, corrected_on: str) -> Json:
    return {
        "penalty_payment_cents": penalty_payment_cents,
        "corrected_on": corrected_on,
    }


def hearing_payload(
    citation_id: str,
    presiding_officer_user_id: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
) -> Json:
    return {
        "citation_id": citation_id,
        "presiding_officer_user_id": presiding_officer_user_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
    }


def hearing_decision_payload(decision: str, **overrides: Any) -> Json:
    return _merge(
        {
            "decision": decision,
            "findings_summary": "Testimony and inspection photographs considered.",
        },
        overrides,
    )


# ------------------------------------------------------- recovery fund -------
def claim_payload(
    fund_account_id: str, complaint_id: str, claimed_amount_cents: int, **overrides: Any
) -> Json:
    return _merge(
        {
            "fund_account_id": fund_account_id,
            "complaint_id": complaint_id,
            "basis": ClaimBasis.FINAL_CITATION,
            "claimed_amount_cents": claimed_amount_cents,
        },
        overrides,
    )


def judgment_claim_payload(
    fund_account_id: str,
    complaint_id: str,
    claimed_amount_cents: int,
    judgment_amount_cents: int,
    judgment_docket_number: str,
    judgment_entered_on: str,
    **overrides: Any,
) -> Json:
    return _merge(
        {
            "fund_account_id": fund_account_id,
            "complaint_id": complaint_id,
            "basis": ClaimBasis.COURT_JUDGMENT,
            "claimed_amount_cents": claimed_amount_cents,
            "judgment_amount_cents": judgment_amount_cents,
            "judgment_docket_number": judgment_docket_number,
            "judgment_entered_on": judgment_entered_on,
        },
        overrides,
    )


def adjudication_payload(outcome: str, **overrides: Any) -> Json:
    return _merge({"outcome": outcome}, overrides)


def payment_payload(expected_fund_account_version: int) -> Json:
    return {"expected_fund_account_version": expected_fund_account_version}


def repayment_payload(
    repayment_amount_cents: int, expected_license_version: int
) -> Json:
    return {
        "repayment_amount_cents": repayment_amount_cents,
        "expected_license_version": expected_license_version,
    }


def ce_credit_payload(
    ce_hours: float, completed_on: str, provider_name: Optional[str] = None
) -> Json:
    return {
        "ce_hours": ce_hours,
        "completed_on": completed_on,
        "provider_name": provider_name or "Cascade Trades Institute",
    }
