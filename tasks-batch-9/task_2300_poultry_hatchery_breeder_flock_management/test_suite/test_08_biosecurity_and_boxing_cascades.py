"""Single writes whose effects travel two or three records deep: a laboratory
release that empties a planned load, a boxing that derates a flock's forecast, and
a reversal that walks an order backwards through its own lifecycle.
"""

from typing import Any, Dict, List

from test_helpers import (
    ApiClient,
    CHICK_PROCESSOR,
    HATCHERY_MANAGER,
    VETERINARIAN,
    AssignmentStatus,
    ChickBatchStatus,
    CondemnedReason,
    CorrectiveActionStatus,
    EggLotStatus,
    FlockStatus,
    ItemStatus,
    LabResult,
    LabTestStatus,
    OccupancyStatus,
    OrderStatus,
    SanitationStatus,
    SetterLoadStatus,
    TriggerReason,
    assert_breeder_flock,
    assert_chick_batch,
    assert_chick_conservation,
    assert_corrective_action,
    assert_delivery_assignment,
    assert_egg_lot,
    assert_forecast_chain,
    assert_incubation_unit,
    assert_lab_test,
    assert_placement_order,
    assert_setter_load,
    assert_setter_load_item,
    assert_two_dp,
    fixtures as fx,
    get_success_data,
    validate_paginated,
    validate_success,
)

GRADE_6200 = {
    "grade_a_count": 6200,
    "cracked_count": 150,
    "dirty_count": 100,
    "small_count": 50,
}

#: Two confirmed orders whose combined need exceeds one batch's saleable pool.
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


