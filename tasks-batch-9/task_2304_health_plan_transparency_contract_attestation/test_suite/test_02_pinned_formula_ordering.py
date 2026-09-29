"""Formulas whose answer depends on the order the steps are taken in.

Two orderings are pinned by the contract: reasonableness components are rounded
before they are summed, and the prescription-drug rebate cap tier is chosen from
gross spend before any rebate is deducted. Both orderings are observable in
stored fields, so each is checked against the figure the other order would have
produced.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    ApiClient,
    DISCLOSURE_UNREASONABLE,
    RX_RECONCILED,
    SECTION_D6_RX_TOTALS,
    SECTION_D7_RX_REBATES,
    VARIANT_DIRECT_ONLY,
    VENDOR_TYPE_CONSULTANT,
    VENDOR_TYPE_PBM,
    assert_rx_submission,
    assert_score_close,
    assert_unreasonableness_is_sum_of_components,
    fixtures as fx,
    validate_success,
)

# The plan year's own dates stay fixed; only the clock moves between cases.
LATE_CLOCK = "2028-05-20T09:00:00Z"
RXDC_PLAN_YEAR = {"attestation_deadline_date": "2028-12-31"}


def _consultant_disclosure(api: ApiClient, **figures: object) -> dict:
    """An ACTIVE plan year with one assessed consultant disclosure."""
    setup = fx.activated_plan_year(api)
    consultant = fx.add_contract_for_vendor_type(
        api,
        setup["plan_year"]["id"],
        VENDOR_TYPE_CONSULTANT,
        annual_fee_cents=541_600,
    )
    return fx.assessed_compensation_disclosure(
        api, consultant["contract"]["id"], **figures
    )


def _reconciled_with_two_packages(
    api: ApiClient,
    first: dict,
    second: dict,
) -> dict:
    """Reconcile a submission fed by exactly two validated packages."""
    setup = fx.activated_plan_year(api, **RXDC_PLAN_YEAR)
    plan_year_id = setup["plan_year"]["id"]
    pbm = fx.add_contract_for_vendor_type(
        api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
    )
    fx.contract_with_secured_data_rights(
        api, pbm["contract"]["id"], expires_at="2028-06-30T00:00:00Z"
    )
    submission = fx.open_rx_submission(api, plan_year_id, reference_year=2027)
    for section, figures in (
        (SECTION_D6_RX_TOTALS, first),
        (SECTION_D7_RX_REBATES, second),
    ):
        package = fx.request_package(
            api,
            submission["id"],
            pbm["vendor"]["id"],
            data_section=section,
            expected_record_count=figures["record_count"],
        )
        fx.validated_package(api, package["id"], pbm["vendor"]["id"], **figures)
    return validate_success(
        api.reconcile_rx_submission(submission["id"], COMPLIANCE_OFFICER_HEADERS)
    )


class TestReasonablenessRoundingOrder:
    """Each component is rounded first; the score is the sum of those roundings."""

    def test_stored_score_is_the_sum_of_already_rounded_components(
        self, api: ApiClient
    ) -> None:
        """The worked consultant case lands on 64.99, not on 65.00.

        PRD 3.7: "A consultant disclosure with 541,600 cents of direct
        compensation against a benchmark of 1,000,000 cents, a
        `services_scope_score` of 4 and a `disclosure_completeness_score` of 2
        produces components of 21.66, 8.33 and 35.00 and a stored score of 64.99
        — where the unpinned order would have stored 65.00."

        Design: Difficulty/combinatorial_formula/reasonableness_per_component_rounding_before_summation
        """
        fx.set_clock(api, "2027-03-02T09:00:00Z")
        assessed = _consultant_disclosure(
            api,
            direct_comp_cents=541_600,
            indirect_comp_cents=900_000,
            benchmark_median_cents=1_000_000,
            services_scope_score=4,
            disclosure_completeness_score=2,
        )

        assert_score_close(assessed["component_price_score"], 21.66)
        assert_score_close(assessed["component_scope_score"], 8.33)
        assert_score_close(assessed["component_disclosure_score"], 35.00)
        assert_score_close(assessed["unreasonableness_score"], 64.99)
        assert abs(assessed["unreasonableness_score"] - 65.00) > 0.001
        assert assessed["status"] == DISCLOSURE_UNREASONABLE
        assert assessed["variant_applied"] == VARIANT_DIRECT_ONLY

    def test_direct_only_variant_drops_the_indirect_amount_from_the_base(
        self, api: ApiClient
    ) -> None:
        """900,000 cents of indirect pay is stored but never priced.

        PRD 3.7: "For a `CONSULTANT` contract the variant `DIRECT_ONLY` applies
        and the compensation base is `direct_comp_cents` alone;
        `indirect_comp_cents` is still disclosed and still stored, but is
        deliberately excluded from the reasonableness base."

        Design: Difficulty/combinatorial_formula/reasonableness_per_component_rounding_before_summation
        """
        fx.set_clock(api, "2027-03-02T09:00:00Z")
        assessed = _consultant_disclosure(
            api,
            direct_comp_cents=541_600,
            indirect_comp_cents=900_000,
            benchmark_median_cents=1_000_000,
            services_scope_score=4,
            disclosure_completeness_score=2,
        )

        assert assessed["indirect_comp_cents"] == 900_000
        # 40 x (541,600 / 1,000,000) = 21.664 -> 21.66. Including the indirect
        # amount would give 40 x 1.4416 = 57.66 instead.
        assert_score_close(assessed["component_price_score"], 21.66)
        assert_unreasonableness_is_sum_of_components(assessed)

    def test_each_component_is_independently_rounded_to_two_places(
        self, api: ApiClient
    ) -> None:
        """Both thirds-based components round on their own before summation.

        PRD 3.7: "Each of the three components is rounded to two decimal places
        **first**, and `unreasonableness_score` is then the sum of the three
        already-rounded components."

        Design: Difficulty/combinatorial_formula/reasonableness_per_component_rounding_before_summation
        """
        fx.set_clock(api, "2027-03-02T09:00:00Z")
        assessed = _consultant_disclosure(
            api,
            direct_comp_cents=250_000,
            indirect_comp_cents=0,
            benchmark_median_cents=1_000_000,
            services_scope_score=3,
            disclosure_completeness_score=3,
        )

        # 40 x 0.25 = 10.00; 25 x 2 / 3 = 16.6667 -> 16.67; 35 x 2 / 3 = 23.3333 -> 23.33.
        assert_score_close(assessed["component_price_score"], 10.00)
        assert_score_close(assessed["component_scope_score"], 16.67)
        assert_score_close(assessed["component_disclosure_score"], 23.33)
        assert_score_close(assessed["unreasonableness_score"], 50.00)


class TestRebateCapTierOrdering:
    """The cap tier is keyed on gross spend, before any rebate is subtracted."""

    def test_tier_selected_from_gross_spend_not_from_a_rebate_net_figure(
        self, api: ApiClient
    ) -> None:
        """Gross 10,500,000 selects 0.20; the net-of-rebate figure would select 0.25.

        PRD 3.6: "The cap tier is then selected **from gross spend, before any
        rebate deduction whatsoever**: `rebate_cap_pct` is 0.25 when
        `gross_spend_cents` is below 10,000,000 cents, 0.20 when it is at least
        10,000,000 cents and below 100,000,000 cents, and 0.15 when it is
        100,000,000 cents or more."

        Design: Difficulty/combinatorial_formula/rxdc_rebate_cap_tier_keyed_on_gross_before_deduction
        """
        fx.set_clock(api, LATE_CLOCK)
        reconciled = _reconciled_with_two_packages(
            api,
            {
                "record_count": 1200,
                "plan_paid_cents": 6_000_000,
                "member_paid_cents": 1_000_000,
                "rebate_cents": 1_800_000,
            },
            {
                "record_count": 800,
                "plan_paid_cents": 3_000_000,
                "member_paid_cents": 500_000,
                "rebate_cents": 1_200_000,
            },
        )

        assert_rx_submission(reconciled)
        assert reconciled["status"] == RX_RECONCILED
        assert reconciled["gross_spend_cents"] == 10_500_000
        assert reconciled["rebate_reported_cents"] == 3_000_000
        # 10,500,000 - 3,000,000 = 7,500,000 would fall in the 0.25 tier.
        assert reconciled["rebate_cap_pct"] == 0.20
        assert reconciled["rebate_credit_cents"] == 2_100_000
        assert reconciled["net_plan_spend_cents"] == 8_400_000
        assert reconciled["assembled_record_count"] == 2000

    def test_tier_floor_is_inclusive_at_ten_million_gross(self, api: ApiClient) -> None:
        """Gross of exactly 10,000,000 sits in the 0.20 tier.

        PRD 3.6: "`rebate_cap_pct` is 0.25 when `gross_spend_cents` is below
        10,000,000 cents, 0.20 when it is at least 10,000,000 cents and below
        100,000,000 cents, and 0.15 when it is 100,000,000 cents or more."

        Design: Difficulty/combinatorial_formula/rxdc_rebate_cap_tier_keyed_on_gross_before_deduction
        """
        fx.set_clock(api, LATE_CLOCK)
        reconciled = _reconciled_with_two_packages(
            api,
            {
                "record_count": 1200,
                "plan_paid_cents": 6_000_000,
                "member_paid_cents": 1_000_000,
                "rebate_cents": 2_500_000,
            },
            {
                "record_count": 800,
                "plan_paid_cents": 2_500_000,
                "member_paid_cents": 500_000,
                "rebate_cents": 1_500_000,
            },
        )

        assert reconciled["gross_spend_cents"] == 10_000_000
        assert reconciled["rebate_reported_cents"] == 4_000_000
        assert reconciled["rebate_cap_pct"] == 0.20
        # min(4,000,000, 0.20 x 10,000,000) = 2,000,000.
        assert reconciled["rebate_credit_cents"] == 2_000_000
        assert reconciled["net_plan_spend_cents"] == 8_000_000

    def test_credit_is_the_reported_rebate_when_it_falls_under_the_cap(
        self, api: ApiClient
    ) -> None:
        """A modest rebate is credited in full rather than at the cap.

        PRD 3.6: "`rebate_credit_cents` is the smaller of
        `rebate_reported_cents` and the product of `rebate_cap_pct` and
        `gross_spend_cents` rounded half up to whole cents; the rounding happens
        before the comparison."

        Design: Difficulty/combinatorial_formula/rxdc_rebate_cap_tier_keyed_on_gross_before_deduction
        """
        fx.set_clock(api, LATE_CLOCK)
        reconciled = _reconciled_with_two_packages(
            api,
            {
                "record_count": 1200,
                "plan_paid_cents": 6_000_000,
                "member_paid_cents": 1_000_000,
                "rebate_cents": 600_000,
            },
            {
                "record_count": 800,
                "plan_paid_cents": 3_000_000,
                "member_paid_cents": 500_000,
                "rebate_cents": 400_000,
            },
        )

        assert reconciled["gross_spend_cents"] == 10_500_000
        assert reconciled["rebate_reported_cents"] == 1_000_000
        assert reconciled["rebate_cap_pct"] == 0.20
        # The cap would allow 2,100,000, so the reported figure is the smaller.
        assert reconciled["rebate_credit_cents"] == 1_000_000
        assert reconciled["net_plan_spend_cents"] == 9_500_000
