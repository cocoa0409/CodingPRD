"""Composite setup helpers — multi-step preambles tests can reuse.

The ATS lifecycle takes 5-15 API calls to reach interesting states
(e.g., an Application in OFFER_STAGE with a single-step approval chain
ready to approve; an Offer in EXTENDED with PASSED BG; a hire that
cascaded a Requisition to CLOSED). Each fixture composes the lower-
level steps so the test body focuses on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "Four of these roles are entity-backed, meaning `X-User-ID` must
    be the `id` of a persisted entity. When `X-User-Role` is
    `Recruiter`, `X-User-ID` is the `id` of the acting `Recruiter` ...
    When `X-User-Role` is `HiringManager`, `X-User-ID` is the `id`
    of the acting `HiringManager` ... When `X-User-Role` is
    `Interviewer`, `X-User-ID` is the `id` of the acting `Interviewer`
    ... When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of
    the acting `Candidate`."

Every ownership-gated call inside a fixture mints headers via
make_<role>_headers(entity_id) with the real entity id — never the
shared placeholder. Opaque-role calls (PlatformAdmin, Compensation,
Executive, ComplianceOfficer, PayrollOperator) may use shared
constants.

CLOCK ANCHORING — PRD §2.11:

    "Because several transitions are time-gated (interview completion
    eligibility, offer expiration, referral payable accrual), the
    system exposes a `PlatformAdmin`-only test-driving capability that
    advances the logical clock to a supplied `to` instant in ISO 8601
    UTC..."

Fixtures pin a known clock via /_clock/advance using
platform_admin_headers and place interview windows / expires_at /
payable_at relative to that anchor.

Setup calls use `get_success_data` (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    REFERRAL_WAITING_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    add_days,
    add_hours,
    add_minutes,
    add_seconds,
    approve_offer_payload,
    clock_advance_payload,
    create_application_payload,
    create_background_check_payload,
    create_candidate_payload,
    create_diversity_goal_payload,
    create_eeo_record_payload,
    create_hiring_manager_payload,
    create_interview_feedback_payload,
    create_interview_payload,
    create_interviewer_payload,
    create_offer_payload,
    create_recruiter_payload,
    create_requisition_payload,
    emit_event_payload,
    extend_offer_payload,
    offer_approval_step_payload,
    parse_iso,
    report_bgc_result_payload,
    request_revision_payload,
)
from .test_users import (
    COMPENSATION_SHARED_ID,
    EXECUTIVE_SHARED_ID,
    TEST_USERS,
    make_candidate_headers,
    make_compensation_headers,
    make_compliance_officer_headers,
    make_executive_headers,
    make_hiring_manager_headers,
    make_interviewer_headers,
    make_payroll_operator_headers,
    make_recruiter_headers,
)


# ===========================================================================
# Logical clock — PRD §2.11
# ===========================================================================
def advance_clock_to_iso(target_iso: str) -> None:
    """PRD §2.11: "advances the logical clock to a supplied `to`
    instant in ISO 8601 UTC". PlatformAdmin-only."""
    h = TEST_USERS["platform_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=target_iso), h,
    )
    get_success_data(resp)


def try_advance_clock_to_iso(target_iso: str) -> bool:
    """Best-effort clock advance. Returns True if the implementation
    accepted the request (or if it had no effect because the clock
    is already past the target); False if it failed for some other
    reason.

    Used by fixtures that pin a starting anchor: PRD §2.11 says
    "advance" (forward-only), so a redundant call from within a test
    that has already pushed the clock forward may be rejected by the
    implementation. The setup just wants the clock to be AT-OR-PAST
    the target, which is already true.
    """
    h = TEST_USERS["platform_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=target_iso), h,
    )
    return 200 <= resp.status_code < 300


def emit_offer_expiry_sweep() -> None:
    h = TEST_USERS["platform_admin_headers"]
    get_success_data(api_client.emit_event(
        emit_event_payload(event_type="OFFER_EXPIRY_SWEEP"), h,
    ))


def emit_referral_payable_sweep() -> None:
    h = TEST_USERS["platform_admin_headers"]
    get_success_data(api_client.emit_event(
        emit_event_payload(event_type="REFERRAL_PAYABLE_SWEEP"), h,
    ))


def init_clock(iso: Optional[str] = None) -> str:
    """Pin the clock to a deterministic anchor. Returns the anchor.

    Uses try_advance: PRD §2.11 says the call "advances" the clock
    (forward-only). When the clock is already past the requested
    anchor (e.g., a nested fixture call within the same test), the
    request may be rejected — the postcondition the caller wants
    ("clock is at or past anchor") is already satisfied, so we
    swallow the rejection."""
    anchor = iso or TEST_DEFAULTS["INITIAL_CLOCK_ISO"]
    try_advance_clock_to_iso(anchor)
    return anchor


# ===========================================================================
# Read helpers
# ===========================================================================
def get_recruiter(recruiter_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_recruiter(recruiter_id, h))


def get_requisition(requisition_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_requisition(requisition_id, h))


def get_application(application_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_application(application_id, h))


def get_offer(offer_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_offer(offer_id, h))


def get_interview(interview_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_interview(interview_id, h))


def get_background_check(bgc_id: str,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_background_check(bgc_id, h))


def get_referral_bonus(bonus_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_referral_bonus(bonus_id, h))


def get_diversity_goal(goal_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_diversity_goal(goal_id, h))


