"""The funding-gap tier edge, the life-safety penalty cap and the damages rounding order."""

from __future__ import annotations

import pytest

from test_helpers import (
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_posture,
    authorize_budget,
    issue_default_notice,
    issued_plan,
    read_budget,
    read_cost_summary,
    read_franchisee,
    read_item,
    read_plan,
    read_property,
    read_risk_summary,
    run_compliance_sweep,
    set_clock,
)


@pytest.fixture
def plan_authorised_ten_percent_short(api):
    """A guest-facing item needing 1182500 with only 1064250 authorised — a gap of exactly a tenth."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "guest_rooms",
                "category": "GUEST_FACING",
                "standards_reference": "GF-10.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Coldspring Hotels LLC",
        contact_email="treasury@coldspringhotels.example",
    )
    budget = authorize_budget(api, scenario, 1064250)
    return scenario, budget


class TestFundingGapTierBoundary:
    def test_a_gap_ratio_of_exactly_one_tenth_takes_the_lower_penalty(
        self, api, plan_authorised_ten_percent_short
    ):
        """"The penalty is 0 points when the total gap is 0, 10 points when the gap ratio is greater
        than 0 and no more than 0.10, and 25 points when the gap ratio is strictly greater than 0.10."
        "Otherwise it is the funding requirement minus the active budget's `total_authorized_cents`,
        floored at 0".

        Design: Corner/calculations/funding_gap_tier_boundary_sits_at_exactly_one_tenth
        """
        scenario, _budget = plan_authorised_ten_percent_short

        run_compliance_sweep(api, scenario.plan_id)

        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "funding_requirement_cents", 1182500, "plan")
        assert_field_equals(plan, "funding_gap_cents", 118250, "plan")
        assert_posture(read_property(api, scenario.property_id), 90, "COMPLIANT")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "GOOD", "franchisee"
        )

    def test_one_cent_less_authorised_crosses_into_the_upper_penalty(
        self, api, plan_authorised_ten_percent_short
    ):
        """"The band boundary is inclusive on the compliant side: a score of exactly 80 is `COMPLIANT`
        and a score of 79 is `AT_RISK`." "else `WATCH` when any is `AT_RISK`".

        Design: Corner/calculations/funding_gap_tier_boundary_sits_at_exactly_one_tenth
        """
        scenario, _budget = plan_authorised_ten_percent_short
        run_compliance_sweep(api, scenario.plan_id)

        authorize_budget(api, scenario, 1064249)
        run_compliance_sweep(api, scenario.plan_id)

        assert_field_equals(
            read_plan(api, scenario.plan_id), "funding_gap_cents", 118251, "plan"
        )
        assert_posture(read_property(api, scenario.property_id), 75, "AT_RISK")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "WATCH", "franchisee"
        )

    def test_the_replacement_budget_supersedes_the_first_authorisation(
        self, api, plan_authorised_ten_percent_short
    ):
        """"Any existing budget of the same plan whose `status` is `DRAFT`, `APPROVED`, `LOCKED` or
        `UNDERFUNDED` becomes `SUPERSEDED` and stops being the plan's active budget; at most one
        active budget therefore exists per plan at any instant." "the `authorized_cents` taken from
        the active budget's `total_authorized_cents` (0 when no active budget exists)".

        Design: Corner/calculations/funding_gap_tier_boundary_sits_at_exactly_one_tenth
        """
        scenario, budget = plan_authorised_ten_percent_short

        replacement = authorize_budget(api, scenario, 1064249)

        assert_field_equals(read_budget(api, budget["id"]), "status", "SUPERSEDED", "first budget")
        assert_field_equals(replacement, "status", "DRAFT", "replacement budget")
        summary = read_cost_summary(api, scenario.plan_id)
        assert_field_equals(summary, "authorized_cents", 1064249, "cost summary")
        assert_field_equals(summary, "funding_gap_cents", 118251, "cost summary")


@pytest.fixture
def three_overdue_life_safety_items(api):
    """Three life-safety items read past their 90-day deadline, then swept."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "first",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-14.1.1",
                "brand_estimated_cost_cents": 100000,
            },
            {
                "key": "second",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-14.1.2",
                "brand_estimated_cost_cents": 100000,
            },
            {
                "key": "third",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-14.1.3",
                "brand_estimated_cost_cents": 100000,
            },
        ],
        legal_name="Greyholt Hotels LLC",
        contact_email="safety@greyholthotels.example",
    )
    set_clock(api, "2026-10-31T00:00:00Z")
    run_compliance_sweep(api, scenario.plan_id)
    return scenario


