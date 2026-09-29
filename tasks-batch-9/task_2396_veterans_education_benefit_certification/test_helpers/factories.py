"""Payload factories.

Each factory returns a valid default body for one write operation, using the
canonical values from :mod:`constants`, and accepts keyword overrides so a test
can vary exactly the one field it is about. Passing ``None`` for a keyword
removes the field entirely, which is how a test omits a required input.
"""

from typing import Any, Dict

from . import constants as c
from .types import JsonDict


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> JsonDict:
    """Apply overrides onto a default body; a value of ``None`` drops the key."""
    body = dict(base)
    for key, value in overrides.items():
        if value is None:
            body.pop(key, None)
        else:
            body[key] = value
    return body


# ─── Officials ────────────────────────────────────────────────────────
def sco_official_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "full_name": c.SCO_NAME,
            "email": c.SCO_EMAIL,
            "official_level": c.LEVEL_SCO,
        },
        overrides,
    )


def supervisory_official_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "full_name": c.SUPERVISORY_NAME,
            "email": c.SUPERVISORY_EMAIL,
            "official_level": c.LEVEL_SUPERVISORY,
        },
        overrides,
    )


# ─── Veteran students ─────────────────────────────────────────────────
def veteran_student_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "student_number": c.STUDENT_NUMBER,
            "full_name": c.STUDENT_NAME,
            "chapter": c.STUDENT_CHAPTER_CH33,
            "benefit_level_pct": c.STUDENT_BENEFIT_LEVEL_PCT,
            "entitlement_days_granted": c.ENTITLEMENT_DAYS_GRANTED,
            "delimiting_date": c.DELIMITING_DATE,
        },
        overrides,
    )


def verify_coe_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "coe_issued_on": c.COE_ISSUED_ON,
            "verified_document_reference": c.COE_REFERENCE,
        },
        overrides,
    )


def account_hold_payload(hold_status: str, **overrides: Any) -> JsonDict:
    return _merge({"hold_status": hold_status}, overrides)


# ─── Terms ────────────────────────────────────────────────────────────
def academic_term_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "term_code": c.TERM_CODE,
            "academic_year": c.ACADEMIC_YEAR,
            "term_type": c.TERM_TYPE_FALL,
            "start_date": c.TERM_START,
            "end_date": c.TERM_END,
            "drop_deadline": c.TERM_DROP_DEADLINE,
            "certification_deadline": c.TERM_CERTIFICATION_DEADLINE,
        },
        overrides,
    )


def spring_term_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "term_code": c.SPRING_TERM_CODE,
            "academic_year": c.ACADEMIC_YEAR,
            "term_type": c.TERM_TYPE_SPRING,
            "start_date": c.SPRING_TERM_START,
            "end_date": c.SPRING_TERM_END,
            "drop_deadline": c.SPRING_TERM_DROP_DEADLINE,
            "certification_deadline": c.SPRING_TERM_CERTIFICATION_DEADLINE,
        },
        overrides,
    )


# ─── Programs and catalog versions ────────────────────────────────────
def program_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "program_code": c.PROGRAM_CODE,
            "name": c.PROGRAM_NAME,
            "degree_level": c.DEGREE_LEVEL_UNDERGRAD,
            "full_time_credit_hours": c.FULL_TIME_CREDIT_HOURS,
            "campus_bah_monthly_cents": c.CAMPUS_BAH_MONTHLY_CENTS,
        },
        overrides,
    )


def catalog_version_payload(program_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "program_id": program_id,
            "catalog_year": c.CATALOG_YEAR,
            "effective_start": c.CATALOG_EFFECTIVE_START,
            "effective_end": c.CATALOG_EFFECTIVE_END,
            "has_published_tuition_schedule": True,
            "has_refund_policy": True,
            "has_program_length_disclosure": True,
        },
        overrides,
    )


def saa_decision_payload(decision: str, **overrides: Any) -> JsonDict:
    return _merge({"decision": decision}, overrides)


def suspend_catalog_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {"suspension_reason": "Tuition schedule withdrawn from publication"},
        overrides,
    )


# ─── Yellow Ribbon ────────────────────────────────────────────────────
def yellow_ribbon_agreement_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "academic_year": c.ACADEMIC_YEAR,
            "degree_level": c.DEGREE_LEVEL_UNDERGRAD,
            "per_student_annual_cap_cents": c.YR_PER_STUDENT_ANNUAL_CAP_CENTS,
            "annual_pool_cents": c.YR_ANNUAL_POOL_CENTS,
            "max_participants": c.YR_MAX_PARTICIPANTS,
        },
        overrides,
    )


