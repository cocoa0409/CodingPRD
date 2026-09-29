"""Multi-term formulae whose order of operations is observable in the result.

Present value rounds each annual term before summation, and the oversight
indirect fee re-rates the whole accumulated subtotal at a tier keyed on the
pre-fee direct figure.
"""
from test_helpers.assertions import (
    assert_ledger_figures,
    assert_oversight_figures,
    assert_percentage,
)
from test_helpers.fixtures import (
    add_alternative,
    create_investigation,
    create_listed_site,
    post_oversight,
    read_ledger,
    read_site,
    set_clock,
)


def _copper_flats_alternatives():
    """Two thirty-year alternatives priced at the same 700 basis point rate."""
    set_clock("2027-02-10T08:00:00Z")
    site = create_listed_site(
        name="Copper Flats Plating", epa_region=8, hrs_score=39.10
    )
    investigation = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-2 feasibility study, groundwater",
    )
    alt_a = add_alternative(
        investigation["id"],
        label="PUMP_AND_TREAT",
        capital_cost_cents=1_250_000_000,
        annual_om_cost_cents=45_000_000,
        om_years=30,
        discount_rate_bp=700,
        effectiveness_score=90,
        implementability_score=62,
    )
    alt_b = add_alternative(
        investigation["id"],
        label="MONITORED_NATURAL_ATTENUATION",
        capital_cost_cents=620_000_000,
        annual_om_cost_cents=22_000_000,
        om_years=30,
        discount_rate_bp=700,
        effectiveness_score=74,
        implementability_score=96,
    )
    return site, investigation, alt_a, alt_b


class TestRemedyPresentValueRoundsEachAnnualTerm:
    def test_thirty_annual_terms_are_each_rounded_before_entering_the_sum(self):
        """Per-term rounding puts the present value one cent above the naive answer.

        PRD: "The `npv_cents` is the `capital_cost_cents` plus, for each operating year counted from 1 up to and including `om_years`, the `annual_om_cost_cents` divided by one plus the discount rate raised to the power of that year number — **with each annual term rounded half up to whole cents before it is added into the running total**."

        Design: Difficulty/combinatorial_formula/remedy_npv_rounds_each_annual_term_before_summation
        """
        _, _, alt_a, alt_b = _copper_flats_alternatives()

        assert alt_a["npv_cents"] == 1808406854
        assert alt_a["npv_cents"] != 1808406853
        assert alt_b["npv_cents"] == 892998906

    def test_cost_score_normalises_the_present_value_in_half_million_dollar_units(self):
        """The cost score subtracts the present value in units of 50,000,000 cents.

        PRD: "Take 100 and subtract the present value expressed in units of 50,000,000 cents — that is, in units of half a million dollars."

        Design: Difficulty/combinatorial_formula/remedy_npv_rounds_each_annual_term_before_summation
        """
        _, _, alt_a, alt_b = _copper_flats_alternatives()

        assert_percentage(alt_a["cost_score"], 63.83, "cost_score")
        assert_percentage(alt_b["cost_score"], 82.14, "cost_score")

    def test_remedy_score_uses_the_unexceeded_weighting_before_any_submission(self):
        """With the action level not yet exceeded the balanced weighting applies.

        PRD: "When the action level has not been exceeded, the score is 0.45 times the `effectiveness_score`, plus 0.35 times the `implementability_score`, plus 0.20 times the `cost_score`, again rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/remedy_npv_rounds_each_annual_term_before_summation
        """
        _, _, alt_a, alt_b = _copper_flats_alternatives()

        assert_percentage(alt_a["remedy_score"], 74.97, "remedy_score")
        assert_percentage(alt_b["remedy_score"], 83.33, "remedy_score")
        assert alt_a["selected_by_rod_id"] in (None, "")


