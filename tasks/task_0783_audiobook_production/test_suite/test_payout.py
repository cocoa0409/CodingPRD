"""Narrator compensation across deal models and the payout ledger invariant."""
from test_helpers import (
    validate_success, admin_headers,
    setup_submitted_full_milestone, setup_provisional_statement,
    qc_pass, finalize_statement, pay_statement,
)

_DIVERGENCE_SALES = [
    {"units_sold": 100, "units_returned": 10, "unit_price_cents": 1500, "occurred_at": "2026-03-15T00:00:00Z"},
    {"units_sold": 50, "units_returned": 0, "unit_price_cents": 2000, "occurred_at": "2026-03-16T00:00:00Z"},
]


def test_per_hour_narrator_credited_flat_fee_at_approval(api):
    """PRD §3.8: "the fee is the title's `finished_hours` multiplied by the
    contract's `per_hour_rate_cents`, rounded half up to whole cents, and it is
    credited to the narrator's `payout_balance_cents` at that approval moment."

    Design: Difficulty/dual_variant_calc/narrator_comp_per_hour_vs_royalty_share
    """
    ctx = setup_submitted_full_milestone(
        api, finished_hours=8.5, deal_type="PER_HOUR", per_hour_rate_cents=25000
    )
    qc_pass(api, ctx["milestone"]["id"])
    narrator = validate_success(api.get_narrator(ctx["narrator"]["id"], admin_headers()), 200)
    assert narrator["payout_balance_cents"] == 212500


def test_per_hour_full_approval_copies_finished_hours(api):
    """PRD §3.5: "A `PASS` moves the milestone `SUBMITTED → APPROVED` and bumps
    the milestone's version. When the approved milestone is a `FULL` deliverable,
    its declared `finished_hours` is copied onto the title's `finished_hours`".

    Design: Difficulty/dual_variant_calc/narrator_comp_per_hour_vs_royalty_share
    """
    ctx = setup_submitted_full_milestone(
        api, finished_hours=8.5, deal_type="PER_HOUR", per_hour_rate_cents=25000
    )
    qc_pass(api, ctx["milestone"]["id"])
    milestone = validate_success(api.get_milestone(ctx["milestone"]["id"], admin_headers()), 200)
    assert milestone["status"] == "APPROVED"
    title = validate_success(api.get_title(ctx["title"]["id"], admin_headers()), 200)
    assert title["finished_hours"] == 8.5


def test_pay_credits_author_and_narrator_balances(api):
    """PRD §3.8: "On payment, the author's `payout_balance_cents` is increased by
    that statement's `author_royalty_cents`, and the narrator's
    `payout_balance_cents` is increased by that statement's `narrator_royalty_cents`".

    Design: Difficulty/compensating_invariant/payout_ledger_pay_then_reverse_conserves_money
    """
    ctx = setup_provisional_statement(
        api, sales=_DIVERGENCE_SALES, exclusivity="EXCLUSIVE",
        retailer_cut_pct=0.40, royalty_share_pct=0.40,
    )
    finalize_statement(api, ctx["statement"]["id"])
    pay_statement(api, ctx["statement"]["id"])
    author = validate_success(api.get_author(ctx["author"]["id"], admin_headers()), 200)
    narrator = validate_success(api.get_narrator(ctx["narrator"]["id"], admin_headers()), 200)
    assert author["payout_balance_cents"] == 77550
    assert narrator["payout_balance_cents"] == 63450


def test_reverse_returns_balances_to_zero(api):
    """PRD §3.8: "Reversal debits the author's `payout_balance_cents` by exactly
    the `author_royalty_cents` previously credited and debits the narrator's
    `payout_balance_cents` by exactly the `narrator_royalty_cents` previously
    credited, leaving the total distributed unchanged."

    Design: Difficulty/compensating_invariant/payout_ledger_pay_then_reverse_conserves_money
    """
    ctx = setup_provisional_statement(
        api, sales=_DIVERGENCE_SALES, exclusivity="EXCLUSIVE",
        retailer_cut_pct=0.40, royalty_share_pct=0.40,
    )
    finalize_statement(api, ctx["statement"]["id"])
    pay_statement(api, ctx["statement"]["id"])
    reversed_st = validate_success(api.reverse_statement(ctx["statement"]["id"], admin_headers()), 200)
    assert reversed_st["status"] == "REVERSED"
    author = validate_success(api.get_author(ctx["author"]["id"], admin_headers()), 200)
    narrator = validate_success(api.get_narrator(ctx["narrator"]["id"], admin_headers()), 200)
    assert author["payout_balance_cents"] == 0
    assert narrator["payout_balance_cents"] == 0
