"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every helper builds its preconditions from scratch using only PRD-declared endpoints —
the test harness restarts the server before every pytest test so the database is empty
at the start of each fixture call.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_department_payload,
    create_requisition_payload,
    create_candidate_payload,
    create_referral_candidate_payload,
    create_application_payload,
    create_interview_payload,
    create_interview_feedback_payload,
    create_offer_payload,
    approve_offer_payload,
    cancel_requisition_payload,
    resolve_background_check_payload,
    create_diversity_goal_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_headers


# ---------- Tier 0: clock ----------

def set_clock(iso_instant: str) -> dict:
    """Set the test-driving clock (PRD §3.8). Returns response data with `now` and
    `revoked_offer_ids`."""
    res = api_client.set_clock(set_clock_payload(iso_instant), TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


# ---------- Tier 1: Department + Requisition state progression ----------

def create_department(budget_cents: int = 200_000_000, **overrides) -> dict:
    """Create a Department (PRD §3.1)."""
    payload = create_department_payload(hiring_budget_cents=budget_cents, **overrides)
    res = api_client.create_department(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def create_requisition(department_id: str, recruiter_headers=None, **overrides) -> dict:
    """Create a DRAFT requisition (PRD §3.2)."""
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    payload = create_requisition_payload(department_id, **overrides)
    res = api_client.create_requisition(payload, headers)
    return get_success_data(res)


def submit_requisition(req_id: str, recruiter_headers=None) -> dict:
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    res = api_client.submit_requisition(req_id, headers)
    return get_success_data(res)


def approve_requisition(req_id: str, hiring_manager_headers=None) -> dict:
    headers = hiring_manager_headers or TEST_USERS["hiring_manager_headers"]
    res = api_client.approve_requisition(req_id, headers)
    return get_success_data(res)


def create_approved_requisition(department_id: str = None,
                                budget_cents: int = 200_000_000,
                                recruiter_headers=None,
                                hiring_manager_headers=None,
                                **req_overrides) -> tuple:
    """Create Dept (if not provided) + Requisition + submit + approve. Returns (dept, req)."""
    if department_id is None:
        dept = create_department(budget_cents=budget_cents)
        department_id = dept["id"]
    else:
        dept = None
    req = create_requisition(department_id, recruiter_headers=recruiter_headers, **req_overrides)
    submit_requisition(req["id"], recruiter_headers=recruiter_headers)
    req_approved = approve_requisition(req["id"], hiring_manager_headers=hiring_manager_headers)
    if dept is None:
        # Re-fetch dept since caller asked us to use an existing one
        get_res = api_client.get_department(department_id, TEST_USERS["platform_admin_headers"])
        dept = get_success_data(get_res)
    return dept, req_approved


# ---------- Tier 2: Candidate + Application ----------

def create_candidate(referral_referrer_user_id: str = None, **overrides) -> dict:
    """Create a Candidate. If referral_referrer_user_id is supplied, source_channel=REFERRAL."""
    if referral_referrer_user_id is not None:
        payload = create_referral_candidate_payload(referral_referrer_user_id, **overrides)
    else:
        payload = create_candidate_payload(**overrides)
    res = api_client.create_candidate(payload, TEST_USERS["recruiter_headers"])
    return get_success_data(res)


def create_application(candidate_id: str, requisition_id: str,
                       recruiter_headers=None) -> dict:
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    payload = create_application_payload(candidate_id, requisition_id)
    res = api_client.create_application(payload, headers)
    return get_success_data(res)


def screen_application(app_id: str, recruiter_headers=None) -> dict:
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    res = api_client.screen_application(app_id, headers)
    return get_success_data(res)


def setup_approved_req_with_screened_app(budget_cents: int = 200_000_000,
                                         req_overrides=None,
                                         candidate_referrer_user_id: str = None,
                                         cand_overrides=None,
                                         recruiter_headers=None,
                                         hiring_manager_headers=None) -> tuple:
    """Dept + APPROVED Requisition + Candidate + Application (SCREENING). Returns
    (dept, req, candidate, app)."""
    dept, req = create_approved_requisition(
        budget_cents=budget_cents,
        recruiter_headers=recruiter_headers,
        hiring_manager_headers=hiring_manager_headers,
        **(req_overrides or {}),
    )
    cand = create_candidate(
        referral_referrer_user_id=candidate_referrer_user_id,
        **(cand_overrides or {}),
    )
    app = create_application(cand["id"], req["id"], recruiter_headers=recruiter_headers)
    app = screen_application(app["id"], recruiter_headers=recruiter_headers)
    return dept, req, cand, app


# ---------- Tier 3: Offer lifecycle shortcuts ----------

def create_offer(application_id: str, base_salary_cents: int = 12_000_000,
                 signing_bonus_cents: int = 0, recruiter_headers=None,
                 **overrides) -> dict:
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    payload = create_offer_payload(application_id, base_salary_cents=base_salary_cents,
                                   signing_bonus_cents=signing_bonus_cents, **overrides)
    res = api_client.create_offer(payload, headers)
    return get_success_data(res)


def comp_approve_offer(offer_id: str, expected_version: int,
                       comp_headers=None) -> dict:
    headers = comp_headers or TEST_USERS["comp_approver_headers"]
    res = api_client.approve_offer(offer_id, approve_offer_payload(expected_version), headers)
    return get_success_data(res)


def vp_approve_offer(offer_id: str, expected_version: int, vp_headers=None) -> dict:
    headers = vp_headers or TEST_USERS["vp_headers"]
    res = api_client.approve_offer(offer_id, approve_offer_payload(expected_version), headers)
    return get_success_data(res)


def fully_approve_offer(offer_id: str, comp_headers=None, vp_headers=None) -> dict:
    """Run both legs of the two-step approval (PRD §3.6). Returns APPROVED offer."""
    # Fetch current version to be safe
    get_res = api_client.get_offer(offer_id, TEST_USERS["recruiter_headers"])
    offer = get_success_data(get_res)
    offer = comp_approve_offer(offer_id, offer["version"], comp_headers=comp_headers)
    offer = vp_approve_offer(offer_id, offer["version"], vp_headers=vp_headers)
    return offer


def extend_offer(offer_id: str, recruiter_headers=None) -> dict:
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    res = api_client.extend_offer(offer_id, headers)
    return get_success_data(res)


def accept_offer(offer_id: str, candidate_headers=None) -> dict:
    headers = candidate_headers or TEST_USERS["candidate_headers"]
    res = api_client.accept_offer(offer_id, headers)
    return get_success_data(res)


def setup_offer_in_state(state: str,
                         budget_cents: int = 200_000_000,
                         base_salary_cents: int = 12_000_000,
                         req_overrides: dict = None,
                         candidate_referrer_user_id: str = None,
                         cand_overrides: dict = None) -> dict:
    """Walk through the full chain to leave an Offer in the requested state.

    Supported states: PENDING_APPROVAL, APPROVED, EXTENDED, ACCEPTED.

    Returns dict with keys: dept, req, candidate, app, offer.
    Caller must set the clock before calling if EXTENDED/ACCEPTED — expires_at depends on it.
    """
    dept, req, cand, app = setup_approved_req_with_screened_app(
        budget_cents=budget_cents,
        req_overrides=req_overrides,
        candidate_referrer_user_id=candidate_referrer_user_id,
        cand_overrides=cand_overrides,
    )
    offer = create_offer(app["id"], base_salary_cents=base_salary_cents)
    if state == "PENDING_APPROVAL":
        return {"dept": dept, "req": req, "candidate": cand, "app": app, "offer": offer}

    if state in {"APPROVED", "EXTENDED", "ACCEPTED"}:
        offer = fully_approve_offer(offer["id"])
    if state == "APPROVED":
        return {"dept": dept, "req": req, "candidate": cand, "app": app, "offer": offer}

    if state in {"EXTENDED", "ACCEPTED"}:
        offer = extend_offer(offer["id"])
    if state == "EXTENDED":
        return {"dept": dept, "req": req, "candidate": cand, "app": app, "offer": offer}

    if state == "ACCEPTED":
        offer = accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))
        return {"dept": dept, "req": req, "candidate": cand, "app": app, "offer": offer}

    raise ValueError(f"Unsupported offer state: {state!r}")


