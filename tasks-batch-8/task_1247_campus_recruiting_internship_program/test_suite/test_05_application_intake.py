"""Application intake: uniqueness, caps, application window, screening gate."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_recruiter_headers, make_candidate_headers,
    create_candidate_payload, create_application_payload,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


class TestCandidateRegistration:
    def test_duplicate_email_rejected(self, api, anonymous_headers):
        """PRD §3.3: "The email is globally unique across the platform,
        compared case-insensitively; a duplicate registration is rejected with
        `ERR_DUPLICATE_EMAIL` (HTTP 409)."

        Design: Corner/validations/duplicate_email_rejected
        """
        resp = api.create_candidate(create_candidate_payload(), anonymous_headers)
        assert resp.status_code == 201
        resp = api.create_candidate(
            create_candidate_payload(
                email="A@X.com", full_name="Other Person",
                expected_graduation_date="2028-05-15T00:00:00Z",
            ),
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestApplicationSubmissionGuards:
    def test_duplicate_application_rejected(self, api):
        """PRD §3.3: "then the candidate must not already hold an application
        in this season (`ERR_DUPLICATE_APPLICATION`, HTTP 409)".

        Design: Corner/validations/duplicate_application_rejected
        """
        ctx = fx.setup_open_season_with_application()
        resp = api.create_application(
            ctx.season["id"],
            create_application_payload(
                candidate_id=ctx.candidate["id"],
                school_target_id=ctx.school["id"],
                relocation_distance_miles=200,
            ),
            make_candidate_headers(ctx.candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)

    def test_school_cap_allows_submission_below_cap(self, api):
        """PRD §3.3: "then the school's cap is checked — counting every
        application of that school in this season whose status is anything
        other than `SCREENED_OUT` or `WITHDRAWN`, a count already equal to
        `application_cap` rejects the submission with
        `ERR_SCHOOL_APPLICATION_CAP_REACHED` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/school_cap_boundary_at_cap
        """
        season = fx.create_season()
        school = fx.create_school(season["id"], application_cap=2)
        fx.advance_season(season["id"])  # OPEN
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        app1 = fx.submit_application(season["id"], c1["id"], school["id"])
        assert app1["status"] == "SUBMITTED"  # count 0 < cap 2
        app2 = fx.submit_application(season["id"], c2["id"], school["id"])
        assert app2["status"] == "SUBMITTED"  # count 1 < cap 2

    def test_school_cap_rejects_at_equality(self, api):
        """PRD §3.3: "a count already equal to `application_cap` rejects the
        submission with `ERR_SCHOOL_APPLICATION_CAP_REACHED` (HTTP 422), so
        screened-out and withdrawn applications free their place but rejected,
        expired, and accepted ones keep counting".

        Design: Difficulty/boundary_precision_check/school_cap_boundary_at_cap
        """
        season = fx.create_season()
        school = fx.create_school(season["id"], application_cap=2)
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        c3 = fx.create_candidate(email="c@x.com", full_name="Candidate C")
        fx.submit_application(season["id"], c1["id"], school["id"])
        fx.submit_application(season["id"], c2["id"], school["id"])
        resp = api.create_application(
            season["id"],
            create_application_payload(
                candidate_id=c3["id"], school_target_id=school["id"],
            ),
            make_candidate_headers(c3["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_APPLICATION_CAP_REACHED)


class TestApplicationWindow:
    def test_application_window_close_instant_inclusive(self, api):
        """PRD §3.3: "then the logical clock must read within the application
        window — at or after `application_open_at` and at or before
        `application_close_at`, both bounds inclusive — failing with
        `ERR_APPLICATION_WINDOW_CLOSED` (HTTP 422) outside it".

        Design: Corner/validations/application_window_inclusive_boundaries
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        fx.set_clock("2026-05-20T00:00:00Z")  # exactly application_close_at
        resp = api.create_application(
            season["id"],
            create_application_payload(
                candidate_id=c1["id"], school_target_id=school["id"],
            ),
            make_candidate_headers(c1["id"]),
        )
        assert validate_success(resp, expected_status=201)["status"] == "SUBMITTED"

    def test_application_window_one_second_past_close_rejected(self, api):
        """PRD §3.3: "then the logical clock must read within the application
        window — at or after `application_open_at` and at or before
        `application_close_at`, both bounds inclusive — failing with
        `ERR_APPLICATION_WINDOW_CLOSED` (HTTP 422) outside it".

        Design: Corner/validations/application_window_inclusive_boundaries
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        fx.set_clock("2026-05-20T00:00:01Z")  # one second past close
        resp = api.create_application(
            season["id"],
            create_application_payload(
                candidate_id=c2["id"], school_target_id=school["id"],
            ),
            make_candidate_headers(c2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED)


class TestScreeningPostureGate:
    def test_screen_requires_selection_posture(self, api):
        """PRD §2.4: "Screening decisions, interview-day creation, day
        locking, slot booking, slot cancellation, no-show marking, and
        interview-evaluation submission and revision require `SELECTION`."

        Design: Difficulty/cross_entity_state_dependency/screen_requires_selection_posture
        """
        ctx = fx.setup_open_season_with_application()
        # Season is still OPEN (never advanced to SELECTION).
        resp = api.screen_application(ctx.application["id"], "SHORTLIST", RECRUITER)
        validate_error(resp, ApiErrorId.ERR_SEASON_POSTURE_FORBIDDEN)

    def test_screen_rejected_posture_leaves_application_untouched(self, api):
        """PRD §3.4: "A `Recruiter` screens a `SUBMITTED` application by
        supplying a `decision` of `SHORTLIST` or `REJECT`; screening an
        application in any other status is rejected with
        `ERR_APPLICATION_STATE_FORBIDDEN` (HTTP 409), and the posture check
        fires before the status check." — under the wrong posture the
        application stays `SUBMITTED` and no final score is stored.

        Design: Difficulty/cross_entity_state_dependency/screen_requires_selection_posture
        """
        ctx = fx.setup_open_season_with_application()
        resp = api.screen_application(ctx.application["id"], "SHORTLIST", RECRUITER)
        validate_error(resp, ApiErrorId.ERR_SEASON_POSTURE_FORBIDDEN)
        app = validate_success(api.get_application(ctx.application["id"], RECRUITER))
        assert app["status"] == "SUBMITTED"
        assert app["screening_score_final"] is None


class TestApplicationWithdraw:
    def test_application_terminal_lockdown_withdraw(self, api):
        """PRD §3.4: "Withdrawal requires `X-User-ID` to equal the
        application's `candidate_id` (`ERR_FORBIDDEN` otherwise) and is
        available from `SUBMITTED`, `SHORTLISTED`, `INTERVIEW_SCHEDULED`,
        `DECISION_PENDING`, and `OFFER_PENDING`; from the terminal statuses
        and from `ACCEPTED` it is rejected with
        `ERR_APPLICATION_STATE_FORBIDDEN`."

        Design: Corner/state_machines/application_terminal_lockdown_withdraw
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        cand = fx.create_candidate()
        app = fx.submit_application(season["id"], cand["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        resp = api.screen_application(app["id"], "REJECT", RECRUITER)
        assert resp.status_code == 200  # SCREENED_OUT (terminal)
        resp = api.withdraw_application(
            app["id"], make_candidate_headers(cand["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_STATE_FORBIDDEN)

    def test_withdraw_interview_stage_cascades_slots(self, api):
        """PRD §3.4: "Withdrawing from `INTERVIEW_SCHEDULED` runs an ordered
        cascade: each of the application's `BOOKED` interview slots is first
        moved to `CANCELLED`, decrementing the owning day's `booked_count` by
        one apiece, with the auto-flip rule of §3.5 suppressed for the
        duration of the cascade; the application's status is set to
        `WITHDRAWN` only after the cancellations complete."

        Design: Corner/state_machines/withdraw_interview_stage_cascades_slots
        """
        ctx = fx.setup_interview_scheduled()
        resp = api.withdraw_application(
            ctx.application["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        assert validate_success(resp)["status"] == "WITHDRAWN"
        slot = validate_success(api.get_interview_slot(ctx.slot["id"], RECRUITER))
        assert slot["status"] == "CANCELLED"
        day = validate_success(api.get_interview_day(ctx.day["id"], RECRUITER))
        assert day["booked_count"] == 0

    def test_withdraw_offer_pending_declines_offer(self, api):
        """PRD §3.4: "Withdrawing from `OFFER_PENDING` runs the longest
        cascade: the `EXTENDED` offer is first moved to `DECLINED` with its
        usual application-flip side effect suppressed; then each `BOOKED`
        slot is cancelled with its `booked_count` decrement, again with
        auto-flip suppressed; and the application is set `WITHDRAWN` last."

        Design: Corner/state_machines/withdraw_offer_pending_declines_offer
        """
        ctx = fx.setup_extended_offer()
        resp = api.withdraw_application(
            ctx.application["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        assert validate_success(resp)["status"] == "WITHDRAWN"
        offer = validate_success(api.get_offer(ctx.offer["id"], RECRUITER))
        assert offer["status"] == "DECLINED"


class TestApplicationListing:
    def test_applications_filtered_by_status(self, api):
        """PRD §2.3: "a season's applications filter by `school_target_id`
        and `status`".

        Design: Corner/endpoints/applications_filtered_by_status
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        app1 = fx.submit_application(season["id"], c1["id"], school["id"])
        app2 = fx.submit_application(season["id"], c2["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        r = api.screen_application(app1["id"], "SHORTLIST", RECRUITER)
        assert r.status_code == 200
        r = api.screen_application(app2["id"], "REJECT", RECRUITER)
        assert r.status_code == 200
        resp = api.list_season_applications(
            season["id"], RECRUITER, params={"status": "SHORTLISTED"},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["id"] == app1["id"]
        resp = api.list_season_applications(
            season["id"], RECRUITER, params={"status": "SCREENED_OUT"},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["id"] == app2["id"]
