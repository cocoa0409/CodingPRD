"""Bid evaluation: record-evaluation, final_score variants (LOWEST_PRICE
and COMPREHENSIVE_SCORING). Covers PRD §3.8.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    decide_award,
    evaluate_all_bids,
    finalize_committee,
    make_expert_headers,
    record_evaluation,
    record_evaluation_payload,
    setup_awarded,
    setup_evaluating,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# LOWEST_PRICE: final_score == bid_price_cents
# ===========================================================================
def test_lowest_price_final_score_equals_bid_price(api, officer_headers):
    """PRD §3.8: "Under LOWEST_PRICE, final_score is set equal to the
    bid's bid_price_cents (an integer); smaller is better, and ties
    are broken by the earliest created_at of the candidate bids."
    """
    bid_specs = [
        {"price": 8_000_000, "technical_score_raw": 90,
         "qualifications": ["Q1", "Q2"]},
        {"price": 10_000_000, "technical_score_raw": 85,
         "qualifications": ["Q1", "Q2"]},
        {"price": 7_000_000, "technical_score_raw": 95,
         "qualifications": ["Q1", "Q2"]},
    ]
    ctx = setup_evaluating(
        evaluation_method="LOWEST_PRICE",
        required_qualifications=["Q1", "Q2"],
        bid_specs=bid_specs,
    )
    evaluated = evaluate_all_bids(ctx)
    # Each bid's final_score must equal its bid_price_cents.
    for b in evaluated:
        assert b["final_score"] == b["bid_price_cents"], (
            f"LOWEST_PRICE final_score must equal bid_price_cents; "
            f"got final_score={b['final_score']} for "
            f"bid_price_cents={b['bid_price_cents']}"
        )


def test_lowest_price_decide_award_picks_minimum_price_bid(api, officer_headers):
    """PRD §3.8: "smaller is better, and ties are broken by the
    earliest created_at of the candidate bids."
    PRD §3.9: "An Award record is created in DECIDED status with
    winning_bid_id set to the bid selected by the evaluation method's
    tie-break rules from §3.8."
    """
    bid_specs = [
        {"price": 8_000_000, "technical_score_raw": 90,
         "qualifications": ["Q1", "Q2"]},
        {"price": 10_000_000, "technical_score_raw": 85,
         "qualifications": ["Q1", "Q2"]},
        {"price": 7_000_000, "technical_score_raw": 95,
         "qualifications": ["Q1", "Q2"]},
    ]
    ctx = setup_awarded(
        evaluation_method="LOWEST_PRICE",
        required_qualifications=["Q1", "Q2"],
        bid_specs=bid_specs,
    )
    # Winner must be the 7_000_000 bid.
    award = ctx["award"]
    winning_bid = next(
        b for b in ctx["bids"] if b["id"] == award["winning_bid_id"]
    )
    assert winning_bid["bid_price_cents"] == 7_000_000
    assert award["award_amount_cents"] == 7_000_000


# ===========================================================================
# COMPREHENSIVE_SCORING: weighted three-component formula
# ===========================================================================
def test_comprehensive_scoring_award_picks_highest_final_score(api):
    """PRD §3.8: "Higher final_score is better under comprehensive
    scoring; ties are broken by the smaller bid_price_cents first and
    then by the earliest created_at."

    Build inputs from the difficulty-design fixture
    bid_score_lowest_vs_comprehensive: weights {price:0.40, technical:0.40,
    qualification:0.20}, bidder qualification mixes selected so the
    winning bidder differs from the lowest-price bidder.
    """
    # Three suppliers: SA(Q1,Q2), SB(Q1,Q2), SC(Q1). Required quals = [Q1,Q2].
    # SC will fail the qualifications subset rule, so configure all to
    # carry both quals for a fair comparison and rely on technical score
    # divergence to drive the win.
    bid_specs = [
        {"price": 8_000_000, "technical_score_raw": 90,
         "qualifications": ["Q1", "Q2"]},  # SA
        {"price": 10_000_000, "technical_score_raw": 85,
         "qualifications": ["Q1", "Q2"]},  # SB
        {"price": 7_000_000, "technical_score_raw": 60,
         "qualifications": ["Q1", "Q2"]},  # SC — cheap but weak technical
    ]
    ctx = setup_awarded(
        evaluation_method="COMPREHENSIVE_SCORING",
        required_qualifications=["Q1", "Q2"],
        bid_specs=bid_specs,
        weights={"price": 0.40, "technical": 0.40, "qualification": 0.20},
        max_technical_score=100,
    )
    award = ctx["award"]
    # The winner under COMPREHENSIVE_SCORING is whichever has the
    # highest final_score. We do not pin SA-specifically here (that's
    # the difficulty-design test_12). We do assert the winner is NOT
    # the lowest-price bid SC, because SC's technical score is so low
    # that the price advantage cannot make up the gap.
    winning_bid = next(
        b for b in ctx["bids"] if b["id"] == award["winning_bid_id"]
    )
    assert winning_bid["bid_price_cents"] != 7_000_000, (
        "COMPREHENSIVE_SCORING should not pick a low technical bid "
        "purely on price"
    )


def test_comprehensive_scoring_final_score_at_two_decimal_places(api):
    """PRD §3.8: "with the resulting sum then rounded once more to two
    decimal places using round-half-up." Confirm the returned
    final_score has at most two decimal places.
    """
    bid_specs = [
        {"price": 9_000_000, "technical_score_raw": 70,
         "qualifications": ["Q1", "Q2"]},
        {"price": 8_000_000, "technical_score_raw": 80,
         "qualifications": ["Q1", "Q2"]},
        {"price": 7_500_000, "technical_score_raw": 90,
         "qualifications": ["Q1", "Q2"]},
    ]
    ctx = setup_evaluating(
        evaluation_method="COMPREHENSIVE_SCORING",
        required_qualifications=["Q1", "Q2"],
        bid_specs=bid_specs,
        weights={"price": 0.40, "technical": 0.40, "qualification": 0.20},
        max_technical_score=100,
    )
    evaluated = evaluate_all_bids(ctx)
    for b in evaluated:
        fs = b["final_score"]
        # Quantize to 2 decimals and confirm equality.
        assert abs(round(fs, 2) - fs) < 1e-9, (
            f"final_score must be rounded to 2dp; got {fs!r}"
        )


# ===========================================================================
# Bid already evaluated (concurrency rule + state machine)
# ===========================================================================
def test_second_evaluation_on_same_bid_rejected(api):
    """PRD §3.8: "Two evaluation experts who race to record a score for
    the same bid serialise on the bid's compare-and-swap from OPENED
    to EVALUATED. Exactly one wins; the loser receives
    ERR_BID_ALREADY_EVALUATED."
    """
    ctx = setup_evaluating()
    expert_id = ctx["committee"]["members"][0]["expert_id"]
    bid = ctx["bids"][0]
    record_evaluation(bid["id"], expert_id)
    # Second attempt.
    res = api.record_evaluation(
        bid["id"], record_evaluation_payload(),
        make_expert_headers(expert_id),
    )
    validate_error(res, "ERR_BID_ALREADY_EVALUATED")


# ===========================================================================
# Finalisation precondition
# ===========================================================================
def test_finalize_committee_before_all_bids_evaluated_rejected(api, officer_headers):
    """PRD §3.8: "The committee is then finalised, transitioning
    EVALUATING → FINALIZED, only when every bid on the project whose
    bid_status is in OPENED or EVALUATED has reached EVALUATED."
    """
    ctx = setup_evaluating()
    expert_id = ctx["committee"]["members"][0]["expert_id"]
    # Only evaluate first bid.
    record_evaluation(ctx["bids"][0]["id"], expert_id)
    res = api.finalize_committee(ctx["committee"]["id"], officer_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_finalize_committee_after_all_evaluated_succeeds(api, officer_headers):
    """PRD §3.8: same precondition; positive path."""
    ctx = setup_evaluating()
    evaluate_all_bids(ctx)
    res = api.finalize_committee(ctx["committee"]["id"], officer_headers)
    data = validate_success(res)
    assert data["committee_status"] == "FINALIZED"


# ===========================================================================
# Decide-award side effects
# ===========================================================================
def test_decide_award_sets_winning_bid_awarded_others_lost(api, officer_headers):
    """PRD §3.9: "As side effects, the winning bid moves to AWARDED and
    every other EVALUATED bid moves to LOST."
    """
    bid_specs = [
        {"price": 8_000_000, "technical_score_raw": 90,
         "qualifications": ["Q1", "Q2"]},
        {"price": 10_000_000, "technical_score_raw": 85,
         "qualifications": ["Q1", "Q2"]},
        {"price": 7_000_000, "technical_score_raw": 95,
         "qualifications": ["Q1", "Q2"]},
    ]
    ctx = setup_awarded(
        evaluation_method="LOWEST_PRICE",
        required_qualifications=["Q1", "Q2"],
        bid_specs=bid_specs,
    )
    listed = api.list_project_bids(
        ctx["project"]["id"], officer_headers, params={"limit": 100},
    )
    bids, _ = validate_paginated(listed)
    awarded = [b for b in bids if b["bid_status"] == "AWARDED"]
    lost = [b for b in bids if b["bid_status"] == "LOST"]
    assert len(awarded) == 1
    assert awarded[0]["id"] == ctx["award"]["winning_bid_id"]
    assert len(lost) == 2
