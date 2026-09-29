"""Two different interval geometries: dock windows and shift windows.

A delivery window is padded symmetrically by ten minutes and compared per
station against the raw windows of live calls; a shift window is extended only
at its end, by its own overtime, and compared against the other plans of the
line. Both are half-open, so touching endpoints are legal in both.
"""

from test_helpers import (
    PRODUCTION_PLANNER_HEADERS,
    ApiErrorId,
    DeliveryCallStatus,
    ShiftPlanStatus,
    base_plant,
    cancel_call,
    delivery_call_payload,
    line_version,
    new_shift_plan,
    read_shift_plan,
    shift_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDockWindowBuffer:
    """Ten clear minutes on either side, counted at one station only."""

    def _dock_taken_from_seven_to_seven_thirty(self, api):
        plant = base_plant(api)
        incumbent = validate_success(
            api.create_delivery_call(
                delivery_call_payload(
                    plant.supplier_id, plant.part_id, plant.st10_id,
                    "2026-08-03T07:00:00Z", "2026-08-03T07:30:00Z",
                ),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )
        return plant, incumbent

    def test_nine_clear_minutes_conflict_at_that_station_only(self, api):
        """The pad reaches back to 07:29 and clips the incumbent's last minute.

        "The dock at a station must have ten clear minutes on either side of every
        delivery: the new call's window, padded by ten minutes before `window_start`
        and ten minutes after `window_end`, may not intersect the unpadded window of
        any other call at the same station whose `status` is `SCHEDULED`,
        `ARRIVED_ON_TIME` or `ARRIVED_LATE`; cancelled and missed calls free their
        dock slot."

        Design: Difficulty/resource_temporal_overlap/dock_window_buffer_padded_on_both_ends_and_station_scoped
        """
        plant, _incumbent = self._dock_taken_from_seven_to_seven_thirty(api)

        validate_error(
            api.create_delivery_call(
                delivery_call_payload(
                    plant.supplier_id, plant.part_id, plant.st10_id,
                    "2026-08-03T07:39:00Z", "2026-08-03T08:09:00Z",
                ),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_DOCK_WINDOW_CONFLICT,
            expected_status=409,
        )

        # The very same window is free at the next station down the line.
        validate_success(
            api.create_delivery_call(
                delivery_call_payload(
                    plant.supplier_id, plant.part_id, plant.st20_id,
                    "2026-08-03T07:39:00Z", "2026-08-03T08:09:00Z",
                ),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )
        _rows, meta = validate_paginated(
            api.list_delivery_calls(PRODUCTION_PLANNER_HEADERS,
                                    {"station_id": plant.st10_id})
        )
        assert meta["total_count"] == 1

    def test_exactly_ten_clear_minutes_book_and_a_cancellation_frees_the_dock(self, api):
        """Touching the pad is not intersecting it, and dead calls hold nothing.

        "The window is half-open — `window_start` is inclusive and `window_end` is
        exclusive — and `window_end` must be strictly after `window_start`."

        Design: Difficulty/resource_temporal_overlap/dock_window_buffer_padded_on_both_ends_and_station_scoped
        """
        plant, incumbent = self._dock_taken_from_seven_to_seven_thirty(api)

        neighbour = validate_success(
            api.create_delivery_call(
                delivery_call_payload(
                    plant.supplier_id, plant.part_id, plant.st10_id,
                    "2026-08-03T07:40:00Z", "2026-08-03T08:10:00Z",
                ),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )
        assert neighbour["status"] == DeliveryCallStatus.SCHEDULED.value

        cancel_call(api, incumbent["id"])
        rebooked = validate_success(
            api.create_delivery_call(
                delivery_call_payload(
                    plant.supplier_id, plant.part_id, plant.st10_id,
                    "2026-08-03T07:00:00Z", "2026-08-03T07:30:00Z",
                ),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )

        assert rebooked["status"] == DeliveryCallStatus.SCHEDULED.value
        rows, meta = validate_paginated(
            api.list_delivery_calls(PRODUCTION_PLANNER_HEADERS,
                                    {"station_id": plant.st10_id})
        )
        assert meta["total_count"] == 3
        by_id = {row["id"]: row["status"] for row in rows}
        assert by_id[incumbent["id"]] == DeliveryCallStatus.CANCELLED.value
        assert by_id[neighbour["id"]] == DeliveryCallStatus.SCHEDULED.value


class TestShiftWindowOverlapUsesTheOvertimeExtendedEnd:
    """Overtime lengthens the plan being created, and can make it collide."""

    def _line_with_an_active_b_shift(self, api):
        plant = base_plant(api)
        plan_b = new_shift_plan(
            api, plant.line_id, shift_code="B", planned_headcount=18,
            shift_start="2026-08-03T14:00:00Z", shift_end="2026-08-03T22:00:00Z",
            overtime_minutes=0,
        )
        return plant, plan_b

    def test_sixty_overtime_minutes_push_the_a_shift_into_the_b_shift(self, api):
        """An 06:00-14:00 plan plus an hour of overtime reaches 15:00.

        "The comparison uses each plan's effective window — from `shift_start` up to
        but not including `shift_end` plus `overtime_minutes` — on absolute
        timestamps, so a `C` shift crossing midnight is compared correctly against
        the next day's `A` shift."

        Design: Difficulty/resource_temporal_overlap/shift_plan_overlap_measured_on_the_overtime_extended_end
        """
        plant, _plan_b = self._line_with_an_active_b_shift(api)
        version_before = line_version(api, plant.line_id)

        validate_error(
            api.create_shift_plan(
                shift_plan_payload(plant.line_id, version_before,
                                   shift_code="A", planned_headcount=20,
                                   overtime_minutes=60),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_SHIFT_WINDOW_OVERLAP,
            expected_status=409,
        )

        # The refusal advanced nothing, so the token the planner holds is current.
        assert line_version(api, plant.line_id) == version_before
        _rows, meta = validate_paginated(
            api.list_line_shift_plans(plant.line_id, PRODUCTION_PLANNER_HEADERS)
        )
        assert meta["total_count"] == 1

    def test_without_overtime_the_same_window_merely_touches_and_is_accepted(self, api):
        """A plan ending exactly where the next begins does not overlap.

        "Touching endpoints are allowed: a plan ending at exactly the instant another
        begins does not overlap. An intersection is `ERR_SHIFT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/shift_plan_overlap_measured_on_the_overtime_extended_end
        """
        plant, plan_b = self._line_with_an_active_b_shift(api)
        version_before = line_version(api, plant.line_id)

        plan_a = validate_success(
            api.create_shift_plan(
                shift_plan_payload(plant.line_id, version_before,
                                   shift_code="A", planned_headcount=20,
                                   overtime_minutes=0),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )

        assert plan_a["status"] == ShiftPlanStatus.ACTIVE.value
        assert plan_a["available_labor_minutes"] == 480
        # A legal neighbour is not the plan being superseded, so B survives intact.
        surviving = read_shift_plan(api, plan_b["id"])
        assert surviving["status"] == ShiftPlanStatus.ACTIVE.value
        assert surviving["available_labor_minutes"] == 480
        _rows, meta = validate_paginated(
            api.list_line_shift_plans(plant.line_id, PRODUCTION_PLANNER_HEADERS)
        )
        assert meta["total_count"] == 2
        assert line_version(api, plant.line_id) == version_before + 1
