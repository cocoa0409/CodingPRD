# -*- coding: utf-8 -*-
"""Bench windows: half-open capacity, committed minutes, queueing and promotion."""
import pytest

from test_helpers import (
    ADMIN_1, INSP_1, ONE_BAND, PLANNER_1, ApiErrorId, api_client as api,
    confirm_reservation, create_bench, create_core, create_order, create_standard,
    read_bench, read_core, read_order, release_reservation, reserve_bench,
    setup_shop, validate_error, validate_paginated, validate_success,
)


class TestHalfOpenWindows:

    def _three_orders_on_one_slot_bench(self):
        world = setup_shop(account_code="NGM-014", asset_tag="CONV-04-GBX",
                           serial_no="SN-OV-1", declared_condition_grade="GRADE_B",
                           labor_hours=4.0, bench_code="B-6")
        cust_id, std_id, asset_id = (world["customer"]["id"], world["standard"]["id"],
                                     world["asset"]["id"])
        world["orders"] = [world["order"]]
        for n in (2, 3):
            core = create_core(cust_id, std_id, serial_no=f"SN-OV-{n}",
                               declared_condition_grade="GRADE_B")
            world["orders"].append(create_order(cust_id, core["id"], asset_id,
                                                labor_hours=4.0))
        return world

    def test_exact_adjacency_is_admitted_on_a_single_slot_bench(self):
        """PRD 3.8: "Capacity uses **half-open** window semantics, with the window running from
        `window_start_at` inclusive to `window_end_at` exclusive."
        PRD 3.8: "Two reservations overlap exactly when each one's start is strictly before the
        other one's end; exact adjacency, where one window's end equals the next window's start,
        is therefore not an overlap and is always admissible."
        PRD 3.8: "If the peak is strictly less than the bench's `parallel_slots`, the new
        reservation is created with `status` of `HELD`."

        Design: Difficulty/resource_temporal_overlap/bench_half_open_windows_admit_adjacency_reject_overlap
        """
        world = self._three_orders_on_one_slot_bench()
        bench_id = world["bench"]["id"]

        first = reserve_bench(world["orders"][0]["id"], bench_id,
                              "2026-09-05T08:00:00Z", "2026-09-05T12:00:00Z")
        assert first["status"] == "HELD"

        resp = api.create_bench_reservation({
            "rebuild_order_id": world["orders"][1]["id"], "bench_id": bench_id,
            "window_start_at": "2026-09-05T12:00:00Z",
            "window_end_at": "2026-09-05T16:00:00Z"}, PLANNER_1)
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "HELD", "end == next start is not an overlap"
        assert adjacent["window_minutes"] == 240

        assert read_bench(bench_id)["committed_minutes"] == 480

    def test_an_overlapping_window_on_a_full_bench_is_a_window_conflict(self):
        """PRD 3.8: "If it is not and `queue_if_full` was false, the request is
        `ERR_BENCH_WINDOW_CONFLICT` (HTTP 409)."
        PRD 3.8: "For the requested window, count at each instant how many of the bench's
        existing reservations with `status` of `HELD` or `CONFIRMED` cover that instant, and
        take the peak of that count across the window; reservations that are `QUEUED`,
        `CONSUMED` or `RELEASED` are invisible to this count."

        Design: Difficulty/resource_temporal_overlap/bench_half_open_windows_admit_adjacency_reject_overlap
        """
        world = self._three_orders_on_one_slot_bench()
        bench_id = world["bench"]["id"]
        reserve_bench(world["orders"][0]["id"], bench_id,
                      "2026-09-05T08:00:00Z", "2026-09-05T12:00:00Z")
        reserve_bench(world["orders"][1]["id"], bench_id,
                      "2026-09-05T12:00:00Z", "2026-09-05T16:00:00Z")

        validate_error(api.create_bench_reservation({
            "rebuild_order_id": world["orders"][2]["id"], "bench_id": bench_id,
            "window_start_at": "2026-09-05T11:00:00Z",
            "window_end_at": "2026-09-05T15:00:00Z", "queue_if_full": False}, PLANNER_1),
            ApiErrorId.ERR_BENCH_WINDOW_CONFLICT.value, 409)

        assert read_bench(bench_id)["committed_minutes"] == 480
        _, meta = validate_paginated(api.list_bench_reservations(bench_id, PLANNER_1))
        assert meta["total_count"] == 2
        _, meta = validate_paginated(api.list_order_bench_reservations(
            world["orders"][2]["id"], PLANNER_1))
        assert meta["total_count"] == 0


