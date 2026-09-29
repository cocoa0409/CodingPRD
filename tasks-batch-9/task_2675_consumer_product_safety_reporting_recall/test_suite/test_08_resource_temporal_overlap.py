"""Two contested timelines with deliberately opposite interval semantics."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_field_values,
    assert_ids_equal,
    assert_unchanged,
)
from test_helpers.test_users import AUDITOR_HEADERS, OFFICER_HEADERS

# The standing inspection slot at MegaMart: half-open, so it runs up to but not
# including 17:00, and the deconfliction predicate widens it by 24 hours a side.
EXISTING_WINDOW = {
    "window_start": "2026-03-17T09:00:00Z",
    "window_end": "2026-03-17T17:00:00Z",
}

# A full day clear of the raw window and still one hour inside the travel buffer.
BUFFER_CONFLICT_WINDOW = {
    "window_start": "2026-03-18T16:00:00Z",
    "window_end": "2026-03-18T20:00:00Z",
}

# Starting at exactly window_end plus 24 hours: the half-open touch is legal.
BUFFER_CLEAR_WINDOW = {
    "window_start": "2026-03-18T17:00:00Z",
    "window_end": "2026-03-18T21:00:00Z",
}

# The first monthly period begins the instant the stop-sale took effect.
FIRST_PERIOD = {
    "period_start": "2026-03-13T00:00:00Z",
    "period_end": "2026-04-12T00:00:00Z",
}

# Sharing the single instant 2026-04-12T00:00:00Z, and also non-contiguous.
TOUCHING_PERIOD = {
    "period_start": "2026-04-12T00:00:00Z",
    "period_end": "2026-05-12T00:00:00Z",
}

# The legal successor: the previous period_end plus exactly 24 hours.
CONTIGUOUS_PERIOD = {
    "period_start": "2026-04-13T00:00:00Z",
    "period_end": "2026-05-13T00:00:00Z",
}

REPORTING_CLOCK = "2026-05-14T00:00:00Z"


def _scheduled_visit_env(api):
    """An approved recall at MegaMart with one scheduled inspection slot."""
    env = fx.approved_recall_env(api)
    visit = fx.create_audit_visit(api, env["notification_id"], **EXISTING_WINDOW)
    env["visit"] = visit
    return env, visit


def _attempt_visit(api, notification_id, window):
    """Schedule one audit visit, returning the raw response."""
    return api.create_audit_visit(
        f.audit_visit_payload(notification_id, **window), headers=AUDITOR_HEADERS
    )


def _visits_at(api, notification_id):
    """Every audit visit recorded against one notification."""
    return validate_paginated(
        api.list_audit_visits(
            {"retailer_notification_id": notification_id}, headers=AUDITOR_HEADERS
        )
    )


def _submitted_first_period_env(api):
    """A monitoring recall whose first monthly period is already filed."""
    env = fx.monitoring_recall_env(api)
    fx.set_clock(api, REPORTING_CLOCK)
    env["first_report"] = fx.submitted_progress_report(
        api, env["recall_id"], effectiveness_basis="UNITS_BASIS", **FIRST_PERIOD
    )
    return env


def _attempt_period(api, recall_id, period):
    """Open one monthly reporting period, returning the raw response."""
    return api.create_progress_report(
        f.progress_report_payload(recall_id, **period), headers=OFFICER_HEADERS
    )


def _reports_on(api, recall_id):
    """Every monthly progress report recorded against one recall."""
    return validate_paginated(
        api.list_progress_reports({"recall_id": recall_id}, headers=OFFICER_HEADERS)
    )


class TestAuditWindowTravelBufferAtOneRetailer:
    """One inspector team covers the store, so the buffer is what collides."""

    def test_a_window_a_day_clear_still_collides_through_the_travel_buffer(self, api):
        """Raw windows that never intersect can still conflict on the buffer.

        The contract states: "Each window is widened by a travel buffer of 24
        hours on each side, and the new visit conflicts with an existing one when
        the new `window_start` falls before the existing `window_end` plus 24
        hours **and** the existing `window_start` falls before the new
        `window_end` plus 24 hours." The comparison set is store-wide, because
        "audit windows are deconflicted **per retailer across all recalls**."

        Design: Difficulty/resource_temporal_overlap/audit_visit_half_open_window_plus_travel_buffer_conflicts_at_same_retailer
        """
        env, first = _scheduled_visit_env(api)
        assert (
            BUFFER_CONFLICT_WINDOW["window_start"] > EXISTING_WINDOW["window_end"]
        ), "the two raw windows must not intersect at all"

        response = _attempt_visit(
            api, env["notification_id"], BUFFER_CONFLICT_WINDOW
        )
        validate_error(response, "ERR_AUDIT_WINDOW_CONFLICT", 409)

        after = fx.get_audit_visit(api, first["id"])
        assert_field_values(after, status="SCHEDULED", verdict="PENDING")
        assert_unchanged(first, after, "window_start", "window_end", "version")

        rows, meta = _visits_at(api, env["notification_id"])
        assert_ids_equal(rows, [first["id"]])
        assert meta["total_count"] == 1, meta

    def test_a_window_starting_exactly_a_buffer_after_the_last_one_is_accepted(
        self, api
    ):
        """The half-open touch at window_end plus 24 hours is legal.

        The contract states: "Because the interval is half-open, a new window
        starting at exactly the existing `window_end` plus 24 hours does not
        conflict." Audit windows are "**half-open**: they include `window_start`
        and exclude `window_end`, and `window_end` must be strictly greater than
        `window_start`."

        Design: Difficulty/resource_temporal_overlap/audit_visit_half_open_window_plus_travel_buffer_conflicts_at_same_retailer
        """
        env, first = _scheduled_visit_env(api)

        second = fx.create_audit_visit(
            api, env["notification_id"], **BUFFER_CLEAR_WINDOW
        )
        assert_field_values(
            second,
            status="SCHEDULED",
            verdict="PENDING",
            retailer_notification_id=env["notification_id"],
        )
        assert second["window_start"].startswith("2026-03-18T17:00:00"), second

        rows, meta = _visits_at(api, env["notification_id"])
        assert_ids_equal(rows, [first["id"], second["id"]])
        assert_created_at_ascending(rows)
        assert meta["total_count"] == 2, meta

    def test_a_completed_visit_no_longer_holds_the_store_slot(self, api):
        """Once the inspection is recorded its window stops deconflicting.

        The contract states: "The comparison set is every other `SCHEDULED` audit
        visit whose `retailer_notification_id` belongs to the same `retailer_id`;
        `COMPLETED` visits are ignored."

        Design: Difficulty/resource_temporal_overlap/audit_visit_half_open_window_plus_travel_buffer_conflicts_at_same_retailer
        """
        env, first = _scheduled_visit_env(api)

        completed = fx.complete_audit_visit(
            api, first["id"], verdict="PASS", shelf_units_found=0
        )
        assert_field_values(completed, status="COMPLETED", verdict="PASS")

        second = fx.create_audit_visit(
            api, env["notification_id"], **BUFFER_CONFLICT_WINDOW
        )
        assert_field_values(second, status="SCHEDULED", verdict="PENDING")
        assert second["window_start"].startswith("2026-03-18T16:00:00"), second

        rows, meta = _visits_at(api, env["notification_id"])
        assert_ids_equal(rows, [first["id"], second["id"]])
        assert meta["total_count"] == 2, meta


class TestMonthlyReportingPeriodsAreClosedIntervals:
    """The recall's reporting timeline, where a shared instant is an overlap."""

    def test_a_period_starting_on_the_previous_period_end_overlaps_and_outranks_the_gap(
        self, api
    ):
        """Sharing one instant is an overlap, reported ahead of the gap rule.

        The contract states: "First, periods may not overlap: because both
        endpoints are inclusive, the new period conflicts with an existing one
        when the new `period_start` is at or before the existing `period_end` and
        the existing `period_start` is at or before the new `period_end`, and a
        conflict is refused with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)." The
        order is fixed, since "Temporal scheduling — in this order: audit-window
        collision (`ERR_AUDIT_WINDOW_CONFLICT`), reporting-period overlap
        (`ERR_REPORT_PERIOD_OVERLAP`), reporting-period gap
        (`ERR_REPORT_PERIOD_GAP`), notice not yet due (`ERR_NOTICE_NOT_DUE`),
        embargo still in force (`ERR_EMBARGO_ACTIVE`)."

        Design: Difficulty/resource_temporal_overlap/progress_report_closed_period_sharing_one_endpoint_instant_overlaps
        """
        env = _submitted_first_period_env(api)
        recall = fx.get_recall(api, env["recall_id"])
        assert recall["stop_sale_effective_at"].startswith("2026-03-13T00:00:00"), (
            "the first period must begin the instant the stop-sale took effect"
        )
        assert (
            TOUCHING_PERIOD["period_start"] == FIRST_PERIOD["period_end"]
        ), "the two closed periods must share exactly one instant"

        response = _attempt_period(api, env["recall_id"], TOUCHING_PERIOD)
        validate_error(response, "ERR_REPORT_PERIOD_OVERLAP", 409)

        first_after = fx.get_progress_report(api, env["first_report"]["id"])
        assert_field_values(first_after, status="SUBMITTED")
        assert_unchanged(
            env["first_report"],
            first_after,
            "period_start",
            "period_end",
            "status",
            "version",
        )

        rows, meta = _reports_on(api, env["recall_id"])
        assert_ids_equal(rows, [env["first_report"]["id"]])
        assert meta["total_count"] == 1, meta

    def test_a_period_starting_a_day_after_the_previous_period_end_is_accepted(
        self, api
    ):
        """The contiguous successor at period_end plus 24 hours is legal.

        The contract states: "Second, periods may not skip time: taking the
        latest `period_end` across that same comparison set, the new
        `period_start` must equal that latest `period_end` plus exactly 24 hours;
        and when no such prior report exists, the new `period_start` must equal
        the recall's `stop_sale_effective_at` exactly, so that the very first
        monthly period begins the instant the stop-sale took effect." The
        contrast is deliberate: "a new reporting period beginning at exactly the
        previous `period_end` *does* overlap, whereas an audit window beginning
        at the previous `window_end` does not."

        Design: Difficulty/resource_temporal_overlap/progress_report_closed_period_sharing_one_endpoint_instant_overlaps
        """
        env = _submitted_first_period_env(api)

        second = fx.create_progress_report(
            api,
            env["recall_id"],
            effectiveness_basis="UNITS_BASIS",
            **CONTIGUOUS_PERIOD,
        )
        assert_field_values(
            second,
            status="DRAFT",
            assessment="PENDING",
            recall_id=env["recall_id"],
            units_corrected_in_period=0,
            cumulative_units_corrected=0,
        )
        assert second["period_start"].startswith("2026-04-13T00:00:00"), second

        rows, meta = _reports_on(api, env["recall_id"])
        assert_ids_equal(rows, [env["first_report"]["id"], second["id"]])
        assert_created_at_ascending(rows)
        assert meta["total_count"] == 2, meta
