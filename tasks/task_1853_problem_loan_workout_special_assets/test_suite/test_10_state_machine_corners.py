"""Corner coverage — state machine corners: initial case state, non-PERFORMING loan
gate, counter materiality, withdraw gating, terminal lockdown, open-referral close
block, NEGOTIATION exit path gate, and guarantor demand ceiling.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_workout_officer_headers, make_special_assets_manager_headers,
    make_loan_accounting_headers, make_credit_committee_headers,
    make_legal_counsel_headers,
    make_borrower_with_loan, open_workout_case, make_borrower,
    setup_case_in_action_plan, setup_case_in_negotiation, setup_case_in_impairment_review,
    create_proposal_payload, create_legal_referral_payload, create_exit_decision_payload,
    create_loan_payload, create_workout_case_payload,
    assert_workout_case,
)
from test_helpers.api_client import api_client


def test_workout_case_initial_state_watchlist(api):
    """PRD §3.2: "Opening the case moves the loan from `PERFORMING` to `WATCHLIST`,
    increments the loan's `version` by one, and creates the case itself in
    `WATCHLIST` status at `version` 1, with `tdr_status` at `NOT_EVALUATED`,
    `resolution_path` at `NONE`, and `loss_given_default_cents`,
    `impairment_reserve_cents`, and `unapplied_cash_cents` all at zero."

    Design: Corner/state_machines/workout_case_initial_state_watchlist
    """
    officer_h = make_workout_officer_headers("officer-s1")
    borrower = make_borrower(officer_h, legal_name="Init State Co", tax_id="55-0000005",
                             naics_code="541330", internal_risk_rating=7)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-S01",
         "original_principal_cents": 15000000, "contractual_rate_bps": 900,
         "days_past_due": 61},
        officer_h))
    case = validate_success(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7,
         "case_officer_id": "officer-s1"},
        officer_h), 201)
    assert_workout_case(case)
    assert case["status"] == "WATCHLIST"
    assert case["tdr_status"] == "NOT_EVALUATED"
    assert case["resolution_path"] == "NONE"
    assert case["loss_given_default_cents"] == 0
    assert case["impairment_reserve_cents"] == 0
    assert case["unapplied_cash_cents"] == 0
    assert case["version"] == 1


def test_case_create_on_non_performing_loan_rejected(api):
    """PRD §3.2: "The loan must currently be `PERFORMING` — opening a case on a loan
    in any other status is rejected with `ERR_LOAN_NOT_PERFORMING` (HTTP 409)."

    Design: Corner/state_machines/case_create_on_non_performing_loan_rejected
    """
    officer_h = make_workout_officer_headers("officer-s2")
    borrower = make_borrower(officer_h, legal_name="Double Case Co", tax_id="55-0000006",
                             naics_code="541511", internal_risk_rating=8)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-S02",
         "original_principal_cents": 12000000, "contractual_rate_bps": 850,
         "days_past_due": 70},
        officer_h))
    validate_success(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8,
         "case_officer_id": "officer-s2"},
        officer_h), 201)

    # The loan is now WATCHLIST, so a second case is rejected (officer header matches
    # the recorded case_officer_id so only the loan-state rule can fire).
    res = api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "MANUAL_REFERRAL", "risk_rating_at_entry": 8,
         "case_officer_id": "officer-s2b"},
        make_workout_officer_headers("officer-s2b"))
    validate_error(res, ApiErrorId.ERR_LOAN_NOT_PERFORMING.value, expected_status=409)


def test_proposal_counter_identical_terms_rejected(api):
    """PRD §3.3: "The officer can record a borrower counter-offer, which requires
    `UNDER_BORROWER_REVIEW` (otherwise `ERR_PROPOSAL_NOT_UNDER_REVIEW`) and requires
    the counter terms to differ from the current terms in at least one of the four
    term fields — a counter that changes nothing is rejected with
    `ERR_COUNTER_NOT_MATERIAL` (HTTP 422)."

    Design: Corner/state_machines/proposal_counter_identical_terms_rejected
    """
    ctx = setup_case_in_negotiation(
        officer_id="officer-s3", manager_id="mgr-s3",
        borrower_overrides={"legal_name": "Counter Test Co", "tax_id": "55-0000007",
                            "naics_code": "541611", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-S03", "original_principal_cents": 11000000,
                        "contractual_rate_bps": 900, "days_past_due": 63},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "Negotiate",
                        "target_resolution_date": "2027-01-15T00:00:00Z", "milestone_count": 1},
    )
    loan, case = ctx["loan"], ctx["case"]
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    prop = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="FORBEARANCE",
                                concession_rate_bps=700, term_extension_months=6,
                                principal_forgiveness_cents=0,
                                borrower_concession_cents=100000),
        ctx["officer_h"]))
    get_success_data(api_client.submit_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))

    # Counter with all four term fields identical to the current terms.
    res = api_client.counter_proposal(
        loan["id"], case["id"], prop["id"],
        {"concession_rate_bps": 700, "term_extension_months": 6,
         "principal_forgiveness_cents": 0, "borrower_concession_cents": 100000},
        ctx["officer_h"])
    validate_error(res, ApiErrorId.ERR_COUNTER_NOT_MATERIAL.value, expected_status=422)


def test_withdraw_from_committee_review_rejected(api):
    """PRD §3.3: "At any point before committee review — from `DRAFT`, `SUBMITTED`,
    `UNDER_BORROWER_REVIEW`, or `COUNTERED` — the officer may withdraw the proposal
    to `WITHDRAWN`; withdrawal from any other state earns
    `ERR_PROPOSAL_NOT_WITHDRAWABLE`."

    Design: Corner/state_machines/withdraw_from_committee_review_rejected
    """
    ctx = setup_case_in_negotiation(
        officer_id="officer-s4", manager_id="mgr-s4",
        borrower_overrides={"legal_name": "Withdraw Test Co", "tax_id": "55-0000008",
                            "naics_code": "541612", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-S04", "original_principal_cents": 13000000,
                        "contractual_rate_bps": 880, "days_past_due": 64},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "Withdraw probe",
                        "target_resolution_date": "2027-02-10T00:00:00Z", "milestone_count": 1},
    )
    loan, case = ctx["loan"], ctx["case"]
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    prop = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="MODIFICATION",
                                concession_rate_bps=800, term_extension_months=3,
                                principal_forgiveness_cents=0, borrower_concession_cents=0),
        ctx["officer_h"]))
    get_success_data(api_client.submit_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    get_success_data(api_client.escalate_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))

    res = api_client.withdraw_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"])
    validate_error(res, ApiErrorId.ERR_PROPOSAL_NOT_WITHDRAWABLE.value, expected_status=409)


def test_terminal_state_lockdown_consummated_proposal(api):
    """PRD §3.3: "A proposal's terminal states are `CONSUMMATED`, `REJECTED`, and
    `WITHDRAWN`; `APPROVED` is explicitly not terminal, because consummation still
    lies ahead."
    PRD §3.3: "At any point before committee review — from `DRAFT`, `SUBMITTED`,
    `UNDER_BORROWER_REVIEW`, or `COUNTERED` — the officer may withdraw the proposal
    to `WITHDRAWN`; withdrawal from any other state earns
    `ERR_PROPOSAL_NOT_WITHDRAWABLE`."

    Design: Corner/state_machines/terminal_state_lockdown_consummated_proposal
    """
    ctx = setup_case_in_impairment_review(
        officer_id="officer-s5", manager_id="mgr-s5", committee_id="cc-s5",
        borrower_overrides={"legal_name": "Terminal Lock Co", "tax_id": "55-0000009",
                            "naics_code": "541613", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-S05", "original_principal_cents": 14000000,
                        "contractual_rate_bps": 920, "days_past_due": 66},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Lock", "target_resolution_date": "2027-03-10T00:00:00Z",
                        "milestone_count": 1},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 500,
                            "term_extension_months": 12, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 0},
        concession=True,
    )
    loan, case, prop = ctx["loan"], ctx["case"], ctx["proposal"]
    assert prop["status"] == "CONSUMMATED"

    # Every non-terminal transition is now closed to this proposal.
    res = api_client.withdraw_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"])
    validate_error(res, ApiErrorId.ERR_PROPOSAL_NOT_WITHDRAWABLE.value, expected_status=409)


def test_case_close_with_open_referral_rejected(api):
    """PRD §3.9: "The case must be in `RESOLUTION` (`ERR_CASE_NOT_RESOLUTION`), every
    legal referral on it must have reached `SETTLED` or `DISMISSED`
    (`ERR_OPEN_REFERRALS_EXIST`), and when the `resolution_path` is
    `RETURN_TO_PERFORMING` the cure must be genuine: the loan's `days_past_due` must
    be under 60 days and its `current_principal_cents` must still be greater than
    zero, else `ERR_CURE_NOT_ESTABLISHED` (HTTP 422)."

    Design: Corner/state_machines/case_close_with_open_referral_rejected
    """
    from test_helpers import setup_case_in_legal
    ctx = setup_case_in_legal(
        officer_id="officer-s6", manager_id="mgr-s6", counsel_id="counsel-s6",
        borrower_overrides={"legal_name": "Open Referral Co", "tax_id": "55-0000010",
                            "naics_code": "541614", "internal_risk_rating": 9},
        loan_overrides={"loan_number": "LN-S06", "original_principal_cents": 16000000,
                        "contractual_rate_bps": 940, "days_past_due": 95},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 9},
        plan_overrides={"plan_text": "Foreclose",
                        "target_resolution_date": "2027-04-15T00:00:00Z", "milestone_count": 1},
        referral_overrides={"referral_kind": "FORECLOSURE", "demand_amount_cents": 0,
                            "statute_deadline": "2028-01-01T00:00:00Z",
                            "decision_rationale": "Foreclosure optimal"},
    )
    loan, case = ctx["loan"], ctx["case"]
    # Referral is ACTIVE. Record the exit decision (LEGAL posture, argmax respected).
    get_success_data(api_client.create_exit_decision(
        loan["id"], case["id"],
        create_exit_decision_payload(chosen_path="FORECLOSURE",
                                     npv_foreclosure_cents=9000000,
                                     npv_deed_in_lieu_cents=8000000,
                                     override_justification=""),
        ctx["manager_h"]))

    res = api_client.close_case(loan["id"], case["id"], ctx["manager_h"])
    validate_error(res, ApiErrorId.ERR_OPEN_REFERRALS_EXIST.value, expected_status=409)


def test_exit_decision_foreclosure_requires_legal_status(api):
    """PRD §3.9: "From `NEGOTIATION`, the decision is available only when the case
    holds at least one `CONSUMMATED` proposal — without one the attempt fails as
    `ERR_CASE_NOT_LEGAL` — the active-referral requirement is waived, and only
    `RETURN_TO_PERFORMING` or `NOTE_SALE` may be chosen; picking `FORECLOSURE` or
    `DEED_IN_LIEU` from `NEGOTIATION` is rejected with `ERR_PATH_REQUIRES_LEGAL`
    (HTTP 422)."

    Design: Corner/state_machines/exit_decision_foreclosure_requires_legal_status
    """
    ctx = setup_case_in_impairment_review(
        officer_id="officer-s7", manager_id="mgr-s7", committee_id="cc-s7",
        borrower_overrides={"legal_name": "Path Gate Co", "tax_id": "55-0000011",
                            "naics_code": "541615", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-S07", "original_principal_cents": 17000000,
                        "contractual_rate_bps": 960, "days_past_due": 67},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Gate", "target_resolution_date": "2027-05-01T00:00:00Z",
                        "milestone_count": 1},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 800,
                            "term_extension_months": 3, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 0},
        concession=True,
    )
    loan, case = ctx["loan"], ctx["case"]
    # Swing the case back to NEGOTIATION (it holds a CONSUMMATED proposal).
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="MODIFICATION",
                                concession_rate_bps=800, term_extension_months=3,
                                principal_forgiveness_cents=0, borrower_concession_cents=0),
        ctx["officer_h"]))
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    assert case["status"] == "NEGOTIATION"

    res = api_client.create_exit_decision(
        loan["id"], case["id"],
        create_exit_decision_payload(chosen_path="FORECLOSURE",
                                     npv_foreclosure_cents=5000000,
                                     npv_deed_in_lieu_cents=4000000,
                                     override_justification=""),
        ctx["manager_h"])
    validate_error(res, ApiErrorId.ERR_PATH_REQUIRES_LEGAL.value, expected_status=422)


def test_guarantor_referral_demand_exceeds_net_worth_rejected(api):
    """PRD §3.7: "The `demand_amount_cents` asked of a guarantor must clear two
    ceilings — it may not exceed the borrower's certified
    `guarantor_net_worth_cents`, and it may not exceed the case's current
    `loss_given_default_cents`; breaching either ceiling is a business-constraint
    violation, `ERR_BUSINESS_CONSTRAINT` (HTTP 422)."

    Design: Corner/state_machines/guarantor_referral_demand_exceeds_net_worth_rejected
    """
    ctx = setup_case_in_negotiation(
        officer_id="officer-s8", manager_id="mgr-s8",
        borrower_overrides={"legal_name": "Weak Guarantor Co", "tax_id": "55-0000012",
                            "naics_code": "541616", "internal_risk_rating": 8,
                            "guarantor_name": "W Guarantor",
                            "guarantor_net_worth_cents": 5000000},
        loan_overrides={"loan_number": "LN-S08", "original_principal_cents": 18000000,
                        "contractual_rate_bps": 980, "days_past_due": 69},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Pursue", "target_resolution_date": "2027-06-01T00:00:00Z",
                        "milestone_count": 1},
    )
    loan, case = ctx["loan"], ctx["case"]

    res = api_client.create_legal_referral(
        loan["id"], case["id"],
        create_legal_referral_payload(referral_kind="GUARANTOR_PURSUITS",
                                      target_guarantor_name="W Guarantor",
                                      demand_amount_cents=5000001,
                                      statute_deadline="2028-01-01T00:00:00Z",
                                      decision_rationale=""),
        ctx["officer_h"])
    # 5,000,001 > guarantor_net_worth 5,000,000.
    validate_error(res, ApiErrorId.ERR_BUSINESS_CONSTRAINT.value, expected_status=422)
