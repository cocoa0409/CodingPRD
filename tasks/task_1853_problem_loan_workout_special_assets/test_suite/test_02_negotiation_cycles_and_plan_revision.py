"""Non-linear state machines: the proposal negotiation cycle and the action-plan
reject/revise/supersede loop.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_workout_officer_headers, make_special_assets_manager_headers,
    setup_case_in_negotiation, setup_case_in_action_plan,
    create_proposal_payload, create_action_plan_payload,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / non_linear_state_machine / proposal_negotiation_cycle_round_increment
# ===========================================================================

def _setup_proposal_under_review():
    ctx = setup_case_in_negotiation(
        officer_id="officer-5", manager_id="mgr-5",
        borrower_overrides={"legal_name": "Everett Logistics", "tax_id": "33-3333333",
                            "naics_code": "484110", "internal_risk_rating": 6},
        loan_overrides={"loan_number": "LN-5005", "original_principal_cents": 50000000,
                        "contractual_rate_bps": 1000, "days_past_due": 65},
        case_overrides={"entry_trigger": "RISK_RATING_DOWNGRADE", "risk_rating_at_entry": 6},
        plan_overrides={"plan_text": "Negotiate", "target_resolution_date": "2027-04-01T00:00:00Z",
                        "milestone_count": 2},
    )
    loan, case = ctx["loan"], ctx["case"]
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    prop = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="FORBEARANCE",
                                concession_rate_bps=900, term_extension_months=6,
                                principal_forgiveness_cents=0,
                                borrower_concession_cents=1000000),
        ctx["officer_h"]))
    prop = get_success_data(api_client.submit_proposal(
        loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    return ctx, prop


def test_negotiation_round_increments_once_per_counter_resubmit_cycle(api):
    """PRD §3.3: "A `COUNTERED` proposal can be resubmitted (from any other state,
    `ERR_PROPOSAL_NOT_COUNTERED`), which increments `negotiation_round`, moves the
    proposal to `RESUBMITTED`, and returns it automatically to
    `UNDER_BORROWER_REVIEW` — the negotiation cycle is deliberately cyclic."
    PRD §3.3: "A proposal's `negotiation_round` starts at 1 and increments by one
    each time the proposal is resubmitted after a counter."

    Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_round_increment
    """
    ctx, prop = _setup_proposal_under_review()
    loan, case = ctx["loan"], ctx["case"]
    assert prop["negotiation_round"] == 1
    assert prop["status"] == "UNDER_BORROWER_REVIEW"

    get_success_data(api_client.counter_proposal(
        loan["id"], case["id"], prop["id"],
        {"concession_rate_bps": 850, "term_extension_months": 6,
         "principal_forgiveness_cents": 0, "borrower_concession_cents": 1000000},
        ctx["officer_h"]))
    after1 = validate_success(api_client.resubmit_proposal(
        loan["id"], case["id"], prop["id"], ctx["officer_h"]), 200)
    assert after1["negotiation_round"] == 2, (
        f"After first counter+resubmit cycle round should be 2, got {after1['negotiation_round']}")
    assert after1["status"] == "UNDER_BORROWER_REVIEW"

    get_success_data(api_client.counter_proposal(
        loan["id"], case["id"], prop["id"],
        {"concession_rate_bps": 800, "term_extension_months": 9,
         "principal_forgiveness_cents": 0, "borrower_concession_cents": 1500000},
        ctx["officer_h"]))
    after2 = validate_success(api_client.resubmit_proposal(
        loan["id"], case["id"], prop["id"], ctx["officer_h"]), 200)
    assert after2["negotiation_round"] == 3
    assert after2["status"] == "UNDER_BORROWER_REVIEW"


def test_counter_replaces_terms_in_place_and_cycle_is_repeatable(api):
    """PRD §3.3: "An accepted counter replaces the proposal's four term fields in
    place and moves the proposal to `COUNTERED`."
    PRD §3.3: "A `COUNTERED` proposal can be resubmitted (from any other state,
    `ERR_PROPOSAL_NOT_COUNTERED`), which increments `negotiation_round`, moves the
    proposal to `RESUBMITTED`, and returns it automatically to
    `UNDER_BORROWER_REVIEW` — the negotiation cycle is deliberately cyclic."

    Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_round_increment
    """
    ctx, prop = _setup_proposal_under_review()
    loan, case = ctx["loan"], ctx["case"]

    countered = validate_success(api_client.counter_proposal(
        loan["id"], case["id"], prop["id"],
        {"concession_rate_bps": 850, "term_extension_months": 6,
         "principal_forgiveness_cents": 0, "borrower_concession_cents": 1000000},
        ctx["officer_h"]), 200)
    assert countered["status"] == "COUNTERED"
    assert countered["concession_rate_bps"] == 850, "counter terms replace the proposal's terms"

    resub = validate_success(api_client.resubmit_proposal(
        loan["id"], case["id"], prop["id"], ctx["officer_h"]), 200)
    assert resub["status"] == "UNDER_BORROWER_REVIEW"

    # Second cycle is reachable from the same proposal: non-linear.
    countered2 = validate_success(api_client.counter_proposal(
        loan["id"], case["id"], prop["id"],
        {"concession_rate_bps": 800, "term_extension_months": 9,
         "principal_forgiveness_cents": 0, "borrower_concession_cents": 1500000},
        ctx["officer_h"]), 200)
    assert countered2["status"] == "COUNTERED"
    assert countered2["term_extension_months"] == 9


# ===========================================================================
# Difficulty / non_linear_state_machine / action_plan_revision_loop_and_supersede
# ===========================================================================

def _setup_approved_plan_after_reject_loop():
    """Plan P1 through one reject-revise loop, then APPROVED (approval_round 2)."""
    ctx = setup_case_in_action_plan(
        officer_id="officer-6", manager_id="mgr-6",
        borrower_overrides={"legal_name": "Fairview Hospitality", "tax_id": "44-4444444",
                            "naics_code": "721110", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-6006", "original_principal_cents": 80000000,
                        "contractual_rate_bps": 950, "days_past_due": 70},
        case_overrides={"entry_trigger": "COVENANT_DEFAULT", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "Plan v1", "target_resolution_date": "2027-02-01T00:00:00Z",
                        "milestone_count": 2},
    )
    loan, case, plan = ctx["loan"], ctx["case"], ctx["plan"]
    get_success_data(api_client.submit_action_plan(loan["id"], case["id"], plan["id"], ctx["officer_h"]))
    get_success_data(api_client.reject_action_plan(loan["id"], case["id"], plan["id"], ctx["manager_h"]))
    get_success_data(api_client.revise_action_plan(loan["id"], case["id"], plan["id"], ctx["officer_h"]))
    get_success_data(api_client.submit_action_plan(loan["id"], case["id"], plan["id"], ctx["officer_h"]))
    p1 = get_success_data(api_client.approve_action_plan(loan["id"], case["id"], plan["id"], ctx["manager_h"]))
    ctx["plan"] = p1
    ctx["case"] = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    return ctx


def test_plan_reject_revise_loop_counts_approval_rounds(api):
    """PRD §3.2: "Approval increments the plan's `approval_round` by one — every pass
    through the submit-decide cycle counts one round, on approval and on rejection
    alike — and the first approval on the case fires a cascade: the case moves from
    `ACTION_PLAN` to `NEGOTIATION`, its `tdr_status` advances to `PENDING_EVALUATION`,
    and the loan moves from `WATCHLIST` to `WORKOUT`."
    PRD §3.2: "Rejection also increments `approval_round`, leaves the case in
    `ACTION_PLAN`, and returns the plan to the officer, who may send a `REJECTED`
    plan back to `DRAFT` through the revision step — attempting to revise a plan that
    is not `REJECTED` fails with `ERR_PLAN_NOT_REJECTED`."

    Design: Difficulty/non_linear_state_machine/action_plan_revision_loop_and_supersede
    """
    ctx = _setup_approved_plan_after_reject_loop()
    p1 = ctx["plan"]
    # One rejection + one approval: approval_round == 2.
    assert p1["status"] == "APPROVED"
    assert p1["approval_round"] == 2, (
        f"Expected approval_round 2 after one reject + one approve, got {p1['approval_round']}")
    # First approval cascade.
    assert ctx["case"]["status"] == "NEGOTIATION"
    assert ctx["case"]["tdr_status"] == "PENDING_EVALUATION"
    loan_after = validate_success(api_client.get_loan(ctx["loan"]["id"], ctx["officer_h"]), 200)
    assert loan_after["status"] == "WORKOUT"


def test_newer_approved_plan_supersedes_predecessor(api):
    """PRD §3.2: "If the newly approved plan was drafted with a `supersedes_plan_id`
    naming a still-`APPROVED` predecessor, that predecessor flips to `SUPERSEDED` in
    the same breath, and the newer plan carries the strategy forward."

    Design: Difficulty/non_linear_state_machine/action_plan_revision_loop_and_supersede
    """
    ctx = _setup_approved_plan_after_reject_loop()
    loan, case, p1 = ctx["loan"], ctx["case"], ctx["plan"]
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))

    p2 = get_success_data(api_client.create_action_plan(
        loan["id"], case["id"],
        create_action_plan_payload(case["version"], plan_text="Plan v2 supersedes",
                                   target_resolution_date="2027-05-01T00:00:00Z",
                                   milestone_count=4, supersedes_plan_id=p1["id"]),
        ctx["officer_h"]))
    get_success_data(api_client.submit_action_plan(loan["id"], case["id"], p2["id"], ctx["officer_h"]))
    p2_after = validate_success(api_client.approve_action_plan(
        loan["id"], case["id"], p2["id"], ctx["manager_h"]), 200)

    assert p2_after["status"] == "APPROVED"
    p1_after = validate_success(api_client.get_action_plan_flat(p1["id"], ctx["officer_h"]), 200)
    assert p1_after["status"] == "SUPERSEDED"
