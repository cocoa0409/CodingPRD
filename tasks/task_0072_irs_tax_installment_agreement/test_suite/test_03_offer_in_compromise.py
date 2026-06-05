"""Offer in Compromise lifecycle: begin-evaluation, accept cascade, reject
compensation, RCP boundary, segregation of duties, and OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_revenue_officer_headers,
    make_case_reviewer_headers,
    setup_account_with_recomputed_period,
    setup_account_with_period_no_recompute,
    setup_offer_in_evaluating,
    setup_approved_agreement,
    submit_offer,
    begin_evaluation,
    propose_agreement,
    approve_agreement,
    post_payment,
    get_account_version,
)

OFFICER = TEST_USERS["revenue_officer_headers"]
REVIEWER = TEST_USERS["case_reviewer_headers"]


def test_oic_reject_from_evaluating_no_payment(api):
    """PRD §3.9: "A CaseReviewer may instead reject an evaluating offer, advancing it
    EVALUATING → REJECTED ... Rejection is compensating: it closes all open CSED
    suspension intervals ... recomputes the account's collection_status to
    ACTIVE_COLLECTION".

    Design: Difficulty/non_linear_state_machine/oic_branching_evaluating_to_reject_with_compensation
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000)
    rejected = validate_success(api.reject_offer(offer["id"], REVIEWER), 200)
    assert rejected["status"] == "REJECTED", rejected

    acct_after = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert acct_after["collection_status"] == "ACTIVE_COLLECTION", acct_after

    data, meta = _list_payments(api, acct["id"])
    assert not any(p["payment_source"] == "OIC_LUMP_SUM" for p in data), data


def test_oic_accept_depth3_cascade(api):
    """PRD §3.9: "On acceptance, a depth-three cascade fires ... every non-SATISFIED
    period on the account is set to ABATED with its balance_due_cents zeroed ... the
    account's collection_status is recomputed to RESOLVED and total_balance_cents to
    zero ... and because the account balance reaches zero, any APPROVED agreement
    auto-closes per §3.5."

    Design: Difficulty/transitive_cascade/oic_accept_depth3_payment_abate_account_resolve_agreement_close
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    # An APPROVED MANUAL agreement so there is something to auto-close.
    agr = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6)
    approved = approve_agreement(acct["id"], agr["id"])

    # OIC by a DIFFERENT officer, moved to EVALUATING.
    offer = submit_offer(acct["id"], 18500000, net_realizable_equity_cents=500000,
                         submitter_user_id="officer-submitter")
    offer = begin_evaluation(offer["id"], reviewer_user_id="reviewer-evaluator")

    v = get_account_version(acct["id"])
    accepted = validate_success(api.accept_offer(
        offer["id"], {"expected_tax_account_version": v},
        make_case_reviewer_headers("reviewer-acceptor")), 200)
    assert accepted["status"] == "ACCEPTED", accepted

    # NOTE: §3.9 sequences "a Payment of offer_amount_cents ... allocated oldest-first;
    # every non-SATISFIED period ... set to ABATED". Because offer_amount exceeds the
    # balance, the oldest-first allocation zeroes the period; whether that zeroed period
    # then reads SATISFIED (the §3.8 payment cascade fired) or ABATED (the abatement step
    # claimed it) is not uniquely determined by the prose. Assert only the uniquely
    # derivable residual (balance zero).
    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["balance_due_cents"] == 0, p

    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["total_balance_cents"] == 0, a
    assert a["collection_status"] == "RESOLVED", a

    closed = validate_success(api.get_agreement(approved["id"], OFFICER), 200)
    assert closed["status"] == "CLOSED", closed


def test_oic_accept_state_check_masks_below_rcp(api):
    """PRD §3.9: "Its checks: the offer must be EVALUATING (else ERR_INVALID_STATE);
    the accepting reviewer's X-User-ID must differ from the recorded
    submitted_by_user_id ... the offer_amount_cents must be at least the computed
    rcp_cents (else ERR_OFFER_BELOW_RCP)".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_oic_accept
    """
    # Offer left in SUBMITTED (no begin-evaluation) and far below any RCP.
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    offer = submit_offer(acct["id"], 100, net_realizable_equity_cents=500000,
                         submitter_user_id="officer-sub-50")
    v = get_account_version(acct["id"])
    res = api.accept_offer(offer["id"], {"expected_tax_account_version": v},
                           make_case_reviewer_headers("reviewer-acc-50"))
    validate_error(res, "ERR_INVALID_STATE")


def test_oic_offer_equals_rcp_accepts_boundary(api):
    """PRD §3.9: "the offer_amount_cents must be at least the computed rcp_cents (else
    ERR_OFFER_BELOW_RCP)".

    Design: Difficulty/boundary_precision_check/oic_offer_equals_rcp_accepts_boundary
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000,
        submitter_user_id="officer-sub-60", reviewer_user_id="reviewer-eval-60")
    assert offer["rcp_cents"] == 18500000, offer
    v = get_account_version(acct["id"])
    accepted = validate_success(api.accept_offer(
        offer["id"], {"expected_tax_account_version": v},
        make_case_reviewer_headers("reviewer-acc-60")), 200)
    assert accepted["status"] == "ACCEPTED", accepted


