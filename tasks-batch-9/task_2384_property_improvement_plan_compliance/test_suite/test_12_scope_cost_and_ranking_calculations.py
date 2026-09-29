"""Deadline horizons, the ranking tie-breaks, the filtered input set and the variance percentage."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    acknowledged_plan,
    assert_decimal_scale,
    assert_field_equals,
    assert_item_state,
    assert_ledger_contains,
    assert_plan_dimensions,
    assert_priority_ranks,
    bootstrap_portfolio,
    file_dispute,
    issue_plan,
    issued_plan,
    ledger_entries,
    read_cost_summary,
    read_item,
    read_plan,
    resolve_dispute,
    scope_plan,
    set_clock,
)


@pytest.fixture
def plan_issued_after_the_clock_was_rewound(api):
    """One item in each category, issued after the clock is moved back to mid-February."""
    portfolio = bootstrap_portfolio(
        api, "Amberton Hotels LLC", "ops@ambertonh.example"
    )
    scenario = scope_plan(
        api,
        portfolio,
        [
            {
                "key": "life_safety",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-3.1.1",
                "brand_estimated_cost_cents": 100000,
            },
            {
                "key": "guest_facing",
                "category": "GUEST_FACING",
                "standards_reference": "GF-3.1.1",
                "brand_estimated_cost_cents": 100000,
            },
            {
                "key": "back_of_house",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-3.1.1",
                "brand_estimated_cost_cents": 100000,
            },
        ],
    )
    set_clock(api, "2026-02-15T00:00:00Z")
    return issue_plan(api, scenario)


class TestCategoryDeadlinesRunFromIssuance:
    def test_the_three_horizons_are_counted_from_the_issuance_date(
        self, api, plan_issued_after_the_clock_was_rewound
    ):
        """"It stamps the three category deadlines from the date of `issued_at`:
        `life_safety_deadline_date` 90 calendar days out, `guest_facing_deadline_date` 270 calendar
        days out, and `back_of_house_deadline_date` 450 calendar days out." "Date arithmetic —
        deadline offsets, cure periods, changeover buffers, extension days — is in whole calendar
        days on UTC dates."

        Design: Corner/calculations/category_deadlines_are_measured_from_the_issuance_clock
        """
        scenario = plan_issued_after_the_clock_was_rewound

        plan = read_plan(api, scenario.plan_id)

        assert_field_equals(plan, "life_safety_deadline_date", "2026-05-16", "plan")
        assert_field_equals(plan, "guest_facing_deadline_date", "2026-11-12", "plan")
        assert_field_equals(plan, "back_of_house_deadline_date", "2027-05-11", "plan")

    def test_every_item_takes_the_deadline_of_its_own_category(
        self, api, plan_issued_after_the_clock_was_rewound
    ):
        """"It then sets `deadline_date` on every item of the plan to the deadline of that item's own
        category — life-safety items to the 90-day date, guest-facing items to the 270-day date,
        back-of-house items to the 450-day date — plus that item's `extension_days_granted`, which is
        0 at this point." "Candidates are ordered by three keys in strict succession: first by
        category, with life safety ordering before guest facing and guest facing before back of
        house".

        Design: Corner/calculations/category_deadlines_are_measured_from_the_issuance_clock
        """
        scenario = plan_issued_after_the_clock_was_rewound

        life_safety = read_item(api, scenario.item_id("life_safety"))
        guest_facing = read_item(api, scenario.item_id("guest_facing"))
        back_of_house = read_item(api, scenario.item_id("back_of_house"))

        assert_item_state(life_safety, deadline_date="2026-05-16", is_overdue=False)
        assert_item_state(guest_facing, deadline_date="2026-11-12", is_overdue=False)
        assert_item_state(back_of_house, deadline_date="2027-05-11", is_overdue=False)
        assert_priority_ranks(
            [life_safety, guest_facing, back_of_house],
            {life_safety["id"]: 1, guest_facing["id"]: 2, back_of_house["id"]: 3},
        )


@pytest.fixture
def three_equally_priced_guest_facing_items(api):
    """Three guest-facing items of identical cost, created in a known order, then issued."""
    return issued_plan(
        api,
        [
            {
                "key": "first",
                "category": "GUEST_FACING",
                "standards_reference": "GF-16.1.1",
                "brand_estimated_cost_cents": 500000,
            },
            {
                "key": "second",
                "category": "GUEST_FACING",
                "standards_reference": "GF-16.1.2",
                "brand_estimated_cost_cents": 500000,
            },
            {
                "key": "third",
                "category": "GUEST_FACING",
                "standards_reference": "GF-16.1.3",
                "brand_estimated_cost_cents": 500000,
            },
        ],
        legal_name="Inglewood Hotels LLC",
        contact_email="ops@inglewoodh.example",
    )


class TestTiedItemsRankByCreationOrder:
    def test_the_final_tie_break_is_creation_order(
        self, api, three_equally_priced_guest_facing_items
    ):
        """"then, for items still tied, by `created_at` ascending. Never by `id`. The ordered
        candidates receive `priority_rank` 1, 2, 3 and so on — contiguous integers with no gaps."

        Design: Corner/calculations/equal_cost_items_in_one_category_rank_by_creation_order
        """
        scenario = three_equally_priced_guest_facing_items

        items = [read_item(api, scenario.item_id(key)) for key in ("first", "second", "third")]

        assert_priority_ranks(
            items, {items[0]["id"]: 1, items[1]["id"]: 2, items[2]["id"]: 3}
        )
        assert sorted(item["priority_rank"] for item in items) == [1, 2, 3], (
            f"the ranks must be contiguous with no duplicates, got {items}"
        )

    def test_the_tied_items_carry_identical_funding_and_deadlines(
        self, api, three_equally_priced_guest_facing_items
    ):
        """"That product is rounded half up to whole cents and stored on the item as
        `item_funding_cents`. Only after every item has been individually rounded are those rounded
        figures summed, and the sum is the plan's `funding_requirement_cents`."

        Design: Corner/calculations/equal_cost_items_in_one_category_rank_by_creation_order
        """
        scenario = three_equally_priced_guest_facing_items

        for key in ("first", "second", "third"):
            item = read_item(api, scenario.item_id(key))
            assert_field_equals(item, "item_funding_cents", 591250, f"{key} item")
            assert_item_state(item, deadline_date="2027-04-28")

        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "brand_scoped_total_cents", 1500000, "plan")
        assert_field_equals(plan, "funding_requirement_cents", 1773750, "plan")


@pytest.fixture
def plan_with_a_removable_second_item(api):
    """A guest-facing item to keep and a back-of-house item the panel will strike out."""
    return acknowledged_plan(
        api,
        [
            {
                "key": "keep",
                "category": "GUEST_FACING",
                "standards_reference": "GF-5.1.1",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "drop",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-5.1.1",
                "brand_estimated_cost_cents": 400000,
            },
        ],
        legal_name="Bramblehill Hotels LLC",
        contact_email="ops@bramblehillh.example",
    )


def _remove_the_second_item(api, scenario):
    dispute = file_dispute(
        api,
        scenario,
        scenario.item_id("drop"),
        claimed_cost_cents=0,
        dispute_basis="SCOPE_REASONABLENESS",
    )
    resolve_dispute(
        api,
        dispute["id"],
        "REMOVE",
        panel_decision_note=(
            "The kitchen hood scope duplicates work accepted under the prior cycle and is struck "
            "from the plan."
        ),
    )
    return dispute


class TestRemovedItemsLeaveTheAggregates:
    def test_both_items_count_before_the_removal(self, api, plan_with_a_removable_second_item):
        """"The included set is every item of the plan whose `status` is neither
        `REMOVED_BY_DISPUTE` nor `VOIDED`." "Only after every item has been individually rounded are
        those rounded figures summed, and the sum is the plan's `funding_requirement_cents`."

        Design: Corner/calculations/removed_items_leave_the_cost_and_funding_aggregates
        """
        scenario = plan_with_a_removable_second_item

        plan = read_plan(api, scenario.plan_id)

        assert_field_equals(plan, "scope_item_count", 2, "plan")
        assert_field_equals(plan, "brand_scoped_total_cents", 1400000, "plan")
        assert_field_equals(plan, "funding_requirement_cents", 1637900, "plan")

    def test_the_removed_item_drops_out_of_every_aggregate(
        self, api, plan_with_a_removable_second_item
    ):
        """"the item becomes `REMOVED_BY_DISPUTE` and thereby leaves every plan aggregate —
        `scope_item_count`, `brand_scoped_total_cents`, `owner_claimed_total_cents`,
        `funding_requirement_cents` and `funding_gap_cents` are all recomputed over the surviving
        items, and `priority_rank` is re-assigned across those survivors."

        Design: Corner/calculations/removed_items_leave_the_cost_and_funding_aggregates
        """
        scenario = plan_with_a_removable_second_item
        _remove_the_second_item(api, scenario)

        plan = read_plan(api, scenario.plan_id)
        survivor = read_item(api, scenario.item_id("keep"))

        assert_item_state(read_item(api, scenario.item_id("drop")), status="REMOVED_BY_DISPUTE")
        assert_field_equals(plan, "scope_item_count", 1, "plan")
        assert_field_equals(plan, "brand_scoped_total_cents", 1000000, "plan")
        assert_field_equals(plan, "funding_requirement_cents", 1182500, "plan")
        assert_plan_dimensions(plan, dispute_state="DISPUTE_RESOLVED_REMOVED")
        assert_priority_ranks([survivor], {survivor["id"]: 1})

    def test_removal_is_a_status_change_and_not_a_delete(
        self, api, plan_with_a_removable_second_item
    ):
        """"`ACCEPTED`, `REMOVED_BY_DISPUTE` and `VOIDED` are the terminal item states." "a ledger
        entry of type `ITEM_REMOVED` is appended carrying the item's id and a `delta_cents` equal to
        the item's `approved_cost_cents` negated."

        Design: Corner/calculations/removed_items_leave_the_cost_and_funding_aggregates
        """
        scenario = plan_with_a_removable_second_item
        _remove_the_second_item(api, scenario)

        removed = read_item(api, scenario.item_id("drop"))

        assert_field_equals(removed, "approved_cost_cents", 400000, "removed item")
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "ITEM_REMOVED",
            delta_cents=-400000,
            item_id=scenario.item_id("drop"),
            count=1,
        )


@pytest.fixture
def plan_with_an_owner_claim_of_one_point_two_million(api):
    """A single guest-facing item the owner prices twenty percent above the brand's figure."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "casegoods",
                "category": "GUEST_FACING",
                "standards_reference": "GF-11.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Dunmarsh Hotels LLC",
        contact_email="ops@dunmarshh.example",
    )
    dispute = file_dispute(
        api,
        scenario,
        scenario.item_id("casegoods"),
        claimed_cost_cents=1200000,
        dispute_basis="COST_ESTIMATE",
    )
    return scenario, dispute


