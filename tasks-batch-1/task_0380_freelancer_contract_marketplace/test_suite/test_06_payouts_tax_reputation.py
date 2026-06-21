"""Payout settlement, the dual-basis 1099 tax record, the $600 reporting boundary,
reputation recomputation, and ranked-proposal ordering.

Queue A: dual_variant_calc / dual_variant_tax_record_gross_vs_net_basis;
         boundary_precision_check / boundary_1099_threshold_inclusive.
Queue B: error_tax_id_missing_on_settle; reputation_score_completed_with_review;
         ranked_proposals_tiebreak_created_at; review_on_noncompleted_contract_rejected.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_tax_record_payload, create_review_payload,
    create_job_posting_payload, create_proposal_payload,
    assert_tax_record,
    make_client_headers, make_freelancer_headers, make_admin_headers,
    create_client, create_freelancer,
    setup_paid_payout, setup_released_milestone, milestone_payout,
    setup_completed_contract,
)


def _freelancer_with_one_paid_payout(api, gross_cents):
    """Active FIXED contract -> release a `gross_cents` milestone -> settle (PAID).
    Returns (ctx, milestone, payout). tax_id_on_file is true so the payout becomes PAID."""
    ctx, m, payout = setup_paid_payout(amount_cents=gross_cents, tax_id_on_file=True,
                                       budget_cents=gross_cents + 20000,
                                       deposit_cents=gross_cents + 20000)
    assert payout["status"] == "PAID"
    return ctx, m, payout


# ─── Dual-basis 1099 ──────────────────────────────────────────────────
def test_tax_record_gross_basis_total(api):
    """PRD §3.9: "Under the default gross basis — the IRS 1099-NEC convention — the
    reportable_gross_cents is the sum of gross_cents over the freelancer's payouts that are
    PAID in that tax_year."
    PRD §3.9: "The form_status is GENERATED when the record is reportable and BELOW_THRESHOLD
    otherwise."

    One PAID payout of gross 60000 -> GROSS_BASIS reportable_gross_cents == 60000, reportable.

    Design: Difficulty/dual_variant_calc/dual_variant_tax_record_gross_vs_net_basis
    """
    ctx, m, payout = _freelancer_with_one_paid_payout(api, 60000)
    assert payout["gross_cents"] == 60000
    res = api.create_tax_record(
        create_tax_record_payload(ctx["freelancer"]["id"], 2026, basis="GROSS_BASIS"),
        make_admin_headers())
    record = validate_success(res, 201)
    assert_tax_record(record)
    assert record["reportable_gross_cents"] == 60000
    assert record["is_reportable"] is True
    assert record["form_status"] == "GENERATED"


def test_tax_record_net_basis_total(api):
    """PRD §3.9: "Under the net basis, used for the platform's internal statement, it is
    instead the sum of net_cents over those same paid payouts."
    PRD §3.9: "The record's is_reportable flag is true when reportable_gross_cents is at
    least the reporting threshold of sixty thousand cents — six hundred dollars — using an
    inclusive comparison, and false below it."

    Same single PAID payout (gross 60000, fee 12000, net 48000) -> NET_BASIS
    reportable_gross_cents == 48000, below threshold, BELOW_THRESHOLD.

    Design: Difficulty/dual_variant_calc/dual_variant_tax_record_gross_vs_net_basis
    """
    ctx, m, payout = _freelancer_with_one_paid_payout(api, 60000)
    # TIER_A 0.20 on gross 60000 -> fee 12000, net 48000.
    assert payout["platform_fee_cents"] == 12000
    assert payout["net_cents"] == 48000
    res = api.create_tax_record(
        create_tax_record_payload(ctx["freelancer"]["id"], 2026, basis="NET_BASIS"),
        make_admin_headers())
    record = validate_success(res, 201)
    assert record["reportable_gross_cents"] == 48000
    assert record["is_reportable"] is False
    assert record["form_status"] == "BELOW_THRESHOLD"


# ─── 1099 threshold inclusivity ───────────────────────────────────────
def test_1099_threshold_inclusive_at_exactly_60000(api):
    """PRD §3.9: "The record's is_reportable flag is true when reportable_gross_cents is at
    least the reporting threshold of sixty thousand cents — six hundred dollars — using an
    inclusive comparison".

    A gross of exactly 60000 (== threshold) is reportable.

    Design: Difficulty/boundary_precision_check/boundary_1099_threshold_inclusive
    """
    ctx, m, payout = _freelancer_with_one_paid_payout(api, 60000)
    res = api.create_tax_record(
        create_tax_record_payload(ctx["freelancer"]["id"], 2026, basis="GROSS_BASIS"),
        make_admin_headers())
    record = validate_success(res, 201)
    assert record["reportable_gross_cents"] == 60000
    assert record["is_reportable"] is True
    assert record["form_status"] == "GENERATED"


def test_1099_below_threshold_not_reportable(api):
    """PRD §3.9: the is_reportable flag is "false below it" — i.e. a reportable_gross_cents
    strictly below 60000 cents is not reportable and the form_status is BELOW_THRESHOLD.

    A single PAID gross of 50000 (< 60000) is below the threshold.

    Design: Difficulty/boundary_precision_check/boundary_1099_threshold_inclusive
    """
    ctx, m, payout = _freelancer_with_one_paid_payout(api, 50000)
    res = api.create_tax_record(
        create_tax_record_payload(ctx["freelancer"]["id"], 2026, basis="GROSS_BASIS"),
        make_admin_headers())
    record = validate_success(res, 201)
    assert record["reportable_gross_cents"] == 50000
    assert record["is_reportable"] is False
    assert record["form_status"] == "BELOW_THRESHOLD"


# ─── Corner: settle blocked for missing tax id ────────────────────────
def test_settle_held_no_tax_id_when_missing(api):
    """PRD §3.6: "Settling a PENDING payout when tax_id_on_file is false instead moves the
    payout to HELD_NO_TAX_ID and makes no lifetime update: the settlement was attempted but
    blocked for missing tax identity."

    Design: Corner/errors/error_tax_id_missing_on_settle
    """
    ctx, m = setup_released_milestone(amount_cents=20000, tax_id_on_file=False,
                                      budget_cents=30000, deposit_cents=20000)
    payout = milestone_payout(m["id"])
    settled = validate_success(api.settle_payout(payout["id"], make_admin_headers()), 200)
    assert settled["status"] == "HELD_NO_TAX_ID"
    freelancer = validate_success(api.get_freelancer(ctx["freelancer"]["id"], make_admin_headers()), 200)
    assert freelancer["lifetime_earnings_cents"] == 0


# ─── Corner: reputation after completed contract + review ─────────────
def test_reputation_score_completed_with_review(api):
    """PRD §3.1: "A raw figure is formed as the completion rate weighted at six tenths plus
    the rating factor weighted at four tenths."
    PRD §3.8: "When the author role is CLIENT, the freelancer's reputation is recomputed,
    since only client-authored ratings feed the reputation average."

    One COMPLETED contract (C=1, L=0) + one CLIENT review of 5: completion_rate=1,
    rating_factor=5/5=1, raw=0.6+0.4=1.0, penalty=0, score = round(100, 2) = 100.0.

    Design: Corner/calculations/reputation_score_completed_with_review
    """
    ctx, m, contract = setup_completed_contract(amount_cents=20000, tax_id_on_file=True,
                                                budget_cents=30000, deposit_cents=20000)
    validate_success(api.create_review(
        create_review_payload(contract["id"], "CLIENT", rating=5, comment="great"),
        ctx["client_headers"]), 201)
    freelancer = validate_success(api.get_freelancer(ctx["freelancer"]["id"], make_admin_headers()), 200)
    assert freelancer["completed_contract_count"] == 1
    assert freelancer["reputation_score"] == 100.0


# ─── Corner: ranked proposals tie-break ───────────────────────────────
def test_ranked_proposals_tiebreak_created_at(api):
    """PRD §3.2: "Candidates are ranked from highest match to lowest, the match figure being
    computed to four decimal places for ordering, and ties are broken by created_at
    ascending — never by id."

    Two identical proposals (same skills/reputation/bid) tie on score; the earlier-created
    proposal ranks first.

    Design: Corner/calculations/ranked_proposals_tiebreak_created_at
    """
    client = create_client()
    ch = make_client_headers(client["id"])
    f1 = create_freelancer(skills=["x"])
    f2 = create_freelancer(skills=["x"])
    posting = validate_success(api.create_job_posting(
        create_job_posting_payload(client["id"], required_skills=["x"]), ch), 201)
    p1 = validate_success(api.create_proposal(
        create_proposal_payload(posting["id"], f1["id"], bid_amount_cents=20000),
        make_freelancer_headers(f1["id"])), 201)
    p2 = validate_success(api.create_proposal(
        create_proposal_payload(posting["id"], f2["id"], bid_amount_cents=20000),
        make_freelancer_headers(f2["id"])), 201)
    data, _ = validate_paginated(api.ranked_proposals(posting["id"], ch))
    ids = [row["id"] for row in data]
    assert p1["id"] in ids and p2["id"] in ids
    assert ids[0] == p1["id"]


# ─── Corner: review on non-completed contract ─────────────────────────
def test_review_on_noncompleted_contract_rejected(api):
    """PRD §3.8: "A review may only be left on a contract that is COMPLETED; an attempt to
    review a contract in any other state is rejected with ERR_REVIEW_CONTRACT_NOT_COMPLETED."

    Design: Corner/validations/review_on_noncompleted_contract_rejected
    """
    from test_helpers import create_active_contract
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=20000,
                                 budget_cents=30000, deposit_cents=0, tax_id_on_file=True)
    res = api.create_review(
        create_review_payload(ctx["contract"]["id"], "CLIENT", rating=4, comment="early"),
        ctx["client_headers"])
    validate_error(res, "ERR_REVIEW_CONTRACT_NOT_COMPLETED", expected_status=409)
