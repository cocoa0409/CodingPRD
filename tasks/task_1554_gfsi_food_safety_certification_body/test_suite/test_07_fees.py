"""Certification fee variants: quote at acceptance, invoice at issuance."""
import pytest

from test_helpers import (
    assert_money,
    setup_granted_chain,
    setup_reported_chain,
)

TWO_HIGH = [
    {"category_code": "BAKERY", "risk_tier": "HIGH"},
    {"category_code": "DAIRY", "risk_tier": "HIGH"},
]


class TestQuoteVsInvoice:
    def test_provisional_fee_quote_at_acceptance(self, api):
        """PRD §2.9: "The quote variant, stored as `provisional_fee_quote`
        when an application is accepted, is the scheme's `base_fee` plus the
        number of scoped product categories multiplied by `per_category_fee`,
        with that single sum rounded half-up to two decimals; the quote has no
        risk-tier multiplier, no day-rate component, and no unannounced
        uplift."

        Design: Difficulty/dual_variant_calc/certification_fee_quote_vs_invoice_divergence
        """
        chain = setup_reported_chain(categories=TWO_HIGH, actual_days=1)
        # round_half_up(2000.00 + 2 x 333.33, 2): flat and unmultiplied.
        assert_money(chain.app["provisional_fee_quote"], 2666.66)

    def test_final_fee_invoice_diverges_from_quote(self, api):
        """PRD §2.9: "The invoice variant, stored as `final_fee` at
        certificate issuance, is the sum of three individually rounded lines:
        the `base_fee` rounded half-up to two decimals; one line per scoped
        category of `per_category_fee` multiplied by the scheme's
        `high_risk_multiplier` when that category's `risk_tier` is `HIGH` and
        by 1.0 otherwise, each such line rounded half-up to two decimals; and
        a day-rate line equal to the issuing audit's `audit_fee`"

        Design: Difficulty/dual_variant_calc/certification_fee_quote_vs_invoice_divergence
        """
        chain = setup_granted_chain(categories=TWO_HIGH, actual_days=1)
        quote = chain.app["provisional_fee_quote"]
        # 2000.00 + 2 x round_half_up(333.33 x 1.5, 2) + round(1 x 1000.00, 2)
        # = 2000.00 + 500.00 + 500.00 + 1000.00.
        assert_money(chain.certificate["final_fee"], 4000.00)
        # Same scope data, different variant: provisional vs final diverge.
        assert chain.certificate["final_fee"] != pytest.approx(quote,
                                                               abs=0.001)


class TestRoundingOrder:
    def test_audit_fee_announced_no_uplift(self, api):
        """PRD §3.5: "The transition `IN_PROGRESS → REPORT_SUBMITTED` freezes
        two computed values onto the audit: the `reported_score`, the reported
        variant of the audit score per §2.9 over all findings of the audit,
        and the `audit_fee`, the day-rate line of §2.9 including the
        unannounced uplift when the audit is `UNANNOUNCED`."

        Design: Difficulty/combinatorial_formula/certification_fee_round_per_line_then_sum
        """
        chain = setup_reported_chain(categories=TWO_HIGH, actual_days=2)
        # INITIAL is announced: round_half_up(2 x 1000.00 x 1.0, 2).
        assert_money(chain.audit["audit_fee"], 2000.00)

    def test_final_fee_round_per_line_then_sum(self, api):
        """PRD §2.9: "Monetary values are handled at two decimal places with
        round-half-up rounding, and the certification fee is assembled with a
        pinned rounding order: each line item is rounded to two decimals
        first, and the rounded lines are then summed — never summed first and
        rounded after."

        Design: Difficulty/combinatorial_formula/certification_fee_round_per_line_then_sum
        """
        chain = setup_granted_chain(categories=TWO_HIGH, actual_days=2)
        # Per-category line: round_half_up(333.33 x 1.5, 2) == 500.00 each
        # (sum-then-round would produce the 4999.99 trap: 2000.00 + 999.99 +
        # 2000.00). Round-per-line-then-sum pins 2000.00 + 500.00 + 500.00 +
        # 2000.00.
        assert_money(chain.certificate["final_fee"], 5000.00)
        assert abs(chain.certificate["final_fee"] - 4999.99) > 0.001
