"""Payload factories — one per collection, input fields only."""
from .constants import TEST_DEFAULTS


def academic_term_payload(**overrides) -> dict:
    payload = {
        "term_code": TEST_DEFAULTS["TERM_CODE"],
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
        "tax_calendar_year": TEST_DEFAULTS["TAX_CALENDAR_YEAR"],
        "session_type": "IN_SESSION",
        "proration_method": "CALENDAR_DAY",
        "remission_drop_deadline": TEST_DEFAULTS["REMISSION_DROP_DEADLINE"],
    }
    payload.update(overrides)
    return payload


def department_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["DEPARTMENT_CODE"],
        "name": TEST_DEFAULTS["DEPARTMENT_NAME"],
    }
    payload.update(overrides)
    return payload


def stipend_policy_payload(term_id: str, **overrides) -> dict:
    payload = {
        "term_id": term_id,
        "assistantship_type": "RESEARCH",
        "degree_level": "DOCTORAL",
        "min_fte_monthly_stipend_cents": TEST_DEFAULTS["MIN_FTE_MONTHLY_STIPEND_CENTS"],
        "per_credit_tuition_cents": TEST_DEFAULTS["PER_CREDIT_TUITION_CENTS"],
        "max_remission_cents_per_term": TEST_DEFAULTS["MAX_REMISSION_CENTS_PER_TERM"],
        "term_insurance_premium_cents": TEST_DEFAULTS["TERM_INSURANCE_PREMIUM_CENTS"],
    }
    payload.update(overrides)
    return payload


def pay_period_payload(term_id: str, sequence_no: int, period_start: str,
                       period_end_exclusive: str, pay_date: str, **overrides) -> dict:
    payload = {
        "term_id": term_id,
        "sequence_no": sequence_no,
        "period_start": period_start,
        "period_end_exclusive": period_end_exclusive,
        "pay_date": pay_date,
    }
    payload.update(overrides)
    return payload


def student_payload(**overrides) -> dict:
    payload = {
        "student_number": "GS-1000",
        "full_name": "Ada Vance",
        "degree_level": "DOCTORAL",
        "is_international": False,
        "cumulative_gpa": 3.60,
        "enrolled_credit_hours": 0,
    }
    payload.update(overrides)
    return payload


def funding_source_payload(department_id: str, **overrides) -> dict:
    payload = {
        "department_id": department_id,
        "source_code": "NSF-A",
        "source_type": "GRANT",
        "authorized_amount_cents": TEST_DEFAULTS["AUTHORIZED_AMOUNT_CENTS"],
        "budget_period_start": TEST_DEFAULTS["BUDGET_PERIOD_START"],
        "budget_period_end": TEST_DEFAULTS["BUDGET_PERIOD_END"],
        "allows_tuition_remission": True,
    }
    payload.update(overrides)
    return payload


def appointment_payload(student_id: str, department_id: str, term_id: str,
                        **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "department_id": department_id,
        "term_id": term_id,
        "assistantship_type": "RESEARCH",
        "effort_pct": TEST_DEFAULTS["EFFORT_PCT"],
        "start_date": TEST_DEFAULTS["TERM_START"],
        "end_date": TEST_DEFAULTS["TERM_END"],
        "monthly_stipend_cents": TEST_DEFAULTS["MONTHLY_STIPEND_CENTS"],
        "supervisor_user_id": TEST_DEFAULTS["SUPERVISOR_USER_ID"],
    }
    payload.update(overrides)
    return payload


def funding_plan_payload(allocations: list, expected_appointment_version: int) -> dict:
    return {
        "allocations": allocations,
        "expected_appointment_version": expected_appointment_version,
    }


def allocation_entry(funding_source_id: str, share_pct: float,
                     is_cost_share: bool = None) -> dict:
    entry = {"funding_source_id": funding_source_id, "share_pct": share_pct}
    if is_cost_share is not None:
        entry["is_cost_share"] = is_cost_share
    return entry


def renewal_decision_payload(appointment_id: str, **overrides) -> dict:
    payload = {"appointment_id": appointment_id}
    payload.update(overrides)
    return payload


def tax_assessment_payload(student_id: str, term_id: str,
                           expected_student_version: int, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "term_id": term_id,
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload
