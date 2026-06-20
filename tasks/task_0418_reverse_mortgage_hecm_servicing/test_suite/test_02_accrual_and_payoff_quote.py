"""Monthly compounding accrual (round-per-month order), the forward-looking
payoff quote (accumulate-then-round), and their divergence on the same loan.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_lender_with_plf,
    create_borrower,
    create_loan,
    originate,
)

_SO = TEST_USERS["servicer_ops_headers"]


def _originate_loan(expected_rate_bps, annual_mip_rate_bps, initial_financed_costs_cents):
    """Originate a LINE_OF_CREDIT loan whose balance == initial_financed_costs."""
    lender = setup_lender_with_plf(plf_overrides={"age": 75,
                                                  "expected_rate_bps": expected_rate_bps,
                                                  "factor_micros": 523000})
    borrower = create_borrower(lender["id"])
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=30000000, expected_rate_bps=expected_rate_bps,
                       draw_type="LINE_OF_CREDIT", annual_mip_rate_bps=annual_mip_rate_bps,
                       initial_financed_costs_cents=initial_financed_costs_cents)
    return originate(loan["id"])


# ---------------------------------------------------------------------------
# combinatorial_formula / mip_interest_accrual_round_per_month_order_pinned
# ---------------------------------------------------------------------------
def test_mip_interest_accrual_round_per_month_order_pinned(api):
    """PRD §3.6: "each per-month component is rounded to whole cents first, then
    added to the balance, and that rounded balance is the base for the next month —
    rounding per period and then accumulating, not accumulating and then rounding."

    Design: Difficulty/combinatorial_formula/mip_interest_accrual_round_per_month_order_pinned
    """
    loan = _originate_loan(expected_rate_bps=500, annual_mip_rate_bps=50,
                           initial_financed_costs_cents=5000000)
    assert loan["principal_balance_cents"] == 5000000
    data = validate_success(api.post_accrual(loan["id"], {"number_of_months": 12}, _SO))
    assert data["principal_balance_cents"] == 5282040
    assert data["months_elapsed"] == 12


def test_post_accrual_advances_months_elapsed(api):
    """PRD §3.6: "After each month is posted, `months_elapsed` increases by 1; over the full run
    it rises by the supplied `number_of_months`."

    Design: Difficulty/combinatorial_formula/mip_interest_accrual_round_per_month_order_pinned
    """
    loan = _originate_loan(expected_rate_bps=500, annual_mip_rate_bps=50,
                           initial_financed_costs_cents=5000000)
    data = validate_success(api.post_accrual(loan["id"], {"number_of_months": 12}, _SO))
    assert data["months_elapsed"] == 12
    assert data["principal_balance_cents"] == 5282040


# ---------------------------------------------------------------------------
# dual_variant_calc / balance_accrual_compound_vs_payoff_quote_projection
# ---------------------------------------------------------------------------
def test_payoff_quote_single_compound_projection(api):
    """PRD §3.6: "the projected balance is the current `principal_balance_cents` multiplied by
    the quantity (1 plus the combined monthly rate) raised to the power of
    `number_of_months`, the whole product rounded half up to whole cents
    (accumulate-then-round)."

    Design: Difficulty/dual_variant_calc/balance_accrual_compound_vs_payoff_quote_projection
    """
    loan = _originate_loan(expected_rate_bps=625, annual_mip_rate_bps=50,
                           initial_financed_costs_cents=5000000)
    quote = validate_success(api.payoff_quote(loan["id"], _SO, params={"number_of_months": 36}))
    assert quote["projected_balance_cents"] == 6118828


def test_accrual_round_per_month_diverges_from_payoff_quote(api):
    """PRD §3.6: "Because of this single-rounding treatment, for the same loan and
    the same number of months the quote's projected figure will generally differ in
    cents from what posting that many months of accrual would yield."

    Design: Difficulty/dual_variant_calc/balance_accrual_compound_vs_payoff_quote_projection
    """
    loan = _originate_loan(expected_rate_bps=625, annual_mip_rate_bps=50,
                           initial_financed_costs_cents=5000000)
    quote = validate_success(api.payoff_quote(loan["id"], _SO, params={"number_of_months": 36}))
    posted = validate_success(api.post_accrual(loan["id"], {"number_of_months": 36}, _SO))
    assert quote["projected_balance_cents"] == 6118828
    assert posted["principal_balance_cents"] == 6118831
    assert posted["principal_balance_cents"] != quote["projected_balance_cents"]
    assert posted["months_elapsed"] == 36


# ---------------------------------------------------------------------------
# endpoints / payoff_quote_computed_read_does_not_mutate_balance
# ---------------------------------------------------------------------------
def test_payoff_quote_does_not_mutate_balance(api):
    """PRD §3.6: "A forward-looking payoff quote answers a different question and
    never mutates anything."

    Design: Corner/endpoints/payoff_quote_computed_read_does_not_mutate_balance
    """
    loan = _originate_loan(expected_rate_bps=500, annual_mip_rate_bps=50,
                           initial_financed_costs_cents=1000000)
    # LUMP draw irrelevant; balance is initial financed costs for this LOC loan.
    bal_before = validate_success(api.get_loan(loan["id"], _SO))["principal_balance_cents"]
    quote = validate_success(api.payoff_quote(loan["id"], _SO, params={"number_of_months": 12}))
    assert quote["loan_id"] == loan["id"]
    assert "projected_balance_cents" in quote
    assert "deficiency_cents" in quote
    assert quote["projected_balance_cents"] >= bal_before
    bal_after = validate_success(api.get_loan(loan["id"], _SO))["principal_balance_cents"]
    assert bal_after == bal_before


# ---------------------------------------------------------------------------
# consistency_model / disbursement_balance_change_visible_in_same_request_response
# ---------------------------------------------------------------------------
def test_disburse_balance_change_immediately_visible(api):
    """PRD §3.5: "Disbursing adds the `approved_amount_cents` to the loan's
    `principal_balance_cents` (posted as an `ADVANCE` ledger entry) and
    subtracts the same `approved_amount_cents` from the loan's
    `available_line_of_credit_cents`, so that balance and remaining line stay
    conserved against each other."

    Design: Corner/consistency_model/disbursement_balance_change_visible_in_same_request_response
    """
    loan = _originate_loan(expected_rate_bps=500, annual_mip_rate_bps=50,
                           initial_financed_costs_cents=1000000)
    v = validate_success(api.get_loan(loan["id"], _SO))["version"]
    disb = validate_success(api.create_disbursement(
        {"loan_id": loan["id"], "kind": "LINE_DRAW", "requested_amount_cents": 100000}, _SO),
        expected_status=201)
    validate_success(api.approve_disbursement(disb["id"], {"expected_loan_version": v}, _SO))
    validate_success(api.disburse_disbursement(disb["id"], _SO))
    reread = validate_success(api.get_loan(loan["id"], _SO))
    assert reread["principal_balance_cents"] == 1100000
    assert reread["available_line_of_credit_cents"] == 14590000