# ---------- Tier 3b: BackgroundCheck flow ----------

def fetch_background_check_for_offer(offer_id: str,
                                     reader_headers=None) -> dict:
    """The BackgroundCheck is created as a cascade of /offers/{id}/accept (PRD §3.6).
    There is no direct create endpoint, so we list by offer_id."""
    headers = reader_headers or TEST_USERS["compliance_officer_headers"]
    res = api_client.list_background_checks(headers, params={"offer_id": offer_id})
    bgcs, _ = _validate_paginated_local(res)
    assert len(bgcs) >= 1, f"Expected at least one BackgroundCheck for offer_id={offer_id}"
    return bgcs[0]


def fetch_referral_bonuses_for_offer(offer_id: str,
                                     reader_headers=None) -> list:
    headers = reader_headers or TEST_USERS["payroll_officer_headers"]
    res = api_client.list_referral_bonuses(headers, params={"offer_id": offer_id})
    bonuses, _ = _validate_paginated_local(res)
    return bonuses


def start_background_check(bgc_id: str, compliance_headers=None) -> dict:
    headers = compliance_headers or TEST_USERS["compliance_officer_headers"]
    res = api_client.start_background_check(bgc_id, headers)
    return get_success_data(res)


def resolve_background_check(bgc_id: str, outcome: str = "PASSED",
                             compliance_headers=None) -> dict:
    headers = compliance_headers or TEST_USERS["compliance_officer_headers"]
    res = api_client.resolve_background_check(
        bgc_id, resolve_background_check_payload(outcome), headers
    )
    return get_success_data(res)


