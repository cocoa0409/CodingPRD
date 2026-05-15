"""Composite setup helpers — multi-step preambles tests can reuse.

PRD §2.1 identity threading:

- HrUser, HiringManager, HrApprover, FinanceApprover are all
  entity_backed:HrUser. After the PlatformAdmin binds an HrUser to a
  Company via POST /recruitment/companies/{id}/hr-bindings, the
  returned HrUser row's `id` is what subsequent HR-side calls must
  send as X-User-ID — so every fixture below threads the bound
  HrUser.id through and builds headers with make_hr_user_headers(id),
  make_hiring_manager_headers(id), make_hr_approver_headers(id),
  make_finance_approver_headers(id). Falling back to a shared HR
  constant would make HR-binding referential integrity (PRD §2.7 #6)
  reject every request before any state machine could be exercised.

- Candidate is entity_backed:Candidate. The registration POST creates
  the row; subsequent ownership-gated calls (accept offer, confirm
  interview slot) use make_candidate_headers(candidate['id']).

- HeadhunterUser is entity_backed:HeadhunterContract. Commission-record
  reads use make_headhunter_headers(contract['id']).

PRD §3.9 clock/sweep semantics: the test driver advances the server
clock via POST /recruitment/_clock/advance, runs the commission sweep
via POST /recruitment/_settlement-sweep/run. These admin-only calls
use platform_admin_headers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    accept_offer_payload,
    blacklist_company_payload,
    candidate_confirm_payload,
    clock_advance_payload,
    create_application_payload,
    create_candidate_payload,
    create_company_payload,
    create_headhunter_contract_payload,
    create_hr_binding_payload,
    create_interview_round_payload,
    create_job_posting_payload,
    create_offer_payload,
    create_onboarding_payload,
    iso_utc,
    publish_slots_payload,
    record_check_payload,
    rescind_offer_payload,
    submit_round_feedback_payload,
    unique_token,
)
from .test_users import (
    PLATFORM_ADMIN_ID,
    TEST_USERS,
    make_candidate_headers,
    make_finance_approver_headers,
    make_hiring_manager_headers,
    make_hr_approver_headers,
    make_hr_user_headers,
    make_platform_admin_headers,
)


# A fixed "epoch" the tests advance from, in PRD §3.9 logical-clock form.
TEST_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _admin() -> Dict[str, str]:
    return TEST_USERS["platform_admin_headers"]


def _data(resp) -> Dict[str, Any]:
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock (PRD §3.9)
# ---------------------------------------------------------------------------
def reset_clock_to_epoch() -> str:
    iso = iso_utc(TEST_EPOCH)
    _data(api_client.clock_advance(clock_advance_payload(iso), _admin()))
    return iso


def advance_clock_to(target: datetime) -> str:
    iso = iso_utc(target)
    _data(api_client.clock_advance(clock_advance_payload(iso), _admin()))
    return iso


def advance_clock_by(seconds: float) -> str:
    """Advance the logical clock from TEST_EPOCH by the given seconds."""
    target = TEST_EPOCH + timedelta(seconds=seconds)
    return advance_clock_to(target)


def run_settlement_sweep() -> Optional[Dict[str, Any]]:
    return _data(api_client.run_settlement_sweep(_admin()))


# ---------------------------------------------------------------------------
# Tier 1 — Company + verification + HR binding (PRD §3.1)
# ---------------------------------------------------------------------------
def create_company(
    verification_tier: str = "BASIC",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a DRAFT Company. Uses the shared HR fallback header — the
    company creation endpoint is HrUser-only but does not exercise
    HR-binding integrity (no Company exists yet to bind to)."""
    payload = create_company_payload(
        verification_tier=verification_tier, **overrides,
    )
    return _data(api_client.create_company(
        payload, TEST_USERS["hr_user_fallback_headers"],
    ))


def submit_company_verification(company_id: str) -> Dict[str, Any]:
    return _data(api_client.submit_verification(
        company_id, TEST_USERS["hr_user_fallback_headers"],
    ))


