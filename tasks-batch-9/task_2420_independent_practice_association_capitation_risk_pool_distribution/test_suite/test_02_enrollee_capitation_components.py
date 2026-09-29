"""Per-member capitation components: enum branches and the nested clamp."""

import pytest

from test_helpers import (
    assert_fields,
    assert_pmpm_components,
    create_active_agreement,
    create_enrollee,
)


def _agreement_with_base_30000(api):
    return create_active_agreement(
        api, base_pmpm_cents=30000, quality_withhold_bps=700, max_panel_size=10
    )


class TestMemberPmpmEnumBranchesAndClamp:
    @pytest.mark.parametrize(
        "age_band,benefit_tier,risk_score_bps,gross,withhold,net",
        [
            ("ADULT", "HMO", 12500, 37500, 2625, 34875),
            ("SENIOR", "HMO_PLUS", 20000, 89500, 6265, 83235),
            ("PEDIATRIC", "HMO", 3000, 8000, 560, 7440),
            ("SENIOR", "HMO_PLUS", 22000, 95000, 6650, 88350),
        ],
    )
    def test_components_across_age_band_and_benefit_tier_combinations(
        self, api, age_band, benefit_tier, risk_score_bps, gross, withhold, net
    ):
        """PRD §3.3: "An `ADULT` member on `HMO` coverage with a `risk_score_bps`
        of 12500 reaches a raw amount of 37500 cents, which sits inside both
        bounds, so `gross_pmpm_cents` is 37500, `withhold_cents` is 2625, and
        `net_pmpm_cents` is 34875."

        Design: Difficulty/combinatorial_formula/member_pmpm_nested_clamp_and_enum_branches
        """
        agreement = _agreement_with_base_30000(api)
        enrollee = create_enrollee(
            api,
            agreement["id"],
            age_band=age_band,
            benefit_tier=benefit_tier,
            risk_score_bps=risk_score_bps,
        )
        assert_pmpm_components(enrollee, gross, withhold, net)

    def test_raw_amount_below_the_floor_is_raised_to_8000_cents(self, api):
        """PRD §3.3: "A `PEDIATRIC` member on `HMO` with a `risk_score_bps` of
        3000 computes a raw amount of 5850 cents, below the floor, so
        `gross_pmpm_cents` becomes 8000, `withhold_cents` 560, and
        `net_pmpm_cents` 7440."

        Design: Difficulty/combinatorial_formula/member_pmpm_nested_clamp_and_enum_branches
        """
        agreement = _agreement_with_base_30000(api)
        enrollee = create_enrollee(
            api,
            agreement["id"],
            age_band="PEDIATRIC",
            benefit_tier="HMO",
            risk_score_bps=3000,
        )

        assert enrollee["gross_pmpm_cents"] == 8000, (
            "the raw amount of 5850 cents is raised to the floor"
        )
        assert enrollee["gross_pmpm_cents"] != 5850

    def test_raw_amount_above_the_ceiling_is_reduced_to_95000_cents(self, api):
        """PRD §3.3: "A `SENIOR` member on `HMO_PLUS` with a `risk_score_bps` of
        22000 computes a raw amount of 98200 cents, above the ceiling, so
        `gross_pmpm_cents` becomes 95000, `withhold_cents` 6650, and
        `net_pmpm_cents` 88350."

        Design: Difficulty/combinatorial_formula/member_pmpm_nested_clamp_and_enum_branches
        """
        agreement = _agreement_with_base_30000(api)
        enrollee = create_enrollee(
            api,
            agreement["id"],
            age_band="SENIOR",
            benefit_tier="HMO_PLUS",
            risk_score_bps=22000,
        )

        assert enrollee["gross_pmpm_cents"] == 95000
        assert enrollee["gross_pmpm_cents"] != 98200

    def test_floor_is_applied_before_the_ceiling(self, api):
        """PRD §3.3: "Applying the bounds in this nested order means a member
        below the floor can never be pushed above the ceiling and a member above
        the ceiling can never be pulled below the floor."

        Design: Difficulty/combinatorial_formula/member_pmpm_nested_clamp_and_enum_branches
        """
        agreement = _agreement_with_base_30000(api)
        floored = create_enrollee(
            api,
            agreement["id"],
            age_band="PEDIATRIC",
            benefit_tier="HMO",
            risk_score_bps=3000,
        )
        capped = create_enrollee(
            api,
            agreement["id"],
            age_band="SENIOR",
            benefit_tier="HMO_PLUS",
            risk_score_bps=22000,
        )

        assert floored["gross_pmpm_cents"] == 8000
        assert capped["gross_pmpm_cents"] == 95000
        assert 8000 <= floored["gross_pmpm_cents"] <= 95000
        assert 8000 <= capped["gross_pmpm_cents"] <= 95000

    def test_flat_tier_add_on_is_applied_after_the_single_rounding(self, api):
        """PRD §3.3: "The tier add-on is a flat cent amount that is never
        risk-adjusted and never age-adjusted, and it is applied after the
        rounding, not before."

        Design: Difficulty/combinatorial_formula/member_pmpm_nested_clamp_and_enum_branches
        """
        agreement = _agreement_with_base_30000(api)
        hmo = create_enrollee(
            api,
            agreement["id"],
            age_band="SENIOR",
            benefit_tier="HMO",
            risk_score_bps=20000,
        )
        hmo_plus = create_enrollee(
            api,
            agreement["id"],
            age_band="SENIOR",
            benefit_tier="HMO_PLUS",
            risk_score_bps=20000,
        )

        assert hmo["gross_pmpm_cents"] == 87000
        assert hmo_plus["gross_pmpm_cents"] == 89500
        assert hmo_plus["gross_pmpm_cents"] - hmo["gross_pmpm_cents"] == 2500, (
            "the HMO_PLUS add-on is a flat 2500 cents, neither age-adjusted nor "
            "risk-adjusted"
        )

    def test_registration_derives_all_three_components_immediately(self, api):
        """PRD §3.3: "A freshly registered enrollee has `assigned_physician_id`
        null and `cumulative_paid_claims_cents` 0."

        Design: Difficulty/combinatorial_formula/member_pmpm_nested_clamp_and_enum_branches
        """
        agreement = _agreement_with_base_30000(api)
        enrollee = create_enrollee(
            api,
            agreement["id"],
            age_band="ADULT",
            benefit_tier="HMO",
            risk_score_bps=12500,
        )

        assert_fields(
            enrollee,
            {
                "gross_pmpm_cents": 37500,
                "withhold_cents": 2625,
                "net_pmpm_cents": 34875,
                "assigned_physician_id": None,
                "cumulative_paid_claims_cents": 0,
            },
        )