class TestCommittedMinutesConservation:

    def _bench_world(self):
        return setup_shop(account_code="BEN-001", customer_name="Bench Works",
                          asset_tag="MILL-07-GBX", model_code="BENCH-SPEC-1",
                          serial_no="SN-BEN-1", declared_condition_grade="GRADE_B",
                          labor_hours=4.0, bench_code="B-8", parallel_slots=2)

    def test_confirming_a_held_window_leaves_the_committed_minutes_untouched(self):
        """PRD 3.8: "A bench's `committed_minutes` is always the full sum of `window_minutes`
        over that bench's reservations whose `status` is `HELD` or `CONFIRMED`; `QUEUED`,
        `CONSUMED` and `RELEASED` rows contribute zero, and the figure is recomputed from
        scratch on every reservation creation and every reservation transition rather than
        adjusted by a delta."
        PRD 3.8: "Confirming a held window, which a `Planner` or `ShopAdmin` does to move it
        `HELD → CONFIRMED`, therefore leaves `committed_minutes` untouched, since both states
        count."

        Design: Difficulty/compensating_invariant/bench_reserve_then_release_conserves_committed_minutes
        """
        world = self._bench_world()
        bench_id = world["bench"]["id"]
        assert read_bench(bench_id)["committed_minutes"] == 0

        reservation = reserve_bench(world["order"]["id"], bench_id,
                                    "2026-09-06T08:00:00Z", "2026-09-06T12:00:00Z")
        assert reservation["window_minutes"] == 240

        confirmed = confirm_reservation(reservation["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert read_bench(bench_id)["committed_minutes"] == 240

    def test_reserve_then_release_returns_committed_minutes_to_its_prior_value(self):
        """PRD 3.8: "Releasing a window moves it to `RELEASED` from `QUEUED`, `HELD` or
        `CONFIRMED`; releasing from `HELD` or `CONFIRMED` drops the bench's committed minutes by
        that window's `window_minutes`, while releasing a `QUEUED` row changes nothing because
        it never contributed."
        PRD 3.8: "The reservation's `window_minutes` is the whole number of minutes between the
        two instants, truncated downward."

        Design: Difficulty/compensating_invariant/bench_reserve_then_release_conserves_committed_minutes
        """
        world = self._bench_world()
        bench_id = world["bench"]["id"]
        reservation = reserve_bench(world["order"]["id"], bench_id,
                                    "2026-09-06T08:00:00Z", "2026-09-06T12:00:00Z")
        confirm_reservation(reservation["id"])
        assert read_bench(bench_id)["committed_minutes"] == 240

        released = release_reservation(reservation["id"])
        assert released["status"] == "RELEASED"
        assert released["window_minutes"] == 240, "the released row keeps its width"
        assert read_bench(bench_id)["committed_minutes"] == 0, (
            "exactly the pre-reservation value"
        )
        _, meta = validate_paginated(api.list_bench_reservations(bench_id, PLANNER_1))
        assert meta["total_count"] == 1


class TestCancellationReleasesAndPromotes:

    def _queued_behind_a_held_window(self):
        world = setup_shop(account_code="NGM-008", asset_tag="CONV-04-GBX",
                           serial_no="SN-A-1", declared_condition_grade="GRADE_B",
                           labor_hours=4.0, bench_code="B-1")
        cust_id, std_id, asset_id = (world["customer"]["id"], world["standard"]["id"],
                                     world["asset"]["id"])
        core_b = create_core(cust_id, std_id, serial_no="SN-B-1",
                             declared_condition_grade="GRADE_B")
        world["order_b"] = create_order(cust_id, core_b["id"], asset_id, labor_hours=4.0)
        world["res_a"] = reserve_bench(world["order"]["id"], world["bench"]["id"],
                                       "2026-09-01T08:00:00Z", "2026-09-01T12:00:00Z")
        world["res_b"] = reserve_bench(world["order_b"]["id"], world["bench"]["id"],
                                       "2026-09-01T10:00:00Z", "2026-09-01T14:00:00Z",
                                       queue_if_full=True)
        return world

    def test_a_full_bench_lands_a_queue_if_full_reservation_directly_in_queued(self):
        """PRD 3.8: "If it is not, and `queue_if_full` was true, the reservation is created
        directly with `status` of `QUEUED` — a creation-time landing, not a later transition."
        PRD 3.8: "A bench's `committed_minutes` is always the full sum of `window_minutes` over
        that bench's reservations whose `status` is `HELD` or `CONFIRMED`; `QUEUED`, `CONSUMED`
        and `RELEASED` rows contribute zero"

        Design: Difficulty/transitive_cascade/order_cancel_releases_bench_and_promotes_queued_reservation
        """
        world = self._queued_behind_a_held_window()
        assert world["res_a"]["status"] == "HELD"
        assert world["res_b"]["status"] == "QUEUED"
        assert world["res_a"]["window_minutes"] == 240
        assert world["res_b"]["window_minutes"] == 240
        assert read_bench(world["bench"]["id"])["committed_minutes"] == 240

    def test_cancelling_the_holder_releases_its_window_and_promotes_the_queue(self):
        """PRD 3.9: "The order moves to `CANCELLED` with the reason recorded and every
        reservation of that order in `QUEUED`, `HELD` or `CONFIRMED` transitions to `RELEASED`.
        Caused by that, each touched bench recomputes `committed_minutes`. Caused by that, queue
        promotion runs on each touched bench, moving the winning `QUEUED` reservation to `HELD`
        and stamping its `promoted_at`. Caused by that, `committed_minutes` is recomputed once
        more so that the promoted window's minutes are included."
        PRD 3.8: "The winner moves `QUEUED → HELD`, its `promoted_at` is stamped from the
        logical clock, and the bench's `committed_minutes` is recomputed to include the newly
        held window."

        Design: Difficulty/transitive_cascade/order_cancel_releases_bench_and_promotes_queued_reservation
        """
        world = self._queued_behind_a_held_window()
        bench_id = world["bench"]["id"]

        cancelled = validate_success(api.cancel_rebuild_order(
            world["order"]["id"], {"cancel_reason": "customer deferred the outage"},
            PLANNER_1))
        assert cancelled["work_status"] == "CANCELLED"

        rows, _ = validate_paginated(api.list_bench_reservations(bench_id, PLANNER_1))
        by_id = {row["id"]: row for row in rows}
        assert by_id[world["res_a"]["id"]]["status"] == "RELEASED"
        assert by_id[world["res_b"]["id"]]["status"] == "HELD"
        assert by_id[world["res_b"]["id"]]["promoted_at"] is not None

        assert read_bench(bench_id)["committed_minutes"] == 240
        assert read_order(world["order_b"]["id"])["work_status"] == "DRAFT", (
            "promotion does not touch the other order's work dimension"
        )


class TestCleanroomPrecedence:

    def _cleanroom_conflict_world(self):
        world = setup_shop(account_code="NGM-010", asset_tag="CONV-04-GBX",
                           model_code="PLAIN-SPEC-1", serial_no="SN-PL-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0,
                           bench_code="B-2")
        cust_id, asset_id = world["customer"]["id"], world["asset"]["id"]
        clean_std = create_standard(model_code="CLEAN-SPEC-1", feature_bands=ONE_BAND,
                                    cleanroom_required=True)
        clean_core = create_core(cust_id, clean_std["id"], serial_no="SN-CL-1",
                                 declared_condition_grade="GRADE_B")
        world["clean_order"] = create_order(cust_id, clean_core["id"], asset_id,
                                            labor_hours=4.0)
        world["res_plain"] = reserve_bench(world["order"]["id"], world["bench"]["id"],
                                           "2026-09-02T08:00:00Z", "2026-09-02T12:00:00Z")
        return world

    def test_cleanroom_is_checked_before_capacity_on_a_full_ordinary_bench(self):
        """PRD 3.8: "Before capacity is even considered, cleanliness is: if the spec governing
        the order's core sets `cleanroom_required`, the reservation must target a bench whose
        `cleanroom` is true, and a reservation on an ordinary bench is
        `ERR_CLEANROOM_BENCH_REQUIRED` (HTTP 422)."
        PRD 2.8: "Safety rules — `ERR_VIBRATION_LINK_REQUIRED`, `ERR_MEASUREMENTS_INCOMPLETE`,
        `ERR_CLEARANCE_OUT_OF_SPEC`, `ERR_REBUILD_LIMIT_REACHED`,
        `ERR_AFTERMARKET_NOT_PERMITTED` and `ERR_CLEANROOM_BENCH_REQUIRED`, all HTTP 422."

        Design: Difficulty/priority_pair_validation_conflict/cleanroom_safety_error_beats_bench_window_temporal_error
        """
        world = self._cleanroom_conflict_world()
        error = validate_error(api.create_bench_reservation({
            "rebuild_order_id": world["clean_order"]["id"],
            "bench_id": world["bench"]["id"],
            "window_start_at": "2026-09-02T10:00:00Z",
            "window_end_at": "2026-09-02T14:00:00Z", "queue_if_full": False}, PLANNER_1),
            ApiErrorId.ERR_CLEANROOM_BENCH_REQUIRED.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_BENCH_WINDOW_CONFLICT.value

    def test_the_refused_cleanroom_reservation_leaves_the_bench_untouched(self):
        """PRD 2.8: "Temporal rules — `ERR_BENCH_WINDOW_CONFLICT` (409),
        `ERR_INSTALL_BUFFER_VIOLATION` (409) and `ERR_WARRANTY_EXPIRED` (422)."
        PRD 2.8: "When a request violates more than one rule, exactly one error is returned, and
        which one is fully determined: rules are evaluated in ascending priority order and the
        **first** rule that fails decides the response."

        Design: Difficulty/priority_pair_validation_conflict/cleanroom_safety_error_beats_bench_window_temporal_error
        """
        world = self._cleanroom_conflict_world()
        validate_error(api.create_bench_reservation({
            "rebuild_order_id": world["clean_order"]["id"],
            "bench_id": world["bench"]["id"],
            "window_start_at": "2026-09-02T10:00:00Z",
            "window_end_at": "2026-09-02T14:00:00Z", "queue_if_full": False}, PLANNER_1),
            ApiErrorId.ERR_CLEANROOM_BENCH_REQUIRED.value, 422)

        _, meta = validate_paginated(
            api.list_bench_reservations(world["bench"]["id"], PLANNER_1))
        assert meta["total_count"] == 1
        assert read_bench(world["bench"]["id"])["committed_minutes"] == 240


class TestWrongStateActions:

    def test_core_and_reservation_actions_answer_with_their_own_state_errors(self):
        """PRD 3.6: "Attempting either scrap or return-as-is from a state that does not admit it
        — for instance scrapping a core still in `RECEIVED` — is `ERR_CORE_UNIT_INVALID_STATE`."
        PRD 3.6: "An `Inspector` or `ShopAdmin` may order a re-inspection, moving the core
        `GRADED → INSPECTING` again, provided the core is currently `GRADED` and no rebuild
        order referencing that core has reached `IN_PROGRESS`, `COMPLETED` or `DELIVERED`; a
        violation of either condition is `ERR_CORE_UNIT_INVALID_STATE` (HTTP 409)."
        PRD 3.8: "Confirming or releasing a reservation whose state does not admit the action is
        `ERR_RESERVATION_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/core_unit_and_reservation_actions_from_wrong_states_are_rejected
        """
        world = setup_shop(account_code="WST-001", customer_name="Wrong State Mill",
                           asset_tag="WST-01-GBX", serial_no="SN-WST-1",
                           declared_condition_grade="GRADE_B", labor_hours=3.0,
                           bench_code="B-WST")
        reservation = reserve_bench(world["order"]["id"], world["bench"]["id"],
                                    "2026-09-09T08:00:00Z", "2026-09-09T12:00:00Z")
        release_reservation(reservation["id"])

        validate_error(api.advance_core_unit(
            world["core"]["id"],
            {"action": "SCRAP", "override_reason": "shop decided to bin it"}, ADMIN_1),
            ApiErrorId.ERR_CORE_UNIT_INVALID_STATE.value, 409)
        validate_error(api.advance_core_unit(
            world["core"]["id"], {"action": "REINSPECT"}, INSP_1),
            ApiErrorId.ERR_CORE_UNIT_INVALID_STATE.value, 409)
        validate_error(api.advance_bench_reservation(
            reservation["id"], {"action": "CONFIRM"}, PLANNER_1),
            ApiErrorId.ERR_RESERVATION_INVALID_STATE.value, 409)

        assert read_core(world["core"]["id"])["status"] == "RECEIVED"
        rows, _ = validate_paginated(
            api.list_bench_reservations(world["bench"]["id"], PLANNER_1))
        assert rows[0]["status"] == "RELEASED"
        assert read_bench(world["bench"]["id"])["committed_minutes"] == 0
