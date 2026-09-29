"""Calculations: the per-year spread, the two de minimis branches, the certified
input filter, the direct-attribution basis, the bond cap, the arbitration window
and the two exposure weightings."""

import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers.fixtures import (
    adjudicate_asset_sale,
    build_asset_sale,
    build_issued_assessment,
    build_priced_assessment,
    build_registry,
    build_reviewed_assessment,
    create_assessment,
    decide_review_request,
    determine_withdrawal_event,
    file_certified_valuations,
    file_contribution_record,
    get_assessment,
    get_employer,
    get_group,
    get_record,
    get_review_request,
    get_transaction,
    get_valuation,
    initiate_arbitration,
    issue_assessment,
    latest_schedule,
    report_withdrawal_event,
    set_clock,
    submit_asset_sale,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_TRUSTEE_SECONDARY_HEADERS,
    TEST_USERS,
)
from test_helpers.types import (
    AdjudicationDisposition,
    AllocationMethod,
    AssumptionRuling,
    ReviewDecision,
)

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

DECIDING_TRUSTEE_ID = TEST_USERS["plan_trustee_secondary"]["user_id"]

# Six plan years, 600000 base units and 12000004 cents: the spread is 100000 units
# and 2000000 cents a year, with the four odd cents parked in 2020.
SIX_YEAR_RECORD = (
    {
        "plan_year_start": 2020,
        "plan_year_end": 2025,
        "contribution_base_units": 600_000,
        "contribution_amount_cents": 12_000_004,
        "contribution_rate_cents_per_cbu": 1_000,
    },
)

# A plan small enough that seventy-five basis points of its UVB total falls below
# the flat statutory cap.
SMALL_PLAN_VALUATION = {
    "uvb_total_cents": 400_000_000,
    "uvb_pool_cents": 40_000_000,
    "all_employer_contributions_cents": 100_000_000,
    "all_employer_cbu": 100_000,
}
SMALL_PLAN_RECORD = (
    {
        "plan_year_start": 2021,
        "plan_year_end": 2025,
        "contribution_base_units": 12_500,
        "contribution_amount_cents": 6_250_000,
        "contribution_rate_cents_per_cbu": 500,
    },
)

DIRECT_ATTRIBUTION_PLAN = {
    "allocation_method": AllocationMethod.DIRECT_ATTRIBUTION.value,
    "unattributable_uvb_cents": 1_000_000_000,
}
ATTRIBUTED_EMPLOYER = dict(
    BASELINE_EMPLOYER,
    directly_attributed_vested_benefits_cents=500_000_000,
    directly_attributed_assets_cents=200_000_000,
)

# Contribution dollars of 20000000, 25000000 and 30000000 for 2023 through 2025:
# a three-year average of 25000000 against a most recent year of 30000000.
SELLER_HISTORY = tuple(
    {
        "plan_year_start": year,
        "plan_year_end": year,
        "contribution_base_units": cbu,
        "contribution_amount_cents": cents,
        "contribution_rate_cents_per_cbu": 1_000,
    }
    for year, cbu, cents in (
        (2023, 20_000, 20_000_000),
        (2024, 25_000, 25_000_000),
        (2025, 30_000, 30_000_000),
    )
)

EXPENSIVE_SALE = {
    "closing_date": "2026-05-01T00:00:00Z",
    "closing_plan_year": 2026,
    "purchase_price_cents": 300_000_000,
    "bond_amount_cents": 30_000_000,
    "buyer_assumes_contribution_obligation": True,
    "workforce_continuity_pct": 0.8,
    "asset_continuity_pct": 0.6,
    "customer_continuity_pct": 0.6,
}
CHEAP_SALE = dict(
    EXPENSIVE_SALE, purchase_price_cents=20_000_000, bond_amount_cents=20_000_000
)
BELOW_THRESHOLD_SALE = dict(EXPENSIVE_SALE, customer_continuity_pct=0.5)


