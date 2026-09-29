"""Two overlap conventions living side by side in the same service.

Hearing sessions compare buffered closed intervals, where touching endpoints
collide. Construction activities compare half-open windows, where touching
endpoints do not.
"""

from test_helpers import ApiErrorId, validate_error, validate_paginated, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestHearingWindowBuffer:
    """A two-hour buffer on each side, compared as closed intervals."""

    def test_session_touching_the_buffer_edge_is_refused(self, api):
        """PRD §3.6: "If those two closed intervals intersect at any point,
        including when they merely touch at an endpoint, the new session is
        refused with `ERR_HEARING_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hearing_window_buffered_closed_interval_touching_rejected
        """
        ctx = fx.setup_accepted_application(api)
        fx.schedule_session(api, ctx, key="sess1", kind="EVIDENTIARY")

        response = api.create_hearing_session(
            f.hearing_session_payload(
                ctx["app"], kind="PUBLIC_TESTIMONY",
                window_start_at="2026-10-05T14:00:00Z",
                window_end_at="2026-10-05T16:00:00Z",
            ),
            fx.HEARING_EXAMINER_HEADERS,
        )
        validate_error(response, ApiErrorId.HEARING_WINDOW_CONFLICT, expected_status=409)

        sessions, meta = validate_paginated(
            api.list_application_hearing_sessions(ctx["app"], fx.COMMISSION_STAFF_HEADERS)
        )
        assert meta["total_count"] == 1, (
            f"The refused session must not be recorded, got {meta['total_count']}"
        )
        assert sessions[0]["status"] == "SCHEDULED", (
            f"The existing session is untouched, got {sessions[0]['status']}"
        )

    def test_session_one_minute_clear_of_the_buffer_is_accepted(self, api):
        """PRD §3.6: "take the new session's closed interval and pad it by two
        hours on each side — that is, from 120 minutes before its start to 120
        minutes after its end — and compare that padded interval against the
        unpadded closed interval of every existing session on the same
        application whose status is `SCHEDULED` or `HELD`."

        Design: Difficulty/resource_temporal_overlap/hearing_window_buffered_closed_interval_touching_rejected
        """
        ctx = fx.setup_accepted_application(api)
        fx.schedule_session(api, ctx, key="sess1", kind="EVIDENTIARY")

        session = validate_success(
            api.create_hearing_session(
                f.hearing_session_payload(
                    ctx["app"], kind="PUBLIC_TESTIMONY",
                    window_start_at="2026-10-05T14:01:00Z",
                    window_end_at="2026-10-05T16:01:00Z",
                ),
                fx.HEARING_EXAMINER_HEADERS,
            ),
            expected_status=201,
        )

        assert session["status"] == "SCHEDULED", (
            f"The accepted session opens at SCHEDULED, got {session['status']}"
        )
        assert str(session["window_start_at"]).startswith("2026-10-05T14:01:00"), (
            f"The stored window keeps the requested start, got "
            f"{session['window_start_at']}"
        )
        assert session["exhibits_admitted_count"] == 0, (
            f"A scheduled session has admitted nothing yet, got "
            f"{session['exhibits_admitted_count']}"
        )
        _, meta = validate_paginated(
            api.list_application_hearing_sessions(ctx["app"], fx.COMMISSION_STAFF_HEADERS)
        )
        assert meta["total_count"] == 2, (
            f"Both sessions now sit on the docket, got {meta['total_count']}"
        )


class TestActivityHalfOpenWindow:
    """Half-open occupation windows: the end instant is excluded."""

    def test_window_overlapping_by_one_day_contends_for_crew(self, api):
        """PRD §3.9: "Sum the `crew_count` of every activity on that same segment
        whose half-open window intersects the new one and whose status is
        `SCHEDULED`, `IN_PROGRESS` or `SUSPENDED`, add the new activity's crew
        count, and refuse the request with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422)
        if that total exceeds the effective limit."

        Design: Difficulty/resource_temporal_overlap/activity_half_open_window_touching_allowed_overlap_rejected
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)

        response = api.create_construction_activity(
            f.construction_activity_payload(
                ctx["cert"], ctx["seg1"], activity_kind="FOUNDATION", crew_count=4,
                window_start_at="2027-08-11T00:00:00Z",
                window_end_at="2027-08-15T00:00:00Z",
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.CREW_CAPACITY_EXCEEDED, expected_status=422)

        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 6, (
            "Only the running activity holds crew slots, got "
            f"{segment['committed_crew_count']}"
        )

    def test_window_starting_exactly_when_the_first_ends_does_not_contend(self, api):
        """PRD §3.9: "The occupation window is **half-open**: it includes its start
        instant and excludes its end instant, so one activity ending exactly when
        another begins does not overlap it."

        Design: Difficulty/resource_temporal_overlap/activity_half_open_window_touching_allowed_overlap_rejected
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)

        activity = validate_success(
            api.create_construction_activity(
                f.construction_activity_payload(
                    ctx["cert"], ctx["seg1"], activity_kind="FOUNDATION", crew_count=4,
                    window_start_at="2027-08-12T00:00:00Z",
                    window_end_at="2027-08-15T00:00:00Z",
                ),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert activity["status"] == "SCHEDULED", (
            f"The touching window is accepted, got {activity['status']}"
        )
        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 10, (
            "The counter sums every live activity on the segment regardless of overlap, "
            f"so 6 plus 4 is 10, got {segment['committed_crew_count']}"
        )
