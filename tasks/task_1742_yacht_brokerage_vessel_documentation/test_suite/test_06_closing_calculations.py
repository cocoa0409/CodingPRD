"""Closing-statement calculation pipeline: commission tiers and co-broke split,
tier fallback, proration rounding order, tax caps, offshore exemption."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_commission_side_split_invariant,
    get_success_data,
    set_clock,
    setup_accepted_offer,
    setup_balanced_statement,
    setup_draft_statement,
    build_statement,
    waive_all_contingencies,
    validate_success,
)

CLOSING = TEST_USERS["closing_officer_headers"]


class TestCommissionTierCoBroke:
    def test_high_tier_cobroke_split(self, api):
        """PRD §3.7: "Under the STANDARD schedule the tier rate is ten percent
        when `gross_price_cents` is below USD 5,000,000, eight percent when it is
        at least USD 5,000,000 and below USD 20,000,000, and six percent when it
        reaches USD 20,000,000" and "Otherwise the deal is co-brokered:
        `selling_side_cents` is half of `commission_cents` rounded half-up, and
        `listing_side_cents` is the remainder, computed by subtraction and never
        re-rounded, so the invariant that the two sides sum exactly to
        `commission_cents` always holds."

        Gross 2500000000 -> 6% -> 150000000; co-broke halves to 75000000 each.

        Design: Difficulty/combinatorial_formula/commission_split_tier_cobroke_nested_min_max
        """
        deal = setup_balanced_statement(
            offer_price_cents=2500000000, list_price_cents=2500000000,
            co_broke=True,
        )
        st = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert st["status"] == "BALANCED"
        assert st["commission_cents"] == 150000000
        assert st["selling_side_cents"] == 75000000
        assert st["listing_side_cents"] == 75000000
        assert_commission_side_split_invariant(st)

    def test_tier_boundary_at_twenty_million_exactly_is_high_tier(self, api):
        """PRD §3.7: "six percent when it reaches USD 20,000,000" — the boundary
        is inclusive, so gross exactly 2000000000 cents takes the HIGH tier.

        Design: Difficulty/combinatorial_formula/commission_split_tier_cobroke_nested_min_max
        """
        deal = setup_balanced_statement(
            offer_price_cents=2000000000, list_price_cents=2000000000,
            co_broke=True,
        )
        st = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert st["commission_cents"] == 120000000
        assert st["selling_side_cents"] == 60000000
        assert st["listing_side_cents"] == 60000000
        assert_commission_side_split_invariant(st)


def test_mid_tier_boundary_at_five_million_exactly(api):
    """PRD §3.7: "eight percent when it is at least USD 5,000,000 and below
    USD 20,000,000" — gross exactly 500000000 cents takes the MID tier, and
    "When the selling agent's brokerage is the listing brokerage — an in-house
    deal — the listing side keeps everything: `listing_side_cents` equals
    `commission_cents` and `selling_side_cents` is zero."

    Design: Corner/calculations/commission_mid_tier_boundary_at_5m_exactly
    """
    deal = setup_balanced_statement(
        offer_price_cents=500000000, list_price_cents=500000000
    )
    st = get_success_data(api.get_closing_statement(deal["statement"]["id"], CLOSING))
    assert st["commission_cents"] == 40000000, (
        "500000000 is at least USD 5,000,000, so MID tier 8% applies, not LOW 10%"
    )
    assert st["listing_side_cents"] == 40000000
    assert st["selling_side_cents"] == 0
    assert_commission_side_split_invariant(st)


def test_brokerage_default_premier_tier_applies_when_listing_omits(api):
    """PRD §3.7: "The schedule code comes from the listing's
    `commission_tier_code` when set, falling back to the brokerage's
    `default_commission_tier_code`; under PREMIER each tier rate is multiplied
    by 1.10 — eleven, 8.8, and 6.6 percent — with the price thresholds unchanged"

    PREMIER-default brokerage, listing silent on tier, in-house gross
    100000000 -> LOW tier 10% x 1.10 = 11% -> commission 11000000.

    Design: Corner/entities/brokerage_default_tier_applied_when_listing_omits
    """
    deal = setup_balanced_statement(
        offer_price_cents=100000000, list_price_cents=100000000,
        brokerage_overrides={"default_commission_tier_code": "PREMIER"},
    )
    st = get_success_data(api.get_closing_statement(deal["statement"]["id"], CLOSING))
    assert st["commission_cents"] == 11000000
    assert st["listing_side_cents"] == 11000000
    assert st["selling_side_cents"] == 0


class TestProrationRoundingOrder:
    def test_proration_closing_mid_month_uses_per_day_round_then_multiply(self, api):
        """PRD §3.7: "the per-day credit to the seller is that fee divided by the
        number of days in the closing month as the calendar at the closing date
        dictates, rounded half-up to whole cents first. `prorations_cents` is that
        rounded per-day figure multiplied by the number of days remaining in the
        month counting the closing day itself, after which a flat fuel credit of
        USD 750 is added with no further rounding — multiplying before rounding is
        forbidden"

        Closing 2026-08-12: round_half_up(450000/31) = 14516; 20 days remain
        inclusive; 14516 * 20 + 75000 = 365320. No escrow deposits exist, so the
        interest component is zero.

        Design: Difficulty/combinatorial_formula/proration_per_day_round_then_multiply_order
        """
        deal = setup_accepted_offer(
            offer_price_cents=300000000, list_price_cents=300000000
        )
        waive_all_contingencies(deal)
        statement = setup_draft_statement(deal)
        set_clock("2026-08-12T00:00:00Z")
        build_statement(deal, statement)
        st = get_success_data(
            api.get_closing_statement(statement["id"], CLOSING)
        )
        assert st["prorations_cents"] == 365320, (
            "pinned order is per-day round THEN multiply: 14516 * 20 + 75000"
        )

    def test_proration_on_first_of_month_exposes_rounding_order(self, api):
        """PRD §3.7: "`prorations_cents` is that rounded per-day figure multiplied
        by the number of days remaining in the month counting the closing day
        itself, after which a flat fuel credit of USD 750 is added with no further
        rounding — multiplying before rounding is forbidden, because the reversed
        order yields different cents."

        Closing 2026-08-01: 14516 * 31 = 449996 (not 450000) + 75000 = 524996.
        The forbidden reverse order would yield 450000 + 75000 = 525000.

        Design: Difficulty/combinatorial_formula/proration_per_day_round_then_multiply_order
        """
        deal = setup_balanced_statement(
            offer_price_cents=300000000, list_price_cents=300000000
        )
        st = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert st["prorations_cents"] == 524996


class TestFloridaTaxCapBoundary:
    def test_uncapped_tax_exactly_at_cap_lands_on_cap(self, api):
        """PRD §3.7: "the assessment's `amount_cents` is the smaller of that
        uncapped figure and the situs cap — landing exactly on the cap whenever
        the uncapped figure reaches or exceeds it" and "The statutory rates are
        FL 6 percent" and "only Florida caps the bill, at USD 18,000"

        FL situs, gross 30000000: 6% = 1800000, exactly the cap -> 1800000.

        Design: Difficulty/boundary_precision_check/fl_tax_cap_boundary_at_exact_cap
        """
        deal = setup_balanced_statement(
            offer_price_cents=30000000, list_price_cents=100000000
        )
        st = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert st["tax_cents"] == 1800000

    def test_uncapped_tax_one_cent_over_cap_still_capped(self, api):
        """PRD §3.7: "landing exactly on the cap whenever the uncapped figure
        reaches or exceeds it" — FL situs, gross 30000017: uncapped rounds to
        1800001, which exceeds the USD 18,000 cap, so the assessment is 1800000.

        Design: Difficulty/boundary_precision_check/fl_tax_cap_boundary_at_exact_cap
        """
        deal = setup_balanced_statement(
            offer_price_cents=30000017, list_price_cents=100000000
        )
        st = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert st["tax_cents"] == 1800000


def test_offshore_delivery_exemption_zeroes_tax(api):
    """PRD §3.7: "When the buyer elected `offshore_delivery` and the assessment's
    `exemption_code` is OFFSHORE_DELIVERY, the basis and amount are both zero —
    `tax_cents` on the statement is likewise zero — and the assessment is
    recorded directly as EXEMPT for audit"

    Design: Corner/calculations/offshore_delivery_exemption_zeroes_tax
    """
    deal = setup_balanced_statement(
        offer_price_cents=300000000,
        list_price_cents=300000000,
        buyer_overrides={"residency_state_code": "NON_US"},
        offer_overrides={"offshore_delivery": True},
    )
    st = get_success_data(api.get_closing_statement(deal["statement"]["id"], CLOSING))
    assert st["tax_cents"] == 0
    assessments = get_success_data(
        api.list_tax_assessments(deal["statement"]["id"], CLOSING)
    )
    exempt = [a for a in assessments if a["status"] == "EXEMPT"]
    assert exempt, "an EXEMPT assessment row must be recorded for audit"
    assert exempt[0]["amount_cents"] == 0
    assert exempt[0]["basis_cents"] == 0