class TestOversightIndirectTierKeyedOnPreFeeSubtotal:
    def test_first_posting_rates_the_subtotal_inside_the_first_tier(self):
        """A 3,000,000 cent subtotal is rated at 1,550 basis points.

        PRD: "When `oversight_direct_cents` is at most 5,000,000 cents — fifty thousand dollars — the rate is 1,550 basis points, or 15.50 percent."

        Design: Difficulty/combinatorial_formula/oversight_indirect_tier_keyed_on_pre_fee_direct_subtotal
        """
        set_clock("2027-03-01T08:00:00Z")
        site = create_listed_site(
            name="Redmill Wood Treating", epa_region=6, hrs_score=33.40
        )
        posted = post_oversight(
            site["id"], 3_000_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-15"
        )

        assert_oversight_figures(posted, 3_000_000, 1550, 465_000, 3_465_000)

    def test_second_posting_keys_the_tier_on_the_direct_subtotal_not_the_billed_total(self):
        """A direct subtotal of 4,600,000 bills 5,313,000, not 5,186,500.

        PRD: "First, **the tier is keyed on the pre-fee direct subtotal, never on the billed total** — keying it on the billed figure is wrong and observably so, because a subtotal just under a ceiling can produce a billed total just over it and would then be re-rated at the wrong tier."

        Design: Difficulty/combinatorial_formula/oversight_indirect_tier_keyed_on_pre_fee_direct_subtotal
        """
        set_clock("2027-03-01T08:00:00Z")
        site = create_listed_site(
            name="Redmill Wood Treating", epa_region=6, hrs_score=33.40
        )
        post_oversight(
            site["id"], 3_000_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-15"
        )
        posted = post_oversight(
            site["id"], 1_600_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-28"
        )

        assert posted["oversight_direct_cents"] == 4_600_000
        assert posted["oversight_indirect_rate_bp"] == 1550
        assert posted["oversight_indirect_cents"] == 713_000
        assert posted["oversight_billed_cents"] == 5_313_000
        assert posted["oversight_billed_cents"] != 5_186_500

    def test_cost_ledger_reports_the_billed_oversight_as_unrecovered_response_cost(self):
        """Billed oversight is the whole response-cost basis and none of it is recovered.

        PRD: "Because billed oversight cost enters the response-cost basis, every accepted posting also recomputes `total_response_cost_cents`, the rest of the cost ledger, and the site's `cost_posture`."

        Design: Difficulty/combinatorial_formula/oversight_indirect_tier_keyed_on_pre_fee_direct_subtotal
        """
        set_clock("2027-03-01T08:00:00Z")
        site = create_listed_site(
            name="Redmill Wood Treating", epa_region=6, hrs_score=33.40
        )
        post_oversight(
            site["id"], 3_000_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-15"
        )
        post_oversight(
            site["id"], 1_600_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-28"
        )

        ledger = read_ledger(site["id"])
        assert_ledger_figures(ledger, 5_313_000, 0, 0, 5_313_000)
        assert ledger["oversight_cap_utilization_pct"] is None

    def test_crossing_a_tier_ceiling_re_rates_the_whole_subtotal_without_blending(self):
        """A 6,000,000 subtotal is entirely re-rated at 1,275 basis points.

        PRD: "Second, **the indirect component is recomputed in full on every posting**: when a posting carries the subtotal across a tier ceiling, the entire accumulated subtotal is re-rated at the new rate."

        Design: Difficulty/combinatorial_formula/oversight_indirect_tier_keyed_on_pre_fee_direct_subtotal
        """
        set_clock("2027-03-01T08:00:00Z")
        site = create_listed_site(
            name="Redmill Wood Treating", epa_region=6, hrs_score=33.40
        )
        post_oversight(
            site["id"], 3_000_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-15"
        )
        post_oversight(
            site["id"], 1_600_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-28"
        )
        posted = post_oversight(
            site["id"], 1_400_000, cost_category="LEGAL_SUPPORT", incurred_on="2027-03-01"
        )

        assert_oversight_figures(posted, 6_000_000, 1275, 765_000, 6_765_000)
        assert posted["oversight_indirect_cents"] != 902_500
        assert read_site(site["id"])["cost_posture"] == "OPEN"
