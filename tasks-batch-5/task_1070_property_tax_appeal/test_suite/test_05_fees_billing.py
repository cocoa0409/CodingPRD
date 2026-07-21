"""Contingency fee variants/tiers and the billing ledger (depth + breadth coverage)."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
BILLING = TEST_USERS["billing_headers"]

# comps producing requested 30000000 under SALES_COMPARISON (single comp, adjusted == sale)
_COMP_30M = [{"comp_address": "x", "sale_price_cents": 30000000,
              "comp_assessed_value_cents": 27000000, "adjustment_pct": 0.00}]


class TestProvisionalVsFinalFee:
    """PROVISIONAL fee 15000 (over projected savings 25000, floored) diverges from FINAL fee 28250
    (over realized savings 75000).
    Design: Difficulty/dual_variant_calc/di_fee_provisional_vs_final_diverge
    """

    def test_provisional_savings_and_fee_at_file(self, api):
        """PRD §3.4: "The **provisional** variant, computed at filing, uses the appeal's
        `requested_value_cents` and is stored in `projected_savings_cents`." and "the fee runs in a
        **provisional** variant at filing — over `projected_savings_cents`, stored in
        `projected_fee_cents` and never billed". requested 29000000 -> savings 25000 -> fee floored 15000.

        Design: Difficulty/dual_variant_calc/di_fee_provisional_vs_final_diverge
        """
        ctx = fx.setup_filed_appeal(api, valuation_method="ASSESSMENT_EQUITY", comps=fx.DUAL_VARIANT_COMPS)
        assert ctx["appeal"]["requested_value_cents"] == 29000000
        assert ctx["appeal"]["projected_savings_cents"] == 25000
        assert ctx["appeal"]["projected_fee_cents"] == 15000

    def test_final_fee_on_invoice_diverges_from_provisional(self, api):
        """PRD §3.4: "a **final** variant when the terminating invoice is created, over
        `realized_savings_cents`, which becomes the billed `fee_amount_cents`." decision 27000000 ->
        realized 75000 -> final fee 28250, differing from the provisional 15000.

        Design: Difficulty/dual_variant_calc/di_fee_provisional_vs_final_diverge
        """
        ctx = fx.setup_decided_appeal(api, decision_value_cents=27000000,
                                      valuation_method="ASSESSMENT_EQUITY", comps=fx.DUAL_VARIANT_COMPS)
        assert ctx["appeal"]["realized_savings_cents"] == 75000
        assert ctx["invoice"]["gross_savings_cents"] == 75000
        assert ctx["invoice"]["fee_amount_cents"] == 28250
        assert ctx["appeal"]["projected_fee_cents"] != ctx["invoice"]["fee_amount_cents"]


class TestTieredMarginalFee:
    """Realized savings 75000 straddles tier1 (50000@0.40) and tier2 (25000@0.33) -> 28250.
    Design: Difficulty/combinatorial_formula/ci_fee_tiered_marginal_spans_two_tiers
    """

    def test_realized_savings_value(self, api):
        """PRD §3.4: "The savings figure is the assessment's immutable `original_assessed_value_cents`
        less the result value under consideration, multiplied by the assessment's `millage_rate`,
        divided by 1000, and rounded half up to whole cents." (30000000-27000000)*25/1000 = 75000.

        Design: Difficulty/combinatorial_formula/ci_fee_tiered_marginal_spans_two_tiers
        """
        ctx = fx.setup_decided_appeal(api, decision_value_cents=27000000,
                                      valuation_method="SALES_COMPARISON", comps=_COMP_30M)
        assert ctx["appeal"]["realized_savings_cents"] == 75000

    def test_marginal_tiers_summed_then_rounded(self, api):
        """PRD §3.4: "The portion up to `tier1_ceiling_cents` is charged at `contingency_tier1_pct`.
        The portion above `tier1_ceiling_cents` but not beyond `tier2_ceiling_cents` ... is charged at
        `contingency_tier2_pct`. ... These three band charges are summed in exact arithmetic, and the
        total is rounded half up to whole cents exactly once, after the three bands are added".
        50000*0.40 + 25000*0.33 = 28250.

        Design: Difficulty/combinatorial_formula/ci_fee_tiered_marginal_spans_two_tiers
        """
        ctx = fx.setup_decided_appeal(api, decision_value_cents=27000000,
                                      valuation_method="SALES_COMPARISON", comps=_COMP_30M)
        assert ctx["invoice"]["fee_amount_cents"] == 28250


def test_fee_minimum_floor_applies(api):
    """PRD §3.4: "Whenever the savings amount is greater than zero, the fee is then raised to at least
    `minimum_fee_cents`: the final fee is the larger of that floor and the rounded tier total."
    realized 25000 -> raw tier fee 10000 < 15000 -> fee 15000.

    Design: Corner/calculations/corner_fee_minimum_floor_applies
    """
    comp = [{"comp_address": "x", "sale_price_cents": 29000000,
             "comp_assessed_value_cents": 29000000, "adjustment_pct": 0.00}]
    ctx = fx.setup_decided_appeal(api, decision_value_cents=29000000,
                                  valuation_method="SALES_COMPARISON", comps=comp)
    assert ctx["appeal"]["realized_savings_cents"] == 25000
    assert ctx["invoice"]["fee_amount_cents"] == 15000


class TestZeroSavingsBoundary:
    """decision == original -> realized 0 -> DRAFT invoice gross 0 -> issue blocked.
    Design: Difficulty/boundary_precision_check/bp_zero_savings_blocks_invoice_issue
    """

    def test_zero_savings_yields_zero_gross_invoice(self, api):
        """PRD §3.7: "The invoice is always created on a decision — even when realized savings are
        zero or negative — so its `gross_savings_cents` copies `realized_savings_cents`".
        decision 30000000 == original -> realized 0.

        Design: Difficulty/boundary_precision_check/bp_zero_savings_blocks_invoice_issue
        """
        ctx = fx.setup_decided_appeal(api, decision_value_cents=30000000,
                                      valuation_method="SALES_COMPARISON", comps=_COMP_30M)
        assert ctx["appeal"]["realized_savings_cents"] == 0
        assert ctx["invoice"]["gross_savings_cents"] == 0

    def test_issue_zero_savings_invoice_rejected(self, api):
        """PRD §3.8: "the invoice's `gross_savings_cents` must be greater than 0, or the request is
        rejected with `ERR_NO_BILLABLE_SAVINGS` — this is the boundary that stops a zero-savings draft
        from ever billing."

        Design: Difficulty/boundary_precision_check/bp_zero_savings_blocks_invoice_issue
        """
        ctx = fx.setup_decided_appeal(api, decision_value_cents=30000000,
                                      valuation_method="SALES_COMPARISON", comps=_COMP_30M)
        resp = api.issue_invoice(ctx["invoice"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_SAVINGS.value)


class TestIssueThenVoidLedgerInvariant:
    """Issue debits ledgers by 28250; void restores them to 0 (conserved fee ledger).
    Design: Difficulty/compensating_invariant/cinv_issue_then_void_preserves_fee_ledger
    """

    def test_void_restores_lifetime_fees_billed(self, api):
        """PRD §3.8: "Because the lifetime figure is credited by the full fee on issue and debited by
        the full fee on void, an issue-then-void sequence provably leaves `lifetime_fees_billed_cents`
        exactly as it began."

        Design: Difficulty/compensating_invariant/cinv_issue_then_void_preserves_fee_ledger
        """
        ctx = fx.setup_issued_invoice(api, decision_value_cents=27000000, comps=_COMP_30M)
        void = validate_success(api.void_invoice(ctx["invoice"]["id"], FIRM_ADMIN))
        assert void["status"] == "VOID"
        client = validate_success(api.get_client(ctx["client_id"], FIRM_ADMIN))
        assert client["lifetime_fees_billed_cents"] == 0

    def test_void_restores_outstanding_balance(self, api):
        """PRD §3.8: "Voiding is a compensating reversal of the issue-time ledger effects: the
        client's `lifetime_fees_billed_cents` is reduced by the invoice's `fee_amount_cents`, and its
        `outstanding_balance_cents` is reduced by the still-unpaid remainder, namely `fee_amount_cents`
        less `amount_paid_cents`."

        Design: Difficulty/compensating_invariant/cinv_issue_then_void_preserves_fee_ledger
        """
        ctx = fx.setup_issued_invoice(api, decision_value_cents=27000000, comps=_COMP_30M)
        validate_success(api.void_invoice(ctx["invoice"]["id"], FIRM_ADMIN))
        client = validate_success(api.get_client(ctx["client_id"], FIRM_ADMIN))
        assert client["outstanding_balance_cents"] == 0


def test_outstanding_balance_after_partial_payment(api):
    """PRD §3.8: "Recording a payment recomputes the invoice's `amount_paid_cents` as the sum of the
    `amount_cents` of all payments applied to it, and decreases the client's `outstanding_balance_cents`
    by the payment's `amount_cents`." Issued fee 28250, pay 10000 -> outstanding 18250, invoice stays ISSUED.

    Design: Corner/cross_cutting_complexity_layers/corner_outstanding_balance_after_partial_payment
    """
    ctx = fx.setup_issued_invoice(api, decision_value_cents=27000000, comps=_COMP_30M)
    pay = validate_success(api.create_payment(ctx["invoice"]["id"], {"amount_cents": 10000, "method": "CHECK"},
                                              BILLING), expected_status=201)
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], BILLING))
    assert invoice["amount_paid_cents"] == 10000
    assert invoice["status"] == "ISSUED"
    client = validate_success(api.get_client(ctx["client_id"], FIRM_ADMIN))
    assert client["outstanding_balance_cents"] == 18250