class TestVariancePercentageScale:
    def test_the_variance_percentage_carries_two_decimal_places(
        self, api, plan_with_an_owner_claim_of_one_point_two_million
    ):
        """"From them, `variance_cents` is the owner-claimed total minus the brand-scoped total, and
        the variance as a percentage is that variance multiplied by 100 and divided by the
        brand-scoped total, rounded half up to 2 decimal places — or exactly `0.00` when the
        brand-scoped total is 0."

        Design: Corner/calculations/cost_variance_percentage_rounds_to_two_decimals
        """
        scenario, _dispute = plan_with_an_owner_claim_of_one_point_two_million

        summary = read_cost_summary(api, scenario.plan_id)

        assert_field_equals(summary, "variance_cents", 200000, "cost summary")
        assert_field_equals(summary, "included_item_count", 1, "cost summary")
        assert Decimal(str(summary["variance_pct"])) == Decimal("20.00"), (
            "200000 * 100 / 1000000 is 20.00 at two decimal places — the divisor is the "
            f"brand-scoped total, never the owner-claimed one; got {summary['variance_pct']!r}"
        )
        assert_decimal_scale(summary["variance_pct"], 2, "cost summary.variance_pct")

    def test_the_funding_side_still_reads_the_approved_figure(
        self, api, plan_with_an_owner_claim_of_one_point_two_million
    ):
        """"it exists for dispute reporting only and never feeds the funding maths." "When the plan
        has no active budget, `funding_gap_cents` is 0." "the `contingency_pct_applied` (the active
        budget's `contingency_pct`, or the ten-percent default when no active budget exists)".

        Design: Corner/calculations/cost_variance_percentage_rounds_to_two_decimals
        """
        scenario, _dispute = plan_with_an_owner_claim_of_one_point_two_million

        summary = read_cost_summary(api, scenario.plan_id)

        assert_field_equals(summary, "funding_requirement_cents", 1182500, "cost summary")
        assert_field_equals(summary, "authorized_cents", 0, "cost summary")
        assert_field_equals(summary, "funding_gap_cents", 0, "cost summary")
        assert Decimal(str(summary["contingency_pct_applied"])) == Decimal("0.10"), (
            f"the ten-percent default applies with no active budget, got {summary!r}"
        )
        assert Decimal(str(summary["funding_gap_pct"])) == Decimal("0.00"), (
            f"no requirement shortfall means a zero gap percentage, got {summary!r}"
        )

    def test_the_two_totals_diverge_the_moment_a_claim_exists(
        self, api, plan_with_an_owner_claim_of_one_point_two_million
    ):
        """"The **owner-claimed variant**, published as `owner_claimed_total_cents`, substitutes
        `owner_claimed_cost_cents` for any item on which a dispute has been filed and falls back to
        `brand_estimated_cost_cents` for the rest". "The two variants are identical until the first
        dispute exists and diverge the instant one does."

        Design: Corner/calculations/cost_variance_percentage_rounds_to_two_decimals
        """
        scenario, dispute = plan_with_an_owner_claim_of_one_point_two_million

        item = read_item(api, scenario.item_id("casegoods"))
        plan = read_plan(api, scenario.plan_id)

        assert_field_equals(dispute, "status", "FILED", "dispute")
        assert_plan_dimensions(plan, status="ISSUED", dispute_state="DISPUTE_OPEN")
        assert_field_equals(item, "owner_claimed_cost_cents", 1200000, "item")
        assert_field_equals(item, "approved_cost_cents", 1000000, "item")
        assert_field_equals(plan, "owner_claimed_total_cents", 1200000, "plan")
        assert_field_equals(plan, "brand_scoped_total_cents", 1000000, "plan")
