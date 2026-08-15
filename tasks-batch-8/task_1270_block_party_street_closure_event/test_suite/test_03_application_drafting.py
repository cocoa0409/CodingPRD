"""Application drafting: event window shape, lead time, segment window conflicts,
and the officer review queue (PRD §2.3, §3.3)."""
import pytest

from test_helpers import (
    OFFICER,
    api_client,
    assert_permit_application,
    create_application_record,
    make_organizer_headers,
    setup_draft_application,
    setup_petition,
    setup_under_review_application,
    submit_application_record,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLeadTimeBoundary:
    def test_exactly_fourteen_days_lead_passes(self, api):
        """PRD §3.3: "the event must start no sooner than the required notice period measured
        from the logical clock — 14 days for a `CITY` segment, 28 days for `COUNTY`, and 45
        days for `STATE_ROUTE` — with an event starting exactly at the deadline passing, and
        anything earlier rejected as `ERR_LEAD_TIME_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/jurisdiction_lead_time_exact_boundary
        """
        ctx = setup_draft_application(
            clock="2026-06-01T12:00:00Z",
            application_overrides={
                "event_start_at": "2026-06-15T12:00:00Z",
                "event_end_at": "2026-06-15T17:00:00Z",
            },
        )
        submitted = submit_application_record(ctx["application"], ctx["organizer"])
        assert submitted["status"] == "UNDER_REVIEW"

    def test_one_second_short_of_lead_rejected(self, api):
        """PRD §3.3: "the event must start no sooner than the required notice period measured
        from the logical clock — 14 days for a `CITY` segment, 28 days for `COUNTY`, and 45
        days for `STATE_ROUTE` — with an event starting exactly at the deadline passing, and
        anything earlier rejected as `ERR_LEAD_TIME_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/jurisdiction_lead_time_exact_boundary
        """
        ctx = setup_draft_application(
            clock="2026-06-01T12:00:00Z",
            application_overrides={
                "event_start_at": "2026-06-15T11:59:59Z",
                "event_end_at": "2026-06-15T16:00:00Z",
            },
        )
        application, organizer = ctx["application"], ctx["organizer"]
        res = api.submit_permit_application(application["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_LEAD_TIME_INSUFFICIENT")
        current = validate_success(
            api.get_permit_application(application["id"], make_organizer_headers(organizer["id"])), 200
        )
        assert current["status"] == "DRAFT"


class TestSegmentWindowConflict:
    def _three_applications(self, api):
        """One UNDER_REVIEW application X plus adjacent Y and overlapping Z drafts."""
        ctx = setup_under_review_application(
            application_overrides={
                "event_start_at": "2026-06-20T14:00:00Z",
                "event_end_at": "2026-06-20T22:00:00Z",
            }
        )
        petition, organizer = ctx["petition"], ctx["organizer"]
        app_y = create_application_record(
            petition, organizer,
            event_start_at="2026-06-20T22:00:00Z", event_end_at="2026-06-21T02:00:00Z",
            expected_attendance=30,
        )
        app_z = create_application_record(
            petition, organizer,
            event_start_at="2026-06-20T21:30:00Z", event_end_at="2026-06-20T23:30:00Z",
            expected_attendance=30,
        )
        ctx["app_y"] = app_y
        ctx["app_z"] = app_z
        return ctx

    def test_adjacent_window_allowed(self, api):
        """PRD §3.3: "Mere adjacency is not a conflict: an event starting exactly when
        another ends (or ending exactly when another starts) passes."

        Design: Difficulty/resource_temporal_overlap/segment_half_open_adjacency_allowed
        """
        ctx = self._three_applications(api)
        organizer = ctx["organizer"]
        submitted = submit_application_record(ctx["app_y"], organizer)
        assert submitted["status"] == "UNDER_REVIEW", (
            "Y starting exactly at X's event_end_at is adjacent, not a conflict"
        )

    def test_true_overlap_rejected(self, api):
        """PRD §3.3: "the new application conflicts with an existing one on the same segment
        when that application's `status` is `UNDER_REVIEW`, `SUSPENDED`, `APPROVED`, or
        `ISSUED` and the windows genuinely overlap — the existing event starts before the
        new one ends and the new one starts before the existing one ends."
        PRD §3.3: "A conflict is rejected with `ERR_SEGMENT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/segment_half_open_adjacency_allowed
        """
        ctx = self._three_applications(api)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        submit_application_record(ctx["app_y"], organizer)
        res = api.submit_permit_application(ctx["app_z"]["id"], headers)
        validate_error(res, "ERR_SEGMENT_WINDOW_CONFLICT")
        current = validate_success(api.get_permit_application(ctx["app_z"]["id"], headers), 200)
        assert current["status"] == "DRAFT"


class TestApplicationDraftingCornerClaims:
    def test_event_window_shape_invalid(self, api):
        """PRD §3.3: "the closure may cross midnight, but the window must be strictly longer
        than zero and no longer than 12 hours, violations surfacing as
        `ERR_EVENT_WINDOW_INVALID`".

        Design: Corner/validations/event_window_invalid_returns_400
        """
        ctx = setup_petition(outcome="collecting")
        petition, organizer = ctx["petition"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        # End before start.
        res = api.create_permit_application(
            {
                "petition_id": petition["id"],
                "event_start_at": "2026-06-20T22:00:00Z",
                "event_end_at": "2026-06-20T14:00:00Z",
                "expected_attendance": 40,
            },
            headers,
        )
        validate_error(res, "ERR_EVENT_WINDOW_INVALID")
        # Thirteen-hour duration exceeds the 12-hour cap.
        res = api.create_permit_application(
            {
                "petition_id": petition["id"],
                "event_start_at": "2026-06-20T08:00:00Z",
                "event_end_at": "2026-06-20T21:00:00Z",
                "expected_attendance": 40,
            },
            headers,
        )
        validate_error(res, "ERR_EVENT_WINDOW_INVALID")

    def test_pagination_and_status_filter(self, api, permit_officer_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
        10, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter skips
        a number of items from the front of the result set and defaults to 0."
        PRD §3.3: "Permit officers browsing their review queue can filter the application
        list by `status` and `organizer_id`, paged through `limit` and `offset`."

        Design: Corner/endpoints/pagination_and_status_filter
        """
        ctx = setup_petition(outcome="collecting")
        petition, organizer = ctx["petition"], ctx["organizer"]
        for start in ("2026-06-20T14:00:00Z", "2026-06-27T14:00:00Z", "2026-07-04T14:00:00Z"):
            create_application_record(
                petition, organizer,
                event_start_at=start,
                event_end_at=start.replace("T14:00:00Z", "T22:00:00Z"),
            )
        page1, meta1 = validate_paginated(
            api.list_permit_applications(permit_officer_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_permit_applications(
                permit_officer_headers, params={"status": "DRAFT", "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for app in page1 + page2:
            assert_permit_application(app)
            assert app["status"] == "DRAFT"
