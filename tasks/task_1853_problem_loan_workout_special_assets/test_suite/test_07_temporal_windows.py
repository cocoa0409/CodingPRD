"""Temporal window semantics: the inclusive 365-day appraisal staleness window and
the strict under-60-days cure requirement on a RETURN_TO_PERFORMING close.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_appraisal_desk_headers, make_loan_accounting_headers,
    make_special_assets_manager_headers, make_workout_officer_headers,
    setup_case_in_impairment_review, make_borrower_with_loan, open_workout_case,
    make_collateral, set_clock,
    create_appraisal_payload, create_exit_decision_payload, create_proposal_payload,
    create_action_plan_payload, create_workout_case_payload,
    make_credit_committee_headers,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / resource_temporal_overlap / appraisal_staleness_window_boundary
# ===========================================================================

def _setup_collateral_with_submitted_appraisal():
    borrower, loan = make_borrower_with_loan(
        "officer-setup-s",
        borrower_overrides={"legal_name": "Orchard Industrial", "tax_id": "12-0000004",
                            "naics_code": "493110", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-1515", "original_principal_cents": 55000000,
                        "contractual_rate_bps": 950, "days_past_due": 85})
    officer_h = make_workout_officer_headers("officer-setup-s")
    item = make_collateral(loan["id"], officer_h, collateral_type="EQUIPMENT",
                           description="CNC line", liquidation_discount_bps=3000)
    desk_h = make_appraisal_desk_headers("appr-2")
    a1 = get_success_data(api_client.create_appraisal(
        loan["id"], item["id"],
        create_appraisal_payload(item["version"], appraised_value_cents=40000000,
                                 effective_date="2025-08-01T00:00:00Z", appraiser_id="appr-2"),
        desk_h))
    get_success_data(api_client.submit_appraisal(loan["id"], item["id"], a1["id"], desk_h))
    return borrower, loan, item, a1, desk_h, officer_h


def test_appraisal_accepted_at_exactly_365_days_staleness(api):
    """PRD §3.5: "Acceptance requires the appraisal to be `SUBMITTED` (else
    `ERR_APPRAISAL_NOT_SUBMITTED`) and requires `staleness_days` of no more than 365
    — an appraisal more than one year old at acceptance is rejected with
    `ERR_APPRAISAL_STALE` (HTTP 422)."
    PRD §3.5: "`current_liquidation_value_cents` becomes that value multiplied by ten
    thousand minus the item's `liquidation_discount_bps`, divided by ten thousand,
    rounded half up to whole cents — multiply first, divide once, round once, with no
    intermediate rounding of the discount factor."

    Design: Difficulty/resource_temporal_overlap/appraisal_staleness_window_boundary
    """
    borrower, loan, item, a1, desk_h, officer_h = _setup_collateral_with_submitted_appraisal()
    # Effective 2025-08-01, clock moved to exactly 2026-08-01: staleness 365 days.
    set_clock("2026-08-01T00:00:00Z")
    accepted = validate_success(api_client.accept_appraisal(
        loan["id"], item["id"], a1["id"], desk_h), 200)
    assert accepted["status"] == "ACCEPTED", "365 days exactly is within the inclusive window"

    item_after = validate_success(api_client.get_collateral(loan["id"], item["id"], desk_h), 200)
    # 40,000,000 x (10000 - 3000) / 10000 = 28,000,000
    assert item_after["current_liquidation_value_cents"] == 28000000


def test_appraisal_rejected_at_366_days_staleness(api):
    """PRD §3.5: "Acceptance requires the appraisal to be `SUBMITTED` (else
    `ERR_APPRAISAL_NOT_SUBMITTED`) and requires `staleness_days` of no more than 365
    — an appraisal more than one year old at acceptance is rejected with
    `ERR_APPRAISAL_STALE` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/appraisal_staleness_window_boundary
    """
    borrower, loan, item, a1, desk_h, officer_h = _setup_collateral_with_submitted_appraisal()
    # Accept the first appraisal at exactly 365 days to walk the item back to PLEDGED.
    set_clock("2026-08-01T00:00:00Z")
    validate_success(api_client.accept_appraisal(loan["id"], item["id"], a1["id"], desk_h), 200)

    # Move the clock to 2026-08-02: the same 2025-08-01 effective date is now 366
    # days old. Order and submit a second appraisal, then accept must fail.
    set_clock("2026-08-02T00:00:00Z")
    item_now = validate_success(api_client.get_collateral(loan["id"], item["id"], desk_h), 200)
    a2 = get_success_data(api_client.create_appraisal(
        loan["id"], item["id"],
        create_appraisal_payload(item_now["version"], appraised_value_cents=40000000,
                                 effective_date="2025-08-01T00:00:00Z", appraiser_id="appr-2"),
        desk_h))
    get_success_data(api_client.submit_appraisal(loan["id"], item["id"], a2["id"], desk_h))
    res = api_client.accept_appraisal(loan["id"], item["id"], a2["id"], desk_h)
    validate_error(res, ApiErrorId.ERR_APPRAISAL_STALE.value, expected_status=422)


# ===========================================================================
# Difficulty / resource_temporal_overlap / case_close_cure_window_sixty_days
# ===========================================================================

def _setup_resolution_case_return_to_performing():
    """Case in RESOLUTION with resolution_path RETURN_TO_PERFORMING (reached from
    NEGOTIATION after a consummated proposal), on a 20,000,000 loan."""
    ctx = setup_case_in_impairment_review(
        officer_id="officer-16", manager_id="mgr-16", committee_id="cc-16",
        borrower_overrides={"legal_name": "Pinecrest Pediatrics", "tax_id": "12-0000005",
                            "naics_code": "621111", "internal_risk_rating": 6,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-1616", "original_principal_cents": 20000000,
                        "contractual_rate_bps": 850, "days_past_due": 62},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 6},
        plan_overrides={"plan_text": "Cure and return",
                        "target_resolution_date": "2027-01-05T00:00:00Z", "milestone_count": 1},
        proposal_overrides={"proposal_kind": "FORBEARANCE", "concession_rate_bps": 850,
                            "term_extension_months": 3, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 100000},
        concession=False,  # rate 850 == contractual 850, zero forgiveness -> no TDR
    )
    loan, case = ctx["loan"], ctx["case"]
    # Exit decision from NEGOTIATION path requires consummated proposal; the case is
    # in IMPAIRMENT_REVIEW now. Draft a new proposal cycle to return to NEGOTIATION
    # is unnecessary: the PRD's NEGOTIATION exit requires consummated proposal, and
    # case is IMPAIRMENT_REVIEW. Instead, record exit from the current posture:
    # IMPAIRMENT_REVIEW is not an exit posture, so first swing back to NEGOTIATION by
    # drafting a new proposal.
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    prop2 = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="FORBEARANCE",
                                concession_rate_bps=850, term_extension_months=3,
                                principal_forgiveness_cents=0,
                                borrower_concession_cents=100000),
        ctx["officer_h"]))
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    assert case["status"] == "NEGOTIATION"
    decision = get_success_data(api_client.create_exit_decision(
        loan["id"], case["id"],
        create_exit_decision_payload(chosen_path="RETURN_TO_PERFORMING",
                                     npv_foreclosure_cents=1000000,
                                     npv_deed_in_lieu_cents=900000,
                                     override_justification="Borrower cured; performing path superior"),
        ctx["manager_h"]))
    ctx["decision"] = decision
    ctx["case"] = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    return ctx


def test_close_return_to_performing_at_60_days_rejected(api):
    """PRD §3.9: "when the `resolution_path` is `RETURN_TO_PERFORMING` the cure must
    be genuine: the loan's `days_past_due` must be under 60 days and its
    `current_principal_cents` must still be greater than zero, else
    `ERR_CURE_NOT_ESTABLISHED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/case_close_cure_window_sixty_days
    """
    ctx = _setup_resolution_case_return_to_performing()
    loan, case = ctx["loan"], ctx["case"]
    assert ctx["case"]["status"] == "RESOLUTION"
    assert ctx["case"]["resolution_path"] == "RETURN_TO_PERFORMING"

    acct_h = make_loan_accounting_headers("acct-16")
    get_success_data(api_client.aging_refresh(loan["id"], {"days_past_due": 60}, acct_h))

    res = api_client.close_case(loan["id"], case["id"], ctx["manager_h"])
    # Exactly 60 is not "under 60": strict inequality fails.
    validate_error(res, ApiErrorId.ERR_CURE_NOT_ESTABLISHED.value, expected_status=422)


def test_close_return_to_performing_at_59_days_succeeds_and_exits_borrower(api):
    """PRD §3.9: "when the `resolution_path` is `RETURN_TO_PERFORMING` the cure must
    be genuine: the loan's `days_past_due` must be under 60 days and its
    `current_principal_cents` must still be greater than zero, else
    `ERR_CURE_NOT_ESTABLISHED` (HTTP 422). Closure moves the case to its terminal
    `CLOSED`, lands the loan in `RESOLVED` — or back in `PERFORMING` when the path
    was `RETURN_TO_PERFORMING`, the only route by which a watchlisted loan regains
    its performing status — and, when this was the borrower's last non-`CLOSED` case
    across all of its loans, flips the borrower's `status` to `EXITED`."

    Design: Difficulty/resource_temporal_overlap/case_close_cure_window_sixty_days
    """
    ctx = _setup_resolution_case_return_to_performing()
    loan, case, borrower = ctx["loan"], ctx["case"], ctx["borrower"]
    acct_h = make_loan_accounting_headers("acct-16")

    get_success_data(api_client.aging_refresh(loan["id"], {"days_past_due": 60}, acct_h))
    res = api_client.close_case(loan["id"], case["id"], ctx["manager_h"])
    validate_error(res, ApiErrorId.ERR_CURE_NOT_ESTABLISHED.value, expected_status=422)

    # Cure to 59 days: strictly under 60 passes.
    get_success_data(api_client.aging_refresh(loan["id"], {"days_past_due": 59}, acct_h))
    closed = validate_success(api_client.close_case(loan["id"], case["id"], ctx["manager_h"]), 200)
    assert closed["status"] == "CLOSED"

    loan_after = validate_success(api_client.get_loan(loan["id"], ctx["officer_h"]), 200)
    assert loan_after["status"] == "PERFORMING"

    borrower_after = validate_success(api_client.get_borrower(borrower["id"], ctx["officer_h"]), 200)
    assert borrower_after["status"] == "EXITED"
