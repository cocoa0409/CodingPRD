"""Depth tests for the ledger-reconciliation and combinatorial-calculation rules:
rent-to-own equity vs payoff divergence, store-credit dual formulas, the repair
invoice rush branch, financing amortization rounding order, and the stacked
lesson-tuition discount order.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data, validate_success,
    make_customer_headers,
    create_customer, create_active_agreement, setup_rto_with_n_paid_months,
    setup_offered_trade_in, setup_listed_consignment, setup_submitted_financing,
    setup_enrollment_linked_to_active_agreement,
    create_unit_payload, create_consignment_payload,
    pay_deposit_payload,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc
# ===========================================================================
class TestEquityVsPayoffDivergence:
    def test_equity_and_payoff_diverge_on_same_agreement(self, api):
        """PRD §3.4: "Concretely, the system first forms the remaining balance as
        the purchase price minus the accrued equity — purchase_price_cents minus
        accrued_equity_cents. It then adds a flat early-buyout fee of 5,000 cents
        (fifty dollars) and adds the current outstanding late-fee balance."
        PRD §2.8: "the accrued equity — and therefore the payoff figure — has changed"

        Design: Difficulty/dual_variant_calc/rto_equity_vs_payoff_diverge_on_agreement
        """
        customer, agreement, _ = setup_rto_with_n_paid_months(
            num_months=3, list_price_cents=120000, monthly_rent_cents=10000,
            equity_rate_pct=0.50,
        )
        data = validate_success(
            api.get_agreement(agreement["id"], make_customer_headers(customer["id"])), 200
        )
        # equity counts UP: 3 * 10000 * 0.50 = 15000
        assert data["accrued_equity_cents"] == 15000
        # payoff counts DOWN and adds the 5000 fee: 120000 - 15000 + 5000 = 110000
        assert data["payoff_quote_cents"] == 110000

    def test_equity_plus_payoff_is_not_purchase_price(self, api):
        """PRD §3.4: "The payoff quote is a deliberately different computation over
        the same payment stream than equity accrual, and the two will not generally
        agree for the same number of months paid."

        Design: Difficulty/dual_variant_calc/rto_equity_vs_payoff_diverge_on_agreement
        """
        customer, agreement, _ = setup_rto_with_n_paid_months(
            num_months=3, list_price_cents=120000, monthly_rent_cents=10000,
            equity_rate_pct=0.50,
        )
        data = validate_success(
            api.get_agreement(agreement["id"], make_customer_headers(customer["id"])), 200
        )
        # 15000 + 110000 = 125000 != 120000 (purchase price) — the 5000 fee breaks
        # complementarity between the two figures.
        assert data["accrued_equity_cents"] + data["payoff_quote_cents"] == 125000
        assert data["purchase_price_cents"] == 120000

    def test_store_credit_tradein_and_consignment_use_distinct_formulas(self, api):
        """PRD §3.7: "the offer is the appraised value multiplied by the condition's
        fraction, floored."
        PRD §3.7: "the consignor payout is the ask price minus that commission."
        PRD §3.7: "two different conserved-quantity formulas writing to the same
        customer balance."

        Design: Difficulty/dual_variant_calc/store_credit_tradein_vs_consignment_diverge_on_customer
        """
        # Trade-in path: USED appraised 80000 -> floor(80000*0.50) = 40000
        customer, trade_in = setup_offered_trade_in(condition="USED", appraised_value_cents=80000)
        accepted = validate_success(api.accept_trade_in(trade_in["id"], SM), 200)
        assert accepted["offer_cents"] == 40000

        # Consignment path for the SAME customer: ask 150000, comm 0.20
        # payout = 150000 - round(150000*0.20) = 150000 - 30000 = 120000
        listing = get_success_data(
            api.create_consignment(
                create_consignment_payload(customer["id"], ask_price_cents=150000, commission_pct=0.20),
                SA,
            )
        )
        sold = validate_success(api.sell_consignment(listing["id"], SA), 200)
        assert sold["consignor_payout_cents"] == 120000

        # Same field, both credits accumulate: 40000 + 120000 = 160000
        cust = validate_success(api.get_customer(customer["id"], SM), 200)
        assert cust["store_credit_cents"] == 160000

    def test_tradein_floors_while_consignment_rounds(self, api):
        """PRD §3.7: "a trade-in counts up a generous fraction of an appraised value
        and floors it, while a consignment counts down from a realized ask price by
        a commission and rounds half up — two different conserved-quantity formulas
        writing to the same customer balance."

        Design: Difficulty/dual_variant_calc/store_credit_tradein_vs_consignment_diverge_on_customer
        """
        customer, trade_in = setup_offered_trade_in(condition="USED", appraised_value_cents=80000)
        accepted = validate_success(api.accept_trade_in(trade_in["id"], SM), 200)
        assert accepted["offer_cents"] == 40000
        cust = validate_success(api.get_customer(customer["id"], SM), 200)
        # only the trade-in credit so far
        assert cust["store_credit_cents"] == 40000


# ===========================================================================
# Difficulty / combinatorial_formula
# ===========================================================================
class TestRepairInvoiceRushBranch:
    def test_rush_surcharge_applies_to_subtotal_not_labor(self, api):
        """PRD §3.6: "If rush is true, a rush surcharge equal to twenty-five percent
        of the subtotal (not of labor alone) is added; if rush is false the surcharge
        is zero. The quoted total is the subtotal plus the surcharge, rounded half up
        to whole cents."

        Design: Difficulty/combinatorial_formula/repair_invoice_rush_branch_mode_a
        """
        customer = create_customer()
        ticket = validate_success(
            api.create_ticket(
                f.create_ticket_payload(customer["id"], labor_hours=2, labor_rate_cents=5000,
                                        parts_cost_cents=3000, rush=True),
                SA,
            ),
            201,
        )
        # labor = 10000 (>= 4000 floor); subtotal = 10000 + 3000 = 13000;
        # surcharge = 0.25 * 13000 = 3250; total = 16250 (not 13000).
        assert ticket["quoted_total_cents"] == 16250

    def test_no_rush_yields_bare_subtotal(self, api):
        """PRD §3.6: "if rush is false the surcharge is zero. The quoted total is the
        subtotal plus the surcharge, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/repair_invoice_rush_branch_mode_a
        """
        customer = create_customer()
        ticket = validate_success(
            api.create_ticket(
                f.create_ticket_payload(customer["id"], labor_hours=2, labor_rate_cents=5000,
                                        parts_cost_cents=3000, rush=False),
                SA,
            ),
            201,
        )
        # labor 10000 + parts 3000 = 13000, no surcharge -> 13000
        assert ticket["quoted_total_cents"] == 13000


class TestFinancingRoundingOrder:
    def test_prime_tier_amortization_rounds_once_at_end(self, api):
        """PRD §3.8: "a score of at least 720 earns the prime rate of 0.0599"
        PRD §3.8: "computes the exact amortized payment from that unrounded rate,
        and then rounds the final payment once to whole cents using round half up."

        Design: Difficulty/combinatorial_formula/financing_terms_rounding_order_mode_b
        """
        customer, application = setup_submitted_financing(
            credit_score=740, principal_cents=240000, term_months=12
        )
        approved = validate_success(api.approve_financing(application["id"], SM), 200)
        assert approved["status"] == "APPROVED"
        assert approved["apr_pct"] == 0.0599
        assert approved["monthly_payment_cents"] == 20655

    def test_near_prime_tier_assigned_at_floor_of_660(self, api):
        """PRD §3.8: "a score from 660 through 719 earns the near-prime rate of 0.1299"

        Design: Difficulty/combinatorial_formula/financing_terms_rounding_order_mode_b
        """
        customer, application = setup_submitted_financing(
            credit_score=660, principal_cents=240000, term_months=12
        )
        approved = validate_success(api.approve_financing(application["id"], SM), 200)
        assert approved["apr_pct"] == 0.1299


class TestLessonTuitionStackedDiscount:
    def test_volume_then_bundle_order_pinned(self, api):
        """PRD §3.9: "the after-volume figure is the base monthly multiplied by one
        minus the volume fraction, rounded half up to whole cents."
        PRD §3.9: "the monthly tuition is the after-volume figure multiplied by one
        minus the bundle fraction, rounded half up to whole cents. The volume discount
        is applied before the bundle discount, and each step rounds in turn."

        Design: Difficulty/combinatorial_formula/lesson_tuition_stacked_discount_order_mode_c
        """
        customer, agreement, enrollment = setup_enrollment_linked_to_active_agreement(
            sessions_per_month=8, base_rate_cents=5000, instrument_family="ORCHESTRA",
        )
        # base 5000*8 = 40000; volume 15% -> 34000; bundle 20% on 34000 -> 27200
        assert enrollment["monthly_tuition_cents"] == 27200
        assert enrollment["status"] == "ACTIVE"

    def test_volume_discount_only_when_no_active_bundle(self, api):
        """PRD §3.9: "if sessions_per_month is at least 8, a volume discount of
        fifteen percent applies, otherwise no volume discount applies"
        PRD §3.9: "a bundle discount of twenty percent applies only when a
        rental_agreement_id is set and the linked RentalAgreement is currently
        ACTIVE, otherwise no bundle discount applies"

        Design: Difficulty/combinatorial_formula/lesson_tuition_stacked_discount_order_mode_c
        """
        customer = create_customer()
        # No rental_agreement_id -> no bundle; sessions 8 -> volume only
        enrollment = validate_success(
            api.create_enrollment(
                f.create_enrollment_payload(customer["id"], instrument_family="GUITAR",
                                            sessions_per_month=8, base_rate_cents=5000),
                SA,
            ),
            201,
        )
        # 40000 * 0.85 = 34000; no bundle -> 34000
        assert enrollment["monthly_tuition_cents"] == 34000
