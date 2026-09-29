"""Laundromat package financing computed twice from two different credit scores,
and the origination-fee tier selected from the pre-fee principal of the same
TERM_60 quote.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CHANNEL_MANAGER, UID_CHANNEL_MANAGER


def _draft_quote_with_one_line(api, channel):
    """A TERM_60 draft for four on-premises machines: 4 x 1250000 of line value,
    450000 of freight and a 500000 cash down payment."""
    model = fx.make_model(api)
    quote = fx.make_quote(
        api,
        channel,
        customer_name="Wash Barn LLC",
        laundromat_site_code="SITE-88",
        stated_credit_score=715,
        financing_program="TERM_60",
        down_payment_cents=500000,
        package_discount_pct=0.00,
        freight_cents=450000,
    )
    fx.add_quote_line(
        api,
        quote["id"],
        channel,
        model["id"],
        quantity=4,
        payment_module="NONE",
        line_discount_pct=0.00,
    )
    return quote


def _submit(api, quote, channel):
    return validate_success(
        api.submit_quote(quote["id"], channel["headers"]), expected_status=200
    )


def _approve(api, quote, verified_credit_score):
    payload = f.quote_decision_payload(
        "APPROVE", verified_credit_score=verified_credit_score
    )
    return validate_success(
        api.decide_quote(quote["id"], payload, CHANNEL_MANAGER), expected_status=200
    )


class TestFinancingProvisionalVersusFinalVariant:
    def test_01_package_money_rollup_passes_freight_through_at_cost(self, api, authorized_distributor):
        """Four machines plus freight and no package discount roll up to the balance the financing acts on.

        PRD: "`total_cents` is `line_subtotal_cents` minus `discount_cents` plus `freight_cents` — the package discount applies to the subtotal only and **never** to freight, which is passed through at cost."
        Design: Difficulty/dual_variant_calc/financing_apr_provisional_vs_final_on_quote_approval
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        submitted = _submit(api, quote, authorized_distributor)

        a.assert_cents(submitted["total_cents"], 5450000)
        a.assert_money_identity(submitted)

    def test_02_submission_computes_the_fee_and_the_financed_principal(self, api, authorized_distributor):
        """The provisional pass is the only one that charges the origination fee and freezes the principal.

        PRD: "`financed_principal_cents` is the pre-fee principal plus `origination_fee_cents`."
        Design: Difficulty/dual_variant_calc/financing_apr_provisional_vs_final_on_quote_approval
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        submitted = _submit(api, quote, authorized_distributor)

        a.assert_cents(submitted["origination_fee_cents"], 123750)
        a.assert_cents(submitted["financed_principal_cents"], 5073750)

    def test_03_provisional_variant_keys_the_apr_on_the_stated_score(self, api, authorized_distributor):
        """A stated score of 715 shaves 100 basis points off the TERM_60 base rate at submission.

        PRD: "The provisional variant runs at submission, takes `stated_credit_score` as its governing score, and writes four fields: `provisional_apr_bp`, `provisional_monthly_payment_cents`, `origination_fee_cents` and `financed_principal_cents`."
        Design: Difficulty/dual_variant_calc/financing_apr_provisional_vs_final_on_quote_approval
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        submitted = _submit(api, quote, authorized_distributor)

        # 1690 base for TERM_60 less 100 for a score at least 700 and below 760.
        assert submitted["provisional_apr_bp"] == 1590
        a.assert_cents(submitted["provisional_monthly_payment_cents"], 123114)
        assert submitted["final_apr_bp"] is None
        assert submitted["monthly_payment_cents"] is None

    def test_04_final_variant_keys_the_apr_on_the_verified_score(self, api, authorized_distributor):
        """A verified score of 668 earns no adjustment at all, so the approval prices the same principal higher.

        PRD: "The final variant runs at approval, takes `verified_credit_score` as its governing score, writes `final_apr_bp` and `monthly_payment_cents`, leaves the provisional pair untouched, and reuses the principal frozen at submission time without recomputing it — an approval therefore never changes how much is being financed, only what it costs."
        Design: Difficulty/dual_variant_calc/financing_apr_provisional_vs_final_on_quote_approval
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        _submit(api, quote, authorized_distributor)
        approved = _approve(api, quote, 668)

        # A score at least 640 and below 700 applies no adjustment to the 1690
        # TERM_60 base rate.
        assert approved["final_apr_bp"] == 1690
        a.assert_cents(approved["monthly_payment_cents"], 125823)
        # The provisional pair and the frozen principal survive the approval.
        assert approved["provisional_apr_bp"] == 1590
        a.assert_cents(approved["provisional_monthly_payment_cents"], 123114)
        a.assert_cents(approved["financed_principal_cents"], 5073750)
        a.assert_cents(approved["origination_fee_cents"], 123750)

    def test_05_approval_stores_the_verified_score_and_the_deciding_operator(self, api, authorized_distributor):
        """The channel decision records who approved the deal and the score it was approved on.

        PRD: "An approval requires `verified_credit_score`, an integer from 300 through 850, and omitting it is `ERR_INVALID_REQUEST`; the score is stored, the final financing variant runs, and the quote moves from `SUBMITTED` to `APPROVED`."
        Design: Difficulty/dual_variant_calc/financing_apr_provisional_vs_final_on_quote_approval
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        _submit(api, quote, authorized_distributor)
        _approve(api, quote, 668)

        reread = validate_success(
            api.get_quote(quote["id"], CHANNEL_MANAGER), expected_status=200
        )
        assert reread["verified_credit_score"] == 668
        a.assert_quote_state(reread, "APPROVED")
        assert reread["decided_by_user_id"] == UID_CHANNEL_MANAGER


