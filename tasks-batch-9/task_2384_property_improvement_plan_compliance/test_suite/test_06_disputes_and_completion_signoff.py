"""The plan's two independent dimensions, and the one place they meet at sign-off."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    INSPECTOR_USER_ID,
    acknowledged_plan,
    assert_field_equals,
    assert_ledger_contains,
    assert_plan_dimensions,
    file_dispute,
    ledger_entries,
    performed_completion_inspection,
    read_budget,
    read_dispute,
    read_inspection,
    read_item,
    read_plan,
    read_property,
    resolve_dispute,
    sign_off_inspection,
    validate_error,
    validate_success,
)


@pytest.fixture
def acknowledged_plan_with_one_item(api):
    """An acknowledged plan carrying a single guest-facing item, ready to be contested."""
    return acknowledged_plan(
        api,
        [
            {
                "key": "furniture",
                "category": "GUEST_FACING",
                "standards_reference": "GF-7.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Copperline Hotels LP",
        contact_email="owner@copperlinehotels.example",
    )


class TestDisputeDimensionCycles:
    def test_the_dispute_dimension_returns_to_open_for_each_new_filing(
        self, api, acknowledged_plan_with_one_item
    ):
        """"Filing works identically from every prior value of the dispute dimension: a plan whose
        `dispute_state` was `NONE`, `DISPUTE_RESOLVED_UPHELD`, `DISPUTE_RESOLVED_REVISED` or
        `DISPUTE_RESOLVED_REMOVED` all return to `DISPUTE_OPEN` for the newly filed dispute".

        Design: Difficulty/non_linear_state_machine/plan_dispute_dimension_cycles_while_status_dimension_holds
        """
        scenario = acknowledged_plan_with_one_item
        assert_plan_dimensions(read_plan(api, scenario.plan_id), dispute_state="NONE")

        first = file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=400000,
            dispute_basis="SCOPE_REASONABLENESS",
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), dispute_state="DISPUTE_OPEN")

        resolve_dispute(api, first["id"], "UPHOLD")
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), dispute_state="DISPUTE_RESOLVED_UPHELD"
        )

        file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=450000,
            dispute_basis="STANDARDS_APPLICABILITY",
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), dispute_state="DISPUTE_OPEN")

    def test_the_lifecycle_dimension_holds_still_through_the_whole_cycle(
        self, api, acknowledged_plan_with_one_item
    ):
        """"The two dimensions evolve independently: filing or resolving a dispute never moves
        `status`, and issuing, acknowledging or completing a plan never moves `dispute_state`."

        Design: Difficulty/non_linear_state_machine/plan_dispute_dimension_cycles_while_status_dimension_holds
        """
        scenario = acknowledged_plan_with_one_item

        first = file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=400000,
            dispute_basis="SCOPE_REASONABLENESS",
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="OWNER_ACKNOWLEDGED")

        resolve_dispute(api, first["id"], "UPHOLD")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="OWNER_ACKNOWLEDGED")

        file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=450000,
            dispute_basis="STANDARDS_APPLICABILITY",
        )
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id),
            status="OWNER_ACKNOWLEDGED",
            dispute_state="DISPUTE_OPEN",
        )

    def test_a_resolved_dispute_stays_resolved_while_a_fresh_contest_opens(
        self, api, acknowledged_plan_with_one_item
    ):
        """"A dispute's three resolved values — `RESOLVED_UPHELD`, `RESOLVED_REVISED` and
        `RESOLVED_REMOVED` — are all terminal; a resolved dispute is never reopened, and a fresh
        contest requires a new filing."

        Design: Difficulty/non_linear_state_machine/plan_dispute_dimension_cycles_while_status_dimension_holds
        """
        scenario = acknowledged_plan_with_one_item
        first = file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=400000,
            dispute_basis="SCOPE_REASONABLENESS",
        )
        resolve_dispute(api, first["id"], "UPHOLD")
        second = file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=450000,
            dispute_basis="STANDARDS_APPLICABILITY",
        )

        assert_field_equals(read_dispute(api, first["id"]), "status", "RESOLVED_UPHELD", "first")
        assert_field_equals(read_dispute(api, second["id"]), "status", "FILED", "second")

    def test_the_latest_claim_is_the_one_the_owner_variant_reports(
        self, api, acknowledged_plan_with_one_item
    ):
        """"Its `owner_claimed_cost_cents` is the `claimed_cost_cents` of the most recently filed
        dispute on that item, and null while no dispute has ever been filed." On an upheld
        resolution "No cost moves: the item's `approved_cost_cents` stays at its
        `brand_estimated_cost_cents`."

        Design: Difficulty/non_linear_state_machine/plan_dispute_dimension_cycles_while_status_dimension_holds
        """
        scenario = acknowledged_plan_with_one_item
        first = file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=400000,
            dispute_basis="SCOPE_REASONABLENESS",
        )
        resolve_dispute(api, first["id"], "UPHOLD")
        file_dispute(
            api,
            scenario,
            scenario.item_id("furniture"),
            claimed_cost_cents=450000,
            dispute_basis="STANDARDS_APPLICABILITY",
        )

        item = read_item(api, scenario.item_id("furniture"))
        plan = read_plan(api, scenario.plan_id)

        assert_field_equals(item, "approved_cost_cents", 1000000, "contested item")
        assert_field_equals(item, "owner_claimed_cost_cents", 450000, "contested item")
        assert_field_equals(plan, "brand_scoped_total_cents", 1000000, "plan")
        assert_field_equals(plan, "owner_claimed_total_cents", 450000, "plan")


@pytest.fixture
def performed_inspection_with_open_dispute(api):
    """Work finished, the completion visit performed, and then the owner contests the price."""
    built = performed_completion_inspection(
        api,
        [
            {
                "key": "guestrooms",
                "category": "GUEST_FACING",
                "standards_reference": "GF-3.3.3",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        1182500,
        legal_name="Fairhaven Lodging LLC",
        contact_email="gm@fairhavenlodging.example",
    )
    scenario = built["scenario"]
    built["dispute"] = file_dispute(
        api,
        scenario,
        scenario.item_id("guestrooms"),
        claimed_cost_cents=1500000,
        dispute_basis="COST_ESTIMATE",
    )
    return built


class TestSignOffMeetsTheDisputeDimension:
    def test_sign_off_is_refused_while_a_dispute_is_open(
        self, api, brand_inspector, performed_inspection_with_open_dispute
    ):
        """"The plan's `dispute_state` must not be `DISPUTE_OPEN`, or
        `ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF`." "The one place the dimensions meet is completion
        sign-off, which is refused while the dispute dimension reads `DISPUTE_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/completion_signoff_gated_by_plan_dispute_dimension
        """
        built = performed_inspection_with_open_dispute
        scenario = built["scenario"]

        response = api.sign_off_inspection(built["inspection"]["id"], brand_inspector)

        validate_error(response, ApiErrorId.ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF, 409)
        assert_field_equals(
            read_plan(api, scenario.plan_id),
            "status",
            "READY_FOR_COMPLETION_INSPECTION",
            "plan",
        )

    def test_the_refused_sign_off_leaves_the_inspection_performed(
        self, api, brand_inspector, performed_inspection_with_open_dispute
    ):
        """"The inspection must be in `PERFORMED`, or `ERR_INSPECTION_NOT_SIGNABLE`."
        "`SIGNED_OFF` is the terminal inspection state."

        Design: Difficulty/cross_entity_state_dependency/completion_signoff_gated_by_plan_dispute_dimension
        """
        built = performed_inspection_with_open_dispute

        validate_error(
            api.sign_off_inspection(built["inspection"]["id"], brand_inspector),
            ApiErrorId.ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF,
            409,
        )

        assert_field_equals(
            read_inspection(api, built["inspection"]["id"]), "status", "PERFORMED", "inspection"
        )

    def test_resolving_the_dispute_releases_the_certification(
        self, api, brand_inspector, performed_inspection_with_open_dispute
    ):
        """"A successful sign-off moves the inspection `PERFORMED → SIGNED_OFF`, stamping
        `signed_off_at` with the logical clock and `signed_off_by_user_id` with the acting
        `X-User-ID`".

        Design: Difficulty/cross_entity_state_dependency/completion_signoff_gated_by_plan_dispute_dimension
        """
        built = performed_inspection_with_open_dispute
        scenario = built["scenario"]
        validate_error(
            api.sign_off_inspection(built["inspection"]["id"], brand_inspector),
            ApiErrorId.ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF,
            409,
        )
        resolve_dispute(api, built["dispute"]["id"], "UPHOLD")

        signed = validate_success(
            api.sign_off_inspection(built["inspection"]["id"], brand_inspector)
        )

        assert_field_equals(signed, "status", "SIGNED_OFF", "inspection")
        assert_field_equals(signed, "signed_off_by_user_id", INSPECTOR_USER_ID, "inspection")
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), dispute_state="DISPUTE_RESOLVED_UPHELD"
        )

    def test_the_certification_drives_the_completion_cascade(
        self, api, performed_inspection_with_open_dispute
    ):
        """"The plan moves `READY_FOR_COMPLETION_INSPECTION → COMPLETED` and its `version`
        increments. Every item of the plan still in `WORK_COMPLETE` becomes `ACCEPTED`, each with
        its `version` incremented." "The plan's active capital budget — whichever of `APPROVED`,
        `LOCKED` or `UNDERFUNDED` it holds — becomes `CLOSED`, freezing `committed_cents`."

        Design: Difficulty/cross_entity_state_dependency/completion_signoff_gated_by_plan_dispute_dimension
        """
        built = performed_inspection_with_open_dispute
        scenario = built["scenario"]
        resolve_dispute(api, built["dispute"]["id"], "UPHOLD")
        sign_off_inspection(api, built["inspection"]["id"])

        assert_field_equals(read_plan(api, scenario.plan_id), "status", "COMPLETED", "plan")
        assert_field_equals(
            read_item(api, scenario.item_id("guestrooms")), "status", "ACCEPTED", "item"
        )
        assert_field_equals(read_budget(api, built["budget"]["id"]), "status", "CLOSED", "budget")

    def test_completion_clears_the_property_s_open_work(
        self, api, performed_inspection_with_open_dispute
    ):
        """"A ledger entry of type `PLAN_COMPLETED` is appended with a null item reference and a
        `delta_cents` of 0. Finally the property's `open_plan_count`, `compliance_risk_score` and
        `compliance_posture` are recomputed, followed by the franchisee's `standing`."

        Design: Difficulty/cross_entity_state_dependency/completion_signoff_gated_by_plan_dispute_dimension
        """
        built = performed_inspection_with_open_dispute
        scenario = built["scenario"]
        resolve_dispute(api, built["dispute"]["id"], "UPHOLD")
        sign_off_inspection(api, built["inspection"]["id"])

        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "PLAN_COMPLETED",
            delta_cents=0,
            item_id=None,
        )
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "open_plan_count", 0, "property")
        assert_field_equals(prop, "compliance_posture", "COMPLIANT", "property")
