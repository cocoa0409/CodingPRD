"""The plan's two cost totals, the variance between them, and the funding requirement."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    assert_cost_summary_shape,
    assert_field_equals,
    assert_ledger_contains,
    assert_plan_dimensions,
    file_dispute,
    issued_plan,
    ledger_entries,
    read_cost_summary,
    read_item,
    read_plan,
    read_risk_summary,
    resolve_dispute,
)


@pytest.fixture
def disputed_two_item_plan(api):
    """A guest-facing and a back-of-house item, with an owner cost claim on the first."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "guest_facing",
                "category": "GUEST_FACING",
                "standards_reference": "GF-4.2.1",
                "brand_estimated_cost_cents": 1234567,
            },
            {
                "key": "back_of_house",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-9.1.4",
                "brand_estimated_cost_cents": 987654,
            },
        ],
        legal_name="Harborline Lodging LLC",
        contact_email="ops@harborline.example",
    )
    file_dispute(
        api,
        scenario,
        scenario.item_id("guest_facing"),
        claimed_cost_cents=2000000,
        dispute_basis="COST_ESTIMATE",
    )
    return scenario


class TestTwoCostVariants:
    def test_brand_and_owner_totals_diverge_the_instant_a_dispute_exists(
        self, api, disputed_two_item_plan
    ):
        """The brand-scoped variant "always reads `brand_estimated_cost_cents` and ignores
        every owner claim"; the owner-claimed variant "substitutes `owner_claimed_cost_cents`
        for any item on which a dispute has been filed and falls back to
        `brand_estimated_cost_cents` for the rest". "The two variants are identical until the
        first dispute exists and diverge the instant one does."

        Design: Difficulty/dual_variant_calc/plan_scope_cost_brand_vs_owner_variance
        """
        summary = read_cost_summary(api, disputed_two_item_plan.plan_id)

        assert_cost_summary_shape(summary)
        assert_field_equals(summary, "included_item_count", 2, "cost summary")
        assert_field_equals(summary, "brand_scoped_total_cents", 1234567 + 987654, "cost summary")
        assert_field_equals(summary, "owner_claimed_total_cents", 2000000 + 987654, "cost summary")

    def test_variance_is_the_owner_total_less_the_brand_total_carried_to_two_places(
        self, api, disputed_two_item_plan
    ):
        """"`variance_cents` is the owner-claimed total minus the brand-scoped total, and the
        variance as a percentage is that variance multiplied by 100 and divided by the
        brand-scoped total, rounded half up to 2 decimal places".

        Design: Difficulty/dual_variant_calc/plan_scope_cost_brand_vs_owner_variance
        """
        summary = read_cost_summary(api, disputed_two_item_plan.plan_id)

        assert_field_equals(summary, "variance_cents", 765433, "cost summary")
        assert Decimal(str(summary["variance_pct"])) == Decimal("34.44"), (
            "765433 * 100 / 2222221 rounds half up to 34.44, "
            f"got {summary['variance_pct']!r}"
        )

    def test_the_owner_claim_lands_only_on_the_contested_item(self, api, disputed_two_item_plan):
        """"The contested item's `owner_claimed_cost_cents` is set to the dispute's
        `claimed_cost_cents`". A new item is created "with `owner_claimed_cost_cents` null",
        and on an upheld figure "the item's `approved_cost_cents` stays at its
        `brand_estimated_cost_cents`".

        Design: Difficulty/dual_variant_calc/plan_scope_cost_brand_vs_owner_variance
        """
        contested = read_item(api, disputed_two_item_plan.item_id("guest_facing"))
        untouched = read_item(api, disputed_two_item_plan.item_id("back_of_house"))

        assert_field_equals(contested, "owner_claimed_cost_cents", 2000000, "contested item")
        assert_field_equals(contested, "approved_cost_cents", 1234567, "contested item")
        assert untouched["owner_claimed_cost_cents"] is None, (
            "an item carrying no dispute keeps a null owner_claimed_cost_cents, got "
            f"{untouched['owner_claimed_cost_cents']!r}"
        )

    def test_only_the_brand_variant_feeds_the_funding_maths(self, api, disputed_two_item_plan):
        """The brand-scoped variant "is the sole input to the funding maths", while the
        owner-claimed variant "exists for dispute reporting only and never feeds the funding
        maths". Each item's `approved_cost_cents` "is multiplied by one plus the contingency and
        then multiplied by that item's category escalation factor — 1.00 for `LIFE_SAFETY`,
        1.075 for `GUEST_FACING`, and 1.035 for `BACK_OF_HOUSE`".

        Design: Difficulty/dual_variant_calc/plan_scope_cost_brand_vs_owner_variance
        """
        summary = read_cost_summary(api, disputed_two_item_plan.plan_id)
        contested = read_item(api, disputed_two_item_plan.item_id("guest_facing"))
        untouched = read_item(api, disputed_two_item_plan.item_id("back_of_house"))

        assert_field_equals(contested, "item_funding_cents", 1459875, "guest-facing item")
        assert_field_equals(untouched, "item_funding_cents", 1124444, "back-of-house item")
        assert_field_equals(
            summary, "funding_requirement_cents", 1459875 + 1124444, "cost summary"
        )

    def test_filing_a_dispute_moves_the_dispute_dimension_alone(
        self, api, disputed_two_item_plan
    ):
        """"The plan's `dispute_state` moves to `DISPUTE_OPEN` while its `status` is left
        completely untouched."

        Design: Difficulty/dual_variant_calc/plan_scope_cost_brand_vs_owner_variance
        """
        plan = read_plan(api, disputed_two_item_plan.plan_id)

        assert_plan_dimensions(plan, status="ISSUED", dispute_state="DISPUTE_OPEN")


