"""RCP calculation variants and payoff_projection — PRD §3.6 + §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    create_draft_oic,
    create_and_activate_agreement,
    create_taxpayer,
    create_tax_liability,
    decide_offer_in_compromise_payload,
    get_offer_in_compromise,
    make_oic_officer_headers,
    parse_iso,
    pay_oic_deposit,
    setup_oic_under_review,
    submit_oic,
    take_up_oic,
    validate_error,
    validate_success,
)


class TestRCPVariants:

    def test_rcp_lump_sum_factor_12_for_schedule_5(self, api):
        """PRD §3.9: "If the proposed payoff schedule is at most five
        monthly installments, the factor is 12; if the schedule is at
        most twenty-four monthly installments, the factor is 24."
        PRD §3.9: "rcp_cents = future_income_cents + equity_cents."

        Claim: MDI 200_000 * 12 = 2_400_000.

        # difficulty: dual_variant_calc/rcp_lump_sum_vs_periodic
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=5_000_000,
        )
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=3_000_000,
            schedule_months=5,
        )
        refreshed = get_offer_in_compromise(oic["id"])
        assert refreshed["rcp_cents"] == 2_400_000, (
            "PRD §3.9: 'rcp_cents = future_income_cents + equity_cents' "
            "= 200_000*12 + 0 = 2_400_000 for schedule_months=5"
        )

    def test_rcp_periodic_factor_24_for_schedule_24(self, api):
        """PRD §3.9: "If the proposed payoff schedule is at most five
        monthly installments, the factor is 12; if the schedule is at
        most twenty-four monthly installments, the factor is 24."

        Claim: MDI 200_000 * 24 = 4_800_000 (exactly 2x the lump-sum
        variant).

        # difficulty: dual_variant_calc/rcp_lump_sum_vs_periodic
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=5_000_000,
        )
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=5_000_000,
            schedule_months=24,
        )
        refreshed = get_offer_in_compromise(oic["id"])
        assert refreshed["rcp_cents"] == 4_800_000, (
            "PRD §3.9: schedule 24 picks FACTOR=24 => 200_000*24 = 4_800_000"
        )

    def test_offer_below_rcp_rejected_on_accept(self, api):
        """PRD §3.8: "an accept where offer_amount_cents is less than
        rcp_cents is rejected with ERR_OIC_BELOW_RCP."

        Claim: offer 1_000_000 against rcp 2_400_000 → ERR_OIC_BELOW_RCP.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=2_000_000,
        )
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_000_000,
            schedule_months=5,
            deposit_cents=200_000,
            take_up_officer_id="oic-officer-A",
        )
        resp = api.decide_offer_in_compromise(
            oic["id"],
            decide_offer_in_compromise_payload("ACCEPT"),
            make_oic_officer_headers("oic-officer-B"),
        )
        validate_error(resp, ApiErrorId.ERR_OIC_BELOW_RCP.value)


class TestPayoffProjection:

    def test_payoff_long_term_pinned_per_pinned_rounding_order(self, api):
        """PRD §3.6: "The pinned rounding order is interest first, then
        penalty, then add — the server must not compute the sum of
        interest and penalty and round once at the end."

        Claim: $10,000 balance with $2,000/month at activation
        2020-01-01 reaches a balance of 0 after exactly 6 simulated
        months under PRD §3.6's pinned per-component rounding —
        planned_payoff_date == 2020-07-01.

        Per-month simulation (interest 0.006667, penalty 0.0025):
          month 1: bal 1_000_000 -> +int 6_667 +pen 2_500 -> 1_009_167
                   -> -200_000 -> 809_167
          month 2: bal 809_167   -> +int 5_396 +pen 2_023 -> 816_586
                   -> -200_000 -> 616_586
          month 3: bal 616_586   -> +int 4_112 +pen 1_541 -> 622_239
                   -> -200_000 -> 422_239
          month 4: bal 422_239   -> +int 2_815 +pen 1_056 -> 426_110
                   -> -200_000 -> 226_110
          month 5: bal 226_110   -> +int 1_508 +pen   565 -> 228_183
                   -> -200_000 -> 28_183
          month 6: bal 28_183    -> +int   188 +pen    70 -> 28_441
                   -> -28_441 = 0 (final partial payment)

        # difficulty: combinatorial_formula/payoff_projection_rounding_order
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=300_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_000_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="DDIA",
        )
        assert agreement["agreement_type"] == "LONG_TERM", (
            "$10k balance with $2k/month is LONG_TERM (not SHORT_TERM "
            "because 4 months * 200_000 = 800_000 < 1_000_000 + interest)"
        )
        expected = parse_iso("2020-07-01T00:00:00.000Z")
        actual = parse_iso(agreement["planned_payoff_date"])
        assert actual == expected, (
            f"PRD §3.6 pinned rounding order yields planned_payoff_date "
            f"2020-07-01; got {actual.isoformat()}"
        )
