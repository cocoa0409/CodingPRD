"""Commission statements: the cash-waterfall commission vs. the billed GROSS commission
divergence, the round-per-line-then-sum total, and finalizing an empty statement."""
from test_helpers import (
    validate_success, validate_error,
    create_carrier, create_commission_statement,
    setup_recovered_with_disbursed_reimbursement,
    setup_two_recovered_claims_same_carrier,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
READER = TEST_USERS["reader_headers"]


def test_accrued_commission_is_waterfall_net_of_deductible(api):
    """PRD §3.6: "From that remainder, `alloc_commission_cents` (bucket two) is the
    carrier's `commission_rate_bps` divided by 10000, multiplied by the remainder,
    rounded half up to whole cents."
    PRD §3.6: "its `accrued_commission_cents` is increased by `alloc_commission_cents`."

    Design: Difficulty/dual_variant_calc/commission_cash_net_vs_billed_gross
    """
    ctx = setup_recovered_with_disbursed_reimbursement(api, commission_basis="GROSS", settled_amount_cents=3_000_000)
    # remainder = 3_000_000 - 500_000 deductible = 2_500_000; 25% => 625_000.
    assert ctx["claim"]["accrued_commission_cents"] == 625_000


def test_billed_gross_commission_diverges_from_cash_commission(api):
    """PRD §3.8: "Under the `GROSS` basis, commission is the carrier's
    `commission_rate_bps` divided by 10000, multiplied by the claim's gross recovery
    `final_recovered_cents`, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/commission_cash_net_vs_billed_gross
    """
    ctx = setup_recovered_with_disbursed_reimbursement(api, commission_basis="GROSS", settled_amount_cents=3_000_000)
    stmt = create_commission_statement(api, ctx["carrier"]["id"])
    line = stmt["lines"][0]
    # GROSS billed = 25% of full gross recovery 3_000_000 = 750_000.
    assert line["commission_cents"] == 750_000
    assert line["commission_cents"] != ctx["claim"]["accrued_commission_cents"], (
        "billed GROSS commission must diverge from the cash-waterfall commission"
    )


def test_statement_total_rounds_per_line_then_sums(api):
    """PRD §3.8: "The total is computed by rounding each line's commission to whole
    cents first and then summing those already-whole per-line `commission_cents` —
    per-claim rounding strictly precedes summation".

    Design: Difficulty/combinatorial_formula/commission_statement_round_per_line_then_sum
    """
    ctx = setup_two_recovered_claims_same_carrier(
        api, commission_basis="NET", commission_rate_bps=2500,
        paid_loss_cents=1_000_033, deductible_cents=0, settled_amount_cents=1_000_033)
    stmt = create_commission_statement(api, ctx["carrier"]["id"])
    finalized = validate_success(api.finalize_commission_statement(stmt["id"], {}, MANAGER))
    assert finalized["status"] == "FINALIZED"
    # round(0.25*1_000_033)=250_008 per line; 250_008 + 250_008 = 500_016 (not 500_017).
    assert finalized["total_commission_cents"] == 500_016


def test_statement_lines_carry_per_claim_rounded_commission(api):
    """PRD §3.8: "Each entry in `lines` records the source `claim_id`, that claim's
    `net_recovery_cents`, and its `commission_cents`."

    Design: Difficulty/combinatorial_formula/commission_statement_round_per_line_then_sum
    """
    ctx = setup_two_recovered_claims_same_carrier(
        api, commission_basis="NET", commission_rate_bps=2500,
        paid_loss_cents=1_000_033, deductible_cents=0, settled_amount_cents=1_000_033)
    stmt = create_commission_statement(api, ctx["carrier"]["id"])
    per_line = [ln["commission_cents"] for ln in stmt["lines"]]
    assert len(per_line) == 2
    assert all(c == 250_008 for c in per_line), f"each line rounds to 250008, got {per_line}"
    assert sum(per_line) == 500_016


def test_finalize_empty_statement_rejected(api):
    """PRD §3.8: "Finalization is permitted only when the statement is `OPEN` and its
    `lines` are non-empty; a statement that is not open, or one with no lines, is
    rejected with `ERR_STATEMENT_NOT_OPEN`."

    Design: Corner/errors/finalize_empty_statement_returns_statement_not_open
    """
    carrier = create_carrier(api, name="Empty Ins", naic_code="55555")
    stmt = create_commission_statement(api, carrier["id"])
    resp = api.finalize_commission_statement(stmt["id"], {}, MANAGER)
    validate_error(resp, "ERR_STATEMENT_NOT_OPEN", 409)