def list_referral_bonuses(
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.list_referral_bonuses(h, params=params)
    body = get_success_data(resp)
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


def list_approval_chain(offer_id: str,
                        headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_approval_chain(offer_id, h)
    body = get_success_data(resp)
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


# ===========================================================================
# Tier 0 — Foundation creators (people).
# PRD §3.1: PlatformAdmin creates Recruiter / HiringManager /
# Interviewer; Recruiter or PlatformAdmin creates Candidate.
# ===========================================================================
def create_recruiter(
    *,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    department_code: Optional[str] = None,
) -> Dict[str, Any]:
    h = TEST_USERS["platform_admin_headers"]
    payload = create_recruiter_payload(
        email=email,
        full_name=full_name,
        department_code=department_code,
    )
    return get_success_data(api_client.create_recruiter(payload, h))


def create_hiring_manager(
    *,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    department_code: Optional[str] = None,
    budget_cents: Optional[int] = None,
) -> Dict[str, Any]:
    h = TEST_USERS["platform_admin_headers"]
    payload = create_hiring_manager_payload(
        email=email,
        full_name=full_name,
        department_code=department_code,
        budget_cents=budget_cents,
    )
    return get_success_data(api_client.create_hiring_manager(payload, h))


def create_interviewer(
    *,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    department_code: Optional[str] = None,
    is_certified_for_eeo: Optional[bool] = None,
) -> Dict[str, Any]:
    h = TEST_USERS["platform_admin_headers"]
    payload = create_interviewer_payload(
        email=email,
        full_name=full_name,
        department_code=department_code,
        is_certified_for_eeo=is_certified_for_eeo,
    )
    return get_success_data(api_client.create_interviewer(payload, h))


def create_candidate(
    *,
    source: str = "DIRECT",
    referrer_employee_id: Optional[str] = None,
    is_in_eeo_protected_class: Optional[bool] = None,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    actor_recruiter_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1: Candidate records are created by a Recruiter or
    PlatformAdmin. When actor_recruiter_id is given, we act as that
    recruiter; otherwise we use PlatformAdmin (opaque)."""
    if actor_recruiter_id is not None:
        h = make_recruiter_headers(actor_recruiter_id)
    else:
        h = TEST_USERS["platform_admin_headers"]
    payload = create_candidate_payload(
        email=email,
        full_name=full_name,
        source=source,
        referrer_employee_id=referrer_employee_id,
        is_in_eeo_protected_class=is_in_eeo_protected_class,
    )
    return get_success_data(api_client.create_candidate(payload, h))


def attach_eeo_record(
    *,
    candidate_id: str,
    gender: str = "DECLINE",
    ethnicity: str = "DECLINE",
    veteran_status: str = "DECLINE",
    disability_status: str = "DECLINE",
    actor: str = "candidate",
) -> Dict[str, Any]:
    """PRD §3.1: "Either the candidate themselves or a
    `ComplianceOfficer` may attach the record."

    Default actor=candidate exercises the ownership-gated path
    (candidate acting on own candidate_id).
    """
    if actor == "candidate":
        h = make_candidate_headers(candidate_id)
    elif actor == "compliance_officer":
        h = TEST_USERS["compliance_officer_headers"]
    else:
        raise ValueError(f"Unknown actor: {actor!r}")
    payload = create_eeo_record_payload(
        gender=gender,
        ethnicity=ethnicity,
        veteran_status=veteran_status,
        disability_status=disability_status,
    )
    return get_success_data(
        api_client.create_eeo_record(candidate_id, payload, h),
    )


def create_diversity_goal(
    *,
    department_code: Optional[str] = None,
    period_year: int = 2026,
    target_protected_class_percentage: float = 30.0,
) -> Dict[str, Any]:
    h = TEST_USERS["platform_admin_headers"]
    payload = create_diversity_goal_payload(
        department_code=department_code,
        period_year=period_year,
        target_protected_class_percentage=target_protected_class_percentage,
    )
    return get_success_data(api_client.create_diversity_goal(payload, h))


# ===========================================================================
# Tier 1 — Requisition state walkers.
# PRD §3.2: Recruiter creates Requisition (DRAFT) → /submit
# (PENDING_APPROVAL) → HiringManager /approve (OPEN).
# ===========================================================================
def create_draft_requisition(
    *,
    recruiter_id: str,
    hiring_manager_id: str,
    seniority_level: str = "SENIOR",
    headcount: int = 1,
    department_code: Optional[str] = None,
    budget_cents: Optional[int] = None,
    job_title: Optional[str] = None,
    target_diversity_goal_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns Requisition in DRAFT."""
    h = make_recruiter_headers(recruiter_id)
    payload = create_requisition_payload(
        recruiter_id=recruiter_id,
        hiring_manager_id=hiring_manager_id,
        job_title=job_title,
        department_code=department_code,
        seniority_level=seniority_level,
        headcount=headcount,
        budget_cents=budget_cents,
        target_diversity_goal_id=target_diversity_goal_id,
    )
    return get_success_data(api_client.create_requisition(payload, h))


def submit_requisition(
    *,
    requisition_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(
        api_client.submit_requisition(requisition_id, h),
    )


def approve_requisition(
    *,
    requisition_id: str,
    hiring_manager_id: str,
) -> Dict[str, Any]:
    h = make_hiring_manager_headers(hiring_manager_id)
    return get_success_data(
        api_client.approve_requisition(requisition_id, h),
    )


def reject_requisition(
    *,
    requisition_id: str,
    hiring_manager_id: str,
) -> Dict[str, Any]:
    h = make_hiring_manager_headers(hiring_manager_id)
    return get_success_data(
        api_client.reject_requisition(requisition_id, h),
    )


def hold_requisition(
    *,
    requisition_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.hold_requisition(requisition_id, h))


def resume_requisition(
    *,
    requisition_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.resume_requisition(requisition_id, h))


def cancel_requisition(
    *,
    requisition_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.cancel_requisition(requisition_id, h))


def setup_open_requisition(
    *,
    seniority_level: str = "SENIOR",
    headcount: int = 1,
    department_code: Optional[str] = None,
    budget_cents: Optional[int] = None,
    hiring_manager_budget_cents: Optional[int] = None,
    target_diversity_goal_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create Recruiter + HiringManager + Requisition, walk through
    submit → approve → OPEN. Returns (recruiter, hiring_manager,
    requisition)."""
    dept = department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
    recruiter = create_recruiter(department_code=dept)
    hm = create_hiring_manager(
        department_code=dept,
        budget_cents=hiring_manager_budget_cents,
    )
    req = create_draft_requisition(
        recruiter_id=recruiter["id"],
        hiring_manager_id=hm["id"],
        seniority_level=seniority_level,
        headcount=headcount,
        department_code=dept,
        budget_cents=budget_cents,
        target_diversity_goal_id=target_diversity_goal_id,
    )
    submit_requisition(requisition_id=req["id"],
                       recruiter_id=recruiter["id"])
    req = approve_requisition(requisition_id=req["id"],
                              hiring_manager_id=hm["id"])
    return recruiter, hm, req


# ===========================================================================
# Tier 2 — Application stage walkers.
# PRD §3.3: APPLIED → SCREENING → INTERVIEWING → OFFER_STAGE.
# ===========================================================================
def create_application(
    *,
    requisition_id: str,
    candidate_id: str,
    actor_recruiter_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.3: "is permitted to either the `Recruiter` who owns the
    requisition or the `Candidate` themselves applying directly."

    If actor_recruiter_id is provided, act as the recruiter; otherwise
    act as the candidate (requires the candidate to be the applicant).
    """
    if actor_recruiter_id is not None:
        h = make_recruiter_headers(actor_recruiter_id)
    else:
        h = make_candidate_headers(candidate_id)
    payload = create_application_payload(candidate_id=candidate_id)
    return get_success_data(
        api_client.create_application(requisition_id, payload, h),
    )


def advance_application(
    *,
    application_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.advance_application(application_id, h))


def schedule_interview(
    *,
    application_id: str,
    recruiter_id: str,
    interviewer_id: str,
    start_at: str,
    end_at: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    payload = create_interview_payload(
        interviewer_id=interviewer_id,
        scheduled_start_at=start_at,
        scheduled_end_at=end_at,
    )
    return get_success_data(
        api_client.create_interview(application_id, payload, h),
    )


def complete_interview(
    *,
    interview_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.complete_interview(interview_id, h))


def submit_feedback(
    *,
    interview_id: str,
    interviewer_id: str,
    overall_score: int = 5,
    recommendation: str = "STRONG_HIRE",
) -> Dict[str, Any]:
    """PRD §3.4: "The submitting `interviewer_id` on the feedback must
    equal the interview's `interviewer_id`". Therefore the Interviewer
    acting MUST have id == the Interview.interviewer_id."""
    h = make_interviewer_headers(interviewer_id)
    payload = create_interview_feedback_payload(
        overall_score=overall_score,
        recommendation=recommendation,
    )
    return get_success_data(
        api_client.create_interview_feedback(interview_id, payload, h),
    )


def advance_application_to_interviewing(
    *,
    application: Dict[str, Any],
    recruiter_id: str,
    interviewer_id: str,
    anchor_iso: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walk APPLIED → SCREENING → INTERVIEWING. Schedule one Interview
    starting at anchor_iso+1h to anchor_iso+2h.

    Returns (application_in_INTERVIEWING, scheduled_interview).
    """
    application = advance_application(application_id=application["id"],
                                      recruiter_id=recruiter_id)
    # PRD §3.3: SCREENING → INTERVIEWING requires at least one SCHEDULED
    # Interview to exist. Schedule it BEFORE the advance.
    start = add_hours(anchor_iso, 1)
    end = add_hours(anchor_iso, 2)
    interview = schedule_interview(
        application_id=application["id"],
        recruiter_id=recruiter_id,
        interviewer_id=interviewer_id,
        start_at=start,
        end_at=end,
    )
    application = advance_application(application_id=application["id"],
                                      recruiter_id=recruiter_id)
    return application, interview


def advance_application_to_offer_stage(
    *,
    application: Dict[str, Any],
    interview: Dict[str, Any],
    recruiter_id: str,
    interviewer_id: str,
    recommendation: str = "STRONG_HIRE",
    overall_score: int = 5,
) -> Dict[str, Any]:
    """From an INTERVIEWING application with a SCHEDULED interview:
    advance the clock past interview.scheduled_end_at, complete the
    interview, submit qualifying feedback, then advance to OFFER_STAGE.
    """
    # PRD §3.4: complete requires now() >= scheduled_end_at. Advance
    # the clock one minute past the scheduled end. If the clock is
    # already past that instant (e.g., a previous test pushed it
    # forward), the call is a no-op — the postcondition "clock >=
    # end_iso" still holds.
    end_iso = interview["scheduled_end_at"]
    try_advance_clock_to_iso(add_minutes(end_iso, 1))
    complete_interview(interview_id=interview["id"],
                       recruiter_id=recruiter_id)
    submit_feedback(interview_id=interview["id"],
                    interviewer_id=interviewer_id,
                    overall_score=overall_score,
                    recommendation=recommendation)
    return advance_application(application_id=application["id"],
                               recruiter_id=recruiter_id)


def setup_application_in_offer_stage(
    *,
    seniority_level: str = "SENIOR",
    headcount: int = 1,
    department_code: Optional[str] = None,
    candidate_protected: bool = False,
    candidate_source: str = "DIRECT",
    candidate_referrer_employee_id: Optional[str] = None,
    attach_eeo: Optional[bool] = None,
    interviewer_is_certified: bool = True,
    requisition_budget_cents: Optional[int] = None,
    hiring_manager_budget_cents: Optional[int] = None,
    target_diversity_goal_id: Optional[str] = None,
    anchor_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Full preamble to an Application in OFFER_STAGE.

    Returns a context dict with: recruiter, hiring_manager, interviewer,
    candidate, requisition, application, interview, anchor_iso.

    candidate_protected drives Candidate.is_in_eeo_protected_class.
    By default, when protected==true we attach an EEORecord (PRD §3.3
    OFCCP gate). Pass attach_eeo=False to deliberately leave it off
    (e.g., to drive ERR_EEO_DATA_MISSING).
    """
    anchor = init_clock(anchor_iso)
    dept = department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
    recruiter, hm, req = setup_open_requisition(
        seniority_level=seniority_level,
        headcount=headcount,
        department_code=dept,
        budget_cents=requisition_budget_cents,
        hiring_manager_budget_cents=hiring_manager_budget_cents,
        target_diversity_goal_id=target_diversity_goal_id,
    )
    # PRD §3.4: Interviewer scoring an EEO-protected candidate must be
    # certified. To keep the happy path frictionless we certify
    # interviewer by default.
    interviewer = create_interviewer(
        department_code=dept,
        is_certified_for_eeo=interviewer_is_certified,
    )
    candidate = create_candidate(
        source=candidate_source,
        referrer_employee_id=candidate_referrer_employee_id,
        is_in_eeo_protected_class=candidate_protected,
        actor_recruiter_id=recruiter["id"],
    )
    should_attach = (
        attach_eeo if attach_eeo is not None else candidate_protected
    )
    if should_attach:
        attach_eeo_record(candidate_id=candidate["id"], actor="candidate")
    application = create_application(
        requisition_id=req["id"],
        candidate_id=candidate["id"],
        actor_recruiter_id=recruiter["id"],
    )
    application, interview = advance_application_to_interviewing(
        application=application,
        recruiter_id=recruiter["id"],
        interviewer_id=interviewer["id"],
        anchor_iso=anchor,
    )
    application = advance_application_to_offer_stage(
        application=application,
        interview=interview,
        recruiter_id=recruiter["id"],
        interviewer_id=interviewer["id"],
    )
    return {
        "recruiter": recruiter,
        "hiring_manager": hm,
        "interviewer": interviewer,
        "candidate": candidate,
        "requisition": req,
        "application": application,
        "interview": interview,
        "anchor_iso": anchor,
    }


def setup_application_in_interviewing(
    *,
    seniority_level: str = "SENIOR",
    headcount: int = 1,
    department_code: Optional[str] = None,
    candidate_protected: bool = False,
    attach_eeo: Optional[bool] = None,
    anchor_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Walks APPLIED → SCREENING → INTERVIEWING (one SCHEDULED
    interview exists). Returns dict like setup_application_in_offer_stage,
    but the application.stage == INTERVIEWING and no feedback/COMPLETED
    yet."""
    anchor = init_clock(anchor_iso)
    dept = department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
    recruiter, hm, req = setup_open_requisition(
        seniority_level=seniority_level,
        headcount=headcount,
        department_code=dept,
    )
    interviewer = create_interviewer(
        department_code=dept, is_certified_for_eeo=True,
    )
    candidate = create_candidate(
        is_in_eeo_protected_class=candidate_protected,
        actor_recruiter_id=recruiter["id"],
    )
    should_attach = (
        attach_eeo if attach_eeo is not None else candidate_protected
    )
    if should_attach:
        attach_eeo_record(candidate_id=candidate["id"], actor="candidate")
    application = create_application(
        requisition_id=req["id"],
        candidate_id=candidate["id"],
        actor_recruiter_id=recruiter["id"],
    )
    application, interview = advance_application_to_interviewing(
        application=application,
        recruiter_id=recruiter["id"],
        interviewer_id=interviewer["id"],
        anchor_iso=anchor,
    )
    return {
        "recruiter": recruiter,
        "hiring_manager": hm,
        "interviewer": interviewer,
        "candidate": candidate,
        "requisition": req,
        "application": application,
        "interview": interview,
        "anchor_iso": anchor,
    }


# ===========================================================================
# Tier 3 — Offer lifecycle helpers.
# PRD §3.5: Recruiter creates Offer → /submit (PENDING_APPROVAL) →
# /approve walks chain → APPROVED → /extend (EXTENDED) → Candidate
# /accept (ACCEPTED).
# ===========================================================================
def create_offer(
    *,
    application_id: str,
    recruiter_id: str,
    base_salary_cents: int = 150_000,
    sign_on_bonus_cents: Optional[int] = None,
    annual_equity_cents: Optional[int] = None,
    approval_chain: List[Dict[str, Any]],
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    payload = create_offer_payload(
        base_salary_cents=base_salary_cents,
        approval_chain=approval_chain,
        sign_on_bonus_cents=sign_on_bonus_cents,
        annual_equity_cents=annual_equity_cents,
    )
    return get_success_data(
        api_client.create_offer(application_id, payload, h),
    )


def submit_offer(
    *,
    offer_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.submit_offer(offer_id, h))


def approve_offer_step(
    *,
    offer_id: str,
    step_order: int,
    approver_role: str,
    approver_id: str,
) -> Dict[str, Any]:
    """approver_role one of HIRING_MANAGER, COMPENSATION, EXECUTIVE.
    approver_id MUST equal the matching OfferApprovalStep.required_approver_id.
    """
    if approver_role == "HIRING_MANAGER":
        h = make_hiring_manager_headers(approver_id)
    elif approver_role == "COMPENSATION":
        h = make_compensation_headers(approver_id)
    elif approver_role == "EXECUTIVE":
        h = make_executive_headers(approver_id)
    else:
        raise ValueError(f"Unknown approver_role: {approver_role!r}")
    payload = approve_offer_payload(step_order=step_order)
    return get_success_data(api_client.approve_offer(offer_id, payload, h))


def request_revision(
    *,
    offer_id: str,
    step_order: int,
    approver_role: str,
    approver_id: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    if approver_role == "HIRING_MANAGER":
        h = make_hiring_manager_headers(approver_id)
    elif approver_role == "COMPENSATION":
        h = make_compensation_headers(approver_id)
    elif approver_role == "EXECUTIVE":
        h = make_executive_headers(approver_id)
    else:
        raise ValueError(f"Unknown approver_role: {approver_role!r}")
    payload = request_revision_payload(step_order=step_order, reason=reason)
    return get_success_data(
        api_client.request_revision_offer(offer_id, payload, h),
    )


def extend_offer(
    *,
    offer_id: str,
    recruiter_id: str,
    expires_at: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    payload = extend_offer_payload(expires_at=expires_at)
    return get_success_data(api_client.extend_offer(offer_id, payload, h))


def accept_offer(
    *,
    offer_id: str,
    candidate_id: str,
) -> Dict[str, Any]:
    h = make_candidate_headers(candidate_id)
    return get_success_data(api_client.accept_offer(offer_id, h))


def decline_offer(
    *,
    offer_id: str,
    candidate_id: str,
) -> Dict[str, Any]:
    h = make_candidate_headers(candidate_id)
    return get_success_data(api_client.decline_offer(offer_id, h))


def rescind_offer(
    *,
    offer_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.rescind_offer(offer_id, h))


def withdraw_application(
    *,
    application_id: str,
    candidate_id: str,
) -> Dict[str, Any]:
    h = make_candidate_headers(candidate_id)
    return get_success_data(
        api_client.withdraw_application(application_id, h),
    )


def reject_application_with_reason(
    *,
    application_id: str,
    recruiter_id: str,
    rejection_reason: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    from .factories import reject_application_payload
    payload = reject_application_payload(rejection_reason=rejection_reason)
    return get_success_data(
        api_client.reject_application(application_id, payload, h),
    )


# ===========================================================================
# Tier 4 — Background check helpers.
# ===========================================================================
def order_background_check(
    *,
    offer_id: str,
    recruiter_id: str,
    vendor: str = "ACME_BG",
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    payload = create_background_check_payload(vendor=vendor)
    return get_success_data(
        api_client.create_background_check(offer_id, payload, h),
    )


def report_bgc_pass(*, bgc_id: str) -> Dict[str, Any]:
    h = TEST_USERS["compliance_officer_headers"]
    payload = report_bgc_result_payload(outcome="PASS")
    return get_success_data(
        api_client.report_background_check_result(bgc_id, payload, h),
    )


def report_bgc_fail(*, bgc_id: str) -> Dict[str, Any]:
    h = TEST_USERS["compliance_officer_headers"]
    payload = report_bgc_result_payload(outcome="FAIL")
    return get_success_data(
        api_client.report_background_check_result(bgc_id, payload, h),
    )


def cancel_background_check(
    *,
    bgc_id: str,
    recruiter_id: str,
) -> Dict[str, Any]:
    h = make_recruiter_headers(recruiter_id)
    return get_success_data(api_client.cancel_background_check(bgc_id, h))


# ===========================================================================
# Tier 5 — Composite scenarios (offer in specific lifecycle states).
# ===========================================================================
def build_single_hm_chain(hiring_manager_id: str) -> List[Dict[str, Any]]:
    """A single-step approval chain with the hiring manager as
    approver. Convenient for the most common offer setup."""
    return [
        offer_approval_step_payload(
            step_order=1,
            approver_role="HIRING_MANAGER",
            required_approver_id=hiring_manager_id,
        ),
    ]


def build_two_step_hm_then_comp_chain(
    *,
    hiring_manager_id: str,
    compensation_id: str = COMPENSATION_SHARED_ID,
) -> List[Dict[str, Any]]:
    return [
        offer_approval_step_payload(
            step_order=1,
            approver_role="HIRING_MANAGER",
            required_approver_id=hiring_manager_id,
        ),
        offer_approval_step_payload(
            step_order=2,
            approver_role="COMPENSATION",
            required_approver_id=compensation_id,
        ),
    ]


def setup_offer_in_pending_approval(
    *,
    base_salary_cents: int = 150_000,
    sign_on_bonus_cents: Optional[int] = None,
    annual_equity_cents: Optional[int] = None,
    seniority_level: str = "SENIOR",
    headcount: int = 1,
    requisition_budget_cents: Optional[int] = None,
    hiring_manager_budget_cents: Optional[int] = None,
    chain_kind: str = "single_hm",
    candidate_protected: bool = False,
    candidate_source: str = "DIRECT",
    candidate_referrer_employee_id: Optional[str] = None,
    target_diversity_goal_id: Optional[str] = None,
    anchor_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Build Application in OFFER_STAGE, then create Offer + /submit
    → PENDING_APPROVAL. Returns context dict including 'offer'.

    chain_kind: 'single_hm' (one HIRING_MANAGER step) or
    'two_step_hm_comp' (HIRING_MANAGER then COMPENSATION).
    """
    ctx = setup_application_in_offer_stage(
        seniority_level=seniority_level,
        headcount=headcount,
        candidate_protected=candidate_protected,
        candidate_source=candidate_source,
        candidate_referrer_employee_id=candidate_referrer_employee_id,
        requisition_budget_cents=requisition_budget_cents,
        hiring_manager_budget_cents=hiring_manager_budget_cents,
        target_diversity_goal_id=target_diversity_goal_id,
        anchor_iso=anchor_iso,
    )
    hm_id = ctx["hiring_manager"]["id"]
    if chain_kind == "single_hm":
        chain = build_single_hm_chain(hm_id)
    elif chain_kind == "two_step_hm_comp":
        chain = build_two_step_hm_then_comp_chain(hiring_manager_id=hm_id)
    else:
        raise ValueError(f"Unknown chain_kind: {chain_kind!r}")
    offer = create_offer(
        application_id=ctx["application"]["id"],
        recruiter_id=ctx["recruiter"]["id"],
        base_salary_cents=base_salary_cents,
        sign_on_bonus_cents=sign_on_bonus_cents,
        annual_equity_cents=annual_equity_cents,
        approval_chain=chain,
    )
    offer = submit_offer(offer_id=offer["id"],
                         recruiter_id=ctx["recruiter"]["id"])
    ctx["offer"] = offer
    return ctx


def setup_offer_approved(
    *,
    base_salary_cents: int = 150_000,
    sign_on_bonus_cents: Optional[int] = None,
    annual_equity_cents: Optional[int] = None,
    seniority_level: str = "SENIOR",
    headcount: int = 1,
    requisition_budget_cents: Optional[int] = None,
    hiring_manager_budget_cents: Optional[int] = None,
    candidate_protected: bool = False,
    candidate_source: str = "DIRECT",
    candidate_referrer_employee_id: Optional[str] = None,
    target_diversity_goal_id: Optional[str] = None,
    bgc_vendor: str = "ACME_BG",
    anchor_iso: Optional[str] = None,
    arm_post_approval_bgc: bool = True,
) -> Dict[str, Any]:
    """Build Offer all the way through APPROVED (single HM step,
    PASSED BG). Returns dict with offer + background_check + the rest
    of the upstream context.

    By default, after the offer is APPROVED, an additional PENDING
    BackgroundCheck is ordered so downstream tests (the §3.7 FAIL
    cascade) can fire FAIL against it while the offer sits in
    APPROVED/EXTENDED/ACCEPTED. PRD §3.7 calls out that "exactly one
    background check may be active per offer" — i.e., at most one
    PENDING — and the post-approval ordering is consistent with that
    rule. Pass arm_post_approval_bgc=False if a test specifically
    needs the offer to have no PENDING BGC at this point (e.g., the
    /approve-needs-PASSED cross-entity gate tests).

    ctx["background_check"] points to the PENDING BGC (the one tests
    will FAIL); ctx["passed_background_check"] points to the BGC that
    PASSED to enable approval.
    """
    ctx = setup_offer_in_pending_approval(
        base_salary_cents=base_salary_cents,
        sign_on_bonus_cents=sign_on_bonus_cents,
        annual_equity_cents=annual_equity_cents,
        seniority_level=seniority_level,
        headcount=headcount,
        requisition_budget_cents=requisition_budget_cents,
        hiring_manager_budget_cents=hiring_manager_budget_cents,
        chain_kind="single_hm",
        candidate_protected=candidate_protected,
        candidate_source=candidate_source,
        candidate_referrer_employee_id=candidate_referrer_employee_id,
        target_diversity_goal_id=target_diversity_goal_id,
        anchor_iso=anchor_iso,
    )
    bgc_passed = order_background_check(
        offer_id=ctx["offer"]["id"],
        recruiter_id=ctx["recruiter"]["id"],
        vendor=bgc_vendor,
    )
    bgc_passed = report_bgc_pass(bgc_id=bgc_passed["id"])
    ctx["passed_background_check"] = bgc_passed
    offer = approve_offer_step(
        offer_id=ctx["offer"]["id"],
        step_order=1,
        approver_role="HIRING_MANAGER",
        approver_id=ctx["hiring_manager"]["id"],
    )
    ctx["offer"] = offer
    if arm_post_approval_bgc:
        # Order a fresh PENDING BGC so the §3.7 FAIL cascade is
        # reachable while the offer is APPROVED/EXTENDED/ACCEPTED.
        bgc_pending = order_background_check(
            offer_id=offer["id"],
            recruiter_id=ctx["recruiter"]["id"],
            vendor=bgc_vendor,
        )
        ctx["background_check"] = bgc_pending
    else:
        ctx["background_check"] = bgc_passed
    return ctx


def setup_offer_extended(
    *,
    expires_at_offset_days: int = 7,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build Offer through EXTENDED. expires_at = anchor + offset days."""
    ctx = setup_offer_approved(**kwargs)
    anchor = ctx["anchor_iso"]
    expires_at = add_days(anchor, expires_at_offset_days)
    offer = extend_offer(
        offer_id=ctx["offer"]["id"],
        recruiter_id=ctx["recruiter"]["id"],
        expires_at=expires_at,
    )
    ctx["offer"] = offer
    ctx["expires_at"] = expires_at
    return ctx


def setup_offer_accepted(**kwargs: Any) -> Dict[str, Any]:
    """Build Offer all the way through ACCEPTED. The hire cascade
    (Application → HIRED, Requisition.filled_count++, possibly
    Requisition→CLOSED, ReferralBonus recompute) has fired by return."""
    ctx = setup_offer_extended(**kwargs)
    offer = accept_offer(
        offer_id=ctx["offer"]["id"],
        candidate_id=ctx["candidate"]["id"],
    )
    ctx["offer"] = offer
    # Re-read parent application + requisition so callers see post-cascade
    # state.
    ctx["application"] = get_application(ctx["application"]["id"])
    ctx["requisition"] = get_requisition(ctx["requisition"]["id"])
    return ctx


# ===========================================================================
# Tier 6 — Referral bonus / diversity goal hire chains.
# ===========================================================================
def setup_referral_hire(
    *,
    seniority_level: str = "SENIOR",
    candidate_protected: bool = False,
    target_diversity_goal_id: Optional[str] = None,
    anchor_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a referral hire all the way through ACCEPTED so that a
    ReferralBonus has been created/computed. The referrer is the
    recruiter; candidate.source = REFERRAL.

    Returns ctx with offer ACCEPTED and a list 'referral_bonuses' read
    from /referral-bonuses filtered by candidate_id.
    """
    anchor = init_clock(anchor_iso)
    dept = TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
    recruiter, hm, req = setup_open_requisition(
        seniority_level=seniority_level,
        headcount=1,
        department_code=dept,
        target_diversity_goal_id=target_diversity_goal_id,
    )
    interviewer = create_interviewer(department_code=dept,
                                     is_certified_for_eeo=True)
    candidate = create_candidate(
        source="REFERRAL",
        referrer_employee_id=recruiter["id"],
        is_in_eeo_protected_class=candidate_protected,
        actor_recruiter_id=recruiter["id"],
    )
    if candidate_protected:
        attach_eeo_record(candidate_id=candidate["id"], actor="candidate")
    application = create_application(
        requisition_id=req["id"],
        candidate_id=candidate["id"],
        actor_recruiter_id=recruiter["id"],
    )
    application, interview = advance_application_to_interviewing(
        application=application,
        recruiter_id=recruiter["id"],
        interviewer_id=interviewer["id"],
        anchor_iso=anchor,
    )
    application = advance_application_to_offer_stage(
        application=application,
        interview=interview,
        recruiter_id=recruiter["id"],
        interviewer_id=interviewer["id"],
    )
    offer = create_offer(
        application_id=application["id"],
        recruiter_id=recruiter["id"],
        base_salary_cents=150_000,
        approval_chain=build_single_hm_chain(hm["id"]),
    )
    offer = submit_offer(offer_id=offer["id"], recruiter_id=recruiter["id"])
    bgc_passed = order_background_check(
        offer_id=offer["id"], recruiter_id=recruiter["id"],
    )
    bgc_passed = report_bgc_pass(bgc_id=bgc_passed["id"])
    offer = approve_offer_step(
        offer_id=offer["id"], step_order=1,
        approver_role="HIRING_MANAGER", approver_id=hm["id"],
    )
    offer = extend_offer(
        offer_id=offer["id"], recruiter_id=recruiter["id"],
        expires_at=add_days(anchor, 7),
    )
    offer = accept_offer(offer_id=offer["id"],
                         candidate_id=candidate["id"])
    # Post-hire: arm a fresh PENDING BGC so the §3.7 post-hire revoke
    # cascade is reachable via report_bgc_fail.
    bgc_pending = order_background_check(
        offer_id=offer["id"], recruiter_id=recruiter["id"],
    )
    application = get_application(application["id"])
    requisition = get_requisition(req["id"])
    bonuses = list_referral_bonuses(
        params={"candidate_id": candidate["id"], "limit": 100},
    )
    return {
        "recruiter": recruiter,
        "hiring_manager": hm,
        "interviewer": interviewer,
        "candidate": candidate,
        "requisition": requisition,
        "application": application,
        "interview": interview,
        "offer": offer,
        "background_check": bgc_pending,
        "passed_background_check": bgc_passed,
        "referral_bonuses": bonuses,
        "anchor_iso": anchor,
    }


# ===========================================================================
# Tier 7 — Difficulty-design composite scenarios.
# ===========================================================================
def setup_two_step_offer_pending_approval(
    *,
    compensation_id: str = COMPENSATION_SHARED_ID,
    anchor_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Offer in PENDING_APPROVAL with TWO OfferApprovalSteps
    (HIRING_MANAGER then COMPENSATION) and a PASSED BackgroundCheck —
    the canonical setup for the renegotiation-cycle test."""
    ctx = setup_offer_in_pending_approval(
        base_salary_cents=150_000,
        sign_on_bonus_cents=0,
        annual_equity_cents=0,
        chain_kind="two_step_hm_comp",
        anchor_iso=anchor_iso,
    )
    bgc = order_background_check(
        offer_id=ctx["offer"]["id"],
        recruiter_id=ctx["recruiter"]["id"],
    )
    bgc = report_bgc_pass(bgc_id=bgc["id"])
    ctx["background_check"] = bgc
    ctx["compensation_id"] = compensation_id
    return ctx


def setup_recruiter_with_n_open_requisitions(
    *,
    n: int,
    department_code: Optional[str] = None,
    anchor_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one Recruiter + one HiringManager and walk n separate
    Requisitions to OPEN (posted_at set, closed_at null). Useful for
    the recruiter open-requisition cap boundary tests.

    Returns dict with recruiter, hiring_manager, requisitions (list).
    """
    if anchor_iso is not None:
        init_clock(anchor_iso)
    dept = department_code or TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
    recruiter = create_recruiter(department_code=dept)
    hm = create_hiring_manager(department_code=dept)
    reqs = []
    for _ in range(n):
        req = create_draft_requisition(
            recruiter_id=recruiter["id"],
            hiring_manager_id=hm["id"],
            seniority_level="SENIOR",
            headcount=1,
            department_code=dept,
        )
        submit_requisition(requisition_id=req["id"],
                           recruiter_id=recruiter["id"])
        req = approve_requisition(requisition_id=req["id"],
                                  hiring_manager_id=hm["id"])
        reqs.append(req)
    return {
        "recruiter": recruiter,
        "hiring_manager": hm,
        "requisitions": reqs,
    }


def setup_interviewer_with_scheduled_interview(
    *,
    start_iso: str,
    end_iso: str,
    anchor_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an Interviewer V and one SCHEDULED Interview on V from
    start_iso to end_iso. Returns dict with the recruiter, V, the
    application, and the existing interview.

    Useful for ERR_INTERVIEWER_DOUBLE_BOOKED tests.
    """
    anchor = init_clock(anchor_iso)
    dept = TEST_DEFAULTS["DEFAULT_DEPARTMENT_CODE"]
    recruiter, hm, req = setup_open_requisition(
        seniority_level="SENIOR", headcount=2, department_code=dept,
    )
    V = create_interviewer(department_code=dept,
                           is_certified_for_eeo=True)
    candidate = create_candidate(
        actor_recruiter_id=recruiter["id"],
    )
    application = create_application(
        requisition_id=req["id"],
        candidate_id=candidate["id"],
        actor_recruiter_id=recruiter["id"],
    )
    # PRD §3.3: APPLIED → SCREENING needs only OPEN; SCREENING →
    # INTERVIEWING needs a SCHEDULED Interview. We move to SCREENING
    # and schedule one Interview.
    application = advance_application(
        application_id=application["id"], recruiter_id=recruiter["id"],
    )
    existing = schedule_interview(
        application_id=application["id"],
        recruiter_id=recruiter["id"],
        interviewer_id=V["id"],
        start_at=start_iso,
        end_at=end_iso,
    )
    return {
        "recruiter": recruiter,
        "hiring_manager": hm,
        "requisition": req,
        "interviewer": V,
        "candidate_a": candidate,
        "application_a": application,
        "interview_a": existing,
        "anchor_iso": anchor,
    }


def make_second_application_under_recruiter(
    *,
    recruiter_id: str,
    hiring_manager_id: str,
    department_code: str,
    headcount: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Companion to setup_interviewer_with_scheduled_interview: build
    a SECOND Requisition + Candidate + Application (in SCREENING) under
    the same recruiter so an additional Interview can be scheduled on
    the same Interviewer."""
    req2 = create_draft_requisition(
        recruiter_id=recruiter_id,
        hiring_manager_id=hiring_manager_id,
        seniority_level="SENIOR",
        headcount=headcount,
        department_code=department_code,
    )
    submit_requisition(requisition_id=req2["id"], recruiter_id=recruiter_id)
    req2 = approve_requisition(requisition_id=req2["id"],
                               hiring_manager_id=hiring_manager_id)
    candidate2 = create_candidate(actor_recruiter_id=recruiter_id)
    application2 = create_application(
        requisition_id=req2["id"],
        candidate_id=candidate2["id"],
        actor_recruiter_id=recruiter_id,
    )
    application2 = advance_application(
        application_id=application2["id"], recruiter_id=recruiter_id,
    )
    return req2, candidate2, application2


__all__ = [
    # Clock / events
    "advance_clock_to_iso",
    "try_advance_clock_to_iso",
    "emit_offer_expiry_sweep",
    "emit_referral_payable_sweep",
    "init_clock",
    # Read helpers
    "get_recruiter",
    "get_requisition",
    "get_application",
    "get_offer",
    "get_interview",
    "get_background_check",
    "get_referral_bonus",
    "get_diversity_goal",
    "list_referral_bonuses",
    "list_approval_chain",
    # Tier 0 — people
    "create_recruiter",
    "create_hiring_manager",
    "create_interviewer",
    "create_candidate",
    "attach_eeo_record",
    "create_diversity_goal",
    # Tier 1 — requisition
    "create_draft_requisition",
    "submit_requisition",
    "approve_requisition",
    "reject_requisition",
    "hold_requisition",
    "resume_requisition",
    "cancel_requisition",
    "setup_open_requisition",
    # Tier 2 — application
    "create_application",
    "advance_application",
    "schedule_interview",
    "complete_interview",
    "submit_feedback",
    "advance_application_to_interviewing",
    "advance_application_to_offer_stage",
    "setup_application_in_offer_stage",
    "setup_application_in_interviewing",
    # Tier 3 — offer
    "create_offer",
    "submit_offer",
    "approve_offer_step",
    "request_revision",
    "extend_offer",
    "accept_offer",
    "decline_offer",
    "rescind_offer",
    "withdraw_application",
    "reject_application_with_reason",
    # Tier 4 — background check
    "order_background_check",
    "report_bgc_pass",
    "report_bgc_fail",
    "cancel_background_check",
    # Tier 5 — composite offer scenarios
    "build_single_hm_chain",
    "build_two_step_hm_then_comp_chain",
    "setup_offer_in_pending_approval",
    "setup_offer_approved",
    "setup_offer_extended",
    "setup_offer_accepted",
    # Tier 6 — referral / diversity
    "setup_referral_hire",
    # Tier 7 — difficulty-design composites
    "setup_two_step_offer_pending_approval",
    "setup_recruiter_with_n_open_requisitions",
    "setup_interviewer_with_scheduled_interview",
    "make_second_application_under_recruiter",
]