# ---------- Tier 4: Interview + Feedback flow ----------

def schedule_interview(application_id: str, panel_user_ids,
                       round_number: int = 1,
                       scheduled_at: str = "2027-01-01T10:00:00Z",
                       duration_minutes: int = 60,
                       recruiter_headers=None) -> dict:
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    payload = create_interview_payload(
        application_id, panel_user_ids, round_number=round_number,
        scheduled_at=scheduled_at, duration_minutes=duration_minutes,
    )
    res = api_client.create_interview(payload, headers)
    return get_success_data(res)


def submit_interview_feedback(interview_id: str, panelist_user_id: str,
                              score: int = 4, comments: str = "ok",
                              submitter_headers=None) -> dict:
    headers = submitter_headers or TEST_USERS["hiring_manager_headers"]
    payload = create_interview_feedback_payload(interview_id, panelist_user_id,
                                                score=score, comments=comments)
    res = api_client.create_interview_feedback(payload, headers)
    return get_success_data(res)


def complete_interview(intv_id: str, recruiter_headers=None) -> dict:
    headers = recruiter_headers or TEST_USERS["recruiter_headers"]
    res = api_client.complete_interview(intv_id, headers)
    return get_success_data(res)


def setup_interview_with_feedback(panel_user_ids,
                                  scores: list,
                                  scheduled_at: str = "2027-01-01T10:00:00Z",
                                  duration_minutes: int = 60,
                                  budget_cents: int = 200_000_000) -> dict:
    """Build full chain: dept + req + cand + app + screened + interview + all feedback submitted.
    `scores` MUST have the same length as panel_user_ids (one feedback per panelist).
    Returns dict with dept, req, candidate, app, interview."""
    assert len(scores) == len(panel_user_ids), \
        "scores must align 1:1 with panel_user_ids"
    dept, req, cand, app = setup_approved_req_with_screened_app(budget_cents=budget_cents)
    interview = schedule_interview(
        app["id"], panel_user_ids,
        scheduled_at=scheduled_at, duration_minutes=duration_minutes,
    )
    for panelist_id, score in zip(panel_user_ids, scores):
        submit_interview_feedback(interview["id"], panelist_id, score=score)
    return {"dept": dept, "req": req, "candidate": cand, "app": app, "interview": interview}


# ---------- Tier 5: DiversityGoal ----------

def create_diversity_goal(department_id: str, target_level: str = "MID",
                          period_year: int = 2027,
                          target_underrepresented_pct: float = 0.50) -> dict:
    payload = create_diversity_goal_payload(
        department_id, target_level=target_level, period_year=period_year,
        target_underrepresented_pct=target_underrepresented_pct,
    )
    res = api_client.create_diversity_goal(payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)


def read_diversity_goal(goal_id: str, hm_headers=None) -> dict:
    headers = hm_headers or TEST_USERS["hiring_manager_headers"]
    res = api_client.get_diversity_goal(goal_id, headers)
    return get_success_data(res)


# ---------- Tier 6: Requisition cancel + OCC ----------

def cancel_requisition_with_version(req_id: str, expected_version: int,
                                    hm_headers=None) -> dict:
    headers = hm_headers or TEST_USERS["hiring_manager_headers"]
    res = api_client.cancel_requisition(
        req_id, cancel_requisition_payload(expected_version), headers
    )
    return get_success_data(res)


def current_requisition_version(req_id: str) -> int:
    res = api_client.get_requisition(req_id, TEST_USERS["recruiter_headers"])
    return get_success_data(res)["version"]


def current_offer_version(offer_id: str) -> int:
    res = api_client.get_offer(offer_id, TEST_USERS["recruiter_headers"])
    return get_success_data(res)["version"]


def current_department_committed(dept_id: str) -> int:
    res = api_client.get_department(dept_id, TEST_USERS["platform_admin_headers"])
    return get_success_data(res)["committed_offer_cents"]


# ---------- Tier 7: pagination helper for fixtures ----------

def _validate_paginated_local(res) -> tuple:
    """Lenient paginated read for fixtures — returns (data, meta) regardless of strict checks."""
    body = res.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    assert res.status_code == 200, f"Setup expected 200, got {res.status_code}: {body}"
    return data, meta
