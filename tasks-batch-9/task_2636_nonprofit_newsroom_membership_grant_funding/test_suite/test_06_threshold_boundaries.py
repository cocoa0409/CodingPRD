"""One cent on either side of two pinned comparisons.

Each pair is built so that the two rows share every other input, which is what
makes the single-cent difference the only possible explanation for the split.
"""

import pytest

from test_helpers import (
    benefit_payload,
    define_tier,
    enrol_member,
    open_fiscal_period,
    publish_tier,
    read_contribution,
    read_sustainability,
    record_contribution,
)


def _patron_benefits(book_value_cents: int):
    """A tote at 1000, event access at 15000 and a book at the value under test,
    supplied in that order."""
    return [
        benefit_payload("TOTE", "TOTE_BAG", 1000),
        benefit_payload("EVENT", "EVENT_ACCESS", 15000),
        benefit_payload("BOOK", "BOOK", book_value_cents),
    ]


def _define_patron_pair():
    """Two ANNUAL tiers at 120000 cents whose only difference is one cent on the
    book: exactly on the threshold, and one cent over it."""
    at_threshold = define_tier(
        benefits=_patron_benefits(2400),
        tier_code="PATRON_AT",
        name="Patron (benefit at threshold)",
        renewal_cadence="ANNUAL",
        contribution_amount_cents=120000,
        grace_period_days=30,
    )
    over_threshold = define_tier(
        benefits=_patron_benefits(2401),
        tier_code="PATRON_OVER",
        name="Patron (benefit one cent over)",
        renewal_cadence="ANNUAL",
        contribution_amount_cents=120000,
        grace_period_days=30,
    )
    return at_threshold, over_threshold


class TestBenefitExactlyOnTheInsubstantialThresholdIsExcluded:
    """The comparison is `<=`, so a benefit sitting on the line is excluded."""

    def test_both_tiers_derive_the_same_threshold(self):
        """2 percent of 120000 is 2400, well under the 13000 ceiling, so both
        tiers share the threshold the book value is measured against.

        PRD: "Concretely, `insubstantial_threshold_cents` is the smaller of two
        quantities: the recurring `contribution_amount_cents` multiplied by 200
        basis points and rounded half up to whole cents, and the flat ceiling of
        13000 cents."

        Design: Difficulty/boundary_precision_check/bp_insubstantial_benefit_equal_to_threshold_is_excluded
        """
        open_fiscal_period()
        at_threshold, over_threshold = _define_patron_pair()

        assert at_threshold["insubstantial_threshold_cents"] == 2400
        assert over_threshold["insubstantial_threshold_cents"] == 2400

    def test_the_book_on_the_line_is_insubstantial_and_the_one_over_is_not(self):
        """The tier holding the 2400 book excludes it and charges 15000; the tier
        holding the 2401 book includes the whole benefit and charges 17401.

        PRD: "A benefit is insubstantial when its per-period value is less than
        *or equal to* `insubstantial_threshold_cents`; a benefit sitting exactly on
        the threshold is insubstantial."

        Design: Difficulty/boundary_precision_check/bp_insubstantial_benefit_equal_to_threshold_is_excluded
        """
        open_fiscal_period()
        at_threshold, over_threshold = _define_patron_pair()

        assert at_threshold["insubstantial_benefit_codes"] == ["TOTE", "BOOK"]
        assert at_threshold["quid_pro_quo_per_period_cents"] == 15000

        assert over_threshold["insubstantial_benefit_codes"] == ["TOTE"]
        assert over_threshold["quid_pro_quo_per_period_cents"] == 17401

        difference = (
            over_threshold["quid_pro_quo_per_period_cents"]
            - at_threshold["quid_pro_quo_per_period_cents"]
        )
        assert difference == 2401

    def test_the_exclusion_never_changes_the_benefit_count(self):
        """`benefit_count` counts the supplied array, not the substantial subset,
        so both tiers report 3 while their quid-pro-quo figures differ.

        PRD: "The `benefit_code` of every insubstantial benefit is collected into
        `insubstantial_benefit_codes`, and `benefit_count` records the number of
        items in `benefits` - zero for a benefit-free tier."

        Design: Difficulty/boundary_precision_check/bp_insubstantial_benefit_equal_to_threshold_is_excluded
        """
        open_fiscal_period()
        at_threshold, over_threshold = _define_patron_pair()

        assert at_threshold["benefit_count"] == 3
        assert over_threshold["benefit_count"] == 3

    def test_the_tier_publishes_because_the_quid_pro_quo_stays_below_the_price(self):
        """15000 is strictly less than 120000, which is the one substantive
        precondition on publication.

        PRD: "Publication has one substantive precondition:
        `quid_pro_quo_per_period_cents` must be **strictly less than**
        `contribution_amount_cents`."

        Design: Difficulty/boundary_precision_check/bp_insubstantial_benefit_equal_to_threshold_is_excluded
        """
        open_fiscal_period()
        at_threshold, _ = _define_patron_pair()

        published = publish_tier(at_threshold["id"])
        assert published["status"] == "PUBLISHED"
        assert published["quid_pro_quo_per_period_cents"] == 15000

    def test_a_membership_contribution_inherits_the_excluded_valuation(self):
        """The receipt splits 120000 into 15000 of benefit value and 105000
        deductible; the one-cent-over tier would have written 17401 / 102599.

        PRD: "A `MEMBERSHIP` contribution takes `quid_pro_quo_cents` from the
        `quid_pro_quo_per_period_cents` of the tier the member references *at the
        moment of evaluation*, and `deductible_cents` is `amount_cents` minus that
        value floored at 0."

        Design: Difficulty/boundary_precision_check/bp_insubstantial_benefit_equal_to_threshold_is_excluded
        """
        period = open_fiscal_period()
        at_threshold, _ = _define_patron_pair()
        publish_tier(at_threshold["id"])
        member = enrol_member(
            at_threshold["id"], email="rosa@example.org", full_name="Rosa Blume"
        )

        contribution = record_contribution(
            period["id"],
            "MEMBERSHIP",
            120000,
            member_id=member["id"],
            received_date="2026-08-10",
        )
        assert contribution["quid_pro_quo_cents"] == 15000
        assert contribution["deductible_cents"] == 105000

        stored = read_contribution(contribution["id"])
        assert stored["quid_pro_quo_cents"] == 15000
        assert stored["deductible_cents"] == 105000


