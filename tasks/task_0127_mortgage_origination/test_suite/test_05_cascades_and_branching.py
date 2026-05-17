"""Cascading side effects (PRD §2.6) and branching underwrite-decision
behaviour (PRD §3.8).

Covers difficulty design instances:
- non_linear_state_machine/loan_application_branching_from_underwriting
- transitive_cascade/appraisal_completion_cascades_ltv_and_pmi_depth_2
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_loan_application,
    create_and_pre_qualify,
    get_loan_application,
    get_rate_lock,
    place_rate_lock,
    setup_application_in_conditional_approval,
    setup_application_in_underwriting,
    setup_completed_appraisal_with_value,
    underwrite_approve,
    underwrite_counter_offer,
    underwrite_decision_payload,
    underwrite_deny,
    validate_error,
    validate_success,
)


# ===========================================================================
# Branching from UNDERWRITING — PRD §3.8
# difficulty: non_linear_state_machine/loan_application_branching_from_underwriting
# ===========================================================================
def test_underwrite_approve_advances_to_conditional_approval(
    api, loan_officer_headers,
):
    """PRD §3.8: "The APPROVE branch advances the application to
    CONDITIONAL_APPROVAL."

    Claim: from UNDERWRITING with passing UDAAP + DTI <= 0.43 + LTV <=
    0.97, decision=APPROVE -> CONDITIONAL_APPROVAL.

    # difficulty: non_linear_state_machine/loan_application_branching_from_underwriting
    """
    _, app, _, _ = setup_application_in_conditional_approval()
    # setup_application_in_conditional_approval already runs the
    # APPROVE branch; verify the terminal state of that flow.
    assert app["status"] == "CONDITIONAL_APPROVAL"


def test_underwrite_counter_offer_routes_back_to_pre_qualified(
    api, loan_officer_headers,
):
    """PRD §3.8: "The COUNTER_OFFER branch routes the application back
    to PRE_QUALIFIED so that the borrower can re-engage with revised
    terms. The supplied counter_offered_amount_cents must be strictly
    greater than zero and strictly less than requested_loan_amount_cents
    ... On a successful counter-offer the system stores
    counter_offered_amount_cents on the application and marks the
    latest LOAN_ESTIMATE Disclosure as SUPERSEDED"

    Claim: from UNDERWRITING, decision=COUNTER_OFFER with
    counter_offered_amount_cents=18_000_000 (less than requested
    20_000_000) -> status=PRE_QUALIFIED, counter_offered_amount_cents
    set, latest LE.status=SUPERSEDED.

    # difficulty: non_linear_state_machine/loan_application_branching_from_underwriting
    """
    _, app, _, le = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        requested_loan_amount_cents=20_000_000,
    )
    out = underwrite_counter_offer(
        app["id"], counter_offered_amount_cents=18_000_000,
        headers=loan_officer_headers,
    )
    assert out["status"] == "PRE_QUALIFIED", (
        "PRD §3.8: COUNTER_OFFER routes back to PRE_QUALIFIED"
    )
    assert out.get("counter_offered_amount_cents") == 18_000_000

    # The latest LOAN_ESTIMATE issued before the counter must now be
    # SUPERSEDED.
    le_list_res = api.list_disclosures(
        app["id"], loan_officer_headers, params={"kind": "LOAN_ESTIMATE"},
    )
    rows, _ = (
        (le_list_res.json()["data"], le_list_res.json()["meta"])
        if le_list_res.status_code == 200 else ([], {})
    )
    # Find the LE created by the fixture (latest issued before counter).
    le_after = next((r for r in rows if r["id"] == le["id"]), None)
    assert le_after is not None, (
        "Latest LE must remain retrievable after counter-offer "
        "(PRD §3.8 prose 'marks the latest LOAN_ESTIMATE Disclosure as "
        "SUPERSEDED')."
    )
    assert le_after["status"] == "SUPERSEDED", (
        "PRD §3.8: counter-offer marks the latest LOAN_ESTIMATE as "
        f"SUPERSEDED; got {le_after['status']}."
    )


def test_underwrite_counter_offer_invalid_zero_rejected(
    api, loan_officer_headers,
):
    """PRD §3.8: "The supplied counter_offered_amount_cents must be
    strictly greater than zero and strictly less than
    requested_loan_amount_cents; violations are rejected with
    ERR_INVALID_COUNTER_OFFER."

    Claim: counter_offered_amount_cents=0 -> ERR_INVALID_COUNTER_OFFER.
    """
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        requested_loan_amount_cents=20_000_000,
    )
    res = api.underwrite_decision(
        app["id"],
        underwrite_decision_payload(
            decision="COUNTER_OFFER",
            counter_offered_amount_cents=0,
        ),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_INVALID_COUNTER_OFFER.value,
        expected_status=422,
    )


def test_underwrite_counter_offer_equal_to_requested_rejected(
    api, loan_officer_headers,
):
    """PRD §3.8: "strictly less than requested_loan_amount_cents".

    Claim: counter == requested -> ERR_INVALID_COUNTER_OFFER.
    """
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        requested_loan_amount_cents=20_000_000,
    )
    res = api.underwrite_decision(
        app["id"],
        underwrite_decision_payload(
            decision="COUNTER_OFFER",
            counter_offered_amount_cents=20_000_000,
        ),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_INVALID_COUNTER_OFFER.value,
        expected_status=422,
    )


def test_underwrite_deny_cascades_disclosures_and_rate_lock(
    api, loan_officer_headers,
):
    """PRD §3.8: "The DENY branch advances the application to DENIED.
    It accepts any UDAAP outcome on file (or none) — a denial does not
    depend on a passing UDAAP. The denial cascades: all non-terminal
    Disclosure rows on the application are forced to VOIDED, and any
    RateLock in LOCKED or EXTENDED is cascaded to CANCELLED with the
    full lock_fee_cents plus extension_fee_paid_cents returned in
    refund_cents"

    Claim: place a RateLock before denial; decision=DENY ->
    status=DENIED, LE.status=VOIDED, RateLock.status=CANCELLED with
    refund_cents == lock_fee_cents + extension_fee_paid_cents.

    # difficulty: non_linear_state_machine/loan_application_branching_from_underwriting
    """
    _, app, _, le = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        requested_loan_amount_cents=20_000_000,
    )
    # NOTE: PRD §3.5 places no preclusion on placing a RateLock while
    # the application is UNDERWRITING (only DENIED/WITHDRAWN/CLOSED are
    # explicitly forbidden for extensions).
    rl = place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    lock_fee = rl["lock_fee_cents"]
    ext_fee = rl.get("extension_fee_paid_cents", 0)

    denied = underwrite_deny(app["id"], headers=loan_officer_headers)
    assert denied["status"] == "DENIED"

    rl_after = get_rate_lock(
        app["id"], headers=loan_officer_headers,
    )
    assert rl_after["status"] == "CANCELLED", (
        "PRD §3.8: DENY cascades RateLock to CANCELLED"
    )
    assert rl_after["refund_cents"] == lock_fee + ext_fee, (
        "PRD §3.8: DENY refund must equal lock_fee_cents + "
        "extension_fee_paid_cents (denial is lender's cause; the 48-hr "
        "free-look does not gate this refund). Got "
        f"refund={rl_after['refund_cents']}, lock_fee={lock_fee}, "
        f"ext_fee={ext_fee}."
    )

    # The latest LE must be VOIDED.
    rows = api.list_disclosures(
        app["id"], loan_officer_headers, params={"kind": "LOAN_ESTIMATE"},
    ).json()["data"]
    le_after = next(r for r in rows if r["id"] == le["id"])
    assert le_after["status"] == "VOIDED", (
        "PRD §3.8: DENY forces every non-terminal Disclosure to VOIDED."
    )


# ===========================================================================
# Appraisal completion → LTV → PMI depth-2 cascade — PRD §2.6 + §3.4
# difficulty: transitive_cascade/appraisal_completion_cascades_ltv_and_pmi_depth_2
# ===========================================================================
def test_appraisal_completion_cascades_ltv_and_pmi(
    api, loan_officer_headers,
):
    """PRD §2.6: "When an Appraisal completes and its
    appraised_value_cents is below the application's sale_price_cents,
    the system recomputes ltv_ratio on the parent LoanApplication using
    the lower value-basis, and if the recomputed ltv_ratio is greater
    than 0.80 it sets pmi_required to true on the application. This is
    a transitive cascade: the appraisal's completion triggers an LTV
    recompute, which in turn flips the PMI flag."

    Claim: sale=$400,000, requested=$330,000, appraised=$380,000 (below
    sale) -> after /appraisal/complete, ltv = 330000/380000 = 0.8684,
    pmi_required becomes true.

    # difficulty: transitive_cascade/appraisal_completion_cascades_ltv_and_pmi_depth_2
    """
    _, app, appr = setup_completed_appraisal_with_value(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=33_000_000,
        appraised_value_cents=38_000_000,
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    # Hop 1: LTV recomputed using appraised as the lower value basis.
    assert app["ltv_ratio"] == pytest.approx(0.8684, abs=0.0001), (
        "PRD §2.6 / §3.7: ltv = 33_000_000 / 38_000_000 = 0.8684"
    )
    # Hop 2: pmi_required flipped because ltv > 0.80.
    assert app["pmi_required"] is True, (
        "PRD §2.6: ltv > 0.80 implies pmi_required = true"
    )
    # Appraisal valid_until: report_date + 120 days at 23:59:59.999 UTC.
    assert appr["valid_until"] == "2026-06-29T23:59:59.999Z", (
        "PRD §3.4: valid_until = report_date + 120 calendar days at "
        "23:59:59.999 UTC. Expected 2026-06-29T23:59:59.999Z."
    )


def test_appraisal_completion_no_pmi_when_appraised_above_sale_price(
    api, loan_officer_headers,
):
    """PRD §2.6: "When an Appraisal completes and its
    appraised_value_cents is below the application's sale_price_cents"
    — only the below-sale-price branch triggers the LTV recompute that
    could flip PMI.

    Claim: with appraised > sale_price AND principal/sale_price < 0.80,
    pmi_required stays false. This validates the negative branch.

    Concretely: sale=$400,000, requested=$300,000 (LTV @ sale =
    0.7500), appraised=$420,000 (above sale). The recompute (if it
    happened) would also produce 0.7500 since sale is the lower basis.
    pmi_required must remain false.
    """
    _, app, _ = setup_completed_appraisal_with_value(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=30_000_000,
        appraised_value_cents=42_000_000,
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    assert app["pmi_required"] is False, (
        "PRD §2.6: ltv <= 0.80 must not set pmi_required = true. "
        f"Got pmi_required={app['pmi_required']}."
    )


def test_underwrite_decision_requires_underwriting_state(
    api, loan_officer_headers,
):
    """PRD §2.10 + §3.8: state-machine source check (PRD §2.10:
    "State-machine checks ... precede business-rule checks") applies
    to underwrite-decision; calling it from a non-UNDERWRITING state
    must return ERR_INVALID_STATE.

    Claim: decision=APPROVE on a fresh INTAKE application ->
    ERR_INVALID_STATE (409).
    """
    _, app = create_and_pre_qualify()
    res = api.underwrite_decision(
        app["id"],
        underwrite_decision_payload(decision="APPROVE"),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409,
    )
