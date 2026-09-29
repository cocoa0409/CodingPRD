"""Two interval-intersection rules with deliberately different endpoint
conventions."""

from test_helpers import (
    ApiErrorId,
    ReportingPeriodStatus,
    TEST_DEFAULTS,
    approx_hours,
    create_hour_entry_payload,
    create_reporting_period_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

OVERLAPPING_PERIOD = create_reporting_period_payload(
    period_code=TEST_DEFAULTS["SECOND_PERIOD_CODE"],
    start_date="2026-04-30",
    end_date=TEST_DEFAULTS["SECOND_PERIOD_END"],
    submission_deadline=TEST_DEFAULTS["SECOND_PERIOD_DEADLINE"],
    correction_window_end=TEST_DEFAULTS["SECOND_PERIOD_CORRECTION_END"],
)
ADJACENT_PERIOD = create_reporting_period_payload(
    period_code=TEST_DEFAULTS["SECOND_PERIOD_CODE"],
    start_date="2026-05-01",
    end_date=TEST_DEFAULTS["SECOND_PERIOD_END"],
    submission_deadline=TEST_DEFAULTS["SECOND_PERIOD_DEADLINE"],
    correction_window_end=TEST_DEFAULTS["SECOND_PERIOD_CORRECTION_END"],
)


class TestShiftIntervalsAreHalfOpen:
    def test_01_a_shift_starting_where_another_ends_is_accepted(
        self, api, supported_quarter
    ):
        """PRD: "treating each shift as the half-open interval that includes its
        start and excludes its end, the new shift's interval must not intersect the
        interval of any other `ACTIVE` hour entry for the same `worker_id` on the
        same `work_date`. Touching endpoints do not intersect, so a shift ending at
        `15:00` and another starting at `15:00` are both accepted".

        Design: Difficulty/resource_temporal_overlap/worker_shift_overlap_half_open_allows_adjacency
        """
        scenario = supported_quarter
        universe = scenario.universe

        data = validate_success(
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    scenario.version,
                    work_date="2026-04-01",
                    shift_start="15:00",
                    shift_end="19:00",
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        assert data["raw_hours"] == approx_hours(4.00)
        assert data["direct_care_hours"] == approx_hours(4.00)

    def test_02_a_shift_overlapping_by_one_minute_is_refused(
        self, api, supported_quarter
    ):
        """PRD: "a genuine intersection is refused with `ERR_SHIFT_OVERLAP`." A
        shift running 14:59 to 16:00 shares the 14:59-to-15:00 minute with the
        07:00-to-15:00 entry already on file for that worker and date.

        Design: Difficulty/resource_temporal_overlap/worker_shift_overlap_half_open_allows_adjacency
        """
        scenario = supported_quarter
        universe = scenario.universe
        validate_success(
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    scenario.version,
                    work_date="2026-04-01",
                    shift_start="15:00",
                    shift_end="19:00",
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        response = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-04-01",
                shift_start="14:59",
                shift_end="16:00",
            ),
            universe.coord_headers,
        )
        validate_error(response, ApiErrorId.ERR_SHIFT_OVERLAP.value)

    def test_03_only_the_two_adjacent_shifts_survive_in_the_rollups(
        self, api, supported_quarter
    ):
        """PRD: "`total_raw_hours` is the sum of `raw_hours`, `total_direct_care_hours`
        the sum of `direct_care_hours`" over the active population, and
        "`reported_hours_total` is refreshed for every worker referenced by the
        active hour population".

        Design: Difficulty/resource_temporal_overlap/worker_shift_overlap_half_open_allows_adjacency
        """
        scenario = supported_quarter
        universe = scenario.universe
        validate_success(
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    scenario.version,
                    work_date="2026-04-01",
                    shift_start="15:00",
                    shift_end="19:00",
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )
        api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-04-01",
                shift_start="14:59",
                shift_end="16:00",
            ),
            universe.coord_headers,
        )

        submission = scenario.refresh()
        assert submission["total_raw_hours"] == approx_hours(12.00)
        assert submission["total_direct_care_hours"] == approx_hours(12.00)

        entries, _ = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {"submission_id": scenario.id, "limit": 100},
            )
        )
        assert len(entries) == 2

        worker = validate_success(
            api.get_worker(universe.w_rn["id"], universe.coord_headers)
        )
        assert worker["reported_hours_total"] == approx_hours(12.00)


class TestPeriodRangesAreClosedInclusive:
    def test_01_sharing_a_single_boundary_date_is_an_intersection(
        self, api, universe, platform_admin_headers
    ):
        """PRD: "the new period's closed-inclusive date range must not intersect the
        closed-inclusive range of any existing period for the same `state_code`, and
        sharing even a single boundary date counts as an intersection and is refused
        with `ERR_PERIOD_OVERLAP`." The existing quarter ends on 2026-04-30, so a new
        quarter starting on 2026-04-30 shares exactly that one day.

        Design: Difficulty/resource_temporal_overlap/reporting_period_overlap_closed_inclusive_rejects_shared_boundary
        """
        response = api.create_reporting_period(
            OVERLAPPING_PERIOD, platform_admin_headers
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_OVERLAP.value)

        existing = validate_success(
            api.get_reporting_period(universe.period_id, platform_admin_headers)
        )
        assert existing["end_date"] == TEST_DEFAULTS["PERIOD_END"]

    def test_02_a_range_starting_the_day_after_is_accepted(
        self, api, universe, platform_admin_headers
    ):
        """PRD: a reporting period "is created with a `period_code` such as `2026Q2`,
        a `state_code`, an inclusive `start_date` and `end_date` in `YYYY-MM-DD` form
        (with `end_date` on or after `start_date`), a `submission_deadline`, and a
        `correction_window_end`" and the system "sets `status` to `OPEN`".

        Design: Difficulty/resource_temporal_overlap/reporting_period_overlap_closed_inclusive_rejects_shared_boundary
        """
        data = validate_success(
            api.create_reporting_period(ADJACENT_PERIOD, platform_admin_headers),
            expected_status=201,
        )

        assert data["start_date"] == "2026-05-01"
        assert data["status"] == ReportingPeriodStatus.OPEN.value

    def test_03_the_state_keeps_exactly_the_two_non_intersecting_quarters(
        self, api, universe, platform_admin_headers
    ):
        """PRD: check 40 is "On period creation, the new period's date range does not
        intersect an existing period for the same state — otherwise
        `ERR_PERIOD_OVERLAP`", so the refused creation leaves no row behind.

        Design: Difficulty/resource_temporal_overlap/reporting_period_overlap_closed_inclusive_rejects_shared_boundary
        """
        api.create_reporting_period(OVERLAPPING_PERIOD, platform_admin_headers)
        validate_success(
            api.create_reporting_period(ADJACENT_PERIOD, platform_admin_headers),
            expected_status=201,
        )

        periods, _ = validate_paginated(
            api.list_reporting_periods(
                platform_admin_headers,
                {"state_code": TEST_DEFAULTS["FACILITY_STATE_CODE"], "limit": 100},
            )
        )
        assert len(periods) == 2
