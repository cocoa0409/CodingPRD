"""Two interval conventions that disagree about what a shared boundary means.

Refresh periods are closed, so two cycles that touch on a single day collide.
Outage windows are half-open, so a window that starts on the instant another ends
is accepted — and then merges with it when the month is scored. Getting either
convention backwards flips exactly one of these calls.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    CYCLE_PENDING,
    POSTURE_COMPLIANT,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CYCLE_CLOCK = "2027-07-01T09:00:00Z"
TOOL_LAUNCH_CLOCK = "2027-01-05T09:00:00Z"
EVALUATION_CLOCK = "2027-07-02T00:00:00Z"
EVALUATION_MONTH = "2027-06"

FIRST_WINDOW = {
    "window_start": "2027-06-10T00:00:00Z",
    "window_end": "2027-06-10T03:00:00Z",
    "cause": "Primary rate cache rebuild",
}
TOUCHING_WINDOW = {
    "window_start": "2027-06-10T03:00:00Z",
    "window_end": "2027-06-10T04:12:00Z",
    "cause": "Follow-on index rebuild starting exactly at the first window's end",
}
OVERLAPPING_WINDOW = {
    "window_start": "2027-06-10T04:00:00Z",
    "window_end": "2027-06-10T05:00:00Z",
    "cause": "Overlapping late-filed incident",
}


def _plan_year_with_june_cycle(api: ApiClient) -> dict:
    """An ACTIVE plan year holding one PENDING cycle over closed June."""
    fx.set_clock(api, CYCLE_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    plan_year_id = setup["plan_year"]["id"]
    june = fx.open_refresh_cycle(
        api,
        plan_year_id,
        period_month=EVALUATION_MONTH,
        period_start="2027-06-01",
        period_end="2027-06-30",
    )
    return {"plan_year_id": plan_year_id, "june": june}


def _live_tool_without_windows(api: ApiClient) -> dict:
    """A LIVE tool with an empty outage history and the clock past June."""
    fx.set_clock(api, TOOL_LAUNCH_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    tool = fx.live_price_comparison_tool(
        api,
        setup["plan_year"]["id"],
        covered_items_count=800,
        sla_target_uptime_pct=99.00,
    )
    fx.set_clock(api, EVALUATION_CLOCK)
    return {"plan_year_id": setup["plan_year"]["id"], "tool_id": tool["id"]}


def _append(api: ApiClient, tool_id: str, window: dict):
    return api.append_outage_window(
        tool_id, f.outage_window_payload(**window), PLATFORM_OPERATOR_HEADERS
    )


class TestRefreshPeriodsAreClosedIntervals:
    """Sharing a single boundary day is a collision, not an abutment."""

    def test_a_period_starting_on_the_incumbent_last_day_is_refused(
        self, api: ApiClient
    ) -> None:
        """2027-06-30 belongs to June, so July may not start on it.

        PRD 3.2: "Because refresh periods are closed intervals, a new cycle whose
        period touches or overlaps a sibling cycle's period on even a single
        boundary day is refused with `ERR_REFRESH_PERIOD_OVERLAP`, and a period
        that falls outside the plan year's own span, or whose `period_end`
        precedes `period_start`, is refused with `ERR_INVALID_INTERVAL`."

        Design: Difficulty/resource_temporal_overlap/refresh_period_closed_interval_shares_boundary_day
        """
        built = _plan_year_with_june_cycle(api)

        response = api.create_refresh_cycle(
            f.refresh_cycle_payload(
                built["plan_year_id"],
                period_month="2027-07",
                period_start="2027-06-30",
                period_end="2027-07-31",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.REFRESH_PERIOD_OVERLAP)

        rows, meta = validate_paginated(
            api.list_refresh_cycles(
                COMPLIANCE_OFFICER_HEADERS,
                params={"plan_year_id": built["plan_year_id"]},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [built["june"]["id"]]

    def test_shifting_the_start_one_day_clear_is_accepted_with_its_own_deadline(
        self, api: ApiClient
    ) -> None:
        """2027-07-01 abuts June without sharing a day, and derives its deadline.

        PRD 3.2: "The service derives `deadline_at` on creation rather than
        accepting it: it is the instant five days after `period_end`, at
        23:59:59.999Z on that fifth day — a five-day grace window on top of the
        period itself."

        Design: Difficulty/resource_temporal_overlap/refresh_period_closed_interval_shares_boundary_day
        """
        built = _plan_year_with_june_cycle(api)
        validate_error(
            api.create_refresh_cycle(
                f.refresh_cycle_payload(
                    built["plan_year_id"],
                    period_month="2027-07",
                    period_start="2027-06-30",
                    period_end="2027-07-31",
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            ApiErrorId.REFRESH_PERIOD_OVERLAP,
        )

        july = validate_success(
            api.create_refresh_cycle(
                f.refresh_cycle_payload(
                    built["plan_year_id"],
                    period_month="2027-07",
                    period_start="2027-07-01",
                    period_end="2027-07-31",
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert july["period_start"] == "2027-07-01"
        assert july["period_end"] == "2027-07-31"
        assert_instant_equals(july["deadline_at"], "2027-08-05T23:59:59.999Z")
        assert july["status"] == CYCLE_PENDING

        rows, meta = validate_paginated(
            api.list_refresh_cycles(
                COMPLIANCE_OFFICER_HEADERS,
                params={"plan_year_id": built["plan_year_id"]},
            )
        )
        assert meta["total_count"] == 2
        june = validate_success(
            api.get_refresh_cycle(built["june"]["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert_instant_equals(june["deadline_at"], "2027-07-05T23:59:59.999Z")
        assert june["status"] == CYCLE_PENDING

    def test_a_period_ending_on_the_incumbent_first_day_is_also_refused(
        self, api: ApiClient
    ) -> None:
        """The collision rule is symmetric across the shared boundary.

        PRD 3.2: "Because refresh periods are closed intervals, a new cycle whose
        period touches or overlaps a sibling cycle's period on even a single
        boundary day is refused with `ERR_REFRESH_PERIOD_OVERLAP`, and a period
        that falls outside the plan year's own span, or whose `period_end`
        precedes `period_start`, is refused with `ERR_INVALID_INTERVAL`."

        Design: Difficulty/resource_temporal_overlap/refresh_period_closed_interval_shares_boundary_day
        """
        built = _plan_year_with_june_cycle(api)

        response = api.create_refresh_cycle(
            f.refresh_cycle_payload(
                built["plan_year_id"],
                period_month="2027-05",
                period_start="2027-05-01",
                period_end="2027-06-01",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.REFRESH_PERIOD_OVERLAP)

        _, meta = validate_paginated(
            api.list_refresh_cycles(
                COMPLIANCE_OFFICER_HEADERS,
                params={"plan_year_id": built["plan_year_id"]},
            )
        )
        assert meta["total_count"] == 1


class TestOutageWindowsAreHalfOpen:
    """Touching windows are accepted; interiors that intersect are not."""

    def test_a_window_starting_at_another_window_end_is_accepted(
        self, api: ApiClient
    ) -> None:
        """03:00Z is the end of one window and a legal start for the next.

        PRD 3.3: "Then collision: because windows are half-open, a window
        beginning at exactly the instant an existing window ends is accepted,
        while any genuine intersection with an existing window of the same tool
        is refused with `ERR_OUTAGE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_windows_touching_allowed_but_interior_overlap_refused
        """
        built = _live_tool_without_windows(api)
        tool_id = built["tool_id"]

        validate_success(_append(api, tool_id, FIRST_WINDOW))
        after_touching = validate_success(_append(api, tool_id, TOUCHING_WINDOW))
        assert len(after_touching["outage_windows"]) == 2

        refused = _append(api, tool_id, OVERLAPPING_WINDOW)
        validate_error(refused, ApiErrorId.OUTAGE_WINDOW_OVERLAP)

        tool = validate_success(
            api.get_price_comparison_tool(tool_id, SPONSOR_ADMIN_HEADERS)
        )
        assert len(tool["outage_windows"]) == 2

    def test_the_touching_pair_merges_into_one_stretch_of_downtime(
        self, api: ApiClient
    ) -> None:
        """Three hours plus seventy-two minutes is one 252-minute interval.

        PRD 3.3: "Three hours of downtime followed immediately by seventy-two
        more minutes is one interval of 252 minutes, not two intervals counted
        separately."

        Design: Difficulty/resource_temporal_overlap/outage_windows_touching_allowed_but_interior_overlap_refused
        """
        built = _live_tool_without_windows(api)
        tool_id = built["tool_id"]
        validate_success(_append(api, tool_id, FIRST_WINDOW))
        validate_success(_append(api, tool_id, TOUCHING_WINDOW))
        validate_error(
            _append(api, tool_id, OVERLAPPING_WINDOW),
            ApiErrorId.OUTAGE_WINDOW_OVERLAP,
        )

        fx.evaluate_tool(api, tool_id, EVALUATION_MONTH)

        tool = validate_success(
            api.get_price_comparison_tool(tool_id, SPONSOR_ADMIN_HEADERS)
        )
        # 42,948 of 43,200 minutes available is 99.4166..., rounding to 99.42.
        assert tool["last_downtime_minutes"] == 252
        assert tool["last_uptime_pct"] == 99.42
        assert tool["sla_breach_open"] is False
        assert tool["breach_onset_date"] is None

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["tool_sla_breach_count"] == 0
        assert plan_year["deficiency_points"] == 0
        assert plan_year["penalty_exposure_cents"] == 0
        assert plan_year["compliance_posture"] == POSTURE_COMPLIANT

    def test_a_third_touching_window_extends_the_same_merged_stretch(
        self, api: ApiClient
    ) -> None:
        """Every touching append is legal and every touch collapses on scoring.

        PRD 3.3: "The sorted windows are then merged: a window is merged into the
        one before it whenever its `window_start` falls at or before the running
        interval's `window_end` — so windows that overlap *and* windows that
        merely touch collapse into a single stretch of downtime."

        Design: Difficulty/resource_temporal_overlap/outage_windows_touching_allowed_but_interior_overlap_refused
        """
        built = _live_tool_without_windows(api)
        tool_id = built["tool_id"]
        validate_success(_append(api, tool_id, FIRST_WINDOW))
        validate_success(_append(api, tool_id, TOUCHING_WINDOW))
        third = validate_success(
            _append(
                api,
                tool_id,
                {
                    "window_start": "2027-06-10T04:12:00Z",
                    "window_end": "2027-06-10T05:00:00Z",
                    "cause": "Third consecutive rebuild",
                },
            )
        )
        assert len(third["outage_windows"]) == 3

        fx.evaluate_tool(api, tool_id, EVALUATION_MONTH)
        tool = validate_success(
            api.get_price_comparison_tool(tool_id, SPONSOR_ADMIN_HEADERS)
        )
        # 00:00Z through 05:00Z is one merged stretch of 300 minutes.
        assert tool["last_downtime_minutes"] == 300
        assert tool["sla_breach_open"] is False