def yellow_ribbon_award_payload(
    certification_id: str, agreement_id: str, expected_agreement_version: int, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "certification_id": certification_id,
            "agreement_id": agreement_id,
            "expected_agreement_version": expected_agreement_version,
        },
        overrides,
    )


def reverse_award_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {"reversal_reason": "Student rescinded Yellow Ribbon participation"},
        overrides,
    )


# ─── Enrollment certifications ────────────────────────────────────────
def certification_payload(
    student_id: str, term_id: str, program_id: str, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "student_id": student_id,
            "term_id": term_id,
            "program_id": program_id,
            "credit_hours_total": c.FULL_TIME_CREDIT_HOURS,
            "credit_hours_online": 0,
            "term_start_certified": c.TERM_START,
            "term_end_certified": c.TERM_END,
        },
        overrides,
    )


def return_certification_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {"return_reason": "Registrar shows 9 credit hours, not 12"}, overrides
    )


def record_va_payment_payload(
    tuition_amount_cents: int, mha_amount_cents: int, posted_on: str, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "tuition_amount_cents": tuition_amount_cents,
            "mha_amount_cents": mha_amount_cents,
            "posted_on": posted_on,
        },
        overrides,
    )


# ─── Tuition and fee reports ──────────────────────────────────────────
def tuition_fee_report_payload(
    certification_id: str, expected_certification_version: int, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "certification_id": certification_id,
            "gross_tuition_cents": c.GROSS_TUITION_CENTS,
            "mandatory_fees_cents": c.MANDATORY_FEES_CENTS,
            "tuition_specific_aid_cents": c.TUITION_SPECIFIC_AID_CENTS,
            "non_tuition_aid_cents": c.NON_TUITION_AID_CENTS,
            "expected_certification_version": expected_certification_version,
        },
        overrides,
    )


# ─── Change reports ───────────────────────────────────────────────────
def credit_hour_reduction_payload(
    certification_id: str,
    effective_date: str,
    new_credit_hours: float,
    new_credit_hours_online: float = 0,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "certification_id": certification_id,
            "change_type": c.CHANGE_TYPE_CREDIT_HOUR_REDUCTION,
            "effective_date": effective_date,
            "mitigating_circumstances_flag": False,
            "new_credit_hours": new_credit_hours,
            "new_credit_hours_online": new_credit_hours_online,
        },
        overrides,
    )


def complete_withdrawal_payload(
    certification_id: str,
    effective_date: str,
    mitigating_circumstances_flag: bool = False,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "certification_id": certification_id,
            "change_type": c.CHANGE_TYPE_COMPLETE_WITHDRAWAL,
            "effective_date": effective_date,
            "mitigating_circumstances_flag": mitigating_circumstances_flag,
        },
        overrides,
    )


def term_date_change_payload(
    certification_id: str,
    effective_date: str,
    new_term_end_certified: str,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "certification_id": certification_id,
            "change_type": c.CHANGE_TYPE_TERM_DATE_CHANGE,
            "effective_date": effective_date,
            "mitigating_circumstances_flag": False,
            "new_term_end_certified": new_term_end_certified,
        },
        overrides,
    )


# ─── Debts ────────────────────────────────────────────────────────────
def notify_debt_payload(**overrides: Any) -> JsonDict:
    return _merge({"notification_channel": c.NOTIFICATION_CHANNEL_EMAIL}, overrides)


def repayment_payload(amount_cents: int, **overrides: Any) -> JsonDict:
    return _merge({"amount_cents": amount_cents}, overrides)


def waive_debt_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {"waiver_reason": "Overpayment traced to an institutional reporting error"},
        overrides,
    )


# ─── Student account charges ──────────────────────────────────────────
def student_account_charge_payload(
    student_id: str, term_id: str, charge_type: str, amount_cents: int, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "student_id": student_id,
            "term_id": term_id,
            "charge_type": charge_type,
            "amount_cents": amount_cents,
        },
        overrides,
    )


# ─── Logical clock ────────────────────────────────────────────────────
def clock_payload(to_iso8601: str, **overrides: Any) -> JsonDict:
    return _merge({"to_iso8601": to_iso8601}, overrides)


def clock_instant(date_iso: str) -> str:
    """Turn a calendar date into the midnight UTC instant the clock accepts."""
    return f"{date_iso}T00:00:00Z"
