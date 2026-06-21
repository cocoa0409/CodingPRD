"""Difficulty Rule 2 — combinatorial_formula.

Two non-linear formula modes:
  (a) franchise_tax — three-input tiered selection (state × entity_type × revenue_band).
  (b) late_fee_accrual — rounding ORDER pinned (per-day round then multiply).
"""
from test_helpers import (
    set_clock,
    setup_active_llc,
    setup_active_corp,
    create_draft_annual_report,
    file_annual_report,
)


class TestFranchiseTaxThreeInputTieredSelection:
    """PRD §3.8: BASE_BY_STATE picks rows by (state, entity_type);
    TIER_MULT_X100 picks multiplier by revenue_band; per-state MIN_FLOOR
    imposes max() lower bound. No closed-form linear formula.
    """

    def test_fl_llc_large_yields_20812_at_file(self, api):
        """PRD §3.8: "Florida charges 138.75 dollars for an `LLC`, 150 dollars for a
        `CORP`, and 500 dollars for an `LP`"
        PRD §3.8: "`LARGE` is 1.50x (multiplier 150)"
        PRD §3.8: "The raw amount is the base in cents multiplied by the tier
        multiplier, then divided by 100 with integer floor"

        Design: Difficulty/combinatorial_formula/cf_franchise_tax_three_input_tiered_selection_mode_a
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="ECHO FL LLC", formation_state_code="FL", revenue_band="LARGE"
        )
        ar = create_draft_annual_report(be, 2024)
        filed = file_annual_report(be, ar["id"])
        # FL LLC LARGE: base=13875, mult=150 -> raw=(13875*150)//100=20812; floor=13875 -> 20812.
        assert filed["franchise_tax_amount_cents"] == 20812
        assert filed["late_fee_cents"] == 0

    def test_fl_corp_large_yields_22500_at_file(self, api):
        """PRD §3.8: "Florida charges 138.75 dollars for an `LLC`, 150 dollars for a
        `CORP`, and 500 dollars for an `LP`"
        PRD §3.8: "The final `franchise_tax_amount_cents` is the larger of the raw
        amount and the state's minimum floor."

        Design: Difficulty/combinatorial_formula/cf_franchise_tax_three_input_tiered_selection_mode_a
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_corp(
            legal_name="FOXTROT FL INC", formation_state_code="FL", revenue_band="LARGE"
        )
        ar = create_draft_annual_report(be, 2024)
        filed = file_annual_report(be, ar["id"])
        # FL CORP LARGE: base=15000, mult=150 -> raw=22500; floor=13875 -> 22500.
        assert filed["franchise_tax_amount_cents"] == 22500
        assert filed["late_fee_cents"] == 0

    def test_fl_llc_vs_corp_diverge_on_entity_type_alone(self, api):
        """PRD §3.8: "The first input is a state-and-type base: California charges
        800 dollars for every entity type, Delaware charges 300 dollars for `LLC`
        and `LP` entities and 175 dollars for a `CORP`, New York charges a flat 25
        dollars across types, Texas charges nothing, Florida charges 138.75 dollars
        for an `LLC`, 150 dollars for a `CORP`, and 500 dollars for an `LP`, and
        Wyoming charges 60 dollars for `LLC` and `CORP` and 100 dollars for `LP`."

        Design: Difficulty/combinatorial_formula/cf_franchise_tax_three_input_tiered_selection_mode_a
        """
        set_clock("2025-03-01T00:00:00Z")
        llc_be, _ = setup_active_llc(
            legal_name="ECHO TYPE LLC", formation_state_code="FL", revenue_band="LARGE"
        )
        corp_be, _ = setup_active_corp(
            legal_name="FOXTROT TYPE INC", formation_state_code="FL", revenue_band="LARGE"
        )
        ar_llc = create_draft_annual_report(llc_be, 2024)
        ar_corp = create_draft_annual_report(corp_be, 2024)
        f_llc = file_annual_report(llc_be, ar_llc["id"])
        f_corp = file_annual_report(corp_be, ar_corp["id"])
        # Same state, same band, different entity_type → different assessed tax.
        assert f_llc["franchise_tax_amount_cents"] != f_corp["franchise_tax_amount_cents"]
        assert f_llc["franchise_tax_amount_cents"] == 20812
        assert f_corp["franchise_tax_amount_cents"] == 22500


class TestLateFeeRoundingOrder:
    """PRD §3.9: per-day fee is rounded half-up to cents BEFORE multiplication by
    days-late. The 'sum then round' alternative is forbidden.
    """

    def test_de_5_days_past_deadline_yields_555_cents_late_fee(self, api):
        """PRD §3.9: "The per-day fee in integer cents is the daily rate plus 50
        hundredths divided by 100 with integer floor — that is, the per-day rate is
        rounded half-up to cents before any multiplication. The accrued amount is
        then the per-day fee in integer cents multiplied by the integer days-late
        count."
        PRD §3.9: "Delaware 111.00 cents per day (11100)"
        PRD §3.9: "the system computes the difference in whole seconds, then converts
        to days-late by ceiling division — any partial day counts as a full day, and
        the minimum days-late is 1."

        Design: Difficulty/combinatorial_formula/cf_late_fee_rounding_order_per_day_then_sum_mode_b
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="GOLF DE LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        # Advance to 4 days 00:00:01 past 2025-04-15T23:59:59Z =>
        # 2025-04-20T00:00:00Z. delta = 345601s; ceil(345601/86400)=5 days.
        # per_day = (11100+50)//100 = 111; accrued = 111*5 = 555.
        set_clock("2025-04-20T00:00:00Z")
        filed = file_annual_report(be, ar["id"])
        assert filed["late_fee_cents"] == 555, (
            f"DE 5-day late fee should be 555 cents (per-day-then-sum), "
            f"got {filed['late_fee_cents']}"
        )

    def test_de_zero_band_franchise_tax_unchanged_at_30000(self, api):
        """PRD §3.8: "Delaware charges 300 dollars for `LLC` and `LP` entities"
        PRD §3.8: "`ZERO` and `MICRO` are 1.00x (multiplier 100)"
        PRD §3.7: "Filing a report — moving it from either `DRAFT` or `DELINQUENT` to
        `FILED` — re-evaluates the assessed franchise tax against the parent's
        current `revenue_band` (the assessed-final variant in §3.8)"

        Design: Difficulty/combinatorial_formula/cf_late_fee_rounding_order_per_day_then_sum_mode_b
        """
        set_clock("2024-12-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="GOLF FT LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        set_clock("2025-04-20T00:00:00Z")
        filed = file_annual_report(be, ar["id"])
        # DE LLC ZERO: base=30000, mult=100 -> raw=30000; floor=17500 -> 30000.
        assert filed["franchise_tax_amount_cents"] == 30000
