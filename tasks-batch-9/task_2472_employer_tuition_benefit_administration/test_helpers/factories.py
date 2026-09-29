"""
Request-payload builders for the Employer Tuition Benefit Administration API.

Each builder mirrors the input list its PRD workflow section declares, and any
argument left at None is omitted from the payload entirely so the server applies
the declared default rather than receiving an explicit null.
"""

from typing import Any, Dict, List, Optional

from .types import CredentialType, FundingModel, JobFamily, Modality, SkillTrack

Payload = Dict[str, Any]


def _compact(payload: Payload) -> Payload:
    """Drop keys whose value is None so declared defaults apply."""
    return {key: value for key, value in payload.items() if value is not None}


# ─── Employers and policies (PRD §3.1) ─────────────────────────────────────
def employer_payload(
    legal_name: str = "Vantage Foods Group",
    benefit_admin_contact_email: str = "benefits@vantage-foods.example",
    fiscal_year_start_month: int = 1,
    status: Optional[str] = None,
) -> Payload:
    return _compact(
        {
            "legal_name": legal_name,
            "benefit_admin_contact_email": benefit_admin_contact_email,
            "fiscal_year_start_month": fiscal_year_start_month,
            "status": status,
        }
    )


def benefit_policy_payload(
    effective_from: str = "2026-01-01",
    effective_to: str = "2027-01-01",
    min_tenure_months: int = 6,
    min_weekly_hours: float = 20,
    eligible_job_families: Optional[List[str]] = None,
    annual_cap_cents: int = 1_000_000,
    funding_model: str = FundingModel.HYBRID,
    reimbursement_pct: float = 0.50,
    max_concurrent_credits: int = 12,
    drop_window_days: int = 14,
    service_commitment_months: int = 12,
    min_passing_grade_points: Optional[float] = None,
    non_catalog_approval_required: Optional[bool] = None,
) -> Payload:
    return _compact(
        {
            "effective_from": effective_from,
            "effective_to": effective_to,
            "min_tenure_months": min_tenure_months,
            "min_weekly_hours": min_weekly_hours,
            "eligible_job_families": (
                eligible_job_families
                if eligible_job_families is not None
                else [JobFamily.OPERATIONS]
            ),
            "annual_cap_cents": annual_cap_cents,
            "funding_model": funding_model,
            "reimbursement_pct": reimbursement_pct,
            "max_concurrent_credits": max_concurrent_credits,
            "drop_window_days": drop_window_days,
            "service_commitment_months": service_commitment_months,
            "min_passing_grade_points": min_passing_grade_points,
            "non_catalog_approval_required": non_catalog_approval_required,
        }
    )


def employee_payload(
    full_name: str = "Rosa Delgado",
    work_email: str = "rosa.delgado@vantage-foods.example",
    hire_date: str = "2024-01-15",
    weekly_hours: float = 40,
    job_family: str = JobFamily.OPERATIONS,
    employment_status: Optional[str] = None,
    termination_date: Optional[str] = None,
) -> Payload:
    return _compact(
        {
            "full_name": full_name,
            "work_email": work_email,
            "hire_date": hire_date,
            "weekly_hours": weekly_hours,
            "job_family": job_family,
            "employment_status": employment_status,
            "termination_date": termination_date,
        }
    )


def employee_patch_payload(
    weekly_hours: Optional[float] = None,
    job_family: Optional[str] = None,
    employment_status: Optional[str] = None,
    termination_date: Optional[str] = None,
) -> Payload:
    return _compact(
        {
            "weekly_hours": weekly_hours,
            "job_family": job_family,
            "employment_status": employment_status,
            "termination_date": termination_date,
        }
    )


# ─── Schools, programs and agreements (PRD §3.2) ───────────────────────────
def school_payload(
    legal_name: str = "Cascade Valley College",
    state_code: str = "WA",
    contact_email: str = "partners@cascadevalley.example",
    accreditation_status: Optional[str] = None,
) -> Payload:
    return _compact(
        {
            "legal_name": legal_name,
            "state_code": state_code,
            "contact_email": contact_email,
            "accreditation_status": accreditation_status,
        }
    )


