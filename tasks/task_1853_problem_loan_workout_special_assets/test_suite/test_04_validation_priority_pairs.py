"""Priority-pair validation conflicts: when one request violates rules at two
priority layers, the earlier layer's error masks the later one (PRD §2.11).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_workout_officer_headers, make_special_assets_manager_headers,
    make_loan_accounting_headers,
    setup_case_in_action_plan, setup_case_in_impairment_review,
    create_impairment_tdr_dcf_payload,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / priority_pair_validation_conflict /
#   state_vs_business_safety_plan_approve_conflict
# ===========================================================================

def test_plan_approve_state_error_masks_segregation_error(api):
    """PRD §2.11: "When a request fails several rules at once, the failure the client
    sees is determined by a fixed priority order; an earlier failure masks every
    later one."
    PRD §2.11: "The target entity's state machine permits the requested transition —
    every from-state and state precondition. Where a transition names a specific
    state error (for example `ERR_PLAN_NOT_DRAFT` or `ERR_CASE_NOT_LEGAL`) that error
    is used; where no more specific state error is defined, the rejection is
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.11: "Segregation-of-duties comparisons (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §3.2: "Approval requires the plan to be `SUBMITTED` (otherwise
    `ERR_PLAN_NOT_SUBMITTED`), requires the approver to be someone other than the
    `case_officer_id` (segregation of duties, `ERR_SEGREGATION_OF_DUTIES`), and
    requires that no other plan on the case currently stand `APPROVED` (a second
    active plan is refused with `ERR_ACTIVE_PLAN_EXISTS`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_plan_approve_conflict
    """
    ctx = setup_case_in_action_plan(
        officer_id="officer-10", manager_id="mgr-10",
        borrower_overrides={"legal_name": "Ironwood Construction", "tax_id": "77-7777777",
                            "naics_code": "236220", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-9009", "original_principal_cents": 45000000,
                        "contractual_rate_bps": 975, "days_past_due": 66},
        case_overrides={"entry_trigger": "MANUAL_REFERRAL", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "Draft plan",
                        "target_resolution_date": "2027-01-20T00:00:00Z", "milestone_count": 1},
    )
    loan, case, plan = ctx["loan"], ctx["case"], ctx["plan"]
    # Plan is still DRAFT (state violation) AND the approver's X-User-ID equals the
    # case_officer_id (segregation violation). Layer 4 (state) masks layer 6 (SoD).
    res = api_client.approve_action_plan(
        loan["id"], case["id"], plan["id"],
        make_special_assets_manager_headers("officer-10"))
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_SUBMITTED.value, expected_status=409)


def test_plan_submit_state_error_masks_segregation_error(api):
    """PRD §2.11: "When a request fails several rules at once, the failure the client
    sees is determined by a fixed priority order; an earlier failure masks every
    later one. The layers, evaluated in this exact sequence, are:"
    PRD §2.11: "The target entity's state machine permits the requested transition —
    every from-state and state precondition. Where a transition names a specific
    state error (for example `ERR_PLAN_NOT_DRAFT` or `ERR_CASE_NOT_LEGAL`) that error
    is used; where no more specific state error is defined, the rejection is
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.11: "Segregation-of-duties comparisons (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §3.2: "The owning officer submits it (`DRAFT` is required, else
    `ERR_PLAN_NOT_DRAFT`), and a `SpecialAssetsManager` then decides."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_plan_approve_conflict
    """
    ctx = setup_case_in_action_plan(
        officer_id="officer-10b", manager_id="mgr-10b",
    )
    loan, case, plan = ctx["loan"], ctx["case"], ctx["plan"]
    get_success_data(api_client.submit_action_plan(loan["id"], case["id"], plan["id"], ctx["officer_h"]))
    # Second submit: plan not DRAFT (state, layer 4) AND caller is not the case
    # officer (SoD, layer 6). State error must win.
    res = api_client.submit_action_plan(
        loan["id"], case["id"], plan["id"],
        make_workout_officer_headers("someone-else"))
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_DRAFT.value, expected_status=409)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict /
#   business_safety_vs_business_fiscal_committee_conflict
# ===========================================================================

def _setup_tdr_rejected_case():
    """Case in IMPAIRMENT_REVIEW with tdr_status == TDR_REJECTED (consummation with
    no concession: rate equals contract, zero forgiveness)."""
    return setup_case_in_impairment_review(
        officer_id="officer-11", manager_id="mgr-11", committee_id="cc-11",
        borrower_overrides={"legal_name": "Juniper Foods", "tax_id": "88-8888888",
                            "naics_code": "311410", "internal_risk_rating": 6,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-1010", "original_principal_cents": 30000000,
                        "contractual_rate_bps": 900, "days_past_due": 62},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 6},
        plan_overrides={"plan_text": "Modify without concession",
                        "target_resolution_date": "2027-02-15T00:00:00Z", "milestone_count": 1},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 900,
                            "term_extension_months": 0, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 500000},
        concession=False,
    )


def test_tdr_method_gate_fires_regardless_of_assessment_inputs(api):
    """PRD §3.6: "or `TDR_DCF`, the discounted-cash-flow approach, which is permitted
    only when the case's `tdr_status` is `TDR_CONFIRMED` — finalizing a `TDR_DCF`
    assessment without that confirmation is rejected with
    `ERR_TDR_METHOD_REQUIRES_TDR` (HTTP 422)."
    PRD §3.4: "The case moves from `NEGOTIATION` to `IMPAIRMENT_REVIEW`, and its
    `tdr_status` resolves from `PENDING_EVALUATION` to `TDR_CONFIRMED` when the flag
    is true or `TDR_REJECTED` when it is false."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_committee_conflict
    """
    ctx = _setup_tdr_rejected_case()
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-11")

    # Same gate with fully in-range inputs: still rejected, confirming the block is
    # the case's tdr_status and not the assessment payload.
    imp = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_tdr_dcf_payload(
            probability_of_default_bps=2000, loss_given_default_bps=3000,
            expected_cash_flows=[{"period_index": 6, "amount_cents": 25000000}]),
        acct_h))
    res = api_client.finalize_impairment(loan["id"], case["id"], imp["id"], acct_h)
    validate_error(res, ApiErrorId.ERR_TDR_METHOD_REQUIRES_TDR.value, expected_status=422)
