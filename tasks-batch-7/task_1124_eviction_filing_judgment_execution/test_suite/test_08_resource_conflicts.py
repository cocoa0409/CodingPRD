"""Resource conflicts: courtroom half-open intervals and deputy day capacity
(PRD 3.5, 3.7)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    create_hearing_payload,
    make_deputy_headers,
    request_and_issue_writ,
    schedule_hearing,
    schedule_lockout,
    setup_case_service_complete,
    setup_judgment_final,
    setup_two_cases_notice_expired,
    serve_all_defendants,
    prepare_package,
    review_package,
    validate_error,
    validate_success,
)
from test_helpers import api_client


def _service_complete_pair():
    """Two CA cases (same landlord) both SERVICE_COMPLETE with
    service_completed_at 2026-06-01T10:00:00Z."""
    ctx_a, ctx_b = setup_two_cases_notice_expired("CA")
    for ctx, names in ((ctx_a, ["Dee A"]), (ctx_b, ["Dee B"])):
        pkg = prepare_package(ctx, defendant_names=names)
        ctx["package"] = review_package(pkg, "ACCEPT", CLERK_A)
        ctx["case"] = ctx["case"]
        serve_all_defendants(ctx)
    return ctx_a, ctx_b


class TestCourtroomHalfOpenOverlap:
    """Depth instance: half-open [start, end) interval intersection per
    courtroom; touching endpoints do NOT collide."""

    def test_interior_overlap_rejected_touching_allowed(self, api):
        """PRD 3.5: "the half-open interval from start_at up to but not
        including end_at must not intersect any other SCHEDULED hearing in
        the same courtroom, though two hearings whose windows merely touch —
        one ending exactly when the other begins — do not conflict
        (ERR_COURTROOM_OVERLAP, HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/courtroom_half_open_overlap
        """
        ctx_a, ctx_b = _service_complete_pair()
        # Case A holds CR-1 10:00-11:00 on 2026-06-15.
        hearing_a = schedule_hearing(
            ctx_a, courtroom="CR-1",
            start_at="2026-06-15T10:00:00Z", end_at="2026-06-15T11:00:00Z")
        assert hearing_a["status"] == "SCHEDULED"

        # Case B: 10:30-11:30 intersects [10:00, 11:00) -> conflict.
        resp = api.create_hearing(
            ctx_b["case"]["id"],
            create_hearing_payload(courtroom="CR-1",
                                   start_at="2026-06-15T10:30:00Z",
                                   end_at="2026-06-15T11:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_COURTROOM_OVERLAP, 409)

        # 11:00-12:00 merely touches [10:00, 11:00) -> allowed.
        ok = api.create_hearing(
            ctx_b["case"]["id"],
            create_hearing_payload(courtroom="CR-1",
                                   start_at="2026-06-15T11:00:00Z",
                                   end_at="2026-06-15T12:00:00Z"),
            CLERK_A,
        )
        assert validate_success(ok, 201)["status"] == "SCHEDULED"

    def test_overlap_is_per_courtroom(self, api):
        """PRD 3.5: "the half-open interval from start_at up to but not
        including end_at must not intersect any other SCHEDULED hearing in
        the same courtroom" — a different courtroom at the same instant does
        not intersect 'the same courtroom'.

        Design: Difficulty/resource_temporal_overlap/courtroom_half_open_overlap
        """
        ctx_a, ctx_b = _service_complete_pair()
        hearing_a = schedule_hearing(
            ctx_a, courtroom="CR-1",
            start_at="2026-06-15T10:00:00Z", end_at="2026-06-15T11:00:00Z")
        assert hearing_a["status"] == "SCHEDULED"

        # Identical window in CR-2 is fine.
        ok = api.create_hearing(
            ctx_b["case"]["id"],
            create_hearing_payload(courtroom="CR-2",
                                   start_at="2026-06-15T10:00:00Z",
                                   end_at="2026-06-15T11:00:00Z"),
            CLERK_A,
        )
        assert validate_success(ok, 201)["status"] == "SCHEDULED"


class TestDeputyDayCapacityAggregate:
    """Depth instance: at most 3 SCHEDULED writs per deputy per UTC calendar
    date of window_start."""

    def _four_issued_writs(self, api):
        ctxs = []
        for _ in range(4):
            ctxs.append(setup_judgment_final("CA"))
        for ctx in ctxs:
            ctx["writ"] = request_and_issue_writ(ctx)
        return ctxs

    def test_third_booking_succeeds_fourth_fails(self, api):
        """PRD 3.7: "scheduling is rejected with ERR_DEPUTY_DAY_CAPACITY
        (HTTP 409) when the assigned deputy already has 3 SCHEDULED writs on
        the UTC calendar date of window_start — so the third booking on a day
        succeeds and the fourth fails."

        Design: Difficulty/resource_temporal_overlap/deputy_day_capacity_aggregate
        """
        ctxs = self._four_issued_writs(api)
        statuses = []
        for ctx in ctxs[:3]:
            resp = api.schedule_lockout(
                ctx["writ"]["id"],
                {"deputy_id": "dep-x",
                 "window_start": "2026-06-26T09:00:00Z",
                 "window_end": "2026-06-26T10:00:00Z"},
                make_deputy_headers("dep-x"),
            )
            statuses.append(validate_success(resp, 200)["status"])
        assert statuses == ["SCHEDULED", "SCHEDULED", "SCHEDULED"]

        resp4 = api.schedule_lockout(
            ctxs[3]["writ"]["id"],
            {"deputy_id": "dep-x",
             "window_start": "2026-06-26T09:00:00Z",
             "window_end": "2026-06-26T10:00:00Z"},
            make_deputy_headers("dep-x"),
        )
        validate_error(resp4, ApiErrorId.ERR_DEPUTY_DAY_CAPACITY, 409)

    def test_capacity_is_per_calendar_date(self, api):
        """PRD 3.7: "the assigned deputy already has 3 SCHEDULED writs on the
        UTC calendar date of window_start" — a booking on a DIFFERENT date
        starts a fresh count.

        Design: Difficulty/resource_temporal_overlap/deputy_day_capacity_aggregate
        """
        ctxs = self._four_issued_writs(api)
        for ctx in ctxs[:3]:
            validate_success(api.schedule_lockout(
                ctx["writ"]["id"],
                {"deputy_id": "dep-x",
                 "window_start": "2026-06-26T09:00:00Z",
                 "window_end": "2026-06-26T10:00:00Z"},
                make_deputy_headers("dep-x")), 200)
        # Same deputy, next calendar date: admitted.
        ok = api.schedule_lockout(
            ctxs[3]["writ"]["id"],
            {"deputy_id": "dep-x",
             "window_start": "2026-06-27T09:00:00Z",
             "window_end": "2026-06-27T10:00:00Z"},
            make_deputy_headers("dep-x"),
        )
        assert validate_success(ok, 200)["status"] == "SCHEDULED"
