"""Factoring advances and the haircut tier math — PRD §3.8."""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_factoring_advance,
    assert_invoice,
    FACTORING_TIER_A_CAP_CENTS,
    FACTORING_TIER_A_RATE,
    FACTORING_TIER_B_CAP_CENTS,
    FACTORING_TIER_B_RATE,
    FACTORING_TIER_C_RATE,
    factor_invoice,
    get_invoice,
    setup_factored_invoice,
    setup_invoiced_load,
    setup_invoice_in_review_dispute,
    setup_load_for_factor_total,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.8 — Haircut tier math.
# ===========================================================================
def _expected_haircut(invoice_total_cents: int) -> int:
    """Mirror PRD §3.8 haircut algorithm: marginal slices, sum
    contributions, round once half-up at the end."""
    a_cap = FACTORING_TIER_A_CAP_CENTS                # 100_000
    b_cap = FACTORING_TIER_B_CAP_CENTS                # 500_000
    a_rate = FACTORING_TIER_A_RATE                    # 0.030
    b_rate = FACTORING_TIER_B_RATE                    # 0.020
    c_rate = FACTORING_TIER_C_RATE                    # 0.010
    T = invoice_total_cents
    a_slice = min(T, a_cap)
    b_slice = max(0, min(T, b_cap) - a_cap)
    c_slice = max(0, T - b_cap)
    raw = a_slice * a_rate + b_slice * b_rate + c_slice * c_rate
    # Half-up to nearest cent.
    import decimal
    quantised = decimal.Decimal(str(raw)).quantize(
        decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP,
    )
    return int(quantised)


