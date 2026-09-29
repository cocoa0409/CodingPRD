"""Two different overlap geometries: a buffered half-open bay and a closed demo window."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    assert_bay_ledger,
    factories,
    fixtures,
    make_commissioning_engineer_headers,
    make_fabrication_manager_headers,
)


class TestBufferedHalfOpenBayWindow:
    """Adjacency is a conflict; a gap of exactly the changeover buffer is free."""

    INCUMBENT_START = "2026-08-10T08:00:00.000Z"
    INCUMBENT_END = "2026-08-10T16:00:00.000Z"
    ADJACENT_START = "2026-08-10T16:00:00.000Z"
    ADJACENT_END = "2026-08-10T18:00:00.000Z"
    BUFFERED_START = "2026-08-10T18:00:00.000Z"
    BUFFERED_END = "2026-08-10T20:00:00.000Z"

    def _shared_bay_with_an_incumbent(self, api):
        state = fixtures.fat_ready_two_stage_project(api)
        state["shared_bay"] = fixtures.seed_test_bay(
            api,
            bay_code="BAY-SHARE",
            max_skid_footprint_sf=5400.0,
            changeover_buffer_minutes=120,
        )
        state["run_f"] = fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["filtration_skid"]["id"]),
            state["shared_bay"]["id"],
            self.INCUMBENT_START,
            self.INCUMBENT_END,
        )
        return state

    def _book_disinfection_skid(self, api, state, start_at, end_at):
        skid = fixtures.current_skid(api, state["disinfection_skid"]["id"])
        return api.create_fat_run(
            factories.fat_run_payload(
                skid["id"],
                state["shared_bay"]["id"],
                skid["version"],
                start_at,
                end_at,
            ),
            make_fabrication_manager_headers(),
        )

    def test_a_window_starting_at_the_incumbents_end_still_collides(self, api):
        """Touching windows fall inside the buffer, so the shared bay runs out of capacity.

        Occupancy is "a **buffered half-open interval**. The booked window is treated
        as inclusive of its start and exclusive of its end, and it is widened by the
        bay's `changeover_buffer_minutes` at *both* ends for the purpose of finding
        conflicts." Its practical consequence is that "adjacency is a conflict: two
        windows that merely touch, with a gap of zero, collide, and so do two windows
        separated by strictly less than the changeover buffer, while a gap of exactly
        the changeover buffer or more is free."

        Design: Difficulty/resource_temporal_overlap/test_bay_buffered_half_open_window_with_aggregate_capacity
        """
        state = self._shared_bay_with_an_incumbent(api)

        response = self._book_disinfection_skid(
            api, state, self.ADJACENT_START, self.ADJACENT_END
        )

        validate_error(response, ApiErrorId.TEST_BAY_CAPACITY_EXCEEDED.value, 409)

    def test_a_gap_of_exactly_the_changeover_buffer_is_free(self, api):
        """Starting two hours after the incumbent's end clears the buffer and is accepted.

        The buffer rule says "an existing run on the same bay whose status is still
        `SCHEDULED` is in the overlap set when the incoming run's start is earlier than
        that run's end extended forward by the buffer, and that run's start is earlier
        than the incoming run's end extended forward by the buffer", so a start exactly
        at the buffered end is not earlier than it and the overlap set stays empty.

        Design: Difficulty/resource_temporal_overlap/test_bay_buffered_half_open_window_with_aggregate_capacity
        """
        state = self._shared_bay_with_an_incumbent(api)

        self._book_disinfection_skid(api, state, self.ADJACENT_START, self.ADJACENT_END)
        response = self._book_disinfection_skid(
            api, state, self.BUFFERED_START, self.BUFFERED_END
        )
        run_d = validate_success(response, 201)

        assert run_d["status"] == "SCHEDULED"
        assert run_d["round_no"] == 1
        assert run_d["duration_minutes"] == 120
        assert run_d["footprint_sf"] == 1200

    def test_both_bookings_stand_and_the_ledger_holds_their_footprint_minutes(self, api):
        """The bay carries 5400 sf for 480 minutes plus 1200 sf for 120 minutes.

        Section 2.11 pins the bay ledger: "at every instant it equals the sum, over
        every factory test run booked on that bay whose status is still `SCHEDULED`, of
        that run's `footprint_sf` multiplied by its `duration_minutes`."

        Design: Difficulty/resource_temporal_overlap/test_bay_buffered_half_open_window_with_aggregate_capacity
        """
        state = self._shared_bay_with_an_incumbent(api)
        self._book_disinfection_skid(api, state, self.BUFFERED_START, self.BUFFERED_END)

        rows, meta = validate_paginated(
            api.list_fat_runs(
                make_fabrication_manager_headers(),
                {"test_bay_id": state["shared_bay"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert all(row["status"] == "SCHEDULED" for row in rows)

        bay = validate_success(
            api.get_test_bay(
                state["shared_bay"]["id"], make_fabrication_manager_headers()
            )
        )
        assert_bay_ledger(bay, 2736000)


class TestClosedDemonstrationWindowOnTheSkid:
    """Both demonstration endpoints are inclusive, so touching windows conflict."""

    INCUMBENT_START = "2026-08-20T00:00:00.000Z"
    INCUMBENT_END = "2026-08-27T00:00:00.000Z"
    ONE_MILLISECOND_LATER = "2026-08-27T00:00:00.001Z"
    SECOND_WINDOW_END = "2026-09-03T00:00:00.000Z"

    def _project_with_a_pending_demo(self, api):
        state = fixtures.commissioning_project(api)
        state["demo_one"] = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.250}],
            self.INCUMBENT_START,
            self.INCUMBENT_END,
        )
        return state

    def _record_second_window(self, api, state, start_at, end_at, measured_value):
        return api.create_performance_demo(
            factories.performance_demo_payload(
                state["project"]["id"],
                state["skid"]["id"],
                [{"parameter": "TURBIDITY_NTU", "measured_value": measured_value}],
                start_at,
                end_at,
            ),
            make_commissioning_engineer_headers(),
        )

    def test_a_window_starting_exactly_at_the_incumbents_end_is_rejected(self, api):
        """The closed interval means the shared instant is an overlap, not a handover.

        A demonstration window "is a **closed** interval on the skid: both
        `window_start_at` and `window_end_at` are inclusive", and "because both
        endpoints are inclusive, a new window whose start is exactly the incumbent's
        end *is* rejected -- which is the opposite of nothing, and precisely the
        opposite behaviour from the half-open bay interval of section 3.7, where the
        end instant is exclusive but a buffer is added to both ends."

        Design: Difficulty/resource_temporal_overlap/demo_window_closed_interval_exclusive_on_skid
        """
        state = self._project_with_a_pending_demo(api)

        response = self._record_second_window(
            api, state, self.INCUMBENT_END, self.SECOND_WINDOW_END, 0.260
        )

        validate_error(response, ApiErrorId.DEMO_WINDOW_CONFLICT.value, 409)

    def test_a_window_starting_one_millisecond_later_is_accepted(self, api):
        """One millisecond past the incumbent's end clears the closed interval.

        A conflict "exists when any demonstration on the same skid whose `result` is
        still `PENDING` satisfies both: the incoming start is at or before that
        demonstration's end, and that demonstration's start is at or before the
        incoming end." An accepted demonstration "is created with `result` `PENDING`,
        `evaluation` an empty array, `min_margin_pct` null, `certified_by_user_id`
        null".

        Design: Difficulty/resource_temporal_overlap/demo_window_closed_interval_exclusive_on_skid
        """
        state = self._project_with_a_pending_demo(api)

        self._record_second_window(
            api, state, self.INCUMBENT_END, self.SECOND_WINDOW_END, 0.260
        )
        response = self._record_second_window(
            api, state, self.ONE_MILLISECOND_LATER, self.SECOND_WINDOW_END, 0.260
        )
        demo_two = validate_success(response, 201)

        assert demo_two["result"] == "PENDING"
        assert demo_two["window_start_at"] == self.ONE_MILLISECOND_LATER
        assert demo_two["min_margin_pct"] is None
        assert demo_two["certified_by_user_id"] is None

        rows, meta = validate_paginated(
            api.list_performance_demos(
                make_commissioning_engineer_headers(),
                {"skid_id": state["skid"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert all(row["result"] == "PENDING" for row in rows)