class TestLifeSafetyPenaltyCap:
    def test_a_third_overdue_life_safety_item_changes_nothing(
        self, api, three_overdue_life_safety_items
    ):
        """"Overdue life-safety items cost 25 points each, but that term is capped at 50 points in
        total, so a third overdue life-safety item changes nothing." "it re-evaluates the overdue flag
        on every item of the plan against the current clock, recomputes the plan's
        `overdue_item_count`".

        Design: Corner/calculations/life_safety_penalty_saturates_at_its_cap
        """
        scenario = three_overdue_life_safety_items

        for key in ("first", "second", "third"):
            assert_item_state(
                read_item(api, scenario.item_id(key)),
                status="SCOPED",
                deadline_date="2026-10-30",
                is_overdue=True,
            )

        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "overdue_item_count", 3, "plan")
        assert_field_equals(plan, "status", "ISSUED", "plan")
        assert_posture(read_property(api, scenario.property_id), 50, "AT_RISK")

    def test_the_risk_read_shows_the_saturated_term_and_its_inputs(
        self, api, three_overdue_life_safety_items
    ):
        """"The property's risk read exposes both variants side by side along with the inputs that
        produced them: `property_id`, `snapshot_score` and `snapshot_posture`, `projected_score` and
        `projected_posture`, the `projection_horizon_days` used (30), the snapshot overdue counts per
        category as `overdue_life_safety_count`, `overdue_guest_facing_count` and
        `overdue_back_of_house_count`". "The penalty is 0 points when the total gap is 0".

        Design: Corner/calculations/life_safety_penalty_saturates_at_its_cap
        """
        scenario = three_overdue_life_safety_items

        summary = read_risk_summary(api, scenario.property_id)

        assert_field_equals(summary, "snapshot_score", 50, "risk summary")
        assert_field_equals(summary, "snapshot_posture", "AT_RISK", "risk summary")
        assert_field_equals(summary, "overdue_life_safety_count", 3, "risk summary")
        assert_field_equals(summary, "funding_gap_penalty", 0, "risk summary")
        assert_field_equals(summary, "projected_score", 50, "risk summary")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "WATCH", "franchisee"
        )


@pytest.fixture
def two_breached_items_of_awkward_cost(api):
    """A life-safety item at 1000010 and a back-of-house item at 555550, both read past due."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "sprinklers",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-12.1.1",
                "brand_estimated_cost_cents": 1000010,
            },
            {
                "key": "laundry",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-12.1.1",
                "brand_estimated_cost_cents": 555550,
            },
        ],
        legal_name="Eastcliff Hotels LLC",
        contact_email="legal@eastcliffhotels.example",
    )
    set_clock(api, "2027-10-26T00:00:00Z")
    run_compliance_sweep(api, scenario.plan_id)
    return scenario


class TestLiquidatedDamagesRoundOnce:
    def test_the_exact_products_are_summed_before_the_single_rounding(
        self, api, two_breached_items_of_awkward_cost
    ):
        """"It computes `liquidated_damages_cents` over exactly those breached items: each item's
        `approved_cost_cents` is multiplied by its category's damages rate — 0.15 for `LIFE_SAFETY`,
        0.08 for `GUEST_FACING`, 0.03 for `BACK_OF_HOUSE` — the exact per-item products are summed,
        and the total is rounded half up to whole cents **once, at the end**. This is deliberately the
        opposite order from the funding requirement of §3.3, which rounds per item before summing; the
        two orders produce different integers and each calculation uses only its own."

        Design: Corner/calculations/liquidated_damages_sum_exactly_before_a_single_rounding
        """
        scenario = two_breached_items_of_awkward_cost

        notice = issue_default_notice(api, scenario, 10)

        assert_field_equals(notice, "liquidated_damages_cents", 166668, "notice")
        assert notice["liquidated_damages_cents"] != 166669, (
            "rounding each product before summing would give 166669, which is the wrong order"
        )

    def test_the_notice_snapshots_the_breach_in_priority_order(
        self, api, two_breached_items_of_awkward_cost
    ):
        """"Issuance creates the notice in `ISSUED` with `issued_by_user_id` set to the acting
        `X-User-ID` and `cure_deadline_date` set to the clock date advanced by `cure_period_days`. It
        snapshots `breached_item_ids` as the ids of every item of the plan whose overdue flag is true
        at that instant, ordered by `priority_rank` ascending".

        Design: Corner/calculations/liquidated_damages_sum_exactly_before_a_single_rounding
        """
        scenario = two_breached_items_of_awkward_cost

        notice = issue_default_notice(api, scenario, 10)

        assert_field_equals(notice, "status", "ISSUED", "notice")
        assert_field_equals(notice, "issued_by_user_id", "bm-001", "notice")
        assert_field_equals(notice, "cure_deadline_date", "2027-11-05", "notice")
        assert notice["breached_item_ids"] == [
            scenario.item_id("sprinklers"),
            scenario.item_id("laundry"),
        ], (
            "life safety ranks ahead of back of house, so the snapshot must run in that order, got "
            f"{notice['breached_item_ids']!r}"
        )

    def test_the_notice_puts_the_property_and_its_owner_into_default(
        self, api, two_breached_items_of_awkward_cost
    ):
        """"Issuance also moves the property's `franchise_agreement_status` to `DEFAULT_NOTICED`, its
        `compliance_posture` to `IN_DEFAULT` and the franchisee's `standing` to `DEFAULT`, and appends
        a ledger entry of type `DEFAULT_ISSUED`." "Overdue life-safety items cost 25 points each ...
        Overdue guest-facing items cost 8 points each and overdue back-of-house items 3 points each,
        both uncapped."

        Design: Corner/calculations/liquidated_damages_sum_exactly_before_a_single_rounding
        """
        scenario = two_breached_items_of_awkward_cost
        issue_default_notice(api, scenario, 10)

        prop = read_property(api, scenario.property_id)

        assert_field_equals(prop, "franchise_agreement_status", "DEFAULT_NOTICED", "property")
        assert_posture(prop, 72, "IN_DEFAULT")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "DEFAULT", "franchisee"
        )
        assert_field_equals(read_plan(api, scenario.plan_id), "status", "ISSUED", "plan")
