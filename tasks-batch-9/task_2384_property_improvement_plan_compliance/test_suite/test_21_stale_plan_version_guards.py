"""Two writers holding a plan version that a dispute, or their own earlier write, has moved on."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_plan_dimensions,
    bootstrap_portfolio,
    capital_budget_payload,
    current_plan_version,
    file_dispute,
    item_revision_payload,
    list_rows,
    read_item,
    read_plan,
    scope_plan,
    validate_error,
    validate_success,
)


@pytest.fixture
def acknowledged_plan_whose_version_the_owner_has_read(api):
    """An acknowledged plan and the version the owner captured before contesting anything."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-39.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Quenington Hotels LLC",
        contact_email="ops@queningtonh.example",
        property_overrides={"name": "Quenington Malt House"},
    )
    return scenario, current_plan_version(api, scenario.plan_id, scenario.owner_headers)


class TestADisputeInvalidatesTheHeldPlanVersion:
    def test_filing_the_dispute_moves_the_version_under_the_writer(
        self, api, acknowledged_plan_whose_version_the_owner_has_read
    ):
        """"The plan's `dispute_state` moves to `DISPUTE_OPEN` while its `status` is left completely
        untouched. The contested item's `owner_claimed_cost_cents` is set to the dispute's
        `claimed_cost_cents`, and the plan's `owner_claimed_total_cents` is recomputed ... And the
        plan's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_blocks_a_budget_create_after_a_dispute
        """
        scenario, stale_version = acknowledged_plan_whose_version_the_owner_has_read

        dispute = file_dispute(
            api,
            scenario,
            scenario.item_id("corridors"),
            claimed_cost_cents=1400000,
            dispute_basis="COST_ESTIMATE",
        )

        assert_field_equals(dispute, "status", "FILED", "dispute")
        plan = read_plan(api, scenario.plan_id)
        assert_plan_dimensions(
            plan, status="OWNER_ACKNOWLEDGED", dispute_state="DISPUTE_OPEN"
        )
        assert_field_equals(plan, "version", stale_version + 1, "plan")
        assert_field_equals(plan, "owner_claimed_total_cents", 1400000, "plan")

    def test_a_budget_authored_against_the_pre_dispute_version_is_refused(
        self, api, acknowledged_plan_whose_version_the_owner_has_read
    ):
        """"if `expected_plan_version` does not equal the plan's current `version` the create is
        rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), which is what stops a writer whose view of
        the plan's scope, cost totals or existing budget is out of date from silently replacing a budget
        it never saw."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_blocks_a_budget_create_after_a_dispute
        """
        scenario, stale_version = acknowledged_plan_whose_version_the_owner_has_read
        file_dispute(
            api,
            scenario,
            scenario.item_id("corridors"),
            claimed_cost_cents=1400000,
            dispute_basis="COST_ESTIMATE",
        )

        response = api.create_capital_budget(
            capital_budget_payload(scenario.plan_id, 1182500, stale_version),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_STALE_PLAN_VERSION, 412)
        _rows, meta = list_rows(api, "list_capital_budgets", plan_id=scenario.plan_id)
        assert meta["total_count"] == 0, f"the refused create must persist nothing, got {meta}"

    def test_the_same_authorisation_lands_once_the_version_is_refreshed(
        self, api, acknowledged_plan_whose_version_the_owner_has_read
    ):
        """"A new budget legitimately supersedes the plan's prior budget, so no state check blocks a
        second create". "The requirement is computed from the brand's figures alone" — so the
        owner-claimed figure moves neither the requirement nor the gap.

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_blocks_a_budget_create_after_a_dispute
        """
        scenario, _stale_version = acknowledged_plan_whose_version_the_owner_has_read
        file_dispute(
            api,
            scenario,
            scenario.item_id("corridors"),
            claimed_cost_cents=1400000,
            dispute_basis="COST_ESTIMATE",
        )
        fresh_version = current_plan_version(api, scenario.plan_id, scenario.owner_headers)

        budget = validate_success(
            api.create_capital_budget(
                capital_budget_payload(scenario.plan_id, 1182500, fresh_version),
                scenario.owner_headers,
            ),
            201,
        )

        assert_field_equals(budget, "status", "DRAFT", "budget")
        assert_field_equals(budget, "total_authorized_cents", 1182500, "budget")
        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "funding_requirement_cents", 1182500, "plan")
        assert_field_equals(plan, "funding_gap_cents", 0, "plan")
        assert_field_equals(plan, "version", fresh_version + 1, "plan")


