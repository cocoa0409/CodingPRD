"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally
omitted.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.10: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 (ISO 8601 UTC with three fractional digits).
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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_hours(iso_ts: str, hours: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(hours=hours))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Random suffix / unique emails.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{random_suffix()}@example.test"


def unique_string(prefix: str = "x") -> str:
    return f"{prefix}-{random_suffix(10)}"


# ---------------------------------------------------------------------------
# Recruiter — POST /recruiters
# PRD §3.1: "supplying the participant's `email` (required to be unique
# within its role), a `full_name`, and a `department_code`"
# ---------------------------------------------------------------------------
def create_recruiter_payload(
    *,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    department_code: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "email": email or unique_email("recruiter"),
        "full_name": full_name or TEST_DEFAULTS["DEFAULT_RECRUITER_FULL_NAME"],
        "department_code": (
            department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# HiringManager — POST /hiring-managers
# PRD §3.1: HiringManager additionally carries budget_cents.
# ---------------------------------------------------------------------------
def create_hiring_manager_payload(
    *,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    department_code: Optional[str] = None,
    budget_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "email": email or unique_email("hm"),
        "full_name": full_name or TEST_DEFAULTS["DEFAULT_HM_FULL_NAME"],
        "department_code": (
            department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
        ),
        "budget_cents": (
            budget_cents if budget_cents is not None
            else TEST_DEFAULTS["DEFAULT_HM_BUDGET_CENTS"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Interviewer — POST /interviewers
# PRD §3.1: Interviewer carries is_certified_for_eeo (default false).
# ---------------------------------------------------------------------------
def create_interviewer_payload(
    *,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    department_code: Optional[str] = None,
    is_certified_for_eeo: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "email": email or unique_email("interviewer"),
        "full_name": full_name or TEST_DEFAULTS["DEFAULT_INTERVIEWER_FULL_NAME"],
        "department_code": (
            department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
        ),
    }
    if is_certified_for_eeo is not None:
        payload["is_certified_for_eeo"] = is_certified_for_eeo
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Requisition — POST /requisitions
# PRD §3.2 input: recruiter_id, hiring_manager_id, job_title,
# department_code, seniority_level, headcount, budget_cents,
# target_diversity_goal_id (optional).
# ---------------------------------------------------------------------------
def create_requisition_payload(
    *,
    recruiter_id: str,
    hiring_manager_id: str,
    job_title: Optional[str] = None,
    department_code: Optional[str] = None,
    seniority_level: str = "SENIOR",
    headcount: int = 1,
    budget_cents: Optional[int] = None,
    target_diversity_goal_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recruiter_id": recruiter_id,
        "hiring_manager_id": hiring_manager_id,
        "job_title": job_title or TEST_DEFAULTS["DEFAULT_JOB_TITLE"],
        "department_code": (
            department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
        ),
        "seniority_level": seniority_level,
        "headcount": headcount,
        "budget_cents": (
            budget_cents if budget_cents is not None
            else TEST_DEFAULTS["DEFAULT_REQ_BUDGET_CENTS"]
        ),
    }
    if target_diversity_goal_id is not None:
        payload["target_diversity_goal_id"] = target_diversity_goal_id
    payload.update(extra)
    return payload


def patch_requisition_payload(
    *,
    version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Candidate — POST /candidates
# PRD §3.1: "When `source` is `REFERRAL`, the request body must also
# include a non-null `referrer_employee_id` ...; conversely, when
# `source` is anything other than `REFERRAL`, `referrer_employee_id`
# must be null."  PRD: is_in_eeo_protected_class defaults to false.
# ---------------------------------------------------------------------------
def create_candidate_payload(
    *,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    source: str = "DIRECT",
    referrer_employee_id: Optional[str] = None,
    is_in_eeo_protected_class: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "email": email or unique_email("candidate"),
        "full_name": full_name or TEST_DEFAULTS["DEFAULT_CANDIDATE_FULL_NAME"],
        "source": source,
    }
    # PRD §3.1: when source != REFERRAL, referrer_employee_id MUST be
    # null. We thread the value explicitly when the caller passes it.
    if referrer_employee_id is not None:
        payload["referrer_employee_id"] = referrer_employee_id
    if is_in_eeo_protected_class is not None:
        payload["is_in_eeo_protected_class"] = is_in_eeo_protected_class
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# EEORecord — POST /candidates/{id}/eeo-record
# PRD §3.1 input fields.
# ---------------------------------------------------------------------------
def create_eeo_record_payload(
    *,
    gender: str = "DECLINE",
    ethnicity: str = "DECLINE",
    veteran_status: str = "DECLINE",
    disability_status: str = "DECLINE",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "gender": gender,
        "ethnicity": ethnicity,
        "veteran_status": veteran_status,
        "disability_status": disability_status,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Application — POST /requisitions/{id}/applications
# PRD §3.3: body is {candidate_id}.
# ---------------------------------------------------------------------------
def create_application_payload(
    *,
    candidate_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"candidate_id": candidate_id}
    payload.update(extra)
    return payload


def reject_application_payload(
    *,
    rejection_reason: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Interview — POST /applications/{id}/interviews
# PRD §3.4 input: interviewer_id, scheduled_start_at, scheduled_end_at.
# ---------------------------------------------------------------------------
def create_interview_payload(
    *,
    interviewer_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "interviewer_id": interviewer_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# InterviewFeedback — POST /interviews/{id}/feedback
# PRD §3.4 input: overall_score, recommendation.
# ---------------------------------------------------------------------------
def create_interview_feedback_payload(
    *,
    overall_score: int = 5,
    recommendation: str = "STRONG_HIRE",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "overall_score": overall_score,
        "recommendation": recommendation,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Offer — POST /applications/{id}/offers
# PRD §3.5 input: base_salary_cents, sign_on_bonus_cents (optional, def
# 0), annual_equity_cents (optional, def 0), approval_chain (array).
# ---------------------------------------------------------------------------
def offer_approval_step_payload(
    *,
    step_order: int,
    approver_role: str,
    required_approver_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    """Single approval-chain entry: PRD §3.5: "Each entry in the
    approval chain materializes as an `OfferApprovalStep` with ... a
    1-based `step_order` ..., an `approver_role` of `HIRING_MANAGER`,
    `COMPENSATION`, or `EXECUTIVE`, and a `required_approver_id`
    identifying the specific approver who must act at that step.\""""
    payload: Dict[str, Any] = {
        "step_order": step_order,
        "approver_role": approver_role,
        "required_approver_id": required_approver_id,
    }
    payload.update(extra)
    return payload


def create_offer_payload(
    *,
    base_salary_cents: int,
    approval_chain: List[Dict[str, Any]],
    sign_on_bonus_cents: Optional[int] = None,
    annual_equity_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "base_salary_cents": base_salary_cents,
        "approval_chain": approval_chain,
    }
    if sign_on_bonus_cents is not None:
        payload["sign_on_bonus_cents"] = sign_on_bonus_cents
    if annual_equity_cents is not None:
        payload["annual_equity_cents"] = annual_equity_cents
    payload.update(extra)
    return payload


def patch_offer_payload(
    *,
    base_salary_cents: Optional[int] = None,
    sign_on_bonus_cents: Optional[int] = None,
    annual_equity_cents: Optional[int] = None,
    version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if base_salary_cents is not None:
        payload["base_salary_cents"] = base_salary_cents
    if sign_on_bonus_cents is not None:
        payload["sign_on_bonus_cents"] = sign_on_bonus_cents
    if annual_equity_cents is not None:
        payload["annual_equity_cents"] = annual_equity_cents
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


def approve_offer_payload(
    *,
    step_order: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"step_order": step_order}
    payload.update(extra)
    return payload


def request_revision_payload(
    *,
    step_order: int,
    reason: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"step_order": step_order}
    if reason is not None:
        payload["reason"] = reason
    payload.update(extra)
    return payload


def extend_offer_payload(
    *,
    expires_at: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expires_at": expires_at}
    payload.update(extra)
    return payload


def rescind_offer_payload(
    *,
    reason: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# BackgroundCheck — PRD §3.7
# ---------------------------------------------------------------------------
def create_background_check_payload(
    *,
    vendor: str = "ACME_BG",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"vendor": vendor}
    payload.update(extra)
    return payload


def report_bgc_result_payload(
    *,
    outcome: str,
    **extra: Any,
) -> Dict[str, Any]:
    """outcome is one of {PASS, FAIL} per PRD §3.7."""
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# DiversityGoal — PRD §3.1, §3.6
# ---------------------------------------------------------------------------
def create_diversity_goal_payload(
    *,
    department_code: Optional[str] = None,
    period_year: int = 2026,
    target_protected_class_percentage: float = 30.0,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "department_code": (
            department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
        ),
        "period_year": period_year,
        "target_protected_class_percentage":
            target_protected_class_percentage,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Test-driving harness — PRD §2.11
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(extra)
    return payload


def emit_event_payload(*, event_type: str, **extra: Any) -> Dict[str, Any]:
    """event_type is one of {OFFER_EXPIRY_SWEEP, REFERRAL_PAYABLE_SWEEP}
    per PRD §2.11."""
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(extra)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "parse_iso",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    "random_suffix",
    "unique_email",
    "unique_string",
    "create_recruiter_payload",
    "create_hiring_manager_payload",
    "create_interviewer_payload",
    "create_requisition_payload",
    "patch_requisition_payload",
    "create_candidate_payload",
    "create_eeo_record_payload",
    "create_application_payload",
    "reject_application_payload",
    "create_interview_payload",
    "create_interview_feedback_payload",
    "offer_approval_step_payload",
    "create_offer_payload",
    "patch_offer_payload",
    "approve_offer_payload",
    "request_revision_payload",
    "extend_offer_payload",
    "rescind_offer_payload",
    "create_background_check_payload",
    "report_bgc_result_payload",
    "create_diversity_goal_payload",
    "clock_advance_payload",
    "emit_event_payload",
]