def test_oic_offer_below_rcp_rejected(api):
    """PRD §3.9: "the offer_amount_cents must be at least the computed rcp_cents (else
    ERR_OFFER_BELOW_RCP)".

    Design: Corner/calculations/offer_below_rcp_rejected_on_accept
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18499999, net_realizable_equity_cents=500000,
        submitter_user_id="officer-sub-42", reviewer_user_id="reviewer-eval-42")
    assert offer["rcp_cents"] == 18500000, offer
    v = get_account_version(acct["id"])
    res = api.accept_offer(offer["id"], {"expected_tax_account_version": v},
                           make_case_reviewer_headers("reviewer-acc-42"))
    validate_error(res, "ERR_OFFER_BELOW_RCP")


def test_oic_accept_segregation_of_duties(api):
    """PRD §3.9: "the accepting reviewer's X-User-ID must differ from the recorded
    submitted_by_user_id, enforcing segregation of duties (else
    ERR_SEGREGATION_OF_DUTIES)".

    Design: Corner/validations/oic_accept_same_user_segregation_violation
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000,
        submitter_user_id="same-user-54", reviewer_user_id="same-user-54")
    v = get_account_version(acct["id"])
    res = api.accept_offer(offer["id"], {"expected_tax_account_version": v},
                           make_case_reviewer_headers("same-user-54"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_balance_conservation_payment_then_oic_abatement(api):
    """PRD §3.8: "For each target period in order, the system applies the smaller of
    the remaining amount and that period's balance_due_cents".
    PRD §3.9: "every non-SATISFIED period on the account is set to ABATED with its
    balance_due_cents zeroed ... the account's collection_status is recomputed to
    RESOLVED and total_balance_cents to zero".

    Design: Difficulty/compensating_invariant/balance_conservation_on_payment_then_oic_abatement
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    post_payment(acct["id"], 300000, payment_source="MANUAL", tax_period_id=period["id"])

    offer = submit_offer(acct["id"], 18500000, net_realizable_equity_cents=500000,
                         submitter_user_id="officer-sub-91")
    offer = begin_evaluation(offer["id"], reviewer_user_id="reviewer-eval-91")

    before = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert before["total_balance_cents"] == 733000, before

    v = get_account_version(acct["id"])
    validate_success(api.accept_offer(
        offer["id"], {"expected_tax_account_version": v},
        make_case_reviewer_headers("reviewer-acc-91")), 200)

    after = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert after["total_balance_cents"] == 0, after
    # §3.9's "non-SATISFIED period -> ABATED" does not uniquely determine the period's
    # terminal status here: the oldest-first OIC payment (offer_amount >> residual) zeroes
    # the period, and whether it reads SATISFIED (the §3.8 payment cascade) or ABATED (the
    # abatement step) is ambiguous in the prose. Assert only the conserved residual.
    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["balance_due_cents"] == 0, p


def test_occ_correct_version_on_oic_accept_succeeds(api):
    """PRD §2.6: "An accept request must likewise carry expected_tax_account_version
    matching the account's current version."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_oic_accept_succeeds
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000,
        submitter_user_id="officer-sub-81", reviewer_user_id="reviewer-eval-81")
    v = get_account_version(acct["id"])
    accepted = validate_success(api.accept_offer(
        offer["id"], {"expected_tax_account_version": v},
        make_case_reviewer_headers("reviewer-acc-81")), 200)
    assert accepted["status"] == "ACCEPTED", accepted
    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["collection_status"] == "RESOLVED", a


def test_oic_reject_closes_suspensions_protection_drops(api):
    """PRD §3.9: "Rejection is compensating: it closes all open CSED suspension
    intervals (appending CSED_SUSPEND_END, extending each csed_date, and decrementing
    csed_protection_count)".

    Design: Difficulty/non_linear_state_machine/oic_branching_evaluating_to_reject_with_compensation
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000)
    # begin-evaluation opened a suspension -> protection count > 0
    before = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert before["csed_protection_count"] >= 1, before
    validate_success(api.reject_offer(offer["id"], REVIEWER), 200)
    after = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert after["csed_protection_count"] == 0, after


def test_oic_accept_posts_lump_sum_payment(api):
    """PRD §3.9: "a Payment of offer_amount_cents with payment_source of OIC_LUMP_SUM
    is created and allocated oldest-first".

    Design: Difficulty/transitive_cascade/oic_accept_depth3_payment_abate_account_resolve_agreement_close
    """
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500000, net_realizable_equity_cents=500000,
        submitter_user_id="officer-sub-acc2", reviewer_user_id="reviewer-eval-acc2",
        recompute=True)
    v = get_account_version(acct["id"])
    validate_success(api.accept_offer(
        offer["id"], {"expected_tax_account_version": v},
        make_case_reviewer_headers("reviewer-acc-acc2")), 200)
    data, meta = _list_payments(api, acct["id"])
    assert any(p["payment_source"] == "OIC_LUMP_SUM" for p in data), data


def test_oic_accept_against_submitted_offer_invalid_state(api):
    """PRD §3.9: "the offer must be EVALUATING (else ERR_INVALID_STATE)".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_oic_accept
    """
    # Offer in SUBMITTED, offer >= any plausible RCP so the only failing check is state.
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    offer = submit_offer(acct["id"], 99000000, net_realizable_equity_cents=500000,
                         submitter_user_id="officer-sub-state2")
    v = get_account_version(acct["id"])
    res = api.accept_offer(offer["id"], {"expected_tax_account_version": v},
                           make_case_reviewer_headers("reviewer-acc-state2"))
    validate_error(res, "ERR_INVALID_STATE")


def test_oic_accept_above_rcp_succeeds_boundary(api):
    """PRD §3.9: "the offer_amount_cents must be at least the computed rcp_cents (else
    ERR_OFFER_BELOW_RCP)".

    Design: Difficulty/boundary_precision_check/oic_offer_equals_rcp_accepts_boundary
    """
    # offer one cent above RCP — the inclusive >= boundary still accepts.
    acct, period, offer = setup_offer_in_evaluating(
        offer_amount_cents=18500001, net_realizable_equity_cents=500000,
        submitter_user_id="officer-sub-bnd2", reviewer_user_id="reviewer-eval-bnd2")
    assert offer["rcp_cents"] == 18500000, offer
    v = get_account_version(acct["id"])
    accepted = validate_success(api.accept_offer(
        offer["id"], {"expected_tax_account_version": v},
        make_case_reviewer_headers("reviewer-acc-bnd2")), 200)
    assert accepted["status"] == "ACCEPTED", accepted


def test_balance_conservation_partial_payment_reduces_total(api):
    """PRD §3.8: "reducing balance_due_cents by the applied amount".
    PRD §3.6: "An account's total_balance_cents is the sum of balance_due_cents across
    only those periods whose period_status is ASSESSED or IN_COLLECTION".

    Design: Difficulty/compensating_invariant/balance_conservation_on_payment_then_oic_abatement
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    before = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert before["total_balance_cents"] == 1033000, before
    post_payment(acct["id"], 300000, payment_source="MANUAL", tax_period_id=period["id"])
    after = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert after["total_balance_cents"] == 733000, after


def _list_payments(api, account_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_payments(OFFICER, params={"tax_account_id": account_id}))