class TestThePerYearSpread:
    def test_the_odd_cents_land_in_the_earliest_year_and_stay_out_of_the_ratio_window(
        self, api
    ):
        """The record's earliest year sits before the five-year window, so the four odd
        cents never reach the numerator and the gross lands on the phase-out start.

        PRD 3.3: "The contribution-dollar figure for a year is derived the same way from
        `contribution_amount_cents`: floor division by the interval length, with the entire
        remainder in cents added to the earliest plan year of the interval."

        Design: Corner/calculations/the_spread_remainder_of_a_multi_year_record_lands_in_the_earliest_plan_year
        """
        scenario = build_priced_assessment(
            api,
            employer_overrides=BASELINE_EMPLOYER,
            contribution_entries=SIX_YEAR_RECORD,
        )
        assessment = scenario["assessment"]

        assert assessment["gross_allocated_cents"] == 10_000_000
        assert assessment["de_minimis_reduction_cents"] == 5_000_000
        assert assessment["net_assessed_cents"] == 5_000_000
        assert assessment["annual_payment_cents"] == 100_000_000
        assert assessment["high_3yr_average_cbu"] == pytest.approx(100_000.0, abs=0.0001)
        assert assessment["peak_contribution_rate_cents_per_cbu"] == 1_000
        assert assessment["allocation_method_applied"] == "MODIFIED_PRESUMPTIVE"
        assert assessment["pool_term_breakdown"] == []


class TestTheDeMinimisBase:
    def test_seventy_five_basis_points_of_a_small_plan_binds_below_the_flat_cap(self, api):
        """On a 400000000-cent UVB total the fraction gives 3000000, so the reduction is
        3000000 rather than the statutory 5000000 and something is still assessed.

        PRD 3.5: "The base reduction is the lesser of that cap and seventy-five basis
        points of the anchor valuation's `uvb_total_cents` — three quarters of one percent
        — with the percentage figure **floored** to whole cents."

        Design: Corner/calculations/the_de_minimis_base_is_capped_by_the_uvb_fraction_not_by_the_statutory_five_million
        """
        scenario = build_priced_assessment(
            api,
            employer_overrides=BASELINE_EMPLOYER,
            valuation_overrides=SMALL_PLAN_VALUATION,
            contribution_entries=SMALL_PLAN_RECORD,
        )
        assessment = scenario["assessment"]

        assert assessment["gross_allocated_cents"] == 5_000_000
        assert assessment["de_minimis_variant_applied"] == "STATUTORY"
        assert assessment["de_minimis_reduction_cents"] == 3_000_000
        assert assessment["net_assessed_cents"] == 2_000_000
        assert assessment["annual_payment_cents"] == 1_250_000


