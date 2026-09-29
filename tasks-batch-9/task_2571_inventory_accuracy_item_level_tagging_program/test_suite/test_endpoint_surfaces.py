"""
Endpoint-level behaviour: the integrity scan's two rules and its unconditional
write, the logical clock, the promising-state filter with its pagination, the
pause/resume round trip and the optional investigation link on an adjustment.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_COUNT_SCHEDULE_NOT_ACTIVE,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_INVESTIGATION_NOT_FOUND,
)
from test_helpers.assertions import assert_clock_instant
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import ADMIN, ANALYST, SUPERVISOR

JUNE_INSTANT = "2026-06-01T00:00:00Z"
SEPTEMBER_INSTANT = "2026-09-15T12:00:00Z"


def _reference_frame(api):
    """An APPAREL category that auto-corrects, one store and one vendor."""
    category = fx.create_category(api, f.apparel_category_payload())
    store = fx.create_store(api, f.store_payload())
    vendor = fx.create_vendor(api)
    assert category["auto_correct_negative"] is True
    return category, store, vendor


class TestIntegrityScanOnACleanPosition:
    def test_a_never_counted_positive_position_triggers_neither_rule(self, api):
        """
        The scan reports nothing on a position no rule matches.

        "Rule two addresses phantom inventory, and it is evaluated against the
        on-hand value as it stands after rule one. It fires only when all five of
        the following hold: `on_hand_units` is strictly greater than 0;
        `reserved_units` is exactly 0; `last_counted_at` is not null; the number of
        calendar days from the UTC date of `last_counted_at` to the UTC date of the
        current logical-clock instant is at least 45; and `on_hand_units` is at
        most 3."

        Design: Corner/endpoints/integrity_scan_on_a_clean_position_is_a_no_op
        """
        category, store, vendor = _reference_frame(api)
        item = fx.create_item(api, f.item_payload(category["id"], vendor["id"]))
        position = fx.create_position(api, store["id"], item["id"], baseline=10)
        assert position["last_counted_at"] is None
        assert position["on_hand_units"] == 10

        scanned = validate_success(api.run_integrity_scan(position["id"], ANALYST))
        assert scanned["corrections_applied"] == 0
        assert scanned["negative_corrected_units"] == 0
        assert scanned["phantom_zeroed_units"] == 0
        assert scanned["auto_posted_adjustment_ids"] == []
        assert scanned["pending_adjustment_ids"] == []
        assert scanned["resulting_on_hand_units"] == 10
        assert scanned["resulting_phantom_units"] == 0
        assert scanned["tag_integrity_hold"] is False
        assert scanned["resulting_promising_state"] == "PROMISABLE"

        rows, meta = validate_paginated(
            api.list_adjustments(SUPERVISOR, {"stock_position_id": position["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_scan_is_a_write_even_when_it_changes_nothing(self, api):
        """
        The version side effect of the scan is unconditional.

        "After both rules have run — and only once, not once per rule — the
        position's `promising_state` is re-derived and then the owning store's
        `fulfillment_status` follows, and the position's `version` is incremented
        by 1."

        Design: Corner/endpoints/integrity_scan_on_a_clean_position_is_a_no_op
        """
        category, store, vendor = _reference_frame(api)
        item = fx.create_item(api, f.item_payload(category["id"], vendor["id"]))
        position = fx.create_position(api, store["id"], item["id"], baseline=10)
        before = position["version"]

        scanned = validate_success(api.run_integrity_scan(position["id"], ANALYST))
        assert scanned["corrections_applied"] == 0

        after = fx.read_position(api, position["id"])
        assert after["version"] == before + 1
        assert after["on_hand_units"] == 10
        assert after["promising_state"] == "PROMISABLE"


class TestIntegrityScanNegativeBranches:
    @staticmethod
    def _driven_negative(api, sku, description, unit_cost_cents, delta_units):
        """One position pushed below zero by a posted, approval-free adjustment."""
        category, store, vendor = _reference_frame(api)
        item = fx.create_item(
            api,
            f.item_payload(
                category["id"],
                vendor["id"],
                sku=sku,
                description=description,
                unit_cost_cents=unit_cost_cents,
            ),
        )
        position = fx.create_position(api, store["id"], item["id"], baseline=1)
        requested = fx.create_adjustment(api, position["id"], delta_units)
        assert requested["value_impact_cents"] == abs(delta_units) * unit_cost_cents
        assert requested["authority_threshold_cents"] == 20000
        assert requested["approval_state"] == "NOT_REQUIRED"
        posted = fx.post_adjustment(api, requested["id"])
        assert posted["posting_state"] == "POSTED"

        driven = fx.read_position(api, position["id"])
        assert driven["on_hand_units"] == 1 + delta_units
        assert driven["negative_correction_count"] == 0
        assert driven["tag_integrity_hold"] is False
        return position["id"]

    def test_a_four_unit_shortfall_is_auto_corrected_and_posted_at_once(self, api):
        """
        Both auto-correct conditions hold, so the correction takes effect immediately.

        "Which branch that adjustment takes depends on two conditions together: the
        absolute value of `on_hand_units` must be at most 5 units **and** the
        category's `auto_correct_negative` must be true. When both hold, the
        adjustment is minted with `approval_state` `NOT_REQUIRED` and
        `posting_state` `POSTED`, so it takes effect immediately, `on_hand_units`
        rises to exactly 0, and the position's `negative_correction_count` is
        incremented by 1."

        Design: Corner/endpoints/integrity_scan_splits_small_negative_auto_post_from_large_negative_approval
        """
        position_id = self._driven_negative(api, "TEE-004", "Polo", 900, -5)

        scanned = validate_success(api.run_integrity_scan(position_id, ANALYST))
        assert scanned["corrections_applied"] == 1
        assert scanned["negative_corrected_units"] == 4
        assert scanned["phantom_zeroed_units"] == 0
        assert len(scanned["auto_posted_adjustment_ids"]) == 1
        assert scanned["pending_adjustment_ids"] == []
        assert scanned["resulting_on_hand_units"] == 0
        assert scanned["tag_integrity_hold"] is False
        assert scanned["resulting_promising_state"] == "PROMISABLE"

        correction = fx.read_adjustment(api, scanned["auto_posted_adjustment_ids"][0])
        assert correction["delta_units"] == 4
        assert correction["reason_code"] == "NEGATIVE_CORRECTION"
        assert correction["authority_threshold_cents"] == 0
        assert correction["approval_state"] == "NOT_REQUIRED"
        assert correction["posting_state"] == "POSTED"
        assert correction["requested_by_user_id"] == "system"
        assert correction["investigation_id"] is None

        corrected = fx.read_position(api, position_id)
        assert corrected["on_hand_units"] == 0
        assert corrected["negative_correction_count"] == 1
        assert corrected["promising_state"] == "PROMISABLE"

    def test_a_six_unit_shortfall_is_routed_to_approval_and_moves_no_units(self, api):
        """
        Past the five-unit ceiling the correction is queued rather than applied.

        "When either fails — the shortfall is 6 units or more, or the category
        forbids auto-correction — the adjustment is minted with `approval_state`
        `PENDING` and `posting_state` `UNPOSTED` so that a supervisor must approve
        it, `on_hand_units` is left untouched and therefore still negative, and the
        position's `tag_integrity_hold` is set to true."

        Design: Corner/endpoints/integrity_scan_splits_small_negative_auto_post_from_large_negative_approval
        """
        position_id = self._driven_negative(api, "TEE-003", "Tank top", 1800, -7)

        scanned = validate_success(api.run_integrity_scan(position_id, ANALYST))
        assert scanned["corrections_applied"] == 1
        assert len(scanned["pending_adjustment_ids"]) == 1
        assert scanned["auto_posted_adjustment_ids"] == []
        assert scanned["resulting_on_hand_units"] == -6
        assert scanned["tag_integrity_hold"] is True
        assert scanned["resulting_promising_state"] == "BLOCKED"

        queued = fx.read_adjustment(api, scanned["pending_adjustment_ids"][0])
        assert queued["delta_units"] == 6
        assert queued["reason_code"] == "NEGATIVE_CORRECTION"
        assert queued["approval_state"] == "PENDING"
        assert queued["posting_state"] == "UNPOSTED"
        assert queued["requested_by_user_id"] == "system"

        held = fx.read_position(api, position_id)
        assert held["on_hand_units"] == -6
        assert held["negative_correction_count"] == 0
        assert held["tag_integrity_hold"] is True
        assert held["promising_state"] == "BLOCKED"

    def test_a_second_scan_of_a_corrected_position_mints_nothing(self, api):
        """
        Once the shortfall is gone the scan detects nothing.

        "The scan is idempotent in effect but not in record-keeping: running it a
        second time on a position already corrected to 0 detects nothing and mints
        nothing."

        Design: Corner/endpoints/integrity_scan_splits_small_negative_auto_post_from_large_negative_approval
        """
        position_id = self._driven_negative(api, "TEE-004", "Polo", 900, -5)
        first = validate_success(api.run_integrity_scan(position_id, ANALYST))
        assert first["corrections_applied"] == 1

        second = validate_success(api.run_integrity_scan(position_id, ANALYST))
        assert second["corrections_applied"] == 0
        assert second["negative_corrected_units"] == 0
        assert second["phantom_zeroed_units"] == 0
        assert second["auto_posted_adjustment_ids"] == []
        assert second["pending_adjustment_ids"] == []
        assert second["resulting_on_hand_units"] == 0

        rows, meta = validate_paginated(
            api.list_adjustments(SUPERVISOR, {"stock_position_id": position_id})
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        assert fx.read_position(api, position_id)["negative_correction_count"] == 1


class TestIntegrityScanPhantomClear:
    @staticmethod
    def _counted_on_the_first_of_june(api, units):
        """One small APPAREL position counted clean while the clock reads June."""
        clocked = validate_success(api.set_clock(JUNE_INSTANT, ADMIN))
        assert clocked["current_utc"] == JUNE_INSTANT

        category, store, vendor = _reference_frame(api)
        item = fx.create_item(
            api,
            f.item_payload(
                category["id"],
                vendor["id"],
                sku="TEE-004",
                description="Polo",
                unit_cost_cents=900,
            ),
        )
        position = fx.create_position(api, store["id"], item["id"], baseline=units)
        schedule = fx.create_schedule(
            api, store["id"], category["id"], first_due_date="2026-06-01"
        )
        task = fx.create_task(
            api,
            schedule["id"],
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-06-03T00:00:00Z",
        )
        fx.start_task(api, task["id"])
        line = fx.add_line(api, task["id"], item["id"], units)
        assert line["variance_units"] == 0
        assert line["within_tolerance"] is True
        submitted = fx.submit_task(api, task["id"])
        assert submitted["status"] == "COUNTED"

        counted = fx.read_position(api, position["id"])
        assert_clock_instant(counted["last_counted_at"], JUNE_INSTANT)
        assert counted["reserved_units"] == 0
        assert counted["on_hand_units"] == units
        return position["id"]

    def test_the_same_position_is_untouched_in_june_and_cleared_in_august(self, api):
        """
        Staleness is measured against the logical clock, not the wall clock.

        "A position at 2 units with `reserved_units` 0 and `last_counted_at` on
        2026-06-01 read against a clock of 2026-08-01 spans 61 days, which is at
        least 45, and 2 is at most 3, so a `PHANTOM_CLEAR` of −2 auto-posts and
        `on_hand_units` becomes 0."

        Design: Corner/endpoints/integrity_scan_phantom_clear_reads_the_logical_clock
        """
        position_id = self._counted_on_the_first_of_june(api, 2)

        on_the_count_date = validate_success(
            api.run_integrity_scan(position_id, ANALYST)
        )
        assert on_the_count_date["corrections_applied"] == 0
        assert on_the_count_date["phantom_zeroed_units"] == 0
        assert on_the_count_date["resulting_on_hand_units"] == 2

        advanced = validate_success(api.set_clock(DEFAULT_CLOCK_UTC, ADMIN))
        assert advanced["current_utc"] == DEFAULT_CLOCK_UTC

        scanned = validate_success(api.run_integrity_scan(position_id, ANALYST))
        assert scanned["corrections_applied"] == 1
        assert scanned["phantom_zeroed_units"] == 2
        assert scanned["negative_corrected_units"] == 0
        assert len(scanned["auto_posted_adjustment_ids"]) == 1
        assert scanned["pending_adjustment_ids"] == []
        assert scanned["resulting_on_hand_units"] == 0
        assert scanned["resulting_phantom_units"] == 0

        correction = fx.read_adjustment(api, scanned["auto_posted_adjustment_ids"][0])
        assert correction["reason_code"] == "PHANTOM_CLEAR"
        assert correction["delta_units"] == -2
        assert correction["approval_state"] == "NOT_REQUIRED"
        assert correction["posting_state"] == "POSTED"
        assert correction["requested_by_user_id"] == "system"

        cleared = fx.read_position(api, position_id)
        assert cleared["on_hand_units"] == 0
        assert cleared["phantom_units"] == 0

    def test_a_four_unit_position_is_above_the_phantom_ceiling(self, api):
        """
        The unit ceiling is part of the conjunction, so four units never qualify.

        "It fires only when all five of the following hold: `on_hand_units` is
        strictly greater than 0; `reserved_units` is exactly 0; `last_counted_at` is
        not null; the number of calendar days from the UTC date of
        `last_counted_at` to the UTC date of the current logical-clock instant is at
        least 45; and `on_hand_units` is at most 3."

        Design: Corner/endpoints/integrity_scan_phantom_clear_reads_the_logical_clock
        """
        position_id = self._counted_on_the_first_of_june(api, 4)
        validate_success(api.set_clock(DEFAULT_CLOCK_UTC, ADMIN))

        scanned = validate_success(api.run_integrity_scan(position_id, ANALYST))
        assert scanned["corrections_applied"] == 0
        assert scanned["phantom_zeroed_units"] == 0
        assert scanned["auto_posted_adjustment_ids"] == []
        assert scanned["resulting_on_hand_units"] == 4
        assert scanned["resulting_phantom_units"] == 0

        untouched = fx.read_position(api, position_id)
        assert untouched["on_hand_units"] == 4
        assert untouched["phantom_units"] == 0

        rows, meta = validate_paginated(
            api.list_adjustments(SUPERVISOR, {"stock_position_id": position_id})
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestTheLogicalClock:
    def test_the_clock_defaults_to_the_documented_instant_and_mutates_no_row(self, api):
        """
        Setting the clock moves later stamps and nothing else.

        "Before the clock has ever been set it reads exactly `2026-08-01T00:00:00Z`,
        and it never falls back to real time. An administrative capability sets the
        clock to a supplied `to_iso8601` instant and reports it back as
        `current_utc`; setting the clock mutates no entity and re-runs no
        calculation."

        Design: Corner/endpoints/clock_endpoint_defaults_to_august_first_and_stamps_new_rows
        """
        category = fx.create_category(api, f.apparel_category_payload())
        assert_clock_instant(category["created_at"], DEFAULT_CLOCK_UTC)
        assert_clock_instant(category["updated_at"], DEFAULT_CLOCK_UTC)

        moved = validate_success(api.set_clock(SEPTEMBER_INSTANT, ADMIN))
        assert moved["current_utc"] == SEPTEMBER_INSTANT

        reread = validate_success(api.get_category(category["id"], ADMIN))
        assert reread["created_at"] == category["created_at"]
        assert reread["updated_at"] == category["updated_at"]
        assert reread["version"] == category["version"]

        store = fx.create_store(api, f.store_payload())
        assert_clock_instant(store["created_at"], SEPTEMBER_INSTANT)

    def test_an_instant_that_is_not_a_utc_timestamp_is_rejected(self, api):
        """
        A malformed instant leaves the clock where it was.

        "A `to_iso8601` value that is not a valid UTC instant is rejected with
        `ERR_INVALID_REQUEST` (HTTP 422)."

        Design: Corner/endpoints/clock_endpoint_defaults_to_august_first_and_stamps_new_rows
        """
        validate_error(
            api.set_clock("not-a-timestamp", ADMIN), ERR_INVALID_REQUEST, 422
        )

        store = fx.create_store(api, f.store_payload())
        assert_clock_instant(store["created_at"], DEFAULT_CLOCK_UTC)


class TestStockPositionListFilters:
    @staticmethod
    def _two_clean_and_one_blocked(api):
        """Three positions at one store, exactly one of them held by the scan."""
        category, store, vendor = _reference_frame(api)
        tee1 = fx.create_item(api, f.item_payload(category["id"], vendor["id"]))
        tee4 = fx.create_item(
            api,
            f.item_payload(
                category["id"],
                vendor["id"],
                sku="TEE-004",
                description="Polo",
                unit_cost_cents=900,
            ),
        )
        tee3 = fx.create_item(
            api,
            f.item_payload(
                category["id"],
                vendor["id"],
                sku="TEE-003",
                description="Tank top",
                unit_cost_cents=1800,
            ),
        )
        fx.create_position(api, store["id"], tee1["id"], baseline=10)
        fx.create_position(api, store["id"], tee4["id"], baseline=10)
        held = fx.create_position(api, store["id"], tee3["id"], baseline=1)

        requested = fx.create_adjustment(api, held["id"], -7)
        fx.post_adjustment(api, requested["id"])
        scanned = validate_success(api.run_integrity_scan(held["id"], ANALYST))
        assert scanned["resulting_on_hand_units"] == -6
        assert scanned["tag_integrity_hold"] is True
        assert scanned["resulting_promising_state"] == "BLOCKED"
        return store["id"], held["id"]

    def test_the_promising_state_filter_returns_only_the_held_position(self, api):
        """
        The filter reads the derived gate, not a stored column.

        "Where §4 declares additional query parameters on a list endpoint, those
        parameters filter the result set by exact match and combine
        conjunctively."

        Design: Corner/endpoints/stock_positions_list_filters_by_promising_state_and_paginates
        """
        store_id, held_id = self._two_clean_and_one_blocked(api)

        rows, meta = validate_paginated(
            api.list_stock_positions(
                SUPERVISOR, {"store_id": store_id, "promising_state": "BLOCKED"}
            )
        )
        assert meta["total_count"] == 1
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == held_id
        assert rows[0]["on_hand_units"] == -6
        assert rows[0]["tag_integrity_hold"] is True

        unfiltered_rows, unfiltered_meta = validate_paginated(
            api.list_stock_positions(SUPERVISOR, {"store_id": store_id})
        )
        assert unfiltered_meta["total_count"] == 3
        assert len(unfiltered_rows) == 3

    def test_the_pages_walk_the_filtered_population(self, api):
        """
        The reported total is the size of the result set before paging.

        "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
        the `meta` object of the envelope, where `total_count` reflects the size of
        the filtered result set before pagination is applied and `has_more` states
        whether rows remain beyond the current page."

        Design: Corner/endpoints/stock_positions_list_filters_by_promising_state_and_paginates
        """
        store_id, _held_id = self._two_clean_and_one_blocked(api)

        first_rows, first_meta = validate_paginated(
            api.list_stock_positions(
                SUPERVISOR, {"store_id": store_id, "limit": 2, "offset": 0}
            )
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        last_rows, last_meta = validate_paginated(
            api.list_stock_positions(
                SUPERVISOR, {"store_id": store_id, "limit": 2, "offset": 2}
            )
        )
        assert len(last_rows) == 1
        assert last_meta["total_count"] == 3
        assert last_meta["offset"] == 2
        assert last_meta["has_more"] is False

        ids = {row["id"] for row in first_rows} | {row["id"] for row in last_rows}
        assert len(ids) == 3

    def test_an_unenumerated_filter_value_is_rejected(self, api):
        """
        The enumerated filter accepts only the values of the field it names.

        "Filters that name an enumerated value — `fulfillment_status` on the store
        list, `promising_state` on the stock-position list, `approval_state` and
        `posting_state` on the adjustment list, `approved_root_cause` on the
        investigation list, `superseded` and `pass_round` on the
        physical-inventory-line list, and `status` wherever it appears — accept only
        the values enumerated for the corresponding field; anything else is rejected
        with `ERR_INVALID_ENUM_VALUE` (HTTP 422)."

        Design: Corner/endpoints/stock_positions_list_filters_by_promising_state_and_paginates
        """
        store_id, _held_id = self._two_clean_and_one_blocked(api)

        validate_error(
            api.list_stock_positions(SUPERVISOR, {"promising_state": "NOT_A_STATE"}),
            ERR_INVALID_ENUM_VALUE,
            422,
        )

        rows, meta = validate_paginated(
            api.list_stock_positions(
                SUPERVISOR, {"store_id": store_id, "promising_state": "PROMISABLE"}
            )
        )
        assert meta["total_count"] == 2
        assert all(row["promising_state"] == "PROMISABLE" for row in rows)

    def test_a_limit_of_zero_is_outside_the_accepted_range(self, api):
        """
        Zero is below the pagination floor.

        "A `limit` outside the range 1 through 100 inclusive, or an `offset` below
        0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

        Design: Corner/endpoints/stock_positions_list_filters_by_promising_state_and_paginates
        """
        store_id, _held_id = self._two_clean_and_one_blocked(api)

        validate_error(
            api.list_stock_positions(SUPERVISOR, {"store_id": store_id, "limit": 0}),
            ERR_INVALID_PAGINATION,
            422,
        )

        rows, meta = validate_paginated(
            api.list_stock_positions(SUPERVISOR, {"store_id": store_id, "limit": 1})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is True


class TestCountSchedulePauseResumeRoundTrip:
    def test_the_round_trip_leaves_the_cadence_and_the_due_date_alone(self, api):
        """
        Resuming restores the schedule without re-basing anything.

        "An `InventorySupervisor` or `ShrinkController` may pause an `ACTIVE`
        schedule, optionally with a `note`, so that no new count task can be opened
        against it, and may resume a `PAUSED` schedule back to `ACTIVE`."

        Design: Corner/endpoints/count_schedule_pause_then_resume_round_trip
        """
        category = fx.create_category(api, f.apparel_category_payload())
        store = fx.create_store(api, f.store_payload())
        schedule = fx.create_schedule(
            api, store["id"], category["id"], first_due_date="2026-08-01"
        )
        assert schedule["status"] == "ACTIVE"
        assert schedule["next_due_date"] == "2026-08-01"
        assert schedule["completed_cycle_count"] == 0
        assert schedule["cadence_days"] == 30

        paused = validate_success(api.pause_count_schedule(schedule["id"], SUPERVISOR))
        assert paused["status"] == "PAUSED"

        resumed = validate_success(api.resume_count_schedule(schedule["id"], SUPERVISOR))
        assert resumed["status"] == "ACTIVE"
        assert resumed["next_due_date"] == "2026-08-01"
        assert resumed["completed_cycle_count"] == 0
        assert resumed["cadence_days"] == 30

        task = fx.create_task(api, schedule["id"])
        assert task["status"] == "SCHEDULED"
        assert task["store_id"] == store["id"]
        assert task["category_id"] == category["id"]

    def test_a_repeat_of_either_step_is_refused(self, api):
        """
        Each step insists on the status it declares as its source.

        "Attempting to pause a schedule that is not `ACTIVE`, or resume one that is
        not `PAUSED`, is rejected with `ERR_COUNT_SCHEDULE_NOT_ACTIVE`."

        Design: Corner/endpoints/count_schedule_pause_then_resume_round_trip
        """
        category = fx.create_category(api, f.apparel_category_payload())
        store = fx.create_store(api, f.store_payload())
        schedule = fx.create_schedule(api, store["id"], category["id"])

        validate_error(
            api.resume_count_schedule(schedule["id"], SUPERVISOR),
            ERR_COUNT_SCHEDULE_NOT_ACTIVE,
            409,
        )
        assert fx.read_schedule(api, schedule["id"])["status"] == "ACTIVE"

        paused = validate_success(api.pause_count_schedule(schedule["id"], SUPERVISOR))
        assert paused["status"] == "PAUSED"

        validate_error(
            api.pause_count_schedule(schedule["id"], SUPERVISOR),
            ERR_COUNT_SCHEDULE_NOT_ACTIVE,
            409,
        )
        assert fx.read_schedule(api, schedule["id"])["status"] == "PAUSED"

        resumed = validate_success(api.resume_count_schedule(schedule["id"], SUPERVISOR))
        assert resumed["status"] == "ACTIVE"

        validate_error(
            api.resume_count_schedule(schedule["id"], SUPERVISOR),
            ERR_COUNT_SCHEDULE_NOT_ACTIVE,
            409,
        )


class TestAdjustmentInvestigationLink:
    def test_an_unknown_link_target_is_reported_before_anything_is_minted(self, api):
        """
        The optional body foreign key is resolved before any arithmetic runs.

        "Foreign keys supplied in a request body are resolved after path
        identifiers, in the order the endpoint's input list declares them, and an
        unresolvable body foreign key raises the same 404 for the type it names — a
        body `store_id` or `destination_store_id` that matches no store raises
        `ERR_STORE_NOT_FOUND`, a body `primary_vendor_id` or `vendor_id` that
        matches no vendor raises `ERR_VENDOR_NOT_FOUND`, a body `category_id` raises
        `ERR_CATEGORY_NOT_FOUND`, a body `item_id` raises `ERR_ITEM_NOT_FOUND`, a
        body `counter_firm_id` raises `ERR_COUNTER_FIRM_NOT_FOUND`, a body
        `count_schedule_id` raises `ERR_COUNT_SCHEDULE_NOT_FOUND`, a body
        `shrink_period_id` raises `ERR_SHRINK_PERIOD_NOT_FOUND`, and a body
        `investigation_id` raises `ERR_INVESTIGATION_NOT_FOUND`."

        Design: Corner/endpoints/adjustment_investigation_link_requires_an_existing_investigation
        """
        world = fx.apparel_reference_world(api, baseline=100)
        version = world["position"]["version"]

        payload = f.adjustment_payload(-5, version)
        payload["investigation_id"] = NON_EXISTENT_UUID
        validate_error(
            api.create_adjustment(world["position_id"], payload, ANALYST),
            ERR_INVESTIGATION_NOT_FOUND,
            404,
        )

        rows, meta = validate_paginated(
            api.list_adjustments(
                SUPERVISOR, {"stock_position_id": world["position_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        untouched = fx.read_position(api, world["position_id"])
        assert untouched["version"] == version
        assert untouched["on_hand_units"] == 100

    def test_the_same_request_without_a_link_keeps_the_loose_strictness(self, api):
        """
        A null link leaves the threshold at the base amount.

        "The strictness factor is 5000 basis points when the cause is `THEFT`, 7500
        basis points when it is `VENDOR_SHORTAGE`, and 10000 basis points in every
        other case — including `DAMAGE`, `PROCESS_ERROR`, a null `investigation_id`,
        and a linked investigation that has not reached `CLOSED`."

        Design: Corner/endpoints/adjustment_investigation_link_requires_an_existing_investigation
        """
        world = fx.apparel_reference_world(api, baseline=100)

        requested = fx.create_adjustment(api, world["position_id"], -5)
        assert requested["investigation_id"] is None
        assert requested["value_impact_cents"] == 6170
        assert requested["authority_threshold_cents"] == 20000
        assert requested["approval_state"] == "NOT_REQUIRED"
        assert requested["posting_state"] == "UNPOSTED"

    def test_a_closed_theft_link_is_what_tightens_the_threshold(self, api):
        """
        The link, once its investigation is finished, halves the base amount.

        "A root cause tightens the threshold, but only once the investigation that
        established it is finished. The governing cause is the `approved_root_cause`
        of the investigation named by `investigation_id`, and only when
        `investigation_id` is not null **and** that investigation's `status` is
        `CLOSED`."

        Design: Corner/endpoints/adjustment_investigation_link_requires_an_existing_investigation
        """
        world = fx.closed_theft_world(api, counted_units=105, baseline=100)
        closed = world["closed_investigation"]
        assert closed["status"] == "CLOSED"
        assert closed["approved_root_cause"] == "THEFT"

        linked = fx.create_adjustment(
            api,
            world["position_id"],
            -5,
            investigation_id=world["investigation_id"],
        )
        assert linked["investigation_id"] == world["investigation_id"]
        assert linked["value_impact_cents"] == 6170
        assert linked["authority_threshold_cents"] == 10000
        assert linked["approval_state"] == "NOT_REQUIRED"
