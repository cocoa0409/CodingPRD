"""Group-block displacement analysis and the negotiate / revise / commit lifecycle.

Covers the group_displacement dual-variant calculation, the cyclic
NEGOTIATING <-> REVISION_REQUESTED loop, and the evaluation preconditions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    set_clock,
    create_property,
    create_room_type,
    create_rate_plan,
    create_inventory_day,
    create_rate_decision,
    publish_decision,
    create_group_block,
    evaluate_group_block,
    ApiErrorId,
)

RM = TEST_USERS["revenue_manager_headers"]
GSM = TEST_USERS["group_sales_manager_headers"]


def _published_bar_with_inventory(stay_date, capacity, sold, revenue, base_rate=230, published_rate=230):
    """Property + master BAR plan published at `published_rate` + one InventoryDay."""
    prop = create_property(name="Disp", total_rooms=capacity)
    rt = create_room_type(prop["id"], code="KING", name="King Room", physical_rooms=capacity)
    plan = create_rate_plan(
        rt["id"], rate_class="BAR", is_master_bar=True,
        base_rate=base_rate, floor_rate=100, ceiling_rate=400,
    )
    create_inventory_day(rt["id"], stay_date, physical_capacity=capacity,
                         transient_sold_rooms=sold, transient_revenue=revenue)
    dec = create_rate_decision(plan["id"], stay_date, requested_rate=published_rate)
    publish_decision(dec["id"], plan["version"])
    return prop, rt, plan


class TestDisplacementDualVariant:
    def test_lrv_method_values_spill_at_bar_rate_reject(self, api):
        """PRD §3.7: "Under the default **LRV** variant (selected when `method` is
        omitted or `LRV`), each night's spill is valued at the room type's
        effective BAR rate — a last-room-value proxy that is the master BAR plan's
        `published_rate` if a master BAR plan exists and has been published, else
        that plan's `base_rate` if a master BAR plan exists but has not yet
        published, else 0 if the room type has no master BAR plan at all."
        PRD §3.7: "the recommendation is `ACCEPT` when the group value is at least
        the displacement cost, and `REJECT` otherwise."

        Design: Difficulty/dual_variant_calc/group_displacement_lrv_vs_forecast_rev_diverge
        """
        set_clock("2026-06-01T00:00:00Z")
        prop, rt, plan = _published_bar_with_inventory(
            "2026-06-06T00:00:00Z", capacity=30, sold=20, revenue=4000, base_rate=230, published_rate=230
        )
        gb = create_group_block(
            rt["id"], "2026-06-06T00:00:00Z", group_name="Acme",
            nights=1, rooms_per_night=10, offered_rate=210,
        )
        data = validate_success(api.evaluate_group_block(gb["id"], {"method": "LRV"}, RM))
        # spill 10 * published_rate 230 = 2300; group_value 2100 < 2300 -> REJECT
        assert data["displacement_cost"] == 2300.00, f"expected 2300.00 got {data['displacement_cost']}"
        assert data["recommendation"] == "REJECT"

    def test_forecast_rev_method_values_spill_at_transient_adr_accept(self, api):
        """PRD §3.7: "Under the **FORECAST_REV** variant (selected when `method`
        is `FORECAST_REV`), each night's spill is instead valued at that night's
        realized transient ADR, which is the night's `transient_revenue` divided by
        its `transient_sold_rooms` (with the denominator treated as at least 1 to
        avoid division by zero)."
        PRD §3.7: "the recommendation is `ACCEPT` when the group value is at least
        the displacement cost, and `REJECT` otherwise."

        Design: Difficulty/dual_variant_calc/group_displacement_lrv_vs_forecast_rev_diverge
        """
        set_clock("2026-06-01T00:00:00Z")
        prop, rt, plan = _published_bar_with_inventory(
            "2026-06-06T00:00:00Z", capacity=30, sold=20, revenue=4000, base_rate=230, published_rate=230
        )
        gb = create_group_block(
            rt["id"], "2026-06-06T00:00:00Z", group_name="Acme",
            nights=1, rooms_per_night=10, offered_rate=210,
        )
        data = validate_success(api.evaluate_group_block(gb["id"], {"method": "FORECAST_REV"}, RM))
        # spill 10 * transient ADR (4000/20=200) = 2000; group_value 2100 >= 2000 -> ACCEPT
        assert data["displacement_cost"] == 2000.00, f"expected 2000.00 got {data['displacement_cost']}"
        assert data["recommendation"] == "ACCEPT"


class TestRevisionLoop:
    def test_request_revision_then_revise_resets_evaluation(self, api):
        """PRD §3.7: "When an evaluation recommends `REJECT`, the `RevenueManager`
        may move the block `NEGOTIATING → REVISION_REQUESTED`, recording that a
        higher rate or smaller block is sought; this requires the block to be
        `NEGOTIATING` and to have been evaluated to a `REJECT` recommendation."
        PRD §3.7: "The `GroupSalesManager` then revises the block while it is
        `REVISION_REQUESTED`, supplying a new `offered_rate` and/or
        `rooms_per_night`; this moves it back `REVISION_REQUESTED → NEGOTIATING`,
        resets `displacement_cost` and `recommendation` to null so the block must
        be re-evaluated, and bumps `version`."

        Design: Difficulty/non_linear_state_machine/group_block_cyclic_negotiating_revision_loop
        """
        set_clock("2026-06-01T00:00:00Z")
        prop, rt, plan = _published_bar_with_inventory(
            "2026-06-06T00:00:00Z", capacity=30, sold=20, revenue=4000, base_rate=230, published_rate=230
        )
        gb = create_group_block(
            rt["id"], "2026-06-06T00:00:00Z", group_name="Acme",
            nights=1, rooms_per_night=10, offered_rate=210,
        )
        evaluate_group_block(gb["id"], "LRV")  # REJECT

        after_req = validate_success(api.request_revision_group_block(gb["id"], RM))
        assert after_req["status"] == "REVISION_REQUESTED"

        after_revise = validate_success(api.revise_group_block(gb["id"], {"offered_rate": 300}, GSM))
        assert after_revise["status"] == "NEGOTIATING"
        assert after_revise["displacement_cost"] is None
        assert after_revise["recommendation"] is None

    def test_revision_loop_allows_reevaluation_after_revise(self, api):
        """PRD §3.7: "The `GroupSalesManager` then revises the block while it is
        `REVISION_REQUESTED`, supplying a new `offered_rate` and/or
        `rooms_per_night`; this moves it back `REVISION_REQUESTED → NEGOTIATING`,
        resets `displacement_cost` and `recommendation` to null so the block must
        be re-evaluated, and bumps `version`."
        PRD §3.7: "the recommendation is `ACCEPT` when the group value is at least
        the displacement cost, and `REJECT` otherwise."

        Design: Difficulty/non_linear_state_machine/group_block_cyclic_negotiating_revision_loop
        """
        set_clock("2026-06-01T00:00:00Z")
        prop, rt, plan = _published_bar_with_inventory(
            "2026-06-06T00:00:00Z", capacity=30, sold=20, revenue=4000, base_rate=230, published_rate=230
        )
        gb = create_group_block(
            rt["id"], "2026-06-06T00:00:00Z", group_name="Acme",
            nights=1, rooms_per_night=10, offered_rate=210,
        )
        evaluate_group_block(gb["id"], "LRV")  # REJECT (value 2100 < cost 2300)
        validate_success(api.request_revision_group_block(gb["id"], RM))
        # Raise offered_rate to 250 -> group_value 2500 >= cost 2300, so re-eval now ACCEPTs.
        validate_success(api.revise_group_block(gb["id"], {"offered_rate": 250}, GSM))
        reeval = validate_success(api.evaluate_group_block(gb["id"], {"method": "LRV"}, RM))
        assert reeval["displacement_cost"] == 2300.00, f"expected 2300.00 got {reeval['displacement_cost']}"
        assert reeval["recommendation"] == "ACCEPT"

    def test_request_revision_on_accept_block_rejected(self, api):
        """PRD §3.7: "this requires the block to be `NEGOTIATING` and to have been
        evaluated to a `REJECT` recommendation, and an unevaluated block (its
        `displacement_cost` still null) is rejected with `ERR_NOT_EVALUATED`."

        Design: Corner/state_machines/request_revision_on_accept_evaluated_block_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="RevReq", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_inventory_day(rt["id"], "2026-06-05T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        gb = create_group_block(
            rt["id"], "2026-06-05T00:00:00Z", group_name="Oscar",
            nights=1, rooms_per_night=3, offered_rate=400,
        )
        ev = evaluate_group_block(gb["id"], "LRV")
        assert ev["recommendation"] == "ACCEPT"
        resp = api.request_revision_group_block(gb["id"], RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestCommitPreconditions:
    def test_commit_without_evaluation_rejected(self, api):
        """PRD §3.7: "it must have been evaluated with an `ACCEPT` recommendation
        (an unevaluated block yields `ERR_NOT_EVALUATED`)."

        Design: Corner/state_machines/commit_group_block_in_negotiating_without_evaluation_returns_not_evaluated
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="NoEval", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_inventory_day(rt["id"], "2026-06-05T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        gb = create_group_block(
            rt["id"], "2026-06-05T00:00:00Z", group_name="Mike",
            nights=1, rooms_per_night=2, offered_rate=300,
        )
        resp = api.commit_group_block(gb["id"], {"expected_room_type_version": rt["version"]}, GSM)
        validate_error(resp, ApiErrorId.ERR_NOT_EVALUATED.value)