class TestTheCertifiedInputFilter:
    def test_the_amended_record_leaves_every_window_and_reshapes_the_schedule(self, api):
        """The superseded row still covers 2021 through 2025, yet only the corrected figures
        reach the gross, the peak rate and the twenty-year cap.

        PRD 2.5: "For contribution history, that means a `ContributionRecord` whose `status`
        is `CERTIFIED`; records whose `status` has become `AMENDED` or `VOID` leave every
        input set immediately and permanently."

        Design: Corner/calculations/amended_contribution_records_are_excluded_from_every_allocation_window
        """
        registry = build_registry(api, employer_overrides=BASELINE_EMPLOYER)
        employer_id = registry["employer"]["id"]
        valuations = file_certified_valuations(api, registry["plan"]["id"])

        original = file_contribution_record(
            api,
            employer_id,
            2021,
            2025,
            contribution_base_units=250_000,
            contribution_amount_cents=250_000_000,
            contribution_rate_cents_per_cbu=1_000,
        )
        correction = file_contribution_record(
            api,
            employer_id,
            2021,
            2025,
            contribution_base_units=100_000,
            contribution_amount_cents=100_000_000,
            contribution_rate_cents_per_cbu=400,
            supersedes_record_id=original["id"],
        )

        assert get_record(api, original["id"])["status"] == "AMENDED"
        assert get_record(api, correction["id"])["status"] == "CERTIFIED"
        _rows, meta = validate_paginated(
            api.list_contribution_records(
                FUND_ADMINISTRATOR_HEADERS,
                {"employer_id": employer_id, "status": "CERTIFIED"},
            )
        )
        assert meta["total_count"] == 1

        event = determine_withdrawal_event(
            api, report_withdrawal_event(api, employer_id)["id"]
        )
        assessment = create_assessment(api, event["id"])
        assert assessment["gross_allocated_cents"] == 100_000_000
        assert assessment["de_minimis_reduction_cents"] == 0
        assert assessment["net_assessed_cents"] == 100_000_000
        assert assessment["annual_payment_cents"] == 8_000_000
        assert assessment["peak_contribution_rate_cents_per_cbu"] == 400

        issue_assessment(api, assessment["id"])
        schedule = latest_schedule(api, assessment["id"])
        assert schedule["amortization_years"] == 20
        assert schedule["forgiven_by_cap_cents"] == 15_247_886
        assert schedule["capped_basis_cents"] == 84_752_114
        assert schedule["installment_count"] == 80
        assert schedule["quarterly_installment_cents"] == 1_059_401
        assert schedule["final_installment_cents"] == 1_059_435

        anchor = get_valuation(api, valuations[2025]["id"])
        assert anchor["allocated_uvb_cents"] == 100_000_000
        assert anchor["unallocated_uvb_cents"] == 9_900_000_000


class TestTheDirectAttributionBasis:
    def test_attributed_benefits_and_a_slice_of_the_unattributable_pool_replace_the_ratio(
        self, api
    ):
        """The anchor's UVB total drops out of the arithmetic: 300000000 of net attributed
        benefits plus a 25000000 slice of the pool makes 325000000, not the 250000000 the
        ratio basis would have produced.

        PRD 3.5: "Under `DIRECT_ATTRIBUTION`, the anchor valuation's `uvb_total_cents` is
        ignored entirely." "The basis is then the employer's
        `directly_attributed_vested_benefits_cents` less its `directly_attributed_assets_cents`
        plus that share, with the whole expression floored at 0 so it can never be negative."

        Design: Corner/calculations/the_direct_attribution_variant_replaces_the_ratio_basis_with_attributed_benefits
        """
        scenario = build_issued_assessment(
            api,
            plan_overrides=DIRECT_ATTRIBUTION_PLAN,
            employer_overrides=ATTRIBUTED_EMPLOYER,
        )
        assessment = scenario["assessment"]

        assert assessment["allocation_method_applied"] == "DIRECT_ATTRIBUTION"
        assert assessment["pool_term_breakdown"] == []
        assert assessment["gross_allocated_cents"] == 325_000_000
        assert assessment["de_minimis_reduction_cents"] == 0
        assert assessment["net_assessed_cents"] == 325_000_000
        assert assessment["annual_payment_cents"] == 50_000_000

        schedule = scenario["schedule"]
        assert schedule["amortization_years"] == 9
        assert schedule["forgiven_by_cap_cents"] == 0
        assert schedule["installment_count"] == 36
        assert schedule["quarterly_installment_cents"] == 9_027_777
        assert schedule["final_installment_cents"] == 9_027_805