@pytest.fixture
def three_life_safety_items_plan(api):
    """Three identically priced life-safety items whose escalated figures each end in a half cent."""
    return issued_plan(
        api,
        [
            {
                "key": f"item{index}",
                "category": "LIFE_SAFETY",
                "standards_reference": f"LS-3.1.{index}",
                "brand_estimated_cost_cents": 100005,
            }
            for index in (1, 2, 3)
        ],
        legal_name="Northgate Inns LLC",
        contact_email="capital@northgateinns.example",
    )


class TestPinnedRoundingOrderOfTheFundingRequirement:
    def test_each_item_is_rounded_before_the_requirement_is_summed(
        self, api, three_life_safety_items_plan
    ):
        """"That product is rounded half up to whole cents and stored on the item as
        `item_funding_cents`. Only after every item has been individually rounded are those
        rounded figures summed, and the sum is the plan's `funding_requirement_cents`."

        Design: Difficulty/combinatorial_formula/funding_requirement_per_item_rounding_then_sum
        """
        for key in ("item1", "item2", "item3"):
            item = read_item(api, three_life_safety_items_plan.item_id(key))
            assert_field_equals(item, "item_funding_cents", 110006, f"item {key}")

        summary = read_cost_summary(api, three_life_safety_items_plan.plan_id)
        assert_field_equals(summary, "funding_requirement_cents", 330018, "cost summary")

    def test_the_sum_then_round_order_is_not_used(self, api, three_life_safety_items_plan):
        """"Rounding each item before summing is the specified order; summing the exact products
        and rounding the total once is not, and produces a different integer."

        Design: Difficulty/combinatorial_formula/funding_requirement_per_item_rounding_then_sum
        """
        summary = read_cost_summary(api, three_life_safety_items_plan.plan_id)

        assert summary["funding_requirement_cents"] != 330017, (
            "330017 is the forbidden sum-then-round figure for three items of 100005 cents "
            "escalated at 1.00 with a 0.10 contingency"
        )
        assert_field_equals(summary, "funding_requirement_cents", 330018, "cost summary")

    def test_the_default_contingency_applies_while_no_budget_is_active(
        self, api, three_life_safety_items_plan
    ):
        """"if the plan has no active budget, the contingency is a default of ten percent, that
        is, 0.10". The cost read publishes "the `authorized_cents` taken from the active
        budget's `total_authorized_cents` (0 when no active budget exists)", and "When the plan
        has no active budget, `funding_gap_cents` is 0."

        Design: Difficulty/combinatorial_formula/funding_requirement_per_item_rounding_then_sum
        """
        summary = read_cost_summary(api, three_life_safety_items_plan.plan_id)

        assert Decimal(str(summary["contingency_pct_applied"])) == Decimal("0.10"), (
            f"contingency_pct_applied should be the 0.10 default, got "
            f"{summary['contingency_pct_applied']!r}"
        )
        assert_field_equals(summary, "brand_scoped_total_cents", 300015, "cost summary")
        assert_field_equals(summary, "authorized_cents", 0, "cost summary")
        assert_field_equals(summary, "funding_gap_cents", 0, "cost summary")


