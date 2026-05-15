"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact schema the PRD declares for the request
body (PRD §3.1–§3.9). Tests pass overrides for the values they want
to control.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Utility — ISO 8601 UTC timestamp helper used by /_clock/advance and tests.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def unique_token(prefix: str = "tok") -> str:
    """A short unique string for fields like business_license_number/email
    that PRD declares unique across all rows."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Company (PRD §3.1)
# ---------------------------------------------------------------------------
def create_company_payload(
    legal_name: str = "Acme Corp",
    business_license_number: Optional[str] = None,
    industry: str = "TECH",
    size_band: str = "MEDIUM",
    verification_tier: str = "BASIC",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "business_license_number": (
            business_license_number or unique_token("lic")
        ),
        "industry": industry,
        "size_band": size_band,
        "verification_tier": verification_tier,
    }
    payload.update(overrides)
    return payload


def blacklist_company_payload(
    blacklist_reason: str = "fraudulent license",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"blacklist_reason": blacklist_reason}
    payload.update(overrides)
    return payload


def create_hr_binding_payload(
    email: Optional[str] = None,
    display_name: str = "Pat HR",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "email": email or f"{unique_token('hr')}@example.com",
        "display_name": display_name,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Job postings (PRD §3.2)
# ---------------------------------------------------------------------------
def create_job_posting_payload(
    company_id: str,
    title: str = TEST_DEFAULTS["POSTING_TITLE"],
    description: str = TEST_DEFAULTS["POSTING_DESCRIPTION"],
    salary_min_cents: int = TEST_DEFAULTS["POSTING_SALARY_MIN_CENTS"],
    salary_max_cents: int = TEST_DEFAULTS["POSTING_SALARY_MAX_CENTS"],
    benefits: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_id": company_id,
        "title": title,
        "description": description,
        "salary_min_cents": salary_min_cents,
        "salary_max_cents": salary_max_cents,
        "benefits": list(benefits) if benefits is not None
        else list(TEST_DEFAULTS["POSTING_BENEFITS"]),
    }
    payload.update(overrides)
    return payload


def reject_posting_payload(
    review_rejection_reason: str = "OTHER",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "review_rejection_reason": review_rejection_reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Candidates (PRD §3.3)
# ---------------------------------------------------------------------------
def create_candidate_payload(
    full_name: str = "Jane Candidate",
    email: Optional[str] = None,
    resume_attachment_url: str = "https://example.com/resume.pdf",
    visibility_mode: str = "PUBLIC",
    visible_to_company_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "email": email or f"{unique_token('cand')}@example.com",
        "resume_attachment_url": resume_attachment_url,
        "visibility_mode": visibility_mode,
    }
    if visible_to_company_ids is not None:
        payload["visible_to_company_ids"] = list(visible_to_company_ids)
    payload.update(overrides)
    return payload


def update_candidate_payload(
    visibility_mode: Optional[str] = None,
    visible_to_company_ids: Optional[List[str]] = None,
    resume_attachment_url: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if visibility_mode is not None:
        payload["visibility_mode"] = visibility_mode
    if visible_to_company_ids is not None:
        payload["visible_to_company_ids"] = list(visible_to_company_ids)
    if resume_attachment_url is not None:
        payload["resume_attachment_url"] = resume_attachment_url
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Applications (PRD §3.4)
# ---------------------------------------------------------------------------
def create_application_payload(
    candidate_id: str,
    job_posting_id: str,
    source_channel: str = "DIRECT",
    headhunter_contract_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "job_posting_id": job_posting_id,
        "source_channel": source_channel,
    }
    if headhunter_contract_id is not None:
        payload["headhunter_contract_id"] = headhunter_contract_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Interview rounds (PRD §3.5)
# ---------------------------------------------------------------------------
def create_interview_round_payload(
    mode: str = "VIDEO",
    interviewer_user_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mode": mode,
        "interviewer_user_ids": list(interviewer_user_ids)
        if interviewer_user_ids is not None else [],
    }
    payload.update(overrides)
    return payload


def publish_slots_payload(
    candidate_time_slot_options: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "candidate_time_slot_options": list(candidate_time_slot_options),
    }
    payload.update(overrides)
    return payload


def candidate_confirm_payload(
    selected_slot: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"selected_slot": selected_slot}
    payload.update(overrides)
    return payload


def submit_round_feedback_payload(
    feedback_decision: str = "PASS",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"feedback_decision": feedback_decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Offers (PRD §3.6)
# ---------------------------------------------------------------------------
def create_offer_payload(
    application_id: str,
    base_salary_cents: int = TEST_DEFAULTS["OFFER_BASE_SALARY_CENTS"],
    sign_on_bonus_cents: int = TEST_DEFAULTS["OFFER_SIGN_ON_BONUS_CENTS"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "base_salary_cents": base_salary_cents,
        "sign_on_bonus_cents": sign_on_bonus_cents,
    }
    payload.update(overrides)
    return payload


def accept_offer_payload(
    competing_offer_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if competing_offer_note is not None:
        payload["competing_offer_note"] = competing_offer_note
    payload.update(overrides)
    return payload


def rescind_offer_payload(
    rescission_reason: str = "BUSINESS_NEED",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rescission_reason": rescission_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Onboardings (PRD §3.7)
# ---------------------------------------------------------------------------
def create_onboarding_payload(
    offer_id: str,
    start_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "offer_id": offer_id,
        "start_date": start_date,
    }
    payload.update(overrides)
    return payload


def record_check_payload(
    check_kind: str = "BACKGROUND",
    outcome: str = "PASSED",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "check_kind": check_kind,
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def conversion_decision_payload(
    decision: str = "PASS",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def onboarding_feedback_payload(
    side: str = "CANDIDATE",
    score: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"side": side, "score": score}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Headhunter contracts (PRD §3.8)
# ---------------------------------------------------------------------------
def create_headhunter_contract_payload(
    headhunter_user_id: Optional[str] = None,
    company_id: str = "",
    fee_model: str = "SUCCESS_FEE",
    success_fee_pct_bps: Optional[int] = 2000,
    retainer_amount_cents: Optional[int] = None,
    trigger_event: str = "OFFER_ACCEPTED",
    clawback_window_days: Optional[int] = None,
    tax_withholding_pct_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "headhunter_user_id": (
            headhunter_user_id or unique_token("hh-user")
        ),
        "company_id": company_id,
        "fee_model": fee_model,
        "trigger_event": trigger_event,
    }
    if success_fee_pct_bps is not None:
        payload["success_fee_pct_bps"] = success_fee_pct_bps
    if retainer_amount_cents is not None:
        payload["retainer_amount_cents"] = retainer_amount_cents
    if clawback_window_days is not None:
        payload["clawback_window_days"] = clawback_window_days
    if tax_withholding_pct_bps is not None:
        payload["tax_withholding_pct_bps"] = tax_withholding_pct_bps
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driver endpoints (PRD §3.9)
# ---------------------------------------------------------------------------
def clock_advance_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def emit_event_payload(
    system: str = "calendar",
    kind: str = "scheduled",
    subject_id: str = "",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "system": system,
        "kind": kind,
        "subject_id": subject_id,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "unique_token",
    "create_company_payload",
    "blacklist_company_payload",
    "create_hr_binding_payload",
    "create_job_posting_payload",
    "reject_posting_payload",
    "create_candidate_payload",
    "update_candidate_payload",
    "create_application_payload",
    "create_interview_round_payload",
    "publish_slots_payload",
    "candidate_confirm_payload",
    "submit_round_feedback_payload",
    "create_offer_payload",
    "accept_offer_payload",
    "rescind_offer_payload",
    "create_onboarding_payload",
    "record_check_payload",
    "conversion_decision_payload",
    "onboarding_feedback_payload",
    "create_headhunter_contract_payload",
    "clock_advance_payload",
    "emit_event_payload",
]
