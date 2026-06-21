"""Interview temporal overlap: half-open per-application interval, 15-min-buffered per-panelist."""
import pytest
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    TEST_USERS, set_clock,
    setup_approved_req_with_screened_app,
    create_candidate, create_application, screen_application,
    schedule_interview, create_interview_payload,
)


# =========================================================================
# Instance: interview_overlap_per_application_half_open_adjacency_allowed
# =========================================================================

class TestInterviewOverlapPerApplication:
    """Two tests on the unbuffered half-open interval semantics for application-level overlap."""

    def test_overlapping_application_interviews_rejected(self, api,
                                                          recruiter_headers):
        """PRD §3.5: "Across the same `application_id`, no two `SCHEDULED`
        interviews may have overlapping intervals. The interval for an
        interview is half-open at `[scheduled_at, scheduled_at +
        duration_minutes)`, so adjacency where one interview's end equals
        another's start is permitted. A violation is rejected with
        `ERR_INTERVIEW_OVERLAP_APPLICATION`."

        Design: Difficulty/resource_temporal_overlap/interview_overlap_per_application_half_open_adjacency_allowed
        """
        set_clock("2026-12-01T00:00:00Z")
        dept, req, cand, app = setup_approved_req_with_screened_app()
        # I1 10:00–11:00 (60 min).
        schedule_interview(app["id"], panel_user_ids=["emp_panelA"],
                           round_number=1,
                           scheduled_at="2026-12-02T10:00:00Z",
                           duration_minutes=60)
        # I2 10:30–11:30 on same application, disjoint panel — overlap 30 min.
        payload = create_interview_payload(
            app["id"], panel_user_ids=["emp_panelB"],
            round_number=2,
            scheduled_at="2026-12-02T10:30:00Z",
            duration_minutes=60,
        )
        res = api_client.create_interview(payload, recruiter_headers)
        validate_error(res, "ERR_INTERVIEW_OVERLAP_APPLICATION", expected_status=422)

    def test_adjacent_application_interviews_allowed_at_boundary(self, api,
                                                                  recruiter_headers):
        """PRD §3.5: "The interval for an interview is half-open at
        `[scheduled_at, scheduled_at + duration_minutes)`, so adjacency
        where one interview's end equals another's start is permitted."

        Design: Difficulty/resource_temporal_overlap/interview_overlap_per_application_half_open_adjacency_allowed
        """
        set_clock("2026-12-01T00:00:00Z")
        dept, req, cand, app = setup_approved_req_with_screened_app()
        # I1 10:00–11:00.
        schedule_interview(app["id"], panel_user_ids=["emp_adjA"],
                           round_number=1,
                           scheduled_at="2026-12-03T10:00:00Z",
                           duration_minutes=60)
        # I2 11:00–12:00 (adjacent end==start, half-open interval allows it). Different
        # panel to keep the panelist-level rule out of scope.
        payload = create_interview_payload(
            app["id"], panel_user_ids=["emp_adjB"],
            round_number=2,
            scheduled_at="2026-12-03T11:00:00Z",
            duration_minutes=60,
        )
        res = api_client.create_interview(payload, recruiter_headers)
        intv2 = validate_success(res, 201)
        assert intv2["status"] == "SCHEDULED"


# =========================================================================
# Instance: interview_overlap_per_panelist_15min_buffered_interval
# =========================================================================

class TestInterviewOverlapPerPanelist:
    """Two tests on the 15-min buffered interval for panelist-level overlap."""

    def test_buffered_overlap_across_applications_for_shared_panelist_rejected(
            self, api, recruiter_headers):
        """PRD §3.5: "For each panelist appearing on the proposed panel, no
        other `SCHEDULED` interview containing that panelist may have an
        overlapping buffered interval. The buffered interval is
        `[scheduled_at - 15 minutes, scheduled_at + duration_minutes + 15
        minutes)`, applying a 15-minute travel buffer on both ends and
        remaining half-open at the upper end. Adjacency at the buffered
        boundary is permitted. A violation is rejected with
        `ERR_INTERVIEW_OVERLAP_PANELIST`."

        Design: Difficulty/resource_temporal_overlap/interview_overlap_per_panelist_15min_buffered_interval
        """
        set_clock("2026-12-10T00:00:00Z")
        dept, req, c1, app1 = setup_approved_req_with_screened_app(
            req_overrides={"openings": 2, "base_salary_max_cents": 15_000_000},
        )
        # Second screened application sharing the requisition (so we can reuse panel).
        c2 = create_candidate(full_name="Pnl Cand 2", email="pnl2_x@example.com")
        app2 = create_application(c2["id"], req["id"])
        screen_application(app2["id"])

        # I1 on app1 at 10:00–11:00; buffered [09:45, 11:15).
        schedule_interview(app1["id"], panel_user_ids=["emp_panelX"],
                           round_number=1,
                           scheduled_at="2026-12-11T10:00:00Z",
                           duration_minutes=60)
        # I2 on app2 at 11:05–12:05; buffered [10:50, 12:20). Buffered intervals overlap
        # [10:50, 11:15) → 25 minutes of buffered overlap.
        payload = create_interview_payload(
            app2["id"], panel_user_ids=["emp_panelX"],
            round_number=1,
            scheduled_at="2026-12-11T11:05:00Z",
            duration_minutes=60,
        )
        res = api_client.create_interview(payload, recruiter_headers)
        validate_error(res, "ERR_INTERVIEW_OVERLAP_PANELIST", expected_status=422)

    def test_buffered_adjacency_at_exact_boundary_allowed(self, api,
                                                           recruiter_headers):
        """PRD §3.5: "Adjacency at the buffered boundary is permitted."

        Two interviews sharing a panelist where the second starts exactly
        15 minutes after the first ends → buffered upper of I1 is
        I1.end + 15 = I2.start, so the buffered intervals touch at the
        upper boundary but do not overlap (half-open at the upper end).

        Design: Difficulty/resource_temporal_overlap/interview_overlap_per_panelist_15min_buffered_interval
        """
        set_clock("2026-12-20T00:00:00Z")
        dept, req, c1, app1 = setup_approved_req_with_screened_app(
            req_overrides={"openings": 2, "base_salary_max_cents": 15_000_000},
        )
        c2 = create_candidate(full_name="Adj Cand 2", email="adj2_x@example.com")
        app2 = create_application(c2["id"], req["id"])
        screen_application(app2["id"])

        # I1 10:00–11:00 → buffered [09:45, 11:15).
        schedule_interview(app1["id"], panel_user_ids=["emp_panelY"],
                           round_number=1,
                           scheduled_at="2026-12-21T10:00:00Z",
                           duration_minutes=60)
        # I2 at 11:30–12:30 → buffered [11:15, 12:45). I2.buffered_start == I1.buffered_end
        # (exact adjacency at the boundary).
        payload = create_interview_payload(
            app2["id"], panel_user_ids=["emp_panelY"],
            round_number=1,
            scheduled_at="2026-12-21T11:30:00Z",
            duration_minutes=60,
        )
        res = api_client.create_interview(payload, recruiter_headers)
        intv2 = validate_success(res, 201)
        assert intv2["status"] == "SCHEDULED"