class TestTheRequiredBond:
    def test_the_greater_of_the_two_lookbacks_is_then_trimmed_to_the_purchase_price(
        self, api
    ):
        """On identical history the 300000000-cent sale bonds the 30000000 most recent year,
        while the 20000000-cent sale is trimmed to its own price.

        PRD 3.9: "It compares that rounded average with the contribution dollars of the single
        plan year immediately preceding the closing plan year and takes the greater of the two.
        It then caps the result at `purchase_price_cents` and takes the lesser."

        Design: Corner/calculations/the_required_sale_of_assets_bond_is_capped_by_the_purchase_price
        """
        scenario = build_asset_sale(
            api, contribution_entries=SELLER_HISTORY, sale_overrides=EXPENSIVE_SALE
        )
        expensive = scenario["transaction"]
        cheap = submit_asset_sale(
            api,
            scenario["employer"]["id"],
            scenario["buyer_group"]["id"],
            **CHEAP_SALE,
        )

        assert expensive["required_bond_cents"] == 30_000_000
        assert cheap["required_bond_cents"] == 20_000_000

        for submission in (expensive, cheap):
            assert submission["status"] == "SUBMITTED"
            assert submission["exemption_status"] == "PENDING"
            assert submission["successor_determination"] == "PENDING"
            assert submission["substantial_continuity_score"] == pytest.approx(
                0.0, abs=0.0001
            )
            assert submission["bond_period_end_plan_year"] is None
            assert submission["adjudicated_at"] is None

        buyer = get_group(api, scenario["buyer_group"]["id"])
        assert buyer["bond_posture"] == "UNBONDED"
        assert buyer["contingent_exposure_cents"] == 0


class TestTheArbitrationWindow:
    def test_the_inner_bound_wins_and_the_last_day_is_still_timely(self, api):
        """A decision ninety days before the outer bound pulls the deadline back to
        2026-11-30, and an initiation at exactly that instant is accepted.

        PRD 3.8: "An inner bound is the trigger instant advanced by sixty days, or absent
        where there is no trigger instant. An outer bound is always `filed_at` advanced by one
        hundred and eighty days. `arbitration_deadline_at` is the outer bound where there is
        no inner bound, and otherwise the earlier of the inner and outer bounds. An
        arbitration initiated at exactly `arbitration_deadline_at` is timely; comparisons are
        at second granularity."

        Design: Corner/calculations/the_arbitration_deadline_takes_the_inner_bound_and_is_inclusive_on_its_last_day
        """
        scenario = build_reviewed_assessment(
            api, decision=None, employer_overrides=BASELINE_EMPLOYER
        )
        filed = scenario["review_request"]
        assert filed["plan_response_deadline_at"].startswith("2026-12-30T00:00:00")
        # While the request is PENDING there is no inner bound, so the deadline sits on
        # the outer bound of 180 days after filing.
        assert filed["arbitration_deadline_at"].startswith("2027-02-28T00:00:00")

        set_clock(api, "2026-10-01T00:00:00Z")
        decided = decide_review_request(
            api,
            filed["id"],
            decision=ReviewDecision.AFFIRMED.value,
            assumption_ruling=AssumptionRuling.REJECTED.value,
            headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
        )
        assert decided["arbitration_deadline_at"].startswith("2026-11-30T00:00:00")

        set_clock(api, "2026-11-30T00:00:00Z")
        arbitration = initiate_arbitration(
            api,
            scenario["assessment"]["id"],
            filed["id"],
            scenario["employer"]["id"],
        )
        assert arbitration["status"] == "BRIEFING"
        assert arbitration["round_number"] == 1

        assert (
            get_assessment(api, scenario["assessment"]["id"])["review_status"] == "DECIDED"
        )

        request = get_review_request(api, filed["id"])
        assert request["status"] == "DECIDED"
        assert request["decision"] == "AFFIRMED"
        assert request["assumption_ruling"] == "REJECTED"
        assert request["decided_by_user_id"] == DECIDING_TRUSTEE_ID
        assert request["recomputed_net_assessed_cents"] is None