class TestOriginationFeeTierKeyedOnPreFeePrincipal:
    def test_01_the_balance_the_pre_fee_principal_is_taken_from(self, api, authorized_distributor):
        """The undiscounted four-machine subtotal plus freight is the balance the down payment is deducted from.

        PRD: "`line_subtotal_cents` is the **sum of the stored, already-rounded** `line_total_cents` values of the surviving lines; it never recomputes a line from its unit price, so line-level rounding is never re-litigated at the package level."
        Design: Difficulty/combinatorial_formula/financing_origination_fee_tier_keyed_on_pre_fee_principal
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        submitted = _submit(api, quote, authorized_distributor)

        a.assert_cents(submitted["line_subtotal_cents"], 5000000)
        a.assert_cents(submitted["discount_cents"], 0)
        a.assert_cents(submitted["total_cents"], 5450000)
        assert submitted["line_count"] == 1

    def test_02_the_tier_is_chosen_from_the_pre_fee_principal(self, api, authorized_distributor):
        """A pre-fee principal of 4950000 sits at or below fifty thousand dollars, so the two-and-a-half percent tier applies.

        PRD: "The tier is keyed on the pre-fee principal, never on the financed principal — the fee does not re-tier itself after being added, and a pre-fee principal just under a tier boundary that crosses it once the fee is added still pays the lower tier's rate."
        Design: Difficulty/combinatorial_formula/financing_origination_fee_tier_keyed_on_pre_fee_principal
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        submitted = _submit(api, quote, authorized_distributor)

        a.assert_cents(submitted["origination_fee_cents"], 123750)
        # Re-tiering on the resulting financed principal, which does cross the
        # fifty-thousand-dollar boundary, would have charged 86625 instead.
        assert submitted["origination_fee_cents"] != 86625
        a.assert_cents(submitted["financed_principal_cents"], 5073750)

    def test_03_provisional_terms_ride_on_the_pre_fee_tier_result(self, api, authorized_distributor):
        """The submitted quote carries the level payment computed over the principal the lower-tier fee produced.

        PRD: "The payment is the `financed_principal_cents` multiplied by the monthly rate, divided by the quantity obtained by subtracting, from one, the value of one plus the monthly rate raised to the power of the negated term in months; the result of that division is rounded half up once to a whole number of cents."
        Design: Difficulty/combinatorial_formula/financing_origination_fee_tier_keyed_on_pre_fee_principal
        """
        quote = _draft_quote_with_one_line(api, authorized_distributor)
        _submit(api, quote, authorized_distributor)

        reread = validate_success(
            api.get_quote(quote["id"], CHANNEL_MANAGER), expected_status=200
        )
        assert reread["provisional_apr_bp"] == 1590
        a.assert_cents(reread["provisional_monthly_payment_cents"], 123114)
        a.assert_quote_state(reread, "SUBMITTED")