def _open_half_target_pair():
    """Two revenue-free periods on a 200000 expense base, one holding exactly the
    rounded half-target of 300000 and one holding a single cent less."""
    exactly_half = open_fiscal_period(
        label="FY2027-HALF-EXACT",
        monthly_expense_base_cents=200000,
        reserve_balance_cents=300000,
    )
    one_cent_short = open_fiscal_period(
        label="FY2027-HALF-MINUS-ONE",
        monthly_expense_base_cents=200000,
        reserve_balance_cents=299999,
    )
    return exactly_half, one_cent_short


class TestReserveBalanceExactlyHalfTargetIsWatchNotConstrained:
    """The CONSTRAINED cut is a strict `<`, so the half-target itself escapes it."""

    def test_a_balance_exactly_on_the_half_target_reports_watch(self):
        """300000 is not strictly below the 300000 half-target, so the ladder
        falls through to WATCH and the release cap is 6000.

        PRD: "otherwise `CONSTRAINED` if `reserve_balance_cents` is strictly below
        `operating_reserve_target_cents` divided by 2 and rounded half up - a
        balance exactly equal to that half-target is **not** constrained"

        Design: Difficulty/boundary_precision_check/bp_reserve_balance_exactly_half_target_is_watch_not_constrained
        """
        exactly_half, _ = _open_half_target_pair()

        picture = read_sustainability(exactly_half["id"])
        assert picture["reserve_months_target"] == 3
        assert picture["operating_reserve_target_cents"] == 600000
        assert picture["reserve_months_ratio_bps"] == 15000
        assert picture["sustainability_posture"] == "WATCH"
        assert picture["restricted_release_cap_pct_bps"] == 6000

    def test_one_cent_below_the_half_target_reports_constrained(self):
        """299999 is strictly below the half-target, so the CONSTRAINED branch
        matches first and the cap drops to 2500.

        PRD: "Seventh, `restricted_release_cap_pct_bps` is read off the posture:
        10000 for `HEALTHY`, 6000 for `WATCH`, 2500 for `CONSTRAINED` and 0 for
        `CRITICAL`."

        Design: Difficulty/boundary_precision_check/bp_reserve_balance_exactly_half_target_is_watch_not_constrained
        """
        _, one_cent_short = _open_half_target_pair()

        picture = read_sustainability(one_cent_short["id"])
        assert picture["reserve_months_target"] == 3
        assert picture["operating_reserve_target_cents"] == 600000
        assert picture["sustainability_posture"] == "CONSTRAINED"
        assert picture["restricted_release_cap_pct_bps"] == 2500

    def test_the_rounded_ratio_cannot_explain_the_split(self):
        """Both periods report the identical ratio of 15000 bps, so the posture
        difference has to come from the balance itself.

        PRD: "Fifth, `reserve_months_ratio_bps` is 10000 times
        `reserve_balance_cents` divided by `monthly_expense_base_cents`, rounded
        half up - measured against one month of expenses, not against the target."

        Design: Difficulty/boundary_precision_check/bp_reserve_balance_exactly_half_target_is_watch_not_constrained
        """
        exactly_half, one_cent_short = _open_half_target_pair()

        first = read_sustainability(exactly_half["id"])
        second = read_sustainability(one_cent_short["id"])

        assert first["reserve_months_ratio_bps"] == 15000
        assert second["reserve_months_ratio_bps"] == 15000
        assert first["sustainability_posture"] != second["sustainability_posture"]

    def test_neither_revenue_free_period_is_critical_or_concentrated(self):
        """With no revenue at all both periods share every concentration input,
        and both balances clear one month of expenses.

        PRD: "the posture is `CRITICAL` if `reserve_balance_cents` is strictly
        below `monthly_expense_base_cents`"

        Design: Difficulty/boundary_precision_check/bp_reserve_balance_exactly_half_target_is_watch_not_constrained
        """
        exactly_half, one_cent_short = _open_half_target_pair()

        for period in (exactly_half, one_cent_short):
            picture = read_sustainability(period["id"])
            assert picture["recognized_revenue_cents"] == 0
            assert picture["concentration_hhi"] == 0
            assert picture["top_source_share_bps"] == 0
            assert picture["sustainability_posture"] != "CRITICAL"