class TestTheSellerContinuingWeighting:
    def test_a_bonded_exemption_scores_a_quarter_of_the_contingent_exposure(self, api):
        """The 30000000-cent bond lands in contingent exposure and is weighted at a quarter,
        so the buying group scores 75.0000 while the seller keeps contributing.

        PRD 3.9: "Where that transaction's `exemption_status` is `EXEMPT_4204`, the
        seller-continuing weighting applies: `exposure_score` is `joint_exposure_cents` plus
        one quarter of `contingent_exposure_cents`, all divided by 100,000, rounded half up to
        four decimal places."

        Design: Corner/calculations/a_bonded_sale_of_assets_scores_only_a_quarter_of_the_buyers_contingent_exposure
        """
        scenario = build_asset_sale(
            api, contribution_entries=SELLER_HISTORY, sale_overrides=EXPENSIVE_SALE
        )
        certified = adjudicate_asset_sale(
            api,
            scenario["transaction"]["id"],
            AdjudicationDisposition.CERTIFY_4204_EXEMPTION.value,
        )

        assert certified["status"] == "EXEMPTION_CERTIFIED"
        assert certified["exemption_status"] == "EXEMPT_4204"
        assert certified["bond_period_end_plan_year"] == 2031
        assert certified["adjudicated_at"].startswith("2026-08-01T00:00:00")
        assert certified["successor_determination"] == "PENDING"
        assert certified["substantial_continuity_score"] == pytest.approx(0.0, abs=0.0001)

        buyer = get_group(api, scenario["buyer_group"]["id"])
        assert buyer["bond_posture"] == "BONDED"
        assert buyer["contingent_exposure_cents"] == 30_000_000
        assert buyer["joint_exposure_cents"] == 0
        assert buyer["exposure_score"] == pytest.approx(75.0, abs=0.0001)

        seller = get_employer(api, scenario["employer"]["id"])
        assert seller["status"] == "CONTRIBUTING"
        assert seller["outstanding_liability_cents"] == 0

        seller_group = get_group(api, scenario["group"]["id"])
        assert seller_group["exposure_score"] == pytest.approx(0.0, abs=0.0001)


class TestTheSubstantialContinuityThreshold:
    def test_a_score_of_exactly_seven_tenths_is_successor_liability(self, api):
        """Halving the workforce fraction, three tenths of the assets and a fifth of the
        customers makes 0.7000 on one sale and 0.6800 on its twin, and only the first is
        successor liability.

        PRD 3.9: "`successor_determination` becomes `SUCCESSOR_LIABLE` when that score is
        greater than or equal to 0.70 — the comparison is inclusive, so a score of exactly
        0.7000 *is* successor liability — and `NO_SUCCESSOR_LIABILITY` otherwise."

        Design: Corner/calculations/the_substantial_continuity_threshold_is_inclusive_at_exactly_zero_point_seven
        """
        scenario = build_asset_sale(
            api, contribution_entries=SELLER_HISTORY, sale_overrides=EXPENSIVE_SALE
        )
        below = submit_asset_sale(
            api,
            scenario["employer"]["id"],
            scenario["buyer_group"]["id"],
            **BELOW_THRESHOLD_SALE,
        )

        at_threshold = adjudicate_asset_sale(
            api,
            scenario["transaction"]["id"],
            AdjudicationDisposition.DETERMINE_SUCCESSOR.value,
        )
        assert at_threshold["substantial_continuity_score"] == pytest.approx(
            0.7, abs=0.0001
        )
        assert at_threshold["successor_determination"] == "SUCCESSOR_LIABLE"
        assert at_threshold["status"] == "SUCCESSOR_DETERMINED"
        assert at_threshold["exemption_status"] == "NOT_EXEMPT"
        assert at_threshold["bond_period_end_plan_year"] is None

        under = adjudicate_asset_sale(
            api, below["id"], AdjudicationDisposition.DETERMINE_SUCCESSOR.value
        )
        assert under["substantial_continuity_score"] == pytest.approx(0.68, abs=0.0001)
        assert under["successor_determination"] == "NO_SUCCESSOR_LIABILITY"
        assert under["status"] == "SUCCESSOR_DETERMINED"

        buyer = get_group(api, scenario["buyer_group"]["id"])
        assert buyer["joint_exposure_cents"] == 0
        assert buyer["exposure_score"] == pytest.approx(0.0, abs=0.0001)
        assert buyer["bond_posture"] == "UNBONDED"

        settled = get_transaction(api, scenario["transaction"]["id"])
        assert settled["successor_determination"] == "SUCCESSOR_LIABLE"