def program_payload(
    name: str = "Certificate in Food Safety Analytics",
    credential_type: str = CredentialType.CERTIFICATE,
    skill_track: str = SkillTrack.DATA_ANALYTICS,
    list_tuition_per_credit_cents: int = 50_000,
    total_credits: int = 12,
    term_length_weeks: int = 10,
) -> Payload:
    return {
        "name": name,
        "credential_type": credential_type,
        "skill_track": skill_track,
        "list_tuition_per_credit_cents": list_tuition_per_credit_cents,
        "total_credits": total_credits,
        "term_length_weeks": term_length_weeks,
    }


def partner_agreement_payload(
    employer_id: str,
    school_id: str,
    negotiated_discount_pct: float = 0.20,
    direct_bill_enabled: Optional[bool] = None,
    effective_from: str = "2026-01-01",
    effective_to: str = "2026-12-31",
) -> Payload:
    return _compact(
        {
            "employer_id": employer_id,
            "school_id": school_id,
            "negotiated_discount_pct": negotiated_discount_pct,
            "direct_bill_enabled": direct_bill_enabled,
            "effective_from": effective_from,
            "effective_to": effective_to,
        }
    )


# ─── Catalog and the exception path (PRD §3.3) ─────────────────────────────
def catalog_listing_payload(
    employer_id: str,
    program_id: str,
    agreement_id: str,
    expected_agreement_version: int,
) -> Payload:
    return {
        "employer_id": employer_id,
        "program_id": program_id,
        "agreement_id": agreement_id,
        "expected_agreement_version": expected_agreement_version,
    }


def program_approval_request_payload(
    employee_id: str,
    program_id: str,
    justification: str = "This credential is required for the next role on my ladder.",
    requested_annual_cost_cents: int = 900_000,
) -> Payload:
    return {
        "employee_id": employee_id,
        "program_id": program_id,
        "justification": justification,
        "requested_annual_cost_cents": requested_annual_cost_cents,
    }


def resubmit_payload(
    justification: Optional[str] = None,
    requested_annual_cost_cents: Optional[int] = None,
) -> Payload:
    return _compact(
        {
            "justification": justification,
            "requested_annual_cost_cents": requested_annual_cost_cents,
        }
    )


def approval_decision_payload(
    decision: str, decision_note: Optional[str] = None
) -> Payload:
    return _compact({"decision": decision, "decision_note": decision_note})


# ─── Enrollment and outcomes (PRD §3.4 – §3.6) ────────────────────────────
def enrollment_payload(
    employee_id: str,
    catalog_listing_id: str,
    expected_employee_version: int,
    term_code: str = "2026-FA",
    term_start_date: str = "2026-09-01",
    term_end_date: str = "2026-12-15",
    credits: int = 4,
    funding_model: Optional[str] = None,
) -> Payload:
    return _compact(
        {
            "employee_id": employee_id,
            "catalog_listing_id": catalog_listing_id,
            "term_code": term_code,
            "term_start_date": term_start_date,
            "term_end_date": term_end_date,
            "credits": credits,
            "expected_employee_version": expected_employee_version,
            "funding_model": funding_model,
        }
    )


def academic_outcome_payload(
    term_code: str,
    completion_status: str,
    credits_earned: int,
    grade_points: Optional[float] = None,
) -> Payload:
    return _compact(
        {
            "term_code": term_code,
            "completion_status": completion_status,
            "credits_earned": credits_earned,
            "grade_points": grade_points,
        }
    )


def coaching_session_payload(
    session_date: str,
    modality: str = Modality.VIDEO,
    risk_flags: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Payload:
    return _compact(
        {
            "session_date": session_date,
            "modality": modality,
            "risk_flags": risk_flags,
            "notes": notes,
        }
    )


def reimbursement_claim_payload(
    amount_requested_cents: int, receipt_reference: str
) -> Payload:
    return {
        "amount_requested_cents": amount_requested_cents,
        "receipt_reference": receipt_reference,
    }


def claim_decision_payload(
    decision: str, decision_note: Optional[str] = None
) -> Payload:
    return _compact({"decision": decision, "decision_note": decision_note})


# ─── Repayment (PRD §3.7) ──────────────────────────────────────────────────
def repayment_payment_payload(amount_cents: int) -> Payload:
    return {"amount_cents": amount_cents}


# ─── Operator batch (PRD §3.9) ─────────────────────────────────────────────
def term_close_payload(
    term_code: str,
    run_annual_true_up: Optional[bool] = None,
    tax_year: Optional[int] = None,
) -> Payload:
    return _compact(
        {
            "term_code": term_code,
            "run_annual_true_up": run_annual_true_up,
            "tax_year": tax_year,
        }
    )
