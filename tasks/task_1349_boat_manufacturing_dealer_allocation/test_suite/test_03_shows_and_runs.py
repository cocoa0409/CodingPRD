"""Boat-show calendar windows and production-run windows: date domains and
the two interval-overlap semantics (PRD §3.2, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_boat_show_event,
    assert_production_run,
    create_boat_show_event_payload,
    create_production_run_payload,
    create_run,
    validate_error,
    validate_paginated,
    validate_success,
)

ALLOC = TEST_USERS["allocation_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ANY = TEST_USERS["any_headers"]


class TestShowEventDateDomain:
    def test_show_event_creation_validates_date_order(self, api):
        """PRD §2.9: "Body schema and field domains: required fields present;
        enum values valid; dates well-formed with start not after end; a
        production run's `build_week_end` exactly seven days after its
        `build_week_start`; amounts non-negative; `hin_serial_start` not greater
        than `hin_serial_end`; a `BOAT_SHOW`-sourced order carries a
        `show_event_id` while other sources must not; `option_package_ids`, when
        provided on an amendment, is non-empty; and no duplicate option
        identifiers appear within one order — any violation is
        `ERR_INVALID_REQUEST`."
        PRD §3.2: "Registering a show takes an `event_name`, the `region` it
        occupies, a `start_date` and an `end_date` with the end no earlier than
        the start"

        Design: Corner/entities/boat_show_event_creation_validates_date_order
        """
        payload = create_boat_show_event_payload(
            event_name="Miami", start_date="2026-08-15", end_date="2026-08-10"
        )
        resp = api.create_boat_show_event(payload, ALLOC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestShowWindowOverlap:
    """Boat-show windows are CLOSED intervals: sharing even one day conflicts."""

    def test_show_overlap_shared_single_day_rejected_disjoint_accepted(self, api):
        """PRD §3.2: "Two shows in the same region may not overlap on their
        closed windows — sharing even a single day is a conflict — and such a
        registration is rejected with `ERR_SHOW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/boat_show_closed_interval_overlap
        """
        e1 = validate_success(
            api.create_boat_show_event(
                create_boat_show_event_payload(
                    event_name="Miami Show", region="SE",
                    start_date="2026-08-10", end_date="2026-08-15",
                ),
                ALLOC,
            ),
            201,
        )
        assert_boat_show_event(e1)
        # E2 shares the single day 2026-08-15 with E1 -> closed-interval conflict.
        resp_conflict = api.create_boat_show_event(
            create_boat_show_event_payload(
                event_name="Tampa Show", region="SE",
                start_date="2026-08-15", end_date="2026-08-20",
            ),
            ALLOC,
        )
        validate_error(resp_conflict, ApiErrorId.ERR_SHOW_WINDOW_OVERLAP)
        # E3 starts the day after E1 ends -> disjoint, accepted.
        e3 = validate_success(
            api.create_boat_show_event(
                create_boat_show_event_payload(
                    event_name="Jacksonville Show", region="SE",
                    start_date="2026-08-16", end_date="2026-08-20",
                ),
                ALLOC,
            ),
            201,
        )
        assert_boat_show_event(e3)

    def test_show_overlap_same_window_different_region_allowed(self, api):
        """PRD §3.2: "Two shows in the same region may not overlap on their
        closed windows — sharing even a single day is a conflict — and such a
        registration is rejected with `ERR_SHOW_WINDOW_OVERLAP`."

        The overlap rule is per-region: the identical window in a different
        region does not conflict.

        Design: Difficulty/resource_temporal_overlap/boat_show_closed_interval_overlap
        """
        validate_success(
            api.create_boat_show_event(
                create_boat_show_event_payload(
                    event_name="Miami Show", region="SE",
                    start_date="2026-08-10", end_date="2026-08-15",
                ),
                ALLOC,
            ),
            201,
        )
        e2 = validate_success(
            api.create_boat_show_event(
                create_boat_show_event_payload(
                    event_name="Seattle Show", region="NW",
                    start_date="2026-08-10", end_date="2026-08-15",
                ),
                ALLOC,
            ),
            201,
        )
        assert_boat_show_event(e2)
        assert e2["region"] == "NW"


class TestProductionRunWeek:
    def test_run_week_must_be_exactly_seven_days(self, api):
        """PRD §3.3: "Creating a run names the `plant_line_code`, declares the
        `season` as `PEAK`, `SHOULDER`, or `OFF_PEAK` (this choice drives the
        seasonal carrying-cost weighting at close), and fixes the build week:
        `build_week_end` must fall exactly seven days after `build_week_start`"
        PRD §2.9: "Body schema and field domains: required fields present;
        enum values valid; dates well-formed with start not after end; a
        production run's `build_week_end` exactly seven days after its
        `build_week_start`; amounts non-negative; `hin_serial_start` not greater
        than `hin_serial_end`; a `BOAT_SHOW`-sourced order carries a
        `show_event_id` while other sources must not; `option_package_ids`, when
        provided on an amendment, is non-empty; and no duplicate option
        identifiers appear within one order — any violation is
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/production_run_week_must_be_exactly_seven_days
        """
        payload = create_production_run_payload(
            plant_line_code="L1",
            build_week_start="2026-08-03",
            build_week_end="2026-08-12",
        )
        resp = api.create_production_run(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRunWindowOverlap:
    """Production-run windows are HALF-OPEN [start, end): end == start is
    permitted; overlapping interiors are rejected."""

    def test_run_half_open_adjacent_allowed_interior_overlap_rejected(self, api):
        """PRD §3.3: "Two runs on the same plant line may not have overlapping
        half-open windows — adjacent runs where one's end equals the other's
        start are permitted — and a colliding registration fails with
        `ERR_LINE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/production_run_half_open_overlap
        """
        r1 = create_run(
            api,
            plant_line_code="L1",
            build_week_start="2026-08-03",
            build_week_end="2026-08-10",
            option_change_cutoff_at="2026-08-05T12:00:00Z",
        )
        # Adjacent: R2 starts exactly when R1 ends -> half-open allows.
        r2 = validate_success(
            api.create_production_run(
                create_production_run_payload(
                    plant_line_code="L1",
                    build_week_start="2026-08-10",
                    build_week_end="2026-08-17",
                    option_change_cutoff_at="2026-08-12T12:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )
        assert_production_run(r2)
        assert r2["status"] == "OPEN"
        # Interior overlap with R1 -> rejected.
        resp = api.create_production_run(
            create_production_run_payload(
                plant_line_code="L1",
                build_week_start="2026-08-09",
                build_week_end="2026-08-16",
                option_change_cutoff_at="2026-08-11T12:00:00Z",
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_OVERLAP)
        fetched = validate_success(api.get_production_run(r1["id"], ANY), 200)
        assert fetched["status"] == "OPEN"

    def test_run_overlap_same_window_different_line_allowed(self, api):
        """PRD §3.3: "Two runs on the same plant line may not have overlapping
        half-open windows — adjacent runs where one's end equals the other's
        start are permitted — and a colliding registration fails with
        `ERR_LINE_WINDOW_OVERLAP`."

        The rule keys on the plant line: the identical week on a different line
        does not collide.

        Design: Difficulty/resource_temporal_overlap/production_run_half_open_overlap
        """
        create_run(api, plant_line_code="L1")
        r2 = validate_success(
            api.create_production_run(
                create_production_run_payload(plant_line_code="L2"), PLANNER
            ),
            201,
        )
        assert_production_run(r2)
        assert r2["plant_line_code"] == "L2"


class TestRunTerminalLockdown:
    def test_run_close_on_closed_run_rejected(self, api):
        """PRD §3.3: "Closing a run is the season checkpoint, performed by a
        `ProductionPlanner` and permitted only while the run is `OPEN` (a second
        close, or any close of a `CLOSED` run, draws `ERR_RUN_NOT_OPEN`)."

        Design: Corner/state_machines/production_run_terminal_lockdown_closed
        """
        run = create_run(api, plant_line_code="L1")
        closed = validate_success(api.close_production_run(run["id"], PLANNER), 200)
        assert closed["status"] == "CLOSED"
        resp = api.close_production_run(run["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_OPEN)


class TestRunListFilter:
    def test_runs_list_filter_by_status(self, api):
        """PRD §3.3: "A new run is `OPEN` with both carrying totals zeroed; the
        run collection can be filtered by `plant_line_code` or `status`."

        Design: Corner/endpoints/production_runs_list_filter_by_status
        """
        r1 = create_run(api, plant_line_code="L1")
        r2 = create_run(api, plant_line_code="L2")
        validate_success(api.close_production_run(r1["id"], PLANNER), 200)
        data, _meta = validate_paginated(
            api.list_production_runs(ANY, params={"status": "CLOSED"})
        )
        assert len(data) >= 1
        ids = {row["id"] for row in data}
        assert r1["id"] in ids
        assert r2["id"] not in ids, "OPEN run must not appear in a CLOSED filter"
        for row in data:
            assert row["status"] == "CLOSED"