def approve_company_verification(company_id: str) -> Dict[str, Any]:
    return _data(api_client.approve_verification(company_id, _admin()))


def reject_company_verification(company_id: str) -> Dict[str, Any]:
    return _data(api_client.reject_verification(company_id, _admin()))


def bind_hr_user(company_id: str, **overrides: Any) -> Dict[str, Any]:
    """PlatformAdmin binds an HrUser to a Company. Returns the bound
    HrUser dict whose `id` is the X-User-ID for subsequent HR-side
    actions against this Company (PRD §2.1)."""
    payload = create_hr_binding_payload(**overrides)
    return _data(api_client.create_hr_binding(company_id, payload, _admin()))


def create_verified_company(
    verification_tier: str = "BASIC",
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """End-to-end: DRAFT → PENDING → VERIFIED + one bound HrUser.

    Returns (company, hr_user). The hr_user.id is the X-User-ID to use
    for any HR-side call against this company."""
    company = create_company(verification_tier=verification_tier, **overrides)
    submit_company_verification(company["id"])
    company = approve_company_verification(company["id"])
    hr_user = bind_hr_user(company["id"])
    return company, hr_user


def setup_company_with_multiple_hr_users(
    n: int = 3,
    verification_tier: str = "BASIC",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a VERIFIED Company with N distinct ACTIVE HrUser rows.
    Used by offer-approval segregation-of-duties tests (PRD §3.6:
    three distinct approvers required)."""
    company, first_hr = create_verified_company(
        verification_tier=verification_tier,
    )
    hr_users = [first_hr]
    for i in range(1, n):
        hr_users.append(bind_hr_user(company["id"]))
    return company, hr_users


def blacklist_company(
    company_id: str,
    blacklist_reason: str = "fraudulent license",
) -> Dict[str, Any]:
    return _data(api_client.blacklist_company(
        company_id, blacklist_company_payload(blacklist_reason),
        _admin(),
    ))


# ---------------------------------------------------------------------------
# Tier 1 — Candidate (PRD §3.3)
# ---------------------------------------------------------------------------
def create_candidate(
    visibility_mode: str = "PUBLIC",
    visible_to_company_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a candidate. Returns the Candidate dict whose `id` is
    the X-User-ID for subsequent ownership-gated calls (accept offer,
    candidate-confirm slot)."""
    payload = create_candidate_payload(
        visibility_mode=visibility_mode,
        visible_to_company_ids=visible_to_company_ids,
        **overrides,
    )
    # The registration POST creates the row; the X-User-ID here is
    # pre-creation so a fallback constant is fine for this single call.
    return _data(api_client.create_candidate(
        payload, TEST_USERS["candidate_fallback_headers"],
    ))


# ---------------------------------------------------------------------------
# Tier 1 — Headhunter contract (PRD §3.8)
# ---------------------------------------------------------------------------
def create_headhunter_contract(
    company_id: str,
    fee_model: str = "SUCCESS_FEE",
    success_fee_pct_bps: Optional[int] = 2000,
    retainer_amount_cents: Optional[int] = None,
    trigger_event: str = "OFFER_ACCEPTED",
    clawback_window_days: Optional[int] = None,
    tax_withholding_pct_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_headhunter_contract_payload(
        company_id=company_id,
        fee_model=fee_model,
        success_fee_pct_bps=success_fee_pct_bps,
        retainer_amount_cents=retainer_amount_cents,
        trigger_event=trigger_event,
        clawback_window_days=clawback_window_days,
        tax_withholding_pct_bps=tax_withholding_pct_bps,
        **overrides,
    )
    return _data(api_client.create_headhunter_contract(payload, _admin()))


# ---------------------------------------------------------------------------
# Tier 2 — Job posting lifecycle (PRD §3.2)
# ---------------------------------------------------------------------------
def create_job_posting(
    company_id: str,
    hr_user_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a JobPosting in DRAFT. hr_user_id is the X-User-ID of an
    HrUser whose binding to company_id is ACTIVE (PRD §2.7 #6)."""
    payload = create_job_posting_payload(company_id=company_id, **overrides)
    return _data(api_client.create_job_posting(
        payload, make_hr_user_headers(hr_user_id),
    ))


def submit_posting_review(posting_id: str, hr_user_id: str) -> Dict[str, Any]:
    return _data(api_client.submit_review_posting(
        posting_id, make_hr_user_headers(hr_user_id),
    ))


def approve_posting(posting_id: str) -> Dict[str, Any]:
    return _data(api_client.approve_posting(posting_id, _admin()))


def take_posting_off_shelf(posting_id: str, hr_user_id: str) -> Dict[str, Any]:
    return _data(api_client.take_off_shelf(
        posting_id, make_hr_user_headers(hr_user_id),
    ))


def create_live_posting(
    company_id: str,
    hr_user_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Full lifecycle DRAFT → UNDER_REVIEW → LIVE.

    Caller supplies a verified company_id and a bound hr_user_id. The
    posting's title/description default to unique tokens so multiple
    LIVE postings on the same Company don't trigger ERR_DUPLICATE_POSTING."""
    kwargs: Dict[str, Any] = dict(overrides)
    if title is not None:
        kwargs["title"] = title
    else:
        kwargs.setdefault("title", f"Engineer {unique_token('job')}")
    if description is not None:
        kwargs["description"] = description
    else:
        kwargs.setdefault(
            "description",
            f"Looking for senior backend engineer {unique_token('desc')}.",
        )
    posting = create_job_posting(company_id, hr_user_id, **kwargs)
    submit_posting_review(posting["id"], hr_user_id)
    return approve_posting(posting["id"])


# ---------------------------------------------------------------------------
# Tier 2 — Application creation (PRD §3.4)
# ---------------------------------------------------------------------------
def submit_application(
    candidate_id: str,
    job_posting_id: str,
    source_channel: str = "DIRECT",
    headhunter_contract_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_application_payload(
        candidate_id=candidate_id,
        job_posting_id=job_posting_id,
        source_channel=source_channel,
        headhunter_contract_id=headhunter_contract_id,
        **overrides,
    )
    return _data(api_client.create_application(
        payload, make_candidate_headers(candidate_id),
    ))


# ---------------------------------------------------------------------------
# Tier 3 — Application lifecycle steps (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------
def mark_application_read(
    application_id: str, hr_user_id: str,
) -> Dict[str, Any]:
    return _data(api_client.mark_application_read(
        application_id, make_hr_user_headers(hr_user_id),
    ))


def forward_application(
    application_id: str, hr_user_id: str,
) -> Dict[str, Any]:
    return _data(api_client.forward_application(
        application_id, make_hr_user_headers(hr_user_id),
    ))


def create_interview_round(
    application_id: str,
    hr_user_id: str,
    interviewer_user_ids: Optional[List[str]] = None,
    mode: str = "VIDEO",
) -> Dict[str, Any]:
    """Create the first InterviewRound. hr_user_id is the HR-side actor;
    interviewer_user_ids defaults to [hr_user_id] (a single-interviewer panel).
    """
    payload = create_interview_round_payload(
        mode=mode,
        interviewer_user_ids=(
            list(interviewer_user_ids)
            if interviewer_user_ids is not None
            else [hr_user_id]
        ),
    )
    return _data(api_client.create_interview_round(
        application_id, payload, make_hr_user_headers(hr_user_id),
    ))


def publish_round_slots(
    round_id: str,
    hr_user_id: str,
    slots: List[datetime],
) -> Dict[str, Any]:
    payload = publish_slots_payload(
        candidate_time_slot_options=[iso_utc(s) for s in slots],
    )
    return _data(api_client.publish_slots(
        round_id, payload, make_hr_user_headers(hr_user_id),
    ))


def candidate_confirm_slot(
    round_id: str,
    candidate_id: str,
    selected_slot: datetime,
) -> Dict[str, Any]:
    payload = candidate_confirm_payload(selected_slot=iso_utc(selected_slot))
    return _data(api_client.candidate_confirm_slot(
        round_id, payload, make_candidate_headers(candidate_id),
    ))


def submit_round_feedback(
    round_id: str,
    hr_user_id: str,
    feedback_decision: str = "PASS",
) -> Dict[str, Any]:
    payload = submit_round_feedback_payload(feedback_decision=feedback_decision)
    return _data(api_client.submit_round_feedback(
        round_id, payload, make_hr_user_headers(hr_user_id),
    ))


# ---------------------------------------------------------------------------
# Tier 3 — End-to-end Application → INTERVIEW + first round PASSED
# ---------------------------------------------------------------------------
def setup_application_at_interview_passed(
    *,
    verification_tier: str = "BASIC",
    source_channel: str = "DIRECT",
    headhunter_contract: Optional[Dict[str, Any]] = None,
    visibility_mode: str = "PUBLIC",
    candidate_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Full preamble through to one InterviewRound in PASSED:

      1. Reset clock.
      2. Create VERIFIED Company + bound HrUser.
      3. Create LIVE JobPosting.
      4. Register a Candidate (or use the supplied one).
      5. Submit Application; mark read; forward.
      6. Create InterviewRound; publish slots; candidate-confirm.
      7. Advance clock past scheduled_end_at; submit PASS feedback.

    Returns a dict with the constructed entities for downstream Offer tests:
      {company, hr_user, hr_users (just one), posting, candidate, application,
       round}
    """
    reset_clock_to_epoch()
    company, hr_user = create_verified_company(
        verification_tier=verification_tier,
    )
    if source_channel == "HEADHUNTER" and headhunter_contract is None:
        headhunter_contract = create_headhunter_contract(
            company_id=company["id"],
            fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2000,
            trigger_event="OFFER_ACCEPTED",
        )
    visible_to = ([company["id"]]
                  if visibility_mode == "COMPANY_ONLY" else None)
    if candidate_id is None:
        candidate = create_candidate(
            visibility_mode=visibility_mode,
            visible_to_company_ids=visible_to,
        )
    else:
        candidate = {"id": candidate_id}
    posting = create_live_posting(company["id"], hr_user["id"])
    application = submit_application(
        candidate_id=candidate["id"],
        job_posting_id=posting["id"],
        source_channel=source_channel,
        headhunter_contract_id=(
            headhunter_contract["id"] if headhunter_contract else None
        ),
    )
    mark_application_read(application["id"], hr_user["id"])
    forward_application(application["id"], hr_user["id"])
    round_row = create_interview_round(
        application["id"], hr_user["id"],
    )
    # Slot one hour after TEST_EPOCH (strictly future at time of publish).
    slot_start = TEST_EPOCH + timedelta(hours=1)
    publish_round_slots(round_row["id"], hr_user["id"], [slot_start])
    round_row = candidate_confirm_slot(
        round_row["id"], candidate["id"], slot_start,
    )
    # Advance clock to scheduled_end_at (= slot_start + 60 min) so the
    # round auto-transitions SCHEDULED → FEEDBACK_PENDING.
    advance_clock_to(slot_start + timedelta(minutes=60))
    round_row = submit_round_feedback(
        round_row["id"], hr_user["id"], "PASS",
    )
    return {
        "company": company,
        "hr_user": hr_user,
        "posting": posting,
        "candidate": candidate,
        "application": application,
        "round": round_row,
        "headhunter_contract": headhunter_contract,
    }


# ---------------------------------------------------------------------------
# Tier 3 — Offer lifecycle (PRD §3.6)
# ---------------------------------------------------------------------------
def create_offer(
    application_id: str,
    hr_user_id: str,
    base_salary_cents: int = 5_000_000,
    sign_on_bonus_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_offer_payload(
        application_id=application_id,
        base_salary_cents=base_salary_cents,
        sign_on_bonus_cents=sign_on_bonus_cents,
        **overrides,
    )
    return _data(api_client.create_offer(
        payload, make_hr_user_headers(hr_user_id),
    ))


def submit_offer_for_approval(
    offer_id: str, hr_user_id: str,
) -> Dict[str, Any]:
    return _data(api_client.submit_offer_approval(
        offer_id, make_hr_user_headers(hr_user_id),
    ))


def hm_approve_offer(offer_id: str, hr_user_id: str) -> Dict[str, Any]:
    return _data(api_client.approve_offer(
        offer_id, make_hiring_manager_headers(hr_user_id),
    ))


def hr_approve_offer(offer_id: str, hr_user_id: str) -> Dict[str, Any]:
    return _data(api_client.approve_offer(
        offer_id, make_hr_approver_headers(hr_user_id),
    ))


def finance_approve_offer(offer_id: str, hr_user_id: str) -> Dict[str, Any]:
    return _data(api_client.approve_offer(
        offer_id, make_finance_approver_headers(hr_user_id),
    ))


def setup_issued_offer(
    *,
    base_salary_cents: int = 5_000_000,
    sign_on_bonus_cents: int = 0,
    source_channel: str = "DIRECT",
    headhunter_contract: Optional[Dict[str, Any]] = None,
    verification_tier: str = "BASIC",
    visibility_mode: str = "PUBLIC",
) -> Dict[str, Any]:
    """End-to-end through to Offer.ISSUED, using three distinct HrUsers
    for HM/HR/Finance (PRD §3.6 segregation of duties).

    Returns the bag {company, hr_user (primary HR-side actor used as HM),
    hr_users [hm, hr, fin], posting, candidate, application, round, offer,
    headhunter_contract}.
    """
    bag = setup_application_at_interview_passed(
        verification_tier=verification_tier,
        source_channel=source_channel,
        headhunter_contract=headhunter_contract,
        visibility_mode=visibility_mode,
    )
    company = bag["company"]
    # The first hr_user was created by setup_application_at_interview_passed.
    # Bind two more so we have three distinct approvers.
    hm_hr = bag["hr_user"]
    hr_approver = bind_hr_user(company["id"])
    finance_approver = bind_hr_user(company["id"])
    # Submit-approval is HrUser-only; use the primary HR-side actor.
    offer = create_offer(
        bag["application"]["id"], hm_hr["id"],
        base_salary_cents=base_salary_cents,
        sign_on_bonus_cents=sign_on_bonus_cents,
    )
    submit_offer_for_approval(offer["id"], hm_hr["id"])
    hm_approve_offer(offer["id"], hm_hr["id"])
    hr_approve_offer(offer["id"], hr_approver["id"])
    offer = finance_approve_offer(offer["id"], finance_approver["id"])
    bag["hr_users"] = [hm_hr, hr_approver, finance_approver]
    bag["offer"] = offer
    return bag


def setup_accepted_offer(
    *,
    base_salary_cents: int = 5_000_000,
    sign_on_bonus_cents: int = 0,
    source_channel: str = "DIRECT",
    headhunter_contract: Optional[Dict[str, Any]] = None,
    verification_tier: str = "BASIC",
) -> Dict[str, Any]:
    """Full lifecycle through Offer.ACCEPTED. If source_channel ==
    HEADHUNTER and the (created) contract's trigger_event is
    OFFER_ACCEPTED, a CommissionRecord is accrued at accept time
    (PRD §3.6, §3.8)."""
    bag = setup_issued_offer(
        base_salary_cents=base_salary_cents,
        sign_on_bonus_cents=sign_on_bonus_cents,
        source_channel=source_channel,
        headhunter_contract=headhunter_contract,
        verification_tier=verification_tier,
    )
    offer_id = bag["offer"]["id"]
    candidate_id = bag["candidate"]["id"]
    bag["offer"] = _data(api_client.accept_offer(
        offer_id, make_candidate_headers(candidate_id),
        accept_offer_payload(),
    ))
    return bag


# ---------------------------------------------------------------------------
# Tier 4 — Onboarding lifecycle (PRD §3.7)
# ---------------------------------------------------------------------------
def create_onboarding(
    offer_id: str,
    hr_user_id: str,
    start_date: Optional[str] = None,
) -> Dict[str, Any]:
    sd = start_date or iso_utc(TEST_EPOCH + timedelta(days=14))
    return _data(api_client.create_onboarding(
        create_onboarding_payload(offer_id=offer_id, start_date=sd),
        make_hr_user_headers(hr_user_id),
    ))


def start_onboarding_checks(
    onboarding_id: str, hr_user_id: str,
) -> Dict[str, Any]:
    return _data(api_client.start_checks(
        onboarding_id, make_hr_user_headers(hr_user_id),
    ))


def record_onboarding_check(
    onboarding_id: str,
    hr_user_id: str,
    check_kind: str = "BACKGROUND",
    outcome: str = "PASSED",
) -> Dict[str, Any]:
    return _data(api_client.record_check(
        onboarding_id,
        record_check_payload(check_kind=check_kind, outcome=outcome),
        make_hr_user_headers(hr_user_id),
    ))


def confirm_onboarded(
    onboarding_id: str, hr_user_id: str,
) -> Dict[str, Any]:
    return _data(api_client.confirm_onboarded(
        onboarding_id, make_hr_user_headers(hr_user_id),
    ))


def setup_onboarded(
    *,
    source_channel: str = "DIRECT",
    headhunter_contract: Optional[Dict[str, Any]] = None,
    start_offset_days: int = 14,
) -> Dict[str, Any]:
    """Full lifecycle through Onboarding.ONBOARDED.

    Marches: accepted offer → onboarding SCHEDULED → CHECKS_RUNNING →
    record BACKGROUND PASSED + MEDICAL PASSED → READY → advance clock
    past start_date → ONBOARDED.
    """
    bag = setup_accepted_offer(
        source_channel=source_channel,
        headhunter_contract=headhunter_contract,
    )
    hr_user_id = bag["hr_user"]["id"]
    start_dt = TEST_EPOCH + timedelta(days=start_offset_days)
    onboarding = create_onboarding(
        bag["offer"]["id"], hr_user_id, start_date=iso_utc(start_dt),
    )
    start_onboarding_checks(onboarding["id"], hr_user_id)
    record_onboarding_check(
        onboarding["id"], hr_user_id, "BACKGROUND", "PASSED",
    )
    record_onboarding_check(
        onboarding["id"], hr_user_id, "MEDICAL", "PASSED",
    )
    advance_clock_to(start_dt)
    onboarding = confirm_onboarded(onboarding["id"], hr_user_id)
    bag["onboarding"] = onboarding
    bag["start_date"] = iso_utc(start_dt)
    return bag


# ---------------------------------------------------------------------------
# Audit log helpers (PRD §3.9)
# ---------------------------------------------------------------------------
def list_audit_events_for(
    subject_entity: str,
    subject_id: str,
    event_kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "limit": 100,
    }
    if event_kind is not None:
        params["event_kind"] = event_kind
    resp = api_client.list_audit_events(_admin(), params=params)
    data = _data(resp)
    if isinstance(data, list):
        return data
    return []


__all__ = [
    "TEST_EPOCH",
    "reset_clock_to_epoch",
    "advance_clock_to",
    "advance_clock_by",
    "run_settlement_sweep",
    "create_company",
    "submit_company_verification",
    "approve_company_verification",
    "reject_company_verification",
    "bind_hr_user",
    "create_verified_company",
    "setup_company_with_multiple_hr_users",
    "blacklist_company",
    "create_candidate",
    "create_headhunter_contract",
    "create_job_posting",
    "submit_posting_review",
    "approve_posting",
    "take_posting_off_shelf",
    "create_live_posting",
    "submit_application",
    "mark_application_read",
    "forward_application",
    "create_interview_round",
    "publish_round_slots",
    "candidate_confirm_slot",
    "submit_round_feedback",
    "setup_application_at_interview_passed",
    "create_offer",
    "submit_offer_for_approval",
    "hm_approve_offer",
    "hr_approve_offer",
    "finance_approve_offer",
    "setup_issued_offer",
    "setup_accepted_offer",
    "create_onboarding",
    "start_onboarding_checks",
    "record_onboarding_check",
    "confirm_onboarded",
    "setup_onboarded",
    "list_audit_events_for",
]
