"""A contribution that invalidates a held property version, and derived reads that never lag."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_plan_dimensions,
    assert_posture,
    credit_reserve_contribution,
    current_property_version,
    list_rows,
    locked_budget,
    read_franchisee,
    read_plan,
    read_property,
    read_risk_summary,
    reserve_draw_payload,
    start_item,
    validate_error,
    validate_success,
)


@pytest.fixture
def running_item_and_a_captured_property_version(api):
    """A locked plan with work under way, and the reserve version the owner captured beforehand."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-40.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Rushmere Hotels LLC",
        contact_email="ops@rushmereh.example",
        property_overrides={"name": "Rushmere Pump Rooms"},
    )
    budget = locked_budget(api, scenario, 1182500, financing_source="RESERVE_DRAW")
    start_item(api, scenario, scenario.item_id("corridors"))
    return (
        scenario,
        budget,
        current_property_version(api, scenario.property_id, scenario.owner_headers),
    )


class TestAContributionInvalidatesTheHeldPropertyVersion:
    def test_the_contribution_lifts_the_corpus_and_the_version(
        self, api, running_item_and_a_captured_property_version
    ):
        """"Separately, the owner credits a monthly reserve contribution by supplying `amount_cents`;
        the contribution adds that amount to both `reserve_balance_cents` and
        `reserve_contributed_total_cents`, so the reserve corpus of §2.10 still balances, and increments
        the property's `version`."

        Design: Corner/cross_cutting_complexity_layers/stale_property_version_blocks_a_draw_after_a_reserve_contribution
        """
        scenario, _budget, stale_version = running_item_and_a_captured_property_version

        credited = credit_reserve_contribution(api, scenario.portfolio, 1000000)

        assert_field_equals(credited, "reserve_balance_cents", 51000000, "property")
        assert_field_equals(credited, "reserve_contributed_total_cents", 1000000, "property")
        assert_field_equals(credited, "version", stale_version + 1, "property")

    def test_a_draw_authored_against_the_pre_contribution_version_is_refused(
        self, api, running_item_and_a_captured_property_version
    ):
        """"a mismatch against the property's current `version` is rejected with
        `ERR_STALE_PROPERTY_VERSION` (HTTP 412), stopping a writer whose view of the reserve balance,
        retention floor or outstanding encumbrances is out of date."

        Design: Corner/cross_cutting_complexity_layers/stale_property_version_blocks_a_draw_after_a_reserve_contribution
        """
        scenario, budget, stale_version = running_item_and_a_captured_property_version
        credit_reserve_contribution(api, scenario.portfolio, 1000000)

        response = api.create_reserve_draw(
            reserve_draw_payload(
                scenario.property_id,
                budget["id"],
                scenario.item_id("corridors"),
                500000,
                stale_version,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_STALE_PROPERTY_VERSION, 412)
        _rows, meta = list_rows(api, "list_reserve_draws", property_id=scenario.property_id)
        assert meta["total_count"] == 0, f"the refused draw must persist nothing, got {meta}"

    def test_the_retry_at_the_fresh_version_encumbers_without_paying(
        self, api, running_item_and_a_captured_property_version
    ):
        """"Two draws that each fit inside the available reserve headroom are both legitimate, so no
        state check rejects the second". "A requested or consented draw *encumbers* its amount: it is
        earmarked but not yet paid." "`initial_reserve_balance_cents` is set to the supplied
        `reserve_balance_cents` and becomes the immutable anchor of the reserve-corpus invariant".

        Design: Corner/cross_cutting_complexity_layers/stale_property_version_blocks_a_draw_after_a_reserve_contribution
        """
        scenario, budget, _stale_version = running_item_and_a_captured_property_version
        credit_reserve_contribution(api, scenario.portfolio, 1000000)
        fresh_version = current_property_version(
            api, scenario.property_id, scenario.owner_headers
        )

        draw = validate_success(
            api.create_reserve_draw(
                reserve_draw_payload(
                    scenario.property_id,
                    budget["id"],
                    scenario.item_id("corridors"),
                    500000,
                    fresh_version,
                ),
                scenario.owner_headers,
            ),
            201,
        )

        assert_field_equals(draw, "status", "REQUESTED", "draw")
        assert_field_equals(draw, "amount_cents", 500000, "draw")
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "version", fresh_version + 1, "property")
        assert_field_equals(prop, "reserve_balance_cents", 51000000, "property")
        assert_field_equals(prop, "initial_reserve_balance_cents", 50000000, "property")
        _rows, meta = list_rows(api, "list_reserve_draws", property_id=scenario.property_id)
        assert meta["total_count"] == 1, f"only the retry may have persisted, got {meta}"


@pytest.fixture
def plan_with_its_start_gate_open(api):
    """An acknowledged plan fully funded at 1182500 and locked, so the first start will succeed."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-42.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Thornbury Hotels LLC",
        contact_email="ops@thornburyh.example",
        property_overrides={"name": "Thornbury Guild Court"},
    )
    locked_budget(api, scenario, 1182500)
    return scenario


class TestEveryDerivedFieldIsCurrentInTheSameResponse:
    def test_the_write_body_itself_already_carries_the_new_state(
        self, api, plan_with_its_start_gate_open
    ):
        """"The item moves `SCOPED → IN_PROGRESS` and its `version` increments. Because the item left
        `SCOPED`, if the plan's `status` was `OWNER_ACKNOWLEDGED` the plan advances `OWNER_ACKNOWLEDGED
        → IN_EXECUTION` and the plan's `version` increments — this is a system transition with no client
        request of its own, fired by the first item of the plan to leave `SCOPED`."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
        """
        scenario = plan_with_its_start_gate_open

        started = validate_success(
            api.start_item(scenario.item_id("corridors"), scenario.owner_headers)
        )

        assert_item_state(started, status="IN_PROGRESS")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")

    def test_the_derived_reads_are_all_current_in_the_same_chain(
        self, api, plan_with_its_start_gate_open
    ):
        """"where the cascade recomputes a derived field, the field must reflect the state as of the end
        of the request, not the state at its start." "And because the plan's status changed, the
        property's `compliance_risk_score` and `compliance_posture` are recomputed, and then the
        franchisee's `standing`."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
        """
        scenario = plan_with_its_start_gate_open
        start_item(api, scenario, scenario.item_id("corridors"))

        summary = read_risk_summary(api, scenario.property_id)

        assert_field_equals(summary, "snapshot_score", 100, "risk summary")
        assert_field_equals(summary, "snapshot_posture", "COMPLIANT", "risk summary")
        assert_field_equals(summary, "funding_gap_penalty", 0, "risk summary")
        assert_field_equals(summary, "projected_score", 100, "risk summary")
        prop = read_property(api, scenario.property_id)
        assert_posture(prop, 100, "COMPLIANT")
        assert_field_equals(prop, "open_plan_count", 1, "property")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "GOOD", "franchisee"
        )
        assert_field_equals(read_plan(api, scenario.plan_id), "funding_gap_cents", 0, "plan")
