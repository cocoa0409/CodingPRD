"""
Field-level, cross-entity and aggregate validation rules, each paired with the
satisfying request that proves the rule is the only thing standing in the way.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CATEGORY_READER_MODE_MISMATCH,
    ERR_COUNT_WINDOW_NOT_DUE,
    ERR_DUPLICATE_STOCK_POSITION,
    ERR_INVALID_WINDOW,
    ERR_ITEM_CATEGORY_MISMATCH,
    ERR_ITEM_NOT_STOCKED_AT_STORE,
    ERR_MAX_LINES_PER_PASS_EXCEEDED,
    ERR_NO_COUNT_LINES,
)
from test_helpers.assertions import assert_pct
from test_helpers.test_users import ANALYST, CONTROLLER, make_counter_headers


def _schedule_world(api, category_payload=None, store_payload=None):
    category = fx.create_category(api, category_payload or f.apparel_category_payload())
    store = fx.create_store(api, store_payload or f.store_payload())
    schedule = fx.create_schedule(
        api, store["id"], category["id"], first_due_date="2026-08-01"
    )
    return category, store, schedule


class TestCountWindowDueBoundary:
    def test_a_window_opening_exactly_on_the_due_date_is_accepted(self, api):
        """
        The due comparison is inclusive of the due date itself.

        "The task copies `store_id` and `category_id` from its schedule rather than
        accepting them, and is born `SCHEDULED` with `recount_round`,
        `counted_line_count`, `variance_line_count` and `total_variance_value_cents`
        all 0, `coverage_pct` at 0.00, and `in_scope_position_count` left at 0 until
        the task is started."

        Design: Corner/validations/count_task_window_start_exactly_on_due_date_is_accepted
        """
        category, store, schedule = _schedule_world(api)
        assert schedule["next_due_date"] == "2026-08-01"

        created = validate_success(
            api.create_count_task(
                f.count_task_payload(
                    schedule["id"],
                    window_start="2026-08-01T00:00:00Z",
                    window_end="2026-08-03T00:00:00Z",
                ),
                ANALYST,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["store_id"] == store["id"]
        assert created["category_id"] == category["id"]
        assert created["in_scope_position_count"] == 0
        assert_pct(created["coverage_pct"], 0.00)
        assert created["recount_round"] == 0

    def test_a_window_opening_one_second_earlier_is_not_yet_due(self, api):
        """
        A calendar date before the due date fails the temporal rule.

        "The calendar date of `window_start` must be on or after the schedule's
        `next_due_date`; an earlier window is rejected with
        `ERR_COUNT_WINDOW_NOT_DUE` (HTTP 422)."

        Design: Corner/validations/count_task_window_start_exactly_on_due_date_is_accepted
        """
        category, store, schedule = _schedule_world(api)

        validate_error(
            api.create_count_task(
                f.count_task_payload(
                    schedule["id"],
                    window_start="2026-07-31T23:59:59Z",
                    window_end="2026-08-03T00:00:00Z",
                ),
                ANALYST,
            ),
            ERR_COUNT_WINDOW_NOT_DUE,
            422,
        )

        rows, meta = validate_paginated(
            api.list_count_tasks(ANALYST, {"count_schedule_id": schedule["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestZeroLengthWindow:
    def test_a_window_that_ends_where_it_starts_is_rejected(self, api):
        """
        The window range check is strict at both ends of the comparison.

        "And `window_end` must be strictly after `window_start`; otherwise
        `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/count_task_zero_length_window_rejected
        """
        category, store, schedule = _schedule_world(api)

        validate_error(
            api.create_count_task(
                f.count_task_payload(
                    schedule["id"],
                    window_start="2026-08-01T00:00:00Z",
                    window_end="2026-08-01T00:00:00Z",
                ),
                ANALYST,
            ),
            ERR_INVALID_WINDOW,
            422,
        )

        rows, meta = validate_paginated(
            api.list_count_tasks(ANALYST, {"count_schedule_id": schedule["id"]})
        )
        assert meta["total_count"] == 0
        assert fx.read_schedule(api, schedule["id"])["next_due_date"] == "2026-08-01"

    def test_a_one_second_window_on_the_due_date_is_accepted(self, api):
        """
        Any strictly positive length satisfies the rule.

        "And `window_end` must be strictly after `window_start`; otherwise
        `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/count_task_zero_length_window_rejected
        """
        category, store, schedule = _schedule_world(api)

        created = validate_success(
            api.create_count_task(
                f.count_task_payload(
                    schedule["id"],
                    window_start="2026-08-01T00:00:00Z",
                    window_end="2026-08-01T00:00:01Z",
                ),
                ANALYST,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"


class TestScheduleReaderModeGate:
    def test_a_handheld_schedule_on_an_overhead_only_category_is_refused(self, api):
        """
        The category gate consults the category, not the store's hardware.

        "The schedule's `reader_mode` must be permitted by the category's
        `reader_mode_required`: a category set to `EITHER` permits both, while a
        category set to `HANDHELD` or `OVERHEAD` permits only that same mode. A
        violation is rejected with `ERR_CATEGORY_READER_MODE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/count_schedule_reader_mode_not_permitted_by_category_rejected
        """
        category = fx.create_category(
            api, f.elec_category_payload(reader_mode_required="OVERHEAD")
        )
        store = fx.create_store(api, f.store_payload())

        validate_error(
            api.create_count_schedule(
                f.count_schedule_payload(
                    store["id"],
                    category["id"],
                    reader_mode="HANDHELD",
                    first_due_date="2026-08-01",
                    cadence_days=14,
                ),
                ANALYST,
            ),
            ERR_CATEGORY_READER_MODE_MISMATCH,
            422,
        )

        rows, meta = validate_paginated(
            api.list_count_schedules(ANALYST, {"category_id": category["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        accepted = validate_success(
            api.create_count_schedule(
                f.count_schedule_payload(
                    store["id"],
                    category["id"],
                    reader_mode="OVERHEAD",
                    first_due_date="2026-08-01",
                    cadence_days=14,
                ),
                ANALYST,
            ),
            201,
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["next_due_date"] == "2026-08-01"

    def test_a_category_left_at_its_default_permits_either_technology(self, api):
        """
        The gate is conditional on how the category was configured.

        "`reader_mode_required`, which is one of `HANDHELD`, `OVERHEAD` or `EITHER`
        and defaults to `EITHER`"

        Design: Corner/validations/count_schedule_reader_mode_not_permitted_by_category_rejected
        """
        category = fx.create_category(
            api, f.toys_category_payload(reader_mode_required=None)
        )
        assert category["reader_mode_required"] == "EITHER"
        store = fx.create_store(api, f.store_payload())

        handheld = validate_success(
            api.create_count_schedule(
                f.count_schedule_payload(
                    store["id"],
                    category["id"],
                    reader_mode="HANDHELD",
                    first_due_date="2026-08-01",
                ),
                ANALYST,
            ),
            201,
        )
        assert handheld["reader_mode"] == "HANDHELD"
        assert handheld["status"] == "ACTIVE"


class TestSubmitPreconditionOrder:
    @staticmethod
    def _empty_started_task(api):
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        return world

    def test_an_empty_task_reports_emptiness_rather_than_coverage(self, api):
        """
        The emptiness check runs ahead of the coverage floor.

        "At least one counted line must be attached — a `counted_line_count` of 0 is
        rejected with `ERR_NO_COUNT_LINES`. The task's weighted `coverage_pct` must be
        at least 90.00, otherwise `ERR_COUNT_COVERAGE_BELOW_MIN`; note that this
        rejection also catches the case where lines do exist but every one of them
        earned a weight of 0.00 because it was read with an overhead reader on a
        handheld task."

        Design: Corner/validations/count_submit_with_no_lines_returns_no_count_lines_not_coverage
        """
        world = self._empty_started_task(api)

        validate_error(
            api.submit_count_task(world["task_id"], ANALYST), ERR_NO_COUNT_LINES, 409
        )

        stalled = fx.read_task(api, world["task_id"])
        assert stalled["status"] == "IN_PROGRESS"
        assert stalled["counted_line_count"] == 0
        assert_pct(stalled["coverage_pct"], 0.00)
        assert stalled["in_scope_position_count"] == 1

    def test_one_covering_line_satisfies_both_checks_at_once(self, api):
        """
        With a line attached the coverage floor is cleared too.

        "The task's weighted `coverage_pct` must be at least 90.00, otherwise
        `ERR_COUNT_COVERAGE_BELOW_MIN`; note that this rejection also catches the
        case where lines do exist but every one of them earned a weight of 0.00
        because it was read with an overhead reader on a handheld task."

        Design: Corner/validations/count_submit_with_no_lines_returns_no_count_lines_not_coverage
        """
        world = self._empty_started_task(api)
        fx.add_line(api, world["task_id"], world["item_id"], 100)

        submitted = fx.submit_task(api, world["task_id"])
        assert submitted["status"] == "COUNTED"
        assert_pct(submitted["coverage_pct"], 100.00)


class TestCountLineCrossEntityChecks:
    @staticmethod
    def _two_category_world(api):
        world = fx.apparel_reference_world(api, baseline=100)
        home = fx.create_category(api, f.home_category_payload())
        pan = fx.create_item(api, f.pan_item_payload(home["id"], world["vendor_id"]))
        fx.create_position(api, world["store_id"], pan["id"], baseline=40)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        world["home_item_id"] = pan["id"]
        return world

    def test_a_sku_from_another_category_is_refused_even_when_stocked(self, api):
        """
        The line's category must match the task's, independently of stocking.

        "The SKU's `category_id` must equal the task's `category_id`, otherwise
        `ERR_ITEM_CATEGORY_MISMATCH`. A stock position must exist for the task's store
        and the named SKU, otherwise `ERR_ITEM_NOT_STOCKED_AT_STORE`."

        Design: Corner/validations/count_line_for_item_outside_task_category_rejected
        """
        world = self._two_category_world(api)

        validate_error(
            api.create_count_line(
                world["task_id"],
                f.count_line_payload(world["home_item_id"], 40),
                ANALYST,
            ),
            ERR_ITEM_CATEGORY_MISMATCH,
            409,
        )

        task = fx.read_task(api, world["task_id"])
        assert task["counted_line_count"] == 0
        assert task["in_scope_position_count"] == 1

        accepted = validate_success(
            api.create_count_line(
                world["task_id"], f.count_line_payload(world["item_id"], 100), ANALYST
            ),
            201,
        )
        assert accepted["stock_position_id"] == world["position_id"]

    def test_an_unstocked_sku_of_the_right_category_reports_the_other_rule(self, api):
        """
        The two cross-entity checks are distinct rules with distinct errors.

        "A stock position must exist for the task's store and the named SKU, otherwise
        `ERR_ITEM_NOT_STOCKED_AT_STORE`."

        Design: Corner/validations/count_line_for_item_outside_task_category_rejected
        """
        world = self._two_category_world(api)
        unstocked = fx.create_item(
            api, f.tee2_item_payload(world["category_id"], world["vendor_id"])
        )

        validate_error(
            api.create_count_line(
                world["task_id"], f.count_line_payload(unstocked["id"], 5), ANALYST
            ),
            ERR_ITEM_NOT_STOCKED_AT_STORE,
            409,
        )

        rows, meta = validate_paginated(
            api.list_count_lines(ANALYST, {"count_task_id": world["task_id"]})
        )
        assert meta["total_count"] == 0


class TestDuplicateStockPosition:
    def test_a_second_position_for_the_same_pair_is_refused(self, api):
        """
        The store-and-SKU pair is the natural key of a position.

        "Only one position may exist per store-and-SKU pair; a second attempt is
        rejected with `ERR_DUPLICATE_STOCK_POSITION`."

        Design: Corner/validations/duplicate_stock_position_for_same_store_and_item_rejected
        """
        world = fx.apparel_reference_world(api, baseline=100)
        original_version = world["position"]["version"]

        validate_error(
            api.create_stock_position(
                f.stock_position_payload(
                    world["store_id"],
                    world["item_id"],
                    baseline_on_hand_units=7,
                ),
                ANALYST,
            ),
            ERR_DUPLICATE_STOCK_POSITION,
            409,
        )

        rows, meta = validate_paginated(
            api.list_stock_positions(
                ANALYST,
                {"store_id": world["store_id"], "item_id": world["item_id"]},
            )
        )
        assert meta["total_count"] == 1

        stored = fx.read_position(api, world["position_id"])
        assert stored["on_hand_units"] == 100
        assert stored["version"] == original_version

    def test_the_same_sku_at_a_second_store_is_accepted(self, api):
        """
        Uniqueness is on the pair, not on the SKU alone.

        "A **stock position** is the intersection of one store and one SKU, and it is
        where the book quantity actually lives."

        Design: Corner/validations/duplicate_stock_position_for_same_store_and_item_rejected
        """
        world = fx.apparel_reference_world(api, baseline=100)
        second_store = fx.create_store(api, f.store_payload(code="S200", name="Store Two"))

        accepted = validate_success(
            api.create_stock_position(
                f.stock_position_payload(
                    second_store["id"], world["item_id"], baseline_on_hand_units=7
                ),
                ANALYST,
            ),
            201,
        )
        assert accepted["on_hand_units"] == 7
        assert accepted["store_id"] == second_store["id"]


class TestMaxLinesPerPass:
    @staticmethod
    def _two_line_pass_at_a_two_line_firm(api):
        category = fx.create_category(api, f.apparel_category_payload())
        store = fx.create_store(api, f.store_payload())
        vendor = fx.create_vendor(api)
        firm = fx.create_counter_firm(
            api,
            f.counter_firm_payload(
                code="CF2",
                name="Counting Firm Two",
                certification_level="TIER_2",
                max_lines_per_pass=2,
            ),
        )
        items = []
        for sku, description, baseline in (
            ("TEE-001", "Crew tee", 100),
            ("TEE-002", "V-neck tee", 50),
            ("TEE-003", "Tank", 10),
        ):
            item = fx.create_item(
                api,
                f.item_payload(
                    category["id"], vendor["id"], sku=sku, description=description
                ),
            )
            fx.create_position(api, store["id"], item["id"], baseline=baseline)
            items.append(item["id"])

        inventory = validate_success(
            api.create_physical_inventory(
                f.physical_inventory_payload(
                    store["id"],
                    firm["id"],
                    scheduled_start_date="2026-08-20",
                    scheduled_end_date="2026-08-22",
                ),
                CONTROLLER,
            ),
            201,
        )
        counter_headers = make_counter_headers(firm["id"])
        started = validate_success(
            api.start_physical_inventory(inventory["id"], counter_headers)
        )
        validate_success(
            api.create_physical_inventory_line(
                inventory["id"],
                f.physical_line_payload(items[0], 100, started["version"]),
                counter_headers,
            ),
            201,
        )
        validate_success(
            api.create_physical_inventory_line(
                inventory["id"],
                f.physical_line_payload(
                    items[1],
                    50,
                    fx.read_physical_inventory(api, inventory["id"])["version"],
                ),
                counter_headers,
            ),
            201,
        )
        return {
            "physical_inventory_id": inventory["id"],
            "items": items,
            "counter_headers": counter_headers,
        }

    def test_the_third_line_of_a_two_line_pass_is_refused(self, api):
        """
        The ceiling counts the line being created.

        "The number of non-superseded lines in the current pass, counting the one
        being created, may not exceed the counting firm's `max_lines_per_pass`,
        otherwise `ERR_MAX_LINES_PER_PASS_EXCEEDED`."

        Design: Corner/validations/physical_line_beyond_counter_firm_max_lines_per_pass_rejected
        """
        world = self._two_line_pass_at_a_two_line_firm(api)
        before = fx.read_physical_inventory(api, world["physical_inventory_id"])
        assert before["line_count"] == 2

        validate_error(
            api.create_physical_inventory_line(
                world["physical_inventory_id"],
                f.physical_line_payload(world["items"][2], 10, before["version"]),
                world["counter_headers"],
            ),
            ERR_MAX_LINES_PER_PASS_EXCEEDED,
            409,
        )

        after = fx.read_physical_inventory(api, world["physical_inventory_id"])
        assert after["line_count"] == 2
        assert after["version"] == before["version"]

        rows, meta = validate_paginated(
            api.list_physical_inventory_lines(
                CONTROLLER,
                {"physical_inventory_id": world["physical_inventory_id"]},
            )
        )
        assert meta["total_count"] == 2

    def test_re_counting_a_sku_already_on_the_pass_consumes_no_capacity(self, api):
        """
        A superseding line replaces rather than adds.

        "Because a superseding line replaces rather than adds, re-counting a SKU does
        not consume additional capacity."

        Design: Corner/validations/physical_line_beyond_counter_firm_max_lines_per_pass_rejected
        """
        world = self._two_line_pass_at_a_two_line_firm(api)
        before = fx.read_physical_inventory(api, world["physical_inventory_id"])

        accepted = validate_success(
            api.create_physical_inventory_line(
                world["physical_inventory_id"],
                f.physical_line_payload(world["items"][1], 45, before["version"]),
                world["counter_headers"],
            ),
            201,
        )
        assert accepted["superseded"] is False
        assert accepted["counted_units"] == 45

        after = fx.read_physical_inventory(api, world["physical_inventory_id"])
        assert after["line_count"] == 2

        rows, meta = validate_paginated(
            api.list_physical_inventory_lines(
                CONTROLLER,
                {"physical_inventory_id": world["physical_inventory_id"]},
            )
        )
        assert meta["total_count"] == 3