class TestLabPositiveEmptiesAPlannedLoad:
    """Flock, lot, draw, load and machine all move on one release."""

    def _positive_release(self, api: ApiClient):
        ctx = fx.planned_load_context(
            api,
            lot_collected_at="2026-07-28T00:00:00Z",
            collected_count=6500,
            grade=GRADE_6200,
            eggs_taken=6000,
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=200,
        )
        pending = fx.register_lab_test(
            api, ctx["flock"]["id"], collected_at="2026-08-01T06:00:00Z"
        )
        assert_lab_test(pending, status=LabTestStatus.PENDING.value)
        ctx["test"] = fx.release_lab_test(
            api, pending["id"], LabResult.POSITIVE.value, VETERINARIAN
        )
        return ctx

    def test_release_holds_the_flock_and_condemns_its_allocated_lot(self, api):
        """PRD 2.7: "Writes therefore propagate, and they propagate **immediately and
        within the same request** that triggered them. There is no deferred reconciliation
        and no eventual consistency: by the time the response is serialised, every
        dependent record the write affects has already moved, been recomputed, had
        `updated_at` refreshed and had `version` incremented." And PRD 3.3: "and then the
        egg condemnation cascade runs: **every** egg lot of that flock currently in
        `IN_STORAGE` or `ALLOCATED` moves to `CONDEMNED` with a `condemned_reason` of
        `FLOCK_EGG_HOLD`."

        Design: Difficulty/transitive_cascade/lab_positive_condemns_eggs_and_aborts_load
        """
        ctx = self._positive_release(api)

        assert_lab_test(
            ctx["test"],
            status=LabTestStatus.POSITIVE.value,
            result=LabResult.POSITIVE.value,
            released_at="2026-08-01T12:00:00Z",
        )
        assert_breeder_flock(
            fx.read_flock(api, ctx["flock"]["id"]),
            status=FlockStatus.EGG_HOLD.value,
            egg_hold_opened_at="2026-08-01T12:00:00Z",
            egg_hold_opened_by_user_id="u_vet_1",
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.CONDEMNED.value,
            condemned_reason=CondemnedReason.FLOCK_EGG_HOLD.value,
            eggs_remaining=0,
            settable_count=6200,
        )

    def test_the_void_and_abort_chain_empties_the_load_and_frees_the_machine(self, api):
        """PRD 3.4: "every `ACTIVE` draw of that lot flips to `item_status` of `VOIDED`;
        each affected setter load has its `total_eggs_set` and `weighted_age_days`
        recomputed over the draws that remain active; and any load left with a
        `total_eggs_set` of 0 and still in `PLANNED` moves to `ABORTED` with an
        `abort_reason` of `EGG_LOTS_CONDEMNED` and releases its incubation unit's
        `occupancy_status` back to `FREE`."

        Design: Difficulty/transitive_cascade/lab_positive_condemns_eggs_and_aborts_load
        """
        ctx = self._positive_release(api)

        load = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(
            load,
            status=SetterLoadStatus.ABORTED.value,
            abort_reason="EGG_LOTS_CONDEMNED",
            total_eggs_set=0,
        )
        assert_setter_load_item(
            fx.list_items_of_load(api, ctx["load"]["id"])[0],
            item_status=ItemStatus.VOIDED.value,
            eggs_taken=6000,
        )
        assert_incubation_unit(
            fx.read_unit(api, ctx["setter_unit"]["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
            sanitation_status=SanitationStatus.SANITIZED.value,
        )
        draws = fx.list_draws_of_lot(api, ctx["lot"]["id"])
        assert len(draws) == 1, (
            f"the voided draw is retained for audit, got {len(draws)} rows"
        )
        assert_setter_load_item(draws[0], item_status=ItemStatus.VOIDED.value)


class TestBoxingBelowThresholdDeratesTheFlock:
    """Boxing recomputes hatchability, opens an action and re-derives the forecast."""

    def _vaccinated_low_hatch_batch(self, api: ApiClient):
        return fx.vaccinated_batch_context(
            api,
            fertile_count=9000,
            hatched_count=8332,
            sexing=fx.LOW_HATCHABILITY_SEXING,
        )

    def test_boxing_below_the_threshold_auto_opens_a_corrective_action(self, api):
        """PRD 3.9: "The new action carries the `flock_id` of the flock, a `trigger_reason`
        of `HATCHABILITY_BELOW_THRESHOLD`, an `observed_hatchability_pct` holding the
        set-basis figure that tripped the threshold, an `opened_at` from the logical clock,
        an `opened_by_user_id` recording the `X-User-ID` of the principal whose boxing call
        caused the auto-open, a `status` of `OPEN`, a `verification_round` of 1 and a null
        `implementation_note`."

        Design: Difficulty/transitive_cascade/box_low_hatchability_opens_action_and_derates_forecast
        """
        ctx = self._vaccinated_low_hatch_batch(api)

        boxed = validate_success(
            api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR), 200
        )

        assert_chick_batch(
            boxed,
            status=ChickBatchStatus.BOXED.value,
            vaccine_cull_count=33,
            cull_count=133,
            saleable_count=8199,
            box_count=82,
        )
        assert_two_dp(boxed["preliminary_yield_pct"], 98.80, "preliminary_yield_pct")
        assert_two_dp(boxed["final_yield_pct"], 98.40, "final_yield_pct")
        assert_two_dp(boxed["quality_score_final"], 98.56, "quality_score_final")

        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert_two_dp(
            flock["hatchability_rolling_pct"], 81.99, "hatchability_rolling_pct"
        )
        assert_two_dp(
            flock["hatchability_fertile_pct"], 91.10, "hatchability_fertile_pct"
        )
        assert flock["corrective_action_count"] == 1, (
            "81.99 percent is strictly below the threshold, so one action is opened"
        )
        rows, meta = validate_paginated(
            api.list_corrective_actions(HATCHERY_MANAGER, {"flock_id": ctx["flock"]["id"]})
        )
        assert meta["total_count"] == 1, f"expected exactly one action, got {rows}"
        action = rows[0]
        assert_corrective_action(
            action,
            flock_id=ctx["flock"]["id"],
            status=CorrectiveActionStatus.OPEN.value,
            trigger_reason=TriggerReason.HATCHABILITY_BELOW_THRESHOLD.value,
            verification_round=1,
            opened_by_user_id="u_proc_1",
            opened_at="2026-08-22T18:00:00Z",
        )
        assert_two_dp(
            action["observed_hatchability_pct"], 81.99, "observed_hatchability_pct"
        )
        assert action["implementation_note"] is None, (
            "a freshly opened action carries no implementation note"
        )

    def test_the_new_action_derates_the_forecast_in_the_same_request(self, api):
        """PRD 3.9: "The flock's `corrective_action_count` is incremented and, because a
        count of 1 or more activates the 0.95 derate, its `settable_forecast` is recomputed
        on the spot — an underperforming flock's forecast drops the moment the
        underperformance is recognised."

        Design: Difficulty/transitive_cascade/box_low_hatchability_opens_action_and_derates_forecast
        """
        ctx = self._vaccinated_low_hatch_batch(api)
        before = fx.read_flock(api, ctx["flock"]["id"])
        assert before["corrective_action_count"] == 0
        assert_forecast_chain(before, settable_forecast=5587)

        validate_success(api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR), 200)

        after = fx.read_flock(api, ctx["flock"]["id"])
        assert_forecast_chain(
            after,
            age_weeks=32,
            photoperiod_hours=16.0,
            feed_grams_per_hen_day=168.0,
            production_rate_pct=74.0,
            lighting_factor=0.8500,
            nutrition_factor=1.0500,
            settable_forecast=5308,
        )