@pytest.fixture
def draft_plan_with_two_items_and_a_captured_version(api):
    """A draft plan holding one guest-facing and one back-of-house item, plus the read version."""
    portfolio = bootstrap_portfolio(
        api,
        "Sedgemoor Hotels LLC",
        "ops@sedgemoorh.example",
        name="Sedgemoor Assembly Hall",
    )
    scenario = scope_plan(
        api,
        portfolio,
        [
            {
                "key": "guest_facing",
                "category": "GUEST_FACING",
                "standards_reference": "GF-41.1.1",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "back_of_house",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-41.1.1",
                "brand_estimated_cost_cents": 500000,
            },
        ],
    )
    return scenario, current_plan_version(api, scenario.plan_id)


def _revise_the_guest_facing_item(api, brand_manager, scenario, version):
    return validate_success(
        api.patch_item(
            scenario.item_id("guest_facing"),
            item_revision_payload(version, brand_estimated_cost_cents=2000000),
            brand_manager,
        )
    )


class TestARevisionInvalidatesTheVersionItWasComputedFrom:
    def test_the_first_revision_rewrites_the_item_and_bumps_the_plan(
        self, api, brand_manager, draft_plan_with_two_items_and_a_captured_version
    ):
        """"A revision rewrites the supplied fields, re-derives `approved_cost_cents` from the new
        `brand_estimated_cost_cents`, recomputes `scope_item_count`, both cost totals and the plan's
        funding requirement, and increments both the item's `version` and the plan's `version`." "That
        product is rounded half up to whole cents and stored on the item as `item_funding_cents`."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_blocks_a_second_item_patch_reusing_the_same_version
        """
        scenario, stale_version = draft_plan_with_two_items_and_a_captured_version

        revised = _revise_the_guest_facing_item(api, brand_manager, scenario, stale_version)

        assert_field_equals(revised, "approved_cost_cents", 2000000, "revised item")
        assert_field_equals(revised, "item_funding_cents", 2365000, "revised item")
        assert_field_equals(
            read_plan(api, scenario.plan_id), "version", stale_version + 1, "plan"
        )

    def test_a_second_revision_reusing_the_same_version_is_refused(
        self, api, brand_manager, draft_plan_with_two_items_and_a_captured_version
    ):
        """"Repeated scope revisions on a draft plan are all legitimate and each one rewrites the plan's
        cost aggregates, so a mismatch against the plan's current `version` is rejected with
        `ERR_STALE_PLAN_VERSION` (HTTP 412) — the only thing that prevents a revision computed against
        superseded aggregates from landing."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_blocks_a_second_item_patch_reusing_the_same_version
        """
        scenario, stale_version = draft_plan_with_two_items_and_a_captured_version
        _revise_the_guest_facing_item(api, brand_manager, scenario, stale_version)

        response = api.patch_item(
            scenario.item_id("back_of_house"),
            item_revision_payload(stale_version, brand_estimated_cost_cents=800000),
            brand_manager,
        )

        validate_error(response, ApiErrorId.ERR_STALE_PLAN_VERSION, 412)
        assert_field_equals(
            read_item(api, scenario.item_id("back_of_house")),
            "brand_estimated_cost_cents",
            500000,
            "back-of-house item",
        )

    def test_the_retry_at_the_fresh_version_lands_and_both_revisions_show_up(
        self, api, brand_manager, draft_plan_with_two_items_and_a_captured_version
    ):
        """"Only after every item has been individually rounded are those rounded figures summed, and
        the sum is the plan's `funding_requirement_cents`." "the item's `approved_cost_cents` is
        multiplied by one plus the contingency and then multiplied by that item's category escalation
        factor — 1.00 for `LIFE_SAFETY`, 1.075 for `GUEST_FACING`, and 1.035 for `BACK_OF_HOUSE`."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_blocks_a_second_item_patch_reusing_the_same_version
        """
        scenario, stale_version = draft_plan_with_two_items_and_a_captured_version
        _revise_the_guest_facing_item(api, brand_manager, scenario, stale_version)
        fresh_version = current_plan_version(api, scenario.plan_id)

        revised = validate_success(
            api.patch_item(
                scenario.item_id("back_of_house"),
                item_revision_payload(fresh_version, brand_estimated_cost_cents=800000),
                brand_manager,
            )
        )

        assert_field_equals(revised, "approved_cost_cents", 800000, "revised item")
        assert_field_equals(revised, "item_funding_cents", 910800, "revised item")
        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "brand_scoped_total_cents", 2800000, "plan")
        assert_field_equals(plan, "funding_requirement_cents", 3275800, "plan")
        assert_field_equals(plan, "scope_item_count", 2, "plan")
        assert_field_equals(plan, "version", fresh_version + 1, "plan")
