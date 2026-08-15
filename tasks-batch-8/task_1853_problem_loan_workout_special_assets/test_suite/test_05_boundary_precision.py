"""Boundary precision: forgiveness cap inclusive equality, and statute-deadline
strictly-after semantics on referral acceptance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_credit_committee_headers, make_loan_accounting_headers,
    make_legal_counsel_headers, make_workout_officer_headers,
    setup_case_in_negotiation, set_clock,
    create_proposal_payload, create_charge_off_payload, create_legal_referral_payload,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / boundary_precision_check / forgiveness_cap_exact_equality_allowed
# ===========================================================================

def _setup_two_cap_proposals():
    """One loan (original 100,000,000, cap 25,000,000) with 20,000,000 charged off,
    and two proposals in COMMITTEE_REVIEW: P1 at forgiveness 5,000,000 (cumulative
    == cap exactly) and P2 at 5,000,001 (cap + 1)."""
    ctx = setup_case_in_negotiation(
        officer_id="officer-12", manager_id="mgr-12",
        borrower_overrides={"legal_name": "Kestrel Aviation", "tax_id": "99-9999999",
                            "naics_code": "481211", "internal_risk_rating": 8,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-1111", "original_principal_cents": 100000000,
                        "contractual_rate_bps": 1000, "days_past_due": 90},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Cap probe", "target_resolution_date": "2027-03-15T00:00:00Z",
                        "milestone_count": 1},
    )
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-12")
    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=20000000, reason_code="PARTIAL_IMPAIRMENT"),
        acct_h))

    proposals = []
    for forgiveness in (5000000, 5000001):
        case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
        prop = get_success_data(api_client.create_proposal(
            loan["id"], case["id"],
            create_proposal_payload(case["version"], proposal_kind="RESTRUCTURE",
                                    concession_rate_bps=700, term_extension_months=6,
                                    principal_forgiveness_cents=forgiveness,
                                    borrower_concession_cents=0),
            ctx["officer_h"]))
        get_success_data(api_client.submit_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
        get_success_data(api_client.escalate_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
        proposals.append(prop)
    ctx["p_ok"], ctx["p_over"] = proposals
    ctx["committee_h"] = make_credit_committee_headers("cc-12")
    return ctx


def test_cumulative_forgiveness_equal_to_cap_is_allowed(api):
    """PRD §3.3: "The ceiling is inclusive: a sum exactly equal to the cap is
    allowed, and only a sum strictly greater is refused with
    `ERR_FORGIVENESS_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/forgiveness_cap_exact_equality_allowed
    """
    ctx = _setup_two_cap_proposals()
    loan, case = ctx["loan"], ctx["case"]
    res = api_client.committee_approve_proposal(
        loan["id"], case["id"], ctx["p_ok"]["id"], ctx["committee_h"])
    approved = validate_success(res, 200)
    # 20,000,000 + 5,000,000 == 25,000,000 == cap exactly -> inclusive boundary passes.
    assert approved["status"] == "APPROVED"


def test_cumulative_forgiveness_one_cent_over_cap_rejected(api):
    """PRD §3.3: "the sum of the loan's `charged_off_principal_cents` already booked
    and this proposal's `principal_forgiveness_cents` must not exceed one quarter of
    the loan's `original_principal_cents` — computed as the original principal times
    twenty-five hundred basis points divided by ten thousand, with any fractional cent
    discarded. The ceiling is inclusive: a sum exactly equal to the cap is allowed,
    and only a sum strictly greater is refused with `ERR_FORGIVENESS_CAP_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/forgiveness_cap_exact_equality_allowed
    """
    ctx = _setup_two_cap_proposals()
    loan, case = ctx["loan"], ctx["case"]
    # Approve the at-cap proposal first so the over-cap attempt runs against an
    # unchanged 20,000,000 charged-off balance (approval books nothing).
    validate_success(api_client.committee_approve_proposal(
        loan["id"], case["id"], ctx["p_ok"]["id"], ctx["committee_h"]), 200)
    res = api_client.committee_approve_proposal(
        loan["id"], case["id"], ctx["p_over"]["id"], ctx["committee_h"])
    # 20,000,000 + 5,000,001 == 25,000,001 > 25,000,000 -> strict > rejects.
    validate_error(res, ApiErrorId.ERR_FORGIVENESS_CAP_EXCEEDED.value, expected_status=422)


# ===========================================================================
# Difficulty / boundary_precision_check /
#   statute_deadline_zero_days_remaining_blocks_accept
# ===========================================================================

def _setup_referral_at_statute_boundary(statute_deadline, clock_at_acceptance):
    """NEGOTIATION case with one GUARANTOR_PURSUITS referral whose statute_deadline
    is strictly after the default clock at creation (PRD §3.7 requires this), with
    the logical clock then advanced to `clock_at_acceptance` so the acceptance-time
    re-check runs against the boundary.

    A charge-off is booked first so the case's loss-given-default recomputes to the
    outstanding principal (39,000,000), clearing the PRD §3.7 demand ceilings for
    the 5,000,000 demand (<= guarantor net worth 20,000,000, <= LGD).
    """
    ctx = setup_case_in_negotiation(
        officer_id="officer-13", manager_id="mgr-13",
        borrower_overrides={"legal_name": "Lakewood Senior Living", "tax_id": "12-0000001",
                            "naics_code": "623110", "internal_risk_rating": 7,
                            "guarantor_name": "P Guarantor",
                            "guarantor_net_worth_cents": 20000000},
        loan_overrides={"loan_number": "LN-1212", "original_principal_cents": 40000000,
                        "contractual_rate_bps": 1025, "days_past_due": 75},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "Guarantor path",
                        "target_resolution_date": "2027-01-10T00:00:00Z", "milestone_count": 1},
    )
    loan, case = ctx["loan"], ctx["case"]
    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=1000000, reason_code="CONFIRMED_LOSS"),
        make_loan_accounting_headers("acct-13")))
    referral = get_success_data(api_client.create_legal_referral(
        loan["id"], case["id"],
        create_legal_referral_payload(referral_kind="GUARANTOR_PURSUITS",
                                      target_guarantor_name="P Guarantor",
                                      demand_amount_cents=5000000,
                                      statute_deadline=statute_deadline,
                                      decision_rationale=""),
        ctx["officer_h"]))
    set_clock(clock_at_acceptance)
    ctx["referral"] = referral
    ctx["counsel_h"] = make_legal_counsel_headers("counsel-13")
    return ctx


def test_statute_deadline_equal_to_clock_blocks_acceptance(api):
    """PRD §3.7: "Counsel accepts it — requiring `PENDING_COUNSEL` (else
    `ERR_REFERRAL_NOT_PENDING`) — and at acceptance the statute deadline is
    re-checked against the logical clock: a deadline that is no longer strictly in
    the future means the limitations window has closed and acceptance fails with
    `ERR_STATUTE_EXPIRED` (HTTP 422)."
    PRD §2.5: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and
    before any explicit set operation the clock continues to read that default — it
    never silently falls back to wall-clock time."

    Design: Difficulty/boundary_precision_check/statute_deadline_zero_days_remaining_blocks_accept
    """
    # Deadline 2026-08-02T00:00:00Z is strictly after the default clock at creation;
    # the clock then advances to exactly the deadline, so at acceptance the deadline
    # is no longer strictly in the future — 'strictly after' fails at equality.
    ctx = _setup_referral_at_statute_boundary(
        statute_deadline="2026-08-02T00:00:00Z",
        clock_at_acceptance="2026-08-02T00:00:00Z")
    loan, case = ctx["loan"], ctx["case"]
    res = api_client.accept_referral(
        loan["id"], case["id"], ctx["referral"]["id"], ctx["counsel_h"])
    validate_error(res, ApiErrorId.ERR_STATUTE_EXPIRED.value, expected_status=422)


def test_statute_deadline_one_second_after_clock_accepted(api):
    """PRD §3.7: "A referral carries a `referral_kind` of `GUARANTOR_PURSUITS`,
    `FORECLOSURE`, `DEED_IN_LIEU`, or `NOTE_SALE_PREP`; a `statute_deadline` that
    must lie strictly after the current logical clock time; and, for guarantor
    pursuits, a non-empty `target_guarantor_name` (the field defaults to an empty
    string and is ignored for the other kinds)."
    PRD §3.7: "Counsel accepts it — requiring `PENDING_COUNSEL` (else
    `ERR_REFERRAL_NOT_PENDING`) — and at acceptance the statute deadline is
    re-checked against the logical clock: a deadline that is no longer strictly in
    the future means the limitations window has closed and acceptance fails with
    `ERR_STATUTE_EXPIRED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/statute_deadline_zero_days_remaining_blocks_accept
    """
    # Deadline one second past the acceptance-time clock: strictly after holds.
    ctx = _setup_referral_at_statute_boundary(
        statute_deadline="2026-08-02T00:00:01Z",
        clock_at_acceptance="2026-08-02T00:00:00Z")
    loan, case = ctx["loan"], ctx["case"]
    accepted = validate_success(api_client.accept_referral(
        loan["id"], case["id"], ctx["referral"]["id"], ctx["counsel_h"]), 200)
    assert accepted["status"] == "ACTIVE"
