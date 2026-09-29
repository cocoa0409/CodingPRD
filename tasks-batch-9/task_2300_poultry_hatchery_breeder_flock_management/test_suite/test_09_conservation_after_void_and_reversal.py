"""The two counting invariants held across their compensating paths.

Eggs are voided out of a load and drawn again; chicks are reversed out of an
assignment and allocated again. In both cases the invariant is checked before the
compensation, immediately after it, and again after the resource is re-committed.
"""

from typing import Any, Dict, List

from test_helpers import (
    ApiClient,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    AssignmentStatus,
    EggLotStatus,
    ItemStatus,
    OrderStatus,
    SetterLoadStatus,
    UnitType,
    assert_chick_batch,
    assert_chick_conservation,
    assert_delivery_assignment,
    assert_egg_conservation,
    assert_egg_lot,
    assert_placement_order,
    assert_setter_load,
    assert_setter_load_item,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_success,
)

GRADE_6200 = {
    "grade_a_count": 6200,
    "cracked_count": 150,
    "dirty_count": 100,
    "small_count": 50,
}

TWO_ORDERS = [
    {"requested_chicks": 5000, "requested_placement_date": "2026-08-22T00:00:00Z"},
    {"requested_chicks": 4250, "requested_placement_date": "2026-08-23T00:00:00Z"},
]


def _assignment_for_order(
    assignments: List[Dict[str, Any]], order_id: str
) -> Dict[str, Any]:
    matches = [a for a in assignments if a["placement_order_id"] == order_id]
    assert len(matches) == 1, (
        f"expected exactly one assignment for order {order_id}, got {matches}"
    )
    return matches[0]


