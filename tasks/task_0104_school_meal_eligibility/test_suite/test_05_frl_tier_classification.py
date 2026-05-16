"""FRL tier classification boundary precision (frl_tier_classification).

PRD §3.4: the eligibility classifier compares the ratio of
declared_annual_income_cents to FEDERAL_POVERTY_GUIDELINE_BY_SIZE
[household_size]. The inequality is non-strict on each upper edge: a
ratio exactly equal to 1.30 yields FREE, a ratio exactly equal to 1.85
yields REDUCED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    FEDERAL_POVERTY_GUIDELINE_BY_SIZE,
    approve_frl_application,
    create_frl_application,
    deny_frl_application,
    setup_district_with_family,
    submit_frl_application,
    validate_error,
)


# ===========================================================================
# §3.4 frl_tier_classification — FREE/REDUCED boundary at 1.30
# ===========================================================================
class TestFreeBoundary:
    """PRD §3.4: "a ratio exactly equal to 1.30 yields FREE"."""

    def test_ratio_exactly_at_free_threshold_yields_free(self, api):
        """PRD §3.4: "When the ratio is at most 1.30, the classifier
        returns FREE. ... Both inequalities are non-strict on the upper
        edge of each band: a ratio exactly equal to 1.30 yields FREE".

        Claim: with household_size=4 (FPL_4=3,090,000) and income
        4,017,000 (ratio == exactly 1.30), decided_tier=FREE.

        # difficulty: boundary_precision_check/frl_tier_ratio_exactly_at_free_threshold
        # difficulty: combinatorial_formula/frl_tier_threshold_with_nested_branches
        """
        district, parent, student = setup_district_with_family()
        # FPL_4 * 1.30 = 3_090_000 * 1.30 = 4_017_000 (exact integer).
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=4_017_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        assert approved["decided_tier"] == "FREE", (
            f"expected FREE at ratio 1.30 (non-strict upper bound), "
            f"got {approved['decided_tier']}"
        )

    def test_ratio_one_cent_above_free_threshold_yields_reduced(self, api):
        """PRD §3.4: "When the ratio is greater than 1.30 but at most
        1.85, the classifier returns REDUCED."

        Claim: with household_size=4 and income 4,017,001 cents (ratio
        slightly above 1.30), decided_tier=REDUCED.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=4_017_001,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        assert approved["decided_tier"] == "REDUCED", (
            f"expected REDUCED at ratio just above 1.30, "
            f"got {approved['decided_tier']}"
        )

    def test_ratio_one_cent_below_free_threshold_yields_free(self, api):
        """PRD §3.4: "When the ratio is at most 1.30, the classifier
        returns FREE."

        Claim: with household_size=4 and income 4,016,999 cents (ratio
        slightly below 1.30), decided_tier=FREE.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=4_016_999,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        assert approved["decided_tier"] == "FREE"


# ===========================================================================
# §3.4 frl_tier_classification — REDUCED/DENIED_PAID boundary at 1.85
# ===========================================================================
class TestReducedBoundary:
    """PRD §3.4: "a ratio exactly equal to 1.85 yields REDUCED"."""

    def test_ratio_exactly_at_reduced_threshold_yields_reduced(self, api):
        """PRD §3.4: "When the ratio is greater than 1.30 but at most
        1.85, the classifier returns REDUCED. ... a ratio exactly equal
        to 1.85 yields REDUCED."

        Claim: with household_size=4 (FPL_4=3,090,000) and income
        5,716,500 (ratio == exactly 1.85), decided_tier=REDUCED.
        """
        district, parent, student = setup_district_with_family()
        # FPL_4 * 1.85 = 3_090_000 * 1.85 = 5_716_500 (exact integer).
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=5_716_500,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        assert approved["decided_tier"] == "REDUCED", (
            f"expected REDUCED at ratio 1.85 (non-strict upper bound), "
            f"got {approved['decided_tier']}"
        )

    def test_ratio_one_cent_above_reduced_threshold_routes_to_deny(
        self, api,
    ):
        """PRD §3.4: "Otherwise it returns DENIED_PAID."
        PRD §3.4: "Approval that would resolve to DENIED_PAID is
        rejected with ERR_INVALID_STATE — the reviewer must instead
        route the application down the deny path."

        Claim: with income 5,716,501 (ratio slightly above 1.85),
        approve is rejected with ERR_INVALID_STATE.
        """
        from test_helpers import TEST_USERS
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=5_716_501,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        res = api.approve_frl_application(
            district["id"], app["id"], TEST_USERS["reviewer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.4 Per-household-size lookup
# ===========================================================================
class TestFederalPovertyGuidelineLookup:
    """PRD §3.4: explicit table of guideline values per household_size."""

    @pytest.mark.parametrize("household_size,fpl_cents", [
        (1, 1_500_000),
        (2, 2_030_000),
        (3, 2_560_000),
        (4, 3_090_000),
        (5, 3_620_000),
        (6, 4_150_000),
        (7, 4_680_000),
        (8, 5_210_000),
    ])
    def test_fpl_captured_on_approve(self, api, household_size, fpl_cents):
        """PRD §3.4: "one person 15,000.00 dollars (1,500,000 cents),
        two people 20,300.00 dollars (2,030,000 cents), three people
        25,600.00 dollars (2,560,000 cents), four people 30,900.00
        dollars (3,090,000 cents), five people 36,200.00 dollars
        (3,620,000 cents), six people 41,500.00 dollars (4,150,000
        cents), seven people 46,800.00 dollars (4,680,000 cents), and
        eight people 52,100.00 dollars (5,210,000 cents)."

        Claim: on approval, federal_poverty_guideline_cents equals the
        looked-up table value for the application's household_size.
        """
        district, parent, student = setup_district_with_family()
        # Pick income safely inside FREE band (ratio ~0.5).
        income = fpl_cents // 2
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=household_size,
            declared_annual_income_cents=income,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        assert approved["federal_poverty_guideline_cents"] == fpl_cents, (
            f"household_size={household_size}: expected FPL "
            f"{fpl_cents}, got "
            f"{approved['federal_poverty_guideline_cents']}"
        )