def test_factor_at_tier_c_haircut_three_tier_sum(api):
    """PRD §3.8: "The first 100,000 cents of T (the slice from 0 up to
    and including 100,000) is charged at 3.0% (rate 0.030). The next
    400,000 cents of T ... is charged at 2.0% (rate 0.020). Any slice
    strictly above 500,000 cents is charged at 1.0% (rate 0.010)."

    Claim: T = 600_000 -> 100_000*0.030 + 400_000*0.020 + 100_000*0.010
    = 3000 + 8000 + 1000 = 12_000 cents.
    """
    brokerage, invoice = setup_load_for_factor_total(
        invoice_total_cents=600_000
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert_factoring_advance(advance)
    assert advance["invoice_total_at_advance_cents"] == 600_000
    assert advance["haircut_cents"] == _expected_haircut(600_000)
    assert advance["haircut_cents"] == 12_000


def test_factor_at_tier_a_only(api):
    """PRD §3.8: "The first 100,000 cents of T (the slice from 0 up to
    and including 100,000) is charged at 3.0% (rate 0.030)."

    Claim: T = 50_000 -> haircut = 1_500 (50_000 * 0.030).
    """
    brokerage, invoice = setup_load_for_factor_total(
        invoice_total_cents=50_000
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert advance["haircut_cents"] == _expected_haircut(50_000)
    assert advance["haircut_cents"] == 1_500


def test_factor_at_tier_b_boundary(api):
    """PRD §3.8 marginal slices: "the slice in (100_000, 500_000]" at
    2.0%.

    Claim: T = 500_000 -> 100_000*0.030 + 400_000*0.020 = 3000 + 8000
    = 11_000.
    """
    brokerage, invoice = setup_load_for_factor_total(
        invoice_total_cents=500_000
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert advance["haircut_cents"] == _expected_haircut(500_000)
    assert advance["haircut_cents"] == 11_000


# ===========================================================================
# §3.8 — Reserve and advanced cents.
# ===========================================================================
def test_factor_reserve_uses_brokerage_factoring_reserve_pct(api):
    """PRD §3.8: "The `reserve_cents` is the brokerage-wide holdback. It
    equals `invoice_total_at_advance_cents` multiplied by
    `factoring_reserve_pct`, divided by 100, with the result rounded
    half-up to a whole number of cents."

    Claim: T = 600_000, factoring_reserve_pct = 5.00 -> reserve = 30_000.
    """
    brokerage, invoice = setup_load_for_factor_total(
        invoice_total_cents=600_000
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert advance["reserve_cents"] == 30_000


def test_factor_advanced_cents_equals_total_minus_haircut_minus_reserve(api):
    """PRD §3.8: "The `advanced_cents` — the cash wired to the brokerage
    — equals `invoice_total_at_advance_cents` minus `haircut_cents` minus
    `reserve_cents`."

    Claim: with T = 600_000, haircut = 12_000, reserve = 30_000,
    advanced == 558_000.
    """
    brokerage, invoice = setup_load_for_factor_total(
        invoice_total_cents=600_000
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert advance["advanced_cents"] == (
        advance["invoice_total_at_advance_cents"]
        - advance["haircut_cents"]
        - advance["reserve_cents"]
    )
    assert advance["advanced_cents"] == 558_000


# ===========================================================================
# §3.8 — Side effects on the invoice.
# ===========================================================================
def test_factor_drives_invoice_balance_to_zero_but_keeps_settlement_issued(api):
    """PRD §3.8: "At factoring time, the brokerage treats the invoice's
    face value as paid against the receivable: `Invoice`.`amount_paid_cents`
    is increased by `invoice_total_at_advance_cents`, which drives
    `balance_due_cents` to zero. ... The invoice does not transition to
    `PAID` in this state, because the parallel settlement dimension only
    auto-advances to `PAID` when `balance_due_cents` reaches zero and
    `factoring_status` is something other than `FACTORED`; while the invoice
    is `FACTORED` it remains `ISSUED` on the settlement axis."

    Claim: after /factor, factoring_status == FACTORED,
    settlement_status == ISSUED, balance_due_cents == 0,
    amount_paid_cents == invoice_total_cents.
    """
    brokerage, _shipper, _c, _q, _l, invoice, advance = (
        setup_factored_invoice()
    )
    assert invoice["factoring_status"] == "FACTORED"
    assert invoice["settlement_status"] == "ISSUED"
    assert invoice["balance_due_cents"] == 0
    assert invoice["amount_paid_cents"] == invoice["invoice_total_cents"]


def test_factor_recourse_owed_starts_at_zero(api):
    """PRD §3.8: "`recourse_owed_cents` is initially zero on a freshly
    factored advance; it becomes non-zero only on the `FACTORED → RECOURSED` cascade described in 3.9."

    Claim: a freshly factored advance has recourse_owed_cents == 0.
    """
    brokerage, _s, _c, _q, _l, _inv, advance = setup_factored_invoice()
    assert advance["recourse_owed_cents"] == 0


# ===========================================================================
# §3.8 — Factor preconditions.
# ===========================================================================
def test_double_factor_rejected(api, broker_ops_headers):
    """PRD §3.8: "A second factoring attempt on an already-`FACTORED` or
    `RECOURSED` invoice likewise yields `ERR_INVOICE_NOT_FACTORABLE`."

    Claim: /factor twice on the same invoice -> the second call returns
    ERR_INVOICE_NOT_FACTORABLE.
    """
    brokerage, _s, _c, _q, _l, _inv, _advance = setup_factored_invoice()
    invoice = _inv
    res = api.factor_invoice(brokerage["id"], invoice["id"],
                             broker_ops_headers)
    validate_error(res, "ERR_INVOICE_NOT_FACTORABLE")


def test_factor_with_open_dispute_rejected(api, broker_ops_headers):
    """PRD §3.8: "Any of the first two failing yields
    `ERR_INVOICE_NOT_FACTORABLE`; an open dispute yields
    `ERR_INVOICE_HAS_OPEN_DISPUTE`."

    Claim: factor on an invoice with a claim in IN_REVIEW state ->
    ERR_INVOICE_HAS_OPEN_DISPUTE.
    """
    brokerage, _s, _c, _q, _l, invoice, _claim = (
        setup_invoice_in_review_dispute(claim_type="OVERCHARGE",
                                        claimed_cents=2_000)
    )
    res = api.factor_invoice(brokerage["id"], invoice["id"],
                             broker_ops_headers)
    validate_error(res, "ERR_INVOICE_HAS_OPEN_DISPUTE")
