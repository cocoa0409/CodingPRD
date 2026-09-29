"""
Window geometry for cycle counts, the overhead reader pool, and the two
precedence pairs that a count task and a counted line resolve.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_COUNT_TASK_INVALID_STATE,
    ERR_COUNT_WINDOW_NOT_DUE,
    ERR_COUNT_WINDOW_OVERLAP,
    ERR_OVERHEAD_READER_CAPACITY_EXCEEDED,
    ERR_READER_MODE_UNSUPPORTED,
)
from test_helpers.assertions import assert_pct
from test_helpers.test_users import ANALYST, SUPERVISOR


def _task(api, schedule_id, start_day, end_day, reader_mode="HANDHELD"):
    return api.create_count_task(
        f.count_task_payload(
            schedule_id,
            reader_mode=reader_mode,
            window_start=f"2026-08-{start_day:02d}T00:00:00Z",
            window_end=f"2026-08-{end_day:02d}T00:00:00Z",
        ),
        ANALYST,
    )


class TestHalfOpenWindowGeometry:
    def test_an_overlapping_window_on_the_same_category_is_rejected(self, api):
        """
        The half-open test decides the collision.

        "Windows are half-open, so two tasks overlap when the requested
        `window_start` is strictly earlier than the existing `window_end` **and**
        the existing `window_start` is strictly earlier than the requested
        `window_end`."

        Design: Difficulty/resource_temporal_overlap/count_window_half_open_adjacency_accepted_overlap_rejected
        """
        world = fx.apparel_reference_world(api, baseline=100)
        schedule = fx.create_schedule(
            api, world["store_id"], world["category_id"], first_due_date="2026-08-01"
        )
        validate_success(_task(api, schedule["id"], 5, 7), 201)

        validate_error(
            _task(api, schedule["id"], 6, 8), ERR_COUNT_WINDOW_OVERLAP, 409
        )

        rows, meta = validate_paginated(api.list_count_tasks(ANALYST))
        assert meta["total_count"] == 1

    def test_windows_touching_at_either_endpoint_are_accepted(self, api):
        """
        Adjacency is legal on both sides.

        "Adjacency is therefore legal: a task starting at the exact instant another
        ends does not collide."

        Design: Difficulty/resource_temporal_overlap/count_window_half_open_adjacency_accepted_overlap_rejected
        """
        world = fx.apparel_reference_world(api, baseline=100)
        schedule = fx.create_schedule(
            api, world["store_id"], world["category_id"], first_due_date="2026-08-01"
        )
        validate_success(_task(api, schedule["id"], 5, 7), 201)

        after = validate_success(_task(api, schedule["id"], 7, 9), 201)
        assert after["status"] == "SCHEDULED"

        before = validate_success(_task(api, schedule["id"], 3, 5), 201)
        assert before["status"] == "SCHEDULED"

        rows, meta = validate_paginated(api.list_count_tasks(ANALYST))
        assert meta["total_count"] == 3

    def test_voiding_the_existing_task_releases_its_claim(self, api):
        """
        Terminal tasks stop holding the merchandise area.

        "no other count task on the same store and the same category, in
        `SCHEDULED`, `IN_PROGRESS` or `COUNTED` status, may hold a window
        overlapping the requested one; tasks that have reached `RECONCILED` or
        `VOIDED` release their claim."

        Design: Difficulty/resource_temporal_overlap/count_window_half_open_adjacency_accepted_overlap_rejected
        """
        world = fx.apparel_reference_world(api, baseline=100)
        schedule = fx.create_schedule(
            api, world["store_id"], world["category_id"], first_due_date="2026-08-01"
        )
        existing = validate_success(_task(api, schedule["id"], 5, 7), 201)
        validate_error(
            _task(api, schedule["id"], 6, 8), ERR_COUNT_WINDOW_OVERLAP, 409
        )

        voided = validate_success(api.void_count_task(existing["id"], SUPERVISOR))
        assert voided["status"] == "VOIDED"

        accepted = validate_success(_task(api, schedule["id"], 6, 8), 201)
        assert accepted["status"] == "SCHEDULED"


class TestOverheadReaderPool:
    @staticmethod
    def _three_overhead_schedules(api):
        world = fx.apparel_reference_world(api, baseline=100)
        home = fx.create_category(api, f.home_category_payload())
        toys = fx.create_category(api, f.toys_category_payload())
        schedules = {
            "apparel": fx.create_schedule(
                api,
                world["store_id"],
                world["category_id"],
                reader_mode="OVERHEAD",
                first_due_date="2026-08-01",
            ),
            "home": fx.create_schedule(
                api,
                world["store_id"],
                home["id"],
                reader_mode="OVERHEAD",
                first_due_date="2026-08-01",
            ),
            "toys": fx.create_schedule(
                api,
                world["store_id"],
                toys["id"],
                reader_mode="OVERHEAD",
                first_due_date="2026-08-01",
            ),
        }
        world["schedules"] = schedules
        world["apparel_task"] = validate_success(
            _task(api, schedules["apparel"]["id"], 5, 8, "OVERHEAD"), 201
        )
        world["home_task"] = validate_success(
            _task(api, schedules["home"]["id"], 6, 9, "OVERHEAD"), 201
        )
        return world

    def test_a_third_overlapping_overhead_task_exhausts_the_pool(self, api):
        """
        The pool is counted across categories at the store.

        "**Check B** enforces aggregate capacity over the overhead reader pool and
        runs only when the requested `reader_mode` is `OVERHEAD`: the number of
        count tasks at the same store with `reader_mode` of `OVERHEAD`, in
        `SCHEDULED`, `IN_PROGRESS` or `COUNTED` status, whose windows overlap the
        requested one under the same half-open test, must be strictly below the
        store's `overhead_reader_capacity`; when that count has already reached the
        capacity the request is rejected with
        `ERR_OVERHEAD_READER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/overhead_reader_pool_aggregate_capacity_exceeded
        """
        world = self._three_overhead_schedules(api)

        validate_error(
            _task(api, world["schedules"]["toys"]["id"], 7, 10, "OVERHEAD"),
            ERR_OVERHEAD_READER_CAPACITY_EXCEEDED,
            409,
        )

        rows, meta = validate_paginated(api.list_count_tasks(ANALYST))
        assert meta["total_count"] == 2

    def test_the_pool_check_only_runs_for_overhead_requests(self, api):
        """
        Check B is conditional on the requested reader mode.

        "`overhead_reader_capacity` declares how many non-terminal overhead count
        tasks may hold overlapping windows at that store simultaneously; it
        defaults to 2 and must be between 0 and 8 inclusive."

        Design: Difficulty/resource_temporal_overlap/overhead_reader_pool_aggregate_capacity_exceeded
        """
        world = self._three_overhead_schedules(api)

        handheld = validate_success(
            _task(api, world["schedules"]["toys"]["id"], 7, 10, "HANDHELD"), 201
        )
        assert handheld["reader_mode"] == "HANDHELD"

    def test_a_non_overlapping_overhead_window_fits_the_pool(self, api):
        """
        Only overlapping overhead tasks consume the pool.

        "`overhead_reader_capacity` declares how many non-terminal overhead count
        tasks may hold overlapping windows at that store simultaneously; it
        defaults to 2 and must be between 0 and 8 inclusive."

        Design: Difficulty/resource_temporal_overlap/overhead_reader_pool_aggregate_capacity_exceeded
        """
        world = self._three_overhead_schedules(api)

        shifted = validate_success(
            _task(api, world["schedules"]["toys"]["id"], 9, 11, "OVERHEAD"), 201
        )
        assert shifted["status"] == "SCHEDULED"

    def test_voiding_one_overhead_task_frees_a_slot(self, api):
        """
        A voided task no longer holds a reader.

        "**Check B** enforces aggregate capacity over the overhead reader pool and
        runs only when the requested `reader_mode` is `OVERHEAD`: the number of
        count tasks at the same store with `reader_mode` of `OVERHEAD`, in
        `SCHEDULED`, `IN_PROGRESS` or `COUNTED` status, whose windows overlap the
        requested one under the same half-open test, must be strictly below the
        store's `overhead_reader_capacity`; when that count has already reached the
        capacity the request is rejected with
        `ERR_OVERHEAD_READER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/overhead_reader_pool_aggregate_capacity_exceeded
        """
        world = self._three_overhead_schedules(api)
        validate_error(
            _task(api, world["schedules"]["toys"]["id"], 7, 10, "OVERHEAD"),
            ERR_OVERHEAD_READER_CAPACITY_EXCEEDED,
            409,
        )

        validate_success(api.void_count_task(world["apparel_task"]["id"], SUPERVISOR))

        accepted = validate_success(
            _task(api, world["schedules"]["toys"]["id"], 7, 10, "OVERHEAD"), 201
        )
        assert accepted["status"] == "SCHEDULED"


class TestReaderModeBeatsWindowNotDue:
    def test_an_unsupported_reader_mode_is_reported_before_the_due_date(self, api):
        """
        The hardware check runs ahead of the temporal check.

        "The task's `reader_mode` must be supported by the store's
        `reader_capability`, otherwise `ERR_READER_MODE_UNSUPPORTED`."

        Design: Difficulty/priority_pair_validation_conflict/reader_mode_beats_window_not_due_on_count_task_create
        """
        category = fx.create_category(api)
        store = fx.create_store(api, f.handheld_only_store_payload())
        schedule = fx.create_schedule(
            api,
            store["id"],
            category["id"],
            reader_mode="HANDHELD",
            first_due_date="2026-09-01",
        )

        validate_error(
            _task(api, schedule["id"], 1, 3, "OVERHEAD"),
            ERR_READER_MODE_UNSUPPORTED,
            422,
        )

        rows, meta = validate_paginated(api.list_count_tasks(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_supported_reader_mode_then_surfaces_the_due_date(self, api):
        """
        With the hardware complaint removed the temporal rule is reported.

        "The calendar date of `window_start` must be on or after the schedule's
        `next_due_date`; an earlier window is rejected with
        `ERR_COUNT_WINDOW_NOT_DUE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/reader_mode_beats_window_not_due_on_count_task_create
        """
        category = fx.create_category(api)
        store = fx.create_store(api, f.handheld_only_store_payload())
        schedule = fx.create_schedule(
            api,
            store["id"],
            category["id"],
            reader_mode="HANDHELD",
            first_due_date="2026-09-01",
        )

        validate_error(
            _task(api, schedule["id"], 1, 3, "HANDHELD"),
            ERR_COUNT_WINDOW_NOT_DUE,
            422,
        )


class TestTaskStateBeatsCategoryMismatch:
    @staticmethod
    def _world_with_a_foreign_sku(api):
        world = fx.apparel_reference_world(api, baseline=100)
        elec = fx.create_category(api, f.elec_category_payload())
        tv = fx.create_item(api, f.tv_item_payload(elec["id"], world["vendor_id"]))
        fx.create_position(api, world["store_id"], tv["id"], baseline=10)
        world["foreign_item_id"] = tv["id"]
        return world

    def test_a_line_offered_after_submit_reports_the_task_state(self, api):
        """
        The state precondition precedes the referential complaint.

        "The task must be `IN_PROGRESS`; a line offered against a task in any other
        status is rejected with `ERR_COUNT_TASK_INVALID_STATE`. The SKU's
        `category_id` must equal the task's `category_id`, otherwise
        `ERR_ITEM_CATEGORY_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_count_line_after_submit
        """
        world = self._world_with_a_foreign_sku(api)
        fx.with_started_task(api, world)
        line = fx.add_line(api, world["task_id"], world["item_id"], 101)

        submitted = fx.submit_task(api, world["task_id"])
        assert submitted["status"] == "COUNTED"
        assert submitted["in_scope_position_count"] == 1
        assert_pct(submitted["coverage_pct"], 100.00)
        assert submitted["variance_line_count"] == 0

        stored = validate_success(api.get_count_line(line["id"], ANALYST))
        assert stored["variance_units"] == 1
        assert stored["variance_value_cents"] == 1327
        assert stored["within_tolerance"] is True

        validate_error(
            api.create_count_line(
                world["task_id"],
                f.count_line_payload(world["foreign_item_id"], 9),
                ANALYST,
            ),
            ERR_COUNT_TASK_INVALID_STATE,
            409,
        )

        after = fx.read_task(api, world["task_id"])
        assert after["counted_line_count"] == 1
        assert after["status"] == "COUNTED"