class TestReversalWalksTheOrderBackwards:
    """Reversal restores the pool and steps a fulfilled order back to confirmed."""

    def _allocated_batch(self, api: ApiClient):
        ctx = fx.allocation_ready_context(
            api,
            farm_capacity=20000,
            orders=TWO_ORDERS,
            allocation_clock="2026-08-22T20:00:00Z",
        )
        ctx["assignments"] = fx.run_allocation(api, ctx["batch"]["id"])
        return ctx

    def test_reversal_restores_the_pool_and_returns_the_order_to_confirmed(self, api):
        """PRD 3.9: "It moves the assignment `ASSIGNED → REVERSED` and unwinds both sides
        of the allocation in the same request: the batch's `unassigned_chicks` grows back
        by `chicks_assigned`, and the served order's `allocated_chicks` shrinks by
        `chicks_assigned` with `remaining_need` recomputed." And: "From `FULFILLED` it
        returns all the way to `CONFIRMED` when the reversal drops `allocated_chicks` to 0,
        in which case `remaining_need` is restored to the full `requested_chicks`."

        Design: Difficulty/transitive_cascade/reverse_assignment_restores_pool_and_steps_order_back
        """
        ctx = self._allocated_batch(api)
        first_order = ctx["orders"][0]
        first = _assignment_for_order(ctx["assignments"], first_order["id"])
        assert_delivery_assignment(
            first,
            chicks_assigned=5000,
            boxes_assigned=50,
            status=AssignmentStatus.ASSIGNED.value,
        )
        assert_placement_order(
            fx.read_order(api, first_order["id"]),
            status=OrderStatus.FULFILLED.value,
            allocated_chicks=5000,
            remaining_need=0,
        )
        assert_chick_batch(
            fx.read_batch(api, ctx["batch"]["id"]), unassigned_chicks=62
        )

        reversed_assignment = validate_success(
            api.reverse_assignment(first["id"], "TRUCK_BREAKDOWN", HATCHERY_MANAGER), 200
        )

        assert_delivery_assignment(
            reversed_assignment,
            status=AssignmentStatus.REVERSED.value,
            reversal_reason="TRUCK_BREAKDOWN",
            chicks_assigned=5000,
        )
        assert_placement_order(
            fx.read_order(api, first_order["id"]),
            status=OrderStatus.CONFIRMED.value,
            allocated_chicks=0,
            remaining_need=5000,
        )
        assert_chick_batch(
            fx.read_batch(api, ctx["batch"]["id"]), unassigned_chicks=5062
        )

    def test_the_second_assignment_and_its_order_are_left_alone(self, api):
        """PRD 2.10: "For every chick batch, `saleable_count` equals `unassigned_chicks`
        plus the sum of `chicks_assigned` across that batch's delivery assignments whose
        status is `ASSIGNED` or `DELIVERED`. A `REVERSED` assignment drops out of the sum,
        which is why reversal must return its chicks to `unassigned_chicks` in the same
        request."

        Design: Difficulty/transitive_cascade/reverse_assignment_restores_pool_and_steps_order_back
        """
        ctx = self._allocated_batch(api)
        first = _assignment_for_order(ctx["assignments"], ctx["orders"][0]["id"])
        second = _assignment_for_order(ctx["assignments"], ctx["orders"][1]["id"])
        before = fx.read_batch(api, ctx["batch"]["id"])

        validate_success(
            api.reverse_assignment(first["id"], "TRUCK_BREAKDOWN", HATCHERY_MANAGER), 200
        )

        assert_delivery_assignment(
            get_success_data(
                api.get_delivery_assignment(second["id"], HATCHERY_MANAGER), 200
            ),
            status=AssignmentStatus.ASSIGNED.value,
            chicks_assigned=4200,
            boxes_assigned=42,
        )
        assert_placement_order(
            fx.read_order(api, ctx["orders"][1]["id"]),
            status=OrderStatus.PARTIALLY_FULFILLED.value,
            allocated_chicks=4200,
            remaining_need=50,
        )
        after = fx.read_batch(api, ctx["batch"]["id"])
        assert_chick_batch(
            after,
            saleable_count=9262,
            cull_count=138,
            unassigned_chicks=5062,
        )
        assert_two_dp(
            after["quality_score_final"],
            before["quality_score_final"],
            "quality_score_final",
        )
        assert_chick_conservation(
            after, fx.list_assignments_of_batch(api, ctx["batch"]["id"])
        )
