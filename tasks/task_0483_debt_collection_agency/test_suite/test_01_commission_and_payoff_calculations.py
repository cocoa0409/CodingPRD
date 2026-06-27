"""Dual-variant and combinatorial calculations: commission GROSS vs NET, the
per-payment rounding order, the settlement floor, and the payoff quote.

All tests translate difficulty-design (queue A) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    create_creditor,
    create_consumer,
    place_account,
    setup_working_account,
    setup_working_account_with_verified_dispute,
    propose_arrangement,
    post_payment,
    refresh_account,
    TEST_USERS,
)

COLLECTOR = TEST_USERS["collector_headers"]


def _working_account_under_creditor(creditor_overrides=None, account_overrides=None):
    """WORKING account whose owning creditor carries the given commission terms.
    Returns the working-account context dict."""
    return setup_working_account(
        creditor_overrides=creditor_overrides or {},
        account_overrides=account_overrides or {},
    )


# ===========================================================================
# dual_variant_calc / commission_gross_vs_net_diverge_on_account
# ===========================================================================
class TestCommissionGrossVsNet:
    """The same collected dollars yield different commission under GROSS vs NET."""

    def test_gross_of_fees_commission_per_payment_rounded_then_summed(self):
        """PRD §3.9: "Under the `GROSS_OF_FEES` variant, commission is computed per
        posted payment and then summed: for each `POSTED` payment on the account,
        multiply that payment's `amount_cents` by the rate and round the product
        half up to whole cents, then add those per-payment rounded amounts together
        — round each line first, then sum."

        Design: Difficulty/dual_variant_calc/commission_gross_vs_net_diverge_on_account
        """
        ctx = _working_account_under_creditor(
            creditor_overrides={
                "name": "Cred A",
                "commission_basis": "GROSS_OF_FEES",
                "commission_rate_bps": 2500,
                "expense_recovery_cents": 10000,
            }
        )
        acct_id = ctx["account"]["id"]
        get_success_data(post_payment(acct_id, 30000))
        get_success_data(post_payment(acct_id, 25000))
        acct = refresh_account(ctx)
        # round(30000*0.25)=7500, round(25000*0.25)=6250, sum=13750
        assert acct["commission_earned_cents"] == 13750, (
            f"GROSS commission should be 13750, got {acct['commission_earned_cents']}"
        )

    def test_net_of_fees_commission_expense_subtracted_then_single_rounding(self):
        """PRD §3.9: "Under the `NET_OF_FEES` variant, the rounding happens once at
        the end: take the total collected (the sum of `amount_cents` across `POSTED`
        payments), subtract the creditor's `expense_recovery_cents`, and take the
        larger of that difference and zero to form the net base; then multiply the
        net base by the rate and round the single product half up to whole cents."

        Design: Difficulty/dual_variant_calc/commission_gross_vs_net_diverge_on_account
        """
        ctx = _working_account_under_creditor(
            creditor_overrides={
                "name": "Cred B",
                "commission_basis": "NET_OF_FEES",
                "commission_rate_bps": 2500,
                "expense_recovery_cents": 10000,
            }
        )
        acct_id = ctx["account"]["id"]
        get_success_data(post_payment(acct_id, 30000))
        get_success_data(post_payment(acct_id, 25000))
        acct = refresh_account(ctx)
        # net base = max(0, 55000 - 10000) = 45000; round(45000*0.25)=11250
        assert acct["commission_earned_cents"] == 11250, (
            f"NET commission should be 11250, got {acct['commission_earned_cents']}"
        )

    def test_gross_and_net_diverge_for_identical_collections(self):
        """PRD §3.9: "The two variants can yield different totals for the same
        payments because gross rounds per line while net rounds once after
        subtracting expenses."

        Design: Difficulty/dual_variant_calc/commission_gross_vs_net_diverge_on_account
        """
        ctx_a = _working_account_under_creditor(
            creditor_overrides={
                "name": "Cred A",
                "commission_basis": "GROSS_OF_FEES",
                "commission_rate_bps": 2500,
                "expense_recovery_cents": 10000,
            }
        )
        ctx_b = _working_account_under_creditor(
            creditor_overrides={
                "name": "Cred B",
                "commission_basis": "NET_OF_FEES",
                "commission_rate_bps": 2500,
                "expense_recovery_cents": 10000,
            }
        )
        for ctx in (ctx_a, ctx_b):
            get_success_data(post_payment(ctx["account"]["id"], 30000))
            get_success_data(post_payment(ctx["account"]["id"], 25000))
        acct_a = refresh_account(ctx_a)
        acct_b = refresh_account(ctx_b)
        assert acct_a["commission_earned_cents"] == 13750
        assert acct_b["commission_earned_cents"] == 11250
        assert acct_a["commission_earned_cents"] != acct_b["commission_earned_cents"]


# ===========================================================================
# combinatorial_formula / commission_rounding_order_per_payment_then_sum
# ===========================================================================
class TestCommissionRoundingOrder:
    """Round-per-payment-then-sum is pinned: two 101-cent payments at 3333 bps
    give 68, not 67."""

    def test_per_payment_rounding_yields_68(self):
        """PRD §3.9: "Under the `GROSS_OF_FEES` variant, commission is computed per
        posted payment and then summed: for each `POSTED` payment on the account,
        multiply that payment's `amount_cents` by the rate and round the product
        half up to whole cents, then add those per-payment rounded amounts together
        — round each line first, then sum."

        Design: Difficulty/combinatorial_formula/commission_rounding_order_per_payment_then_sum
        """
        ctx = _working_account_under_creditor(
            creditor_overrides={
                "name": "Cred",
                "commission_basis": "GROSS_OF_FEES",
                "commission_rate_bps": 3333,
            }
        )
        acct_id = ctx["account"]["id"]
        get_success_data(post_payment(acct_id, 101))
        get_success_data(post_payment(acct_id, 101))
        acct = refresh_account(ctx)
        # round(101*0.3333)=round(33.66)=34 per payment; 34+34=68
        assert acct["commission_earned_cents"] == 68

    def test_not_sum_first_then_round_67(self):
        """PRD §3.9: "for each `POSTED` payment on the account, multiply that
        payment's `amount_cents` by the rate and round the product half up to whole
        cents, then add those per-payment rounded amounts together — round each line
        first, then sum."

        Design: Difficulty/combinatorial_formula/commission_rounding_order_per_payment_then_sum
        """
        ctx = _working_account_under_creditor(
            creditor_overrides={
                "name": "Cred",
                "commission_basis": "GROSS_OF_FEES",
                "commission_rate_bps": 3333,
            }
        )
        acct_id = ctx["account"]["id"]
        get_success_data(post_payment(acct_id, 101))
        get_success_data(post_payment(acct_id, 101))
        acct = refresh_account(ctx)
        # summing first (202*0.3333=67.33 -> 67) would be wrong
        assert acct["commission_earned_cents"] != 67


# ===========================================================================
# combinatorial_formula / settlement_floor_three_input_nested_minmax
# ===========================================================================
class TestSettlementFloorCombination:
    """Floor = max(age_floor, balance_floor) + verified bump; an offer below it is
    rejected and the ledger is untouched."""

    def _setup_aged_high_balance_verified(self):
        # balance 1,500,000 (>= $10,000 -> balance_floor 4000);
        # charge_off 2023-09-23 vs clock 2026-01-01 -> age ~830 days (>= 730 -> age_floor 3000);
        # one VERIFIED dispute -> floor bumped to min(4000+1000, 10000) = 5000 bps.
        ctx = setup_working_account_with_verified_dispute(
            clock="2026-01-01T00:00:00Z",
            account_overrides={
                "original_principal_cents": 1500000,
                "charge_off_date": "2023-09-23T00:00:00Z",
                "sol_years": 10,
            },
        )
        return ctx

    def test_offer_below_floor_rejected_with_below_floor_error(self):
        """PRD §3.6: "Also for a `SETTLEMENT`, the offered `offer_pct_bps` must be at
        least the computed settlement floor in basis points, and an offer below that
        floor is rejected with `ERR_SETTLEMENT_BELOW_FLOOR`."

        Design: Difficulty/combinatorial_formula/settlement_floor_three_input_nested_minmax
        """
        ctx = self._setup_aged_high_balance_verified()
        arr = propose_arrangement(ctx["account"]["id"], "SETTLEMENT", offer_pct_bps=4900)
        res = api_client.accept_arrangement(arr["id"], COLLECTOR)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_BELOW_FLOOR.value)

    def test_rejected_accept_leaves_balance_unchanged(self):
        """PRD §3.6: "Acceptance changes no ledger amounts on its own; the debt is
        satisfied only when payments post against the arrangement."

        Design: Difficulty/combinatorial_formula/settlement_floor_three_input_nested_minmax
        """
        ctx = self._setup_aged_high_balance_verified()
        arr = propose_arrangement(ctx["account"]["id"], "SETTLEMENT", offer_pct_bps=4900)
        api_client.accept_arrangement(arr["id"], COLLECTOR)
        acct = refresh_account(ctx)
        assert acct["balance_cents"] == 1500000, "balance must be unchanged after rejected accept"


# ===========================================================================
# dual_variant_calc / payoff_quote_date_vs_good_through_diverge_on_arrangement
# ===========================================================================
class TestPayoffQuoteDualVariant:
    """The same SETTLEMENT arrangement yields two payoff totals depending on as_of."""

    def _setup_settlement_arrangement(self):
        ctx = setup_working_account(
            clock="2026-01-01T00:00:00Z",
            account_overrides={"original_principal_cents": 100000},
        )
        arr = propose_arrangement(
            ctx["account"]["id"], "SETTLEMENT",
            offer_pct_bps=6000, good_through="2026-01-11T00:00:00Z",
        )
        return arr

    def test_quote_date_no_accrual(self):
        """PRD §3.10: "Under the `QUOTE_DATE` mode the payoff is exactly that base,
        with no accrual."

        Design: Difficulty/dual_variant_calc/payoff_quote_date_vs_good_through_diverge_on_arrangement
        """
        arr = self._setup_settlement_arrangement()
        res = api_client.payoff_quote(arr["id"], COLLECTOR, params={"as_of": "QUOTE_DATE"})
        data = validate_success(res, 200)
        # base = round(100000*6000/10000) = 60000
        assert data["payoff_cents"] == 60000
        assert data["as_of"] == "QUOTE_DATE"

    def test_good_through_adds_admin_fee_per_whole_day(self):
        """PRD §3.10: "Under the `GOOD_THROUGH` mode the payoff adds a per-day
        administrative fee from the clock to the arrangement's `good_through` date:
        take the number of whole days from the current clock to `good_through`,
        computed by flooring the elapsed time to whole days and never going below
        zero, and add 50 cents — the administrative fee of fifty cents per day — for
        each of those whole days on top of the base."

        Design: Difficulty/dual_variant_calc/payoff_quote_date_vs_good_through_diverge_on_arrangement
        """
        arr = self._setup_settlement_arrangement()
        res = api_client.payoff_quote(arr["id"], COLLECTOR, params={"as_of": "GOOD_THROUGH"})
        data = validate_success(res, 200)
        # base 60000 + 10 whole days * 50 = 60500
        assert data["payoff_cents"] == 60500
        assert data["as_of"] == "GOOD_THROUGH"

    def test_good_through_exceeds_quote_date_by_500(self):
        """PRD §3.10: "The same arrangement therefore yields two legitimately
        different payoff totals depending on the requested `as_of` mode."

        Design: Difficulty/dual_variant_calc/payoff_quote_date_vs_good_through_diverge_on_arrangement
        """
        arr = self._setup_settlement_arrangement()
        gt = validate_success(
            api_client.payoff_quote(arr["id"], COLLECTOR, params={"as_of": "GOOD_THROUGH"}), 200
        )
        qd = validate_success(
            api_client.payoff_quote(arr["id"], COLLECTOR, params={"as_of": "QUOTE_DATE"}), 200
        )
        assert gt["payoff_cents"] - qd["payoff_cents"] == 500
