"""Composite setup helpers for the Problem Loan Workout API.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty database before
every test). Fixtures use get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: segregation-of-duties rules compare X-User-ID strings
against the case's case_officer_id, so every fixture names its officer,
manager, committee, desk, counsel, and accounting users explicitly.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_borrower_payload, create_loan_payload, create_workout_case_payload,
    create_action_plan_payload, create_proposal_payload, create_collateral_payload,
    create_appraisal_payload, create_impairment_cecl_payload, create_impairment_tdr_dcf_payload,
    create_legal_referral_payload, create_charge_off_payload, create_recovery_payload,
    create_exit_decision_payload,
)
from .test_users import (
    make_workout_officer_headers, make_special_assets_manager_headers,
    make_credit_committee_headers, make_appraisal_desk_headers,
    make_legal_counsel_headers, make_loan_accounting_headers,
    make_portfolio_analyst_headers, make_system_admin_headers,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


# ─── Tier 1: base entities ────────────────────────────

def make_borrower(officer_headers=None, **overrides):
    """Create a borrower. Returns the Borrower dict."""
    h = officer_headers or make_workout_officer_headers("officer-setup")
    return get_success_data(api_client.create_borrower(create_borrower_payload(**overrides), h))


def make_loan(borrower_id, officer_headers=None, **overrides):
    """Book a loan against a borrower. Returns the Loan dict (PERFORMING)."""
    h = officer_headers or make_workout_officer_headers("officer-setup")
    return get_success_data(api_client.create_loan(create_loan_payload(borrower_id, **overrides), h))


def make_borrower_with_loan(officer_id="officer-setup", borrower_overrides=None, loan_overrides=None):
    """Borrower + one PERFORMING loan. Returns (borrower, loan)."""
    h = make_workout_officer_headers(officer_id)
    borrower = make_borrower(h, **(borrower_overrides or {}))
    loan = make_loan(borrower["id"], h, **(loan_overrides or {}))
    return borrower, loan


def open_workout_case(loan_id, officer_id="officer-1", manager_id="mgr-1", **overrides):
    """Open a workout case on a PERFORMING loan. Returns (case, officer_headers, manager_headers)."""
    officer_h = make_workout_officer_headers(officer_id)
    payload = create_workout_case_payload(case_officer_id=officer_id, **overrides)
    case = get_success_data(api_client.create_workout_case(loan_id, payload, officer_h))
    return case, officer_h, make_special_assets_manager_headers(manager_id)


# ─── Tier 2: state progression up the case machine ────

def setup_case_in_action_plan(officer_id="officer-1", manager_id="mgr-1",
                              borrower_overrides=None, loan_overrides=None,
                              case_overrides=None, plan_overrides=None):
    """Borrower + loan + workout case with a first DRAFT action plan (case in ACTION_PLAN).

    Returns dict with keys: borrower, loan, case, plan, officer_h, manager_h.
    """
    borrower, loan = make_borrower_with_loan(officer_id, borrower_overrides, loan_overrides)
    case, officer_h, manager_h = open_workout_case(
        loan["id"], officer_id=officer_id, manager_id=manager_id, **(case_overrides or {}))
    plan = get_success_data(api_client.create_action_plan(
        loan["id"], case["id"],
        create_action_plan_payload(case["version"], **(plan_overrides or {})),
        officer_h))
    return {
        "borrower": borrower, "loan": loan, "case": case, "plan": plan,
        "officer_h": officer_h, "manager_h": manager_h,
    }


def setup_case_in_negotiation(officer_id="officer-1", manager_id="mgr-1",
                              borrower_overrides=None, loan_overrides=None,
                              case_overrides=None, plan_overrides=None):
    """Case driven to NEGOTIATION via an APPROVED first action plan.

    Returns dict with keys: borrower, loan, case (refreshed), plan, officer_h, manager_h.
    """
    ctx = setup_case_in_action_plan(officer_id, manager_id, borrower_overrides,
                                    loan_overrides, case_overrides, plan_overrides)
    loan, case, plan = ctx["loan"], ctx["case"], ctx["plan"]
    get_success_data(api_client.submit_action_plan(loan["id"], case["id"], plan["id"], ctx["officer_h"]))
    get_success_data(api_client.approve_action_plan(loan["id"], case["id"], plan["id"], ctx["manager_h"]))
    ctx["case"] = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    ctx["loan"] = get_success_data(api_client.get_loan(loan["id"], ctx["officer_h"]))
    return ctx


# ─── Tier 3: proposals and consummation ───────────────

def make_proposal_under_review(ctx, committee_id=None, proposal_overrides=None):
    """Draft + submit a proposal on a NEGOTIATION case. Returns proposal in UNDER_BORROWER_REVIEW."""
    loan, case = ctx["loan"], ctx["case"]
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    proposal = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], **(proposal_overrides or {})),
        ctx["officer_h"]))
    proposal = get_success_data(api_client.submit_proposal(
        loan["id"], case["id"], proposal["id"], ctx["officer_h"]))
    return proposal


def make_proposal_approved(ctx, committee_id="cc-1", proposal_overrides=None):
    """Draft a proposal and walk it to APPROVED (submit → escalate → committee-approve)."""
    proposal = make_proposal_under_review(ctx, committee_id, proposal_overrides)
    loan, case = ctx["loan"], ctx["case"]
    get_success_data(api_client.escalate_proposal(loan["id"], case["id"], proposal["id"], ctx["officer_h"]))
    committee_h = make_credit_committee_headers(committee_id)
    proposal = get_success_data(api_client.committee_approve_proposal(
        loan["id"], case["id"], proposal["id"], committee_h))
    ctx["case"] = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    return proposal


def setup_case_in_impairment_review(officer_id="officer-1", manager_id="mgr-1",
                                    committee_id="cc-1", concession=True,
                                    borrower_overrides=None, loan_overrides=None,
                                    case_overrides=None, plan_overrides=None,
                                    proposal_overrides=None):
    """Case driven to IMPAIRMENT_REVIEW via a consummated proposal.

    concession=True (default) drafts a proposal with concession_rate_bps strictly
    below the loan's contractual rate so tdr_flag computes true
    (tdr_status == TDR_CONFIRMED); concession=False uses a non-concession rate
    (equal to contract) so tdr_status == TDR_REJECTED.

    Returns dict with keys: borrower, loan, case (refreshed), plan, proposal,
    officer_h, manager_h.
    """
    loan_ov = dict(loan_overrides or {})
    rate = loan_ov.get("contractual_rate_bps", 1000)
    ctx = setup_case_in_negotiation(officer_id, manager_id, borrower_overrides,
                                    loan_ov, case_overrides, plan_overrides)
    prop_ov = dict(proposal_overrides or {})
    if "concession_rate_bps" not in prop_ov:
        prop_ov["concession_rate_bps"] = rate - 100 if concession else rate
    proposal = make_proposal_approved(ctx, committee_id, prop_ov)
    loan, case = ctx["loan"], ctx["case"]
    proposal = get_success_data(api_client.consummate_proposal(
        loan["id"], case["id"], proposal["id"], ctx["officer_h"]))
    ctx["proposal"] = proposal
    ctx["case"] = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    ctx["loan"] = get_success_data(api_client.get_loan(loan["id"], ctx["officer_h"]))
    return ctx


# ─── Tier 4: legal track ──────────────────────────────

def setup_case_in_legal(officer_id="officer-1", manager_id="mgr-1", counsel_id="counsel-1",
                        referral_overrides=None, accept=True, **kwargs):
    """Case driven to LEGAL via a legal referral; optionally accepted to ACTIVE.

    Returns ctx dict additionally keyed: referral, counsel_h.
    """
    ctx = setup_case_in_negotiation(officer_id, manager_id, **kwargs)
    loan, case = ctx["loan"], ctx["case"]
    referral = get_success_data(api_client.create_legal_referral(
        loan["id"], case["id"],
        create_legal_referral_payload(**(referral_overrides or {})),
        ctx["officer_h"]))
    counsel_h = make_legal_counsel_headers(counsel_id)
    if accept:
        referral = get_success_data(api_client.accept_referral(
            loan["id"], case["id"], referral["id"], counsel_h))
    ctx["referral"] = referral
    ctx["counsel_h"] = counsel_h
    ctx["case"] = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    ctx["loan"] = get_success_data(api_client.get_loan(loan["id"], ctx["officer_h"]))
    return ctx


# ─── Tier 5: collateral / appraisal helpers ───────────

def make_collateral(loan_id, officer_headers=None, **overrides):
    """Pledge a collateral item on a loan. Returns the CollateralItem (PLEDGED)."""
    h = officer_headers or make_workout_officer_headers("officer-setup")
    return get_success_data(api_client.create_collateral(
        loan_id, create_collateral_payload(**overrides), h))


def make_accepted_appraisal(loan_id, collateral_id, desk_id="appr-1", appraisal_overrides=None):
    """Order, submit, and accept an appraisal on a collateral item.

    Returns (item_after, appraisal_after).
    """
    desk_h = make_appraisal_desk_headers(desk_id)
    item = get_success_data(api_client.get_collateral(loan_id, collateral_id, desk_h))
    appraisal = get_success_data(api_client.create_appraisal(
        loan_id, collateral_id,
        create_appraisal_payload(item["version"], appraiser_id=desk_id, **(appraisal_overrides or {})),
        desk_h))
    get_success_data(api_client.submit_appraisal(loan_id, collateral_id, appraisal["id"], desk_h))
    appraisal = get_success_data(api_client.accept_appraisal(loan_id, collateral_id, appraisal["id"], desk_h))
    item = get_success_data(api_client.get_collateral(loan_id, collateral_id, desk_h))
    return item, appraisal


def set_clock(to_iso8601: str):
    """Advance the logical clock (SystemAdmin only)."""
    return get_success_data(api_client.set_clock(
        {"to_iso8601": to_iso8601}, make_system_admin_headers("admin-clock")))