class TestEggConservationAcrossVoidAndRestore:
    """Two lots feed one load; aborting it must give every egg back."""

    def _two_lots_in_one_load(self, api: ApiClient):
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot_1 = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=15.0,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=6500,
        )
        lot_2 = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=15.0,
            collected_at="2026-07-31T00:00:00Z",
            collected_count=6500,
        )
        unit_1 = fx.create_unit(api, code="U1", unit_type=UnitType.SETTER.value)
        unit_2 = fx.create_unit(api, code="U2", unit_type=UnitType.SETTER.value)
        profile = fx.create_profile(api)
        load_1 = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(unit_1["id"], profile["id"], "2026-08-01T18:00:00Z"),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        load_2 = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(unit_2["id"], profile["id"], "2026-08-02T18:00:00Z"),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        fx.draw_eggs(api, load_1["id"], lot_1["id"], 6000)
        fx.draw_eggs(api, load_1["id"], lot_2["id"], 4000)
        return {
            "lot_1": lot_1,
            "lot_2": lot_2,
            "load_1": load_1,
            "load_2": load_2,
        }

    def test_abort_from_planned_restores_every_egg_to_both_lots(self, api):
        """PRD 3.5: "From `PLANNED`, every `ACTIVE` draw flips to `VOIDED` and returns its
        `eggs_taken` to its lot's `eggs_remaining`, `total_eggs_set` is recomputed to 0, and
        every lot whose eggs are thereby fully restored steps back `ALLOCATED → IN_STORAGE`
        — the eggs live to be set another day."

        Design: Difficulty/compensating_invariant/egg_conservation_across_void_and_restore
        """
        ctx = self._two_lots_in_one_load(api)
        assert_egg_lot(
            fx.read_lot(api, ctx["lot_1"]["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=200,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot_2"]["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=2200,
        )
        assert_setter_load(
            fx.read_load(api, ctx["load_1"]["id"]), total_eggs_set=10000
        )

        aborted = validate_success(
            api.abort_setter_load(ctx["load_1"]["id"], "PLAN_CHANGE", HATCHERY_MANAGER),
            200,
        )

        assert_setter_load(
            aborted,
            status=SetterLoadStatus.ABORTED.value,
            abort_reason="PLAN_CHANGE",
            total_eggs_set=0,
        )
        for lot_key in ("lot_1", "lot_2"):
            assert_egg_lot(
                fx.read_lot(api, ctx[lot_key]["id"]),
                status=EggLotStatus.IN_STORAGE.value,
                settable_count=6200,
                eggs_remaining=6200,
            )

    def test_voided_draws_keep_their_eggs_taken_and_drop_out_of_the_sum(self, api):
        """PRD 2.10: "For every egg lot, `settable_count` equals `eggs_remaining` plus the
        sum of `eggs_taken` across that lot's draws whose `item_status` is `ACTIVE`. Draws
        whose `item_status` is `VOIDED` drop out of the sum entirely, which is exactly why
        voiding a draw must return its eggs to the lot in the same request."

        Design: Difficulty/compensating_invariant/egg_conservation_across_void_and_restore
        """
        ctx = self._two_lots_in_one_load(api)
        for lot_key in ("lot_1", "lot_2"):
            lot_id = ctx[lot_key]["id"]
            assert_egg_conservation(
                fx.read_lot(api, lot_id), fx.list_draws_of_lot(api, lot_id)
            )

        validate_success(
            api.abort_setter_load(ctx["load_1"]["id"], "PLAN_CHANGE", HATCHERY_MANAGER),
            200,
        )

        for lot_key, expected_taken in (("lot_1", 6000), ("lot_2", 4000)):
            lot_id = ctx[lot_key]["id"]
            draws = fx.list_draws_of_lot(api, lot_id)
            assert len(draws) == 1, (
                f"the voided draw is retained for audit, got {len(draws)} rows"
            )
            assert_setter_load_item(
                draws[0],
                item_status=ItemStatus.VOIDED.value,
                eggs_taken=expected_taken,
            )
            assert_egg_conservation(fx.read_lot(api, lot_id), draws)

    def test_restored_eggs_can_be_drawn_again_into_another_load(self, api):
        """PRD 3.5: "Voided draws are excluded from every aggregate, and voiding one
        returns its `eggs_taken` to the lot's `eggs_remaining`." And: "The lot's
        `eggs_remaining` is reduced by `eggs_taken`, the lot moves `IN_STORAGE → ALLOCATED`
        on the first draw and stays in `ALLOCATED` on every further draw into another
        planned load".

        Design: Difficulty/compensating_invariant/egg_conservation_across_void_and_restore
        """
        ctx = self._two_lots_in_one_load(api)
        validate_success(
            api.abort_setter_load(ctx["load_1"]["id"], "PLAN_CHANGE", HATCHERY_MANAGER),
            200,
        )
        restored = fx.read_lot(api, ctx["lot_1"]["id"])

        response = api.draw_eggs(
            ctx["load_2"]["id"],
            f.draw_payload(restored["id"], 6200, restored["version"]),
            INCUBATION_OPERATOR,
        )

        item = validate_success(response, 201)
        assert_setter_load_item(
            item,
            setter_load_id=ctx["load_2"]["id"],
            egg_lot_id=restored["id"],
            eggs_taken=6200,
            item_status=ItemStatus.ACTIVE.value,
        )
        after = fx.read_lot(api, restored["id"])
        assert_egg_lot(
            after, status=EggLotStatus.ALLOCATED.value, eggs_remaining=0
        )
        assert_egg_conservation(after, fx.list_draws_of_lot(api, restored["id"]))
        assert_setter_load(fx.read_load(api, ctx["load_2"]["id"]), total_eggs_set=6200)


class TestChickConservationAcrossReverseAndReallocation:
    """Reversing an assignment returns the chicks, and the waterfall grants them again."""

    def _allocated_batch(self, api: ApiClient):
        ctx = fx.allocation_ready_context(
            api,
            farm_capacity=20000,
            orders=TWO_ORDERS,
            allocation_clock="2026-08-22T20:00:00Z",
        )
        ctx["assignments"] = fx.run_allocation(api, ctx["batch"]["id"])
        return ctx

    def test_allocation_run_leaves_a_sub_box_remainder_unassigned(self, api):
        """PRD 2.10: "Because every chick grant is an exact multiple of the standard box of
        100 chicks — counted as `boxes_assigned` on the assignment and bounded by the
        batch's own `box_count` — a batch's `unassigned_chicks` can legitimately settle on a
        sub-box remainder that no allocation run will ever move."

        Design: Difficulty/compensating_invariant/chick_conservation_across_reverse_and_reallocation
        """
        ctx = self._allocated_batch(api)

        first = _assignment_for_order(ctx["assignments"], ctx["orders"][0]["id"])
        second = _assignment_for_order(ctx["assignments"], ctx["orders"][1]["id"])
        assert_delivery_assignment(first, chicks_assigned=5000, boxes_assigned=50)
        assert_delivery_assignment(second, chicks_assigned=4200, boxes_assigned=42)
        assert_placement_order(
            fx.read_order(api, ctx["orders"][0]["id"]),
            status=OrderStatus.FULFILLED.value,
            allocated_chicks=5000,
        )
        assert_placement_order(
            fx.read_order(api, ctx["orders"][1]["id"]),
            status=OrderStatus.PARTIALLY_FULFILLED.value,
            allocated_chicks=4200,
            remaining_need=50,
        )
        batch = fx.read_batch(api, ctx["batch"]["id"])
        assert_chick_batch(batch, saleable_count=9262, unassigned_chicks=62)
        assert_chick_conservation(
            batch, fx.list_assignments_of_batch(api, ctx["batch"]["id"])
        )

    def test_reversal_returns_the_chicks_and_the_orders_full_need(self, api):
        """PRD 3.9: "From `PARTIALLY_FULFILLED` it likewise returns to `CONFIRMED` when
        `allocated_chicks` reaches 0, again with `remaining_need` restored to
        `requested_chicks`."

        Design: Difficulty/compensating_invariant/chick_conservation_across_reverse_and_reallocation
        """
        ctx = self._allocated_batch(api)
        second_order = ctx["orders"][1]
        second = _assignment_for_order(ctx["assignments"], second_order["id"])

        reversed_assignment = validate_success(
            api.reverse_assignment(second["id"], "FARM_HOUSING_DELAY", HATCHERY_MANAGER),
            200,
        )

        assert_delivery_assignment(
            reversed_assignment,
            status=AssignmentStatus.REVERSED.value,
            reversal_reason="FARM_HOUSING_DELAY",
        )
        assert_placement_order(
            fx.read_order(api, second_order["id"]),
            status=OrderStatus.CONFIRMED.value,
            allocated_chicks=0,
            remaining_need=4250,
        )
        batch = fx.read_batch(api, ctx["batch"]["id"])
        assert_chick_batch(batch, saleable_count=9262, unassigned_chicks=4262)
        assert_chick_conservation(
            batch, fx.list_assignments_of_batch(api, ctx["batch"]["id"])
        )

    def test_reallocation_grants_the_same_whole_box_figure_again(self, api):
        """PRD 3.8: "Otherwise take the smaller of the order's `remaining_need` and the
        pool, divide by 100 discarding the remainder, and multiply back by 100: that
        whole-box figure is the grant." And PRD 3.8: "Once the walk ends, the batch's
        `unassigned_chicks` is set to whatever remains in the pool, and any sub-box
        remainder simply stays there — it is never allocated."

        Design: Difficulty/compensating_invariant/chick_conservation_across_reverse_and_reallocation
        """
        ctx = self._allocated_batch(api)
        second_order = ctx["orders"][1]
        second = _assignment_for_order(ctx["assignments"], second_order["id"])
        before = fx.read_batch(api, ctx["batch"]["id"])
        validate_success(
            api.reverse_assignment(second["id"], "FARM_HOUSING_DELAY", HATCHERY_MANAGER),
            200,
        )

        rerun = fx.run_allocation(api, ctx["batch"]["id"])

        regranted = _assignment_for_order(rerun, second_order["id"])
        assert_delivery_assignment(
            regranted,
            chicks_assigned=4200,
            boxes_assigned=42,
            status=AssignmentStatus.ASSIGNED.value,
        )
        after = fx.read_batch(api, ctx["batch"]["id"])
        assert_chick_batch(
            after,
            saleable_count=9262,
            cull_count=138,
            unassigned_chicks=62,
        )
        assert_two_dp(
            after["quality_score_final"],
            before["quality_score_final"],
            "quality_score_final",
        )
        assert_chick_conservation(
            after, fx.list_assignments_of_batch(api, ctx["batch"]["id"])
        )