@pytest.fixture
def plan_with_its_only_item_removed(api):
    """A relicensing plan whose single item has been argued out of scope entirely."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "only",
                "category": "GUEST_FACING",
                "standards_reference": "GF-1.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Pinegrove Hospitality LLC",
        contact_email="asset@pinegrovehospitality.example",
        trigger_type="RELICENSING",
    )
    dispute = file_dispute(
        api,
        scenario,
        scenario.item_id("only"),
        claimed_cost_cents=0,
        dispute_basis="STANDARDS_APPLICABILITY",
    )
    resolve_dispute(api, dispute["id"], "REMOVE")
    return scenario


class TestEmptyIncludedSet:
    def test_removal_empties_the_included_set(self, api, plan_with_its_only_item_removed):
        """"the item becomes `REMOVED_BY_DISPUTE` and thereby leaves every plan aggregate".
        "The included set is every item of the plan whose `status` is neither
        `REMOVED_BY_DISPUTE` nor `VOIDED`."

        Design: Difficulty/boundary_precision_check/empty_scope_cost_summary_zero_denominator
        """
        item = read_item(api, plan_with_its_only_item_removed.item_id("only"))
        summary = read_cost_summary(api, plan_with_its_only_item_removed.plan_id)

        assert_field_equals(item, "status", "REMOVED_BY_DISPUTE", "removed item")
        assert_field_equals(summary, "included_item_count", 0, "cost summary")
        assert_field_equals(summary, "brand_scoped_total_cents", 0, "cost summary")
        assert_field_equals(summary, "owner_claimed_total_cents", 0, "cost summary")

    def test_a_zero_brand_total_reports_a_zero_percentage_rather_than_dividing(
        self, api, plan_with_its_only_item_removed
    ):
        """"An empty included set yields 0 for both totals, 0 variance and `0.00` for the
        variance percentage." The gap percentage "is `0.00` when the requirement is 0".

        Design: Difficulty/boundary_precision_check/empty_scope_cost_summary_zero_denominator
        """
        summary = read_cost_summary(api, plan_with_its_only_item_removed.plan_id)

        assert_field_equals(summary, "variance_cents", 0, "cost summary")
        assert Decimal(str(summary["variance_pct"])) == Decimal("0.00"), (
            f"variance_pct should be 0.00 on an empty included set, got {summary['variance_pct']!r}"
        )
        assert_field_equals(summary, "funding_requirement_cents", 0, "cost summary")
        assert_field_equals(summary, "funding_gap_cents", 0, "cost summary")
        assert Decimal(str(summary["funding_gap_pct"])) == Decimal("0.00"), (
            f"funding_gap_pct should be 0.00 when the requirement is 0, "
            f"got {summary['funding_gap_pct']!r}"
        )

    def test_removal_leaves_the_lifecycle_dimension_where_it_was(
        self, api, plan_with_its_only_item_removed
    ):
        """"The plan's `dispute_state` becomes `DISPUTE_RESOLVED_REMOVED` with `status`
        untouched". An emptied plan's aggregates are "all recomputed over the surviving items".

        Design: Difficulty/boundary_precision_check/empty_scope_cost_summary_zero_denominator
        """
        plan = read_plan(api, plan_with_its_only_item_removed.plan_id)

        assert_plan_dimensions(plan, status="ISSUED", dispute_state="DISPUTE_RESOLVED_REMOVED")
        assert_field_equals(plan, "scope_item_count", 0, "plan")

    def test_removal_appends_a_negated_cost_entry_and_restores_a_clean_score(
        self, api, plan_with_its_only_item_removed
    ):
        """"a ledger entry of type `ITEM_REMOVED` is appended carrying the item's id and a
        `delta_cents` equal to the item's `approved_cost_cents` negated". With no overdue item,
        no open defect and no funding gap, "The five penalties are subtracted from 100".

        Design: Difficulty/boundary_precision_check/empty_scope_cost_summary_zero_denominator
        """
        entries = ledger_entries(api, plan_id=plan_with_its_only_item_removed.plan_id)
        assert_ledger_contains(
            entries,
            "ITEM_REMOVED",
            delta_cents=-1000000,
            item_id=plan_with_its_only_item_removed.item_id("only"),
        )

        risk = read_risk_summary(api, plan_with_its_only_item_removed.property_id)
        assert_field_equals(risk, "snapshot_score", 100, "risk summary")
        assert_field_equals(risk, "snapshot_posture", "COMPLIANT", "risk summary")
