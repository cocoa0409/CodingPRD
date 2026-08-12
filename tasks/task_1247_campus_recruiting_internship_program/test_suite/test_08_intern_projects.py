"""Intern projects, assignments, intern evaluations, return-offer decisions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_recruiter_headers, make_mentor_headers, make_evaluator_headers,
    make_candidate_headers, create_interview_day_payload,
    create_interview_slot_payload,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


class TestAssignmentGuards:
    def test_assign_requires_accepted_application(self, api):
        """PRD §3.7: "Its guards fire in order: the posture gate; the
        application must be `ACCEPTED` (`ERR_APPLICATION_STATE_FORBIDDEN`)".

        Design: Corner/validations/assign_requires_accepted_application
        """
        # DECISION_PENDING application, season advanced twice with no offer:
        # SELECTION -> OFFER_PERIOD -> INTERN_ACTIVE leaves it DECISION_PENDING.
        ctx = fx.setup_decision_pending()
        fx.advance_season(ctx.season["id"])  # OFFER_PERIOD
        fx.advance_season(ctx.season["id"])  # INTERN_ACTIVE
        mentor = fx.create_employee(
            ctx.season["id"], full_name="Moe", email="moe@co.com",
        )
        proj = validate_success(api.create_intern_project(
            ctx.season["id"], {"title": "Project P", "capacity": 2}, RECRUITER,
        ), expected_status=201)
        resp = api.create_project_assignment(
            proj["id"],
            {"application_id": ctx.application["id"],
             "mentor_id": mentor["id"]},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_STATE_FORBIDDEN)

    def test_closed_project_blocks_assignment(self, api):
        """PRD §3.7: "the project must still be `OPEN`
        (`ERR_PROJECT_STATE_FORBIDDEN`, HTTP 409)".

        Design: Corner/validations/closed_project_blocks_assignment
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])  # INTERN_ACTIVE
        mentor = fx.create_employee(
            ctx.season["id"], full_name="Moe", email="moe@co.com",
        )
        proj = validate_success(api.create_intern_project(
            ctx.season["id"], {"title": "Project P", "capacity": 2}, RECRUITER,
        ), expected_status=201)
        resp = api.close_intern_project(proj["id"], RECRUITER)
        assert resp.status_code == 200
        resp = api.create_project_assignment(
            proj["id"],
            {"application_id": ctx.application["id"],
             "mentor_id": mentor["id"]},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_STATE_FORBIDDEN)

    def test_capability_missing_mentor(self, api):
        """PRD §3.7: "then the mentor's `can_mentor` capability
        (`ERR_CAPABILITY_MISSING`)".

        Design: Corner/validations/capability_missing_mentor
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])
        mentor = fx.create_employee(
            ctx.season["id"], full_name="Moe", email="moe@co.com",
            can_mentor=False,
        )
        proj = validate_success(api.create_intern_project(
            ctx.season["id"], {"title": "Project P", "capacity": 2}, RECRUITER,
        ), expected_status=201)
        resp = api.create_project_assignment(
            proj["id"],
            {"application_id": ctx.application["id"],
             "mentor_id": mentor["id"]},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_CAPABILITY_MISSING)

    def test_sod_mentor_previously_evaluated(self, api):
        """PRD §3.7: "then segregation of duties — the proposed mentor must
        not have submitted an evaluation on any interview slot of that
        application, failing with `ERR_MENTOR_CONFLICT_OF_INTEREST`
        (HTTP 422)".

        Design: Corner/validations/sod_mentor_previously_evaluated
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])
        proj = validate_success(api.create_intern_project(
            ctx.season["id"], {"title": "Project P", "capacity": 2}, RECRUITER,
        ), expected_status=201)
        # ctx.evaluator submitted the application's interview evaluation.
        resp = api.create_project_assignment(
            proj["id"],
            {"application_id": ctx.application["id"],
             "mentor_id": ctx.evaluator["id"]},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_MENTOR_CONFLICT_OF_INTEREST)

    def test_assignment_pool_limits(self, api):
        """PRD §3.7: "then the two capacity checks, project first and mentor
        second: a project whose `assigned_count` has reached its `capacity`
        rejects with `ERR_PROJECT_AT_CAPACITY` (HTTP 422), and a mentor whose
        `assigned_intern_count` has reached their `max_interns` rejects with
        `ERR_MENTOR_AT_CAPACITY` (HTTP 422); and finally uniqueness — an
        application may hold at most one project assignment, so a second
        attempt fails with `ERR_ASSIGNMENT_EXISTS` (HTTP 409)".

        Design: Corner/validations/assignment_pool_limits
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
        for app in (app1, app2):
            r = api.screen_application(app["id"], "SHORTLIST", RECRUITER)
            assert r.status_code == 200
        ev = fx.create_employee(season["id"])
        men1 = fx.create_employee(
            season["id"], full_name="Moe", email="moe@co.com", max_interns=1,
        )
        men2 = fx.create_employee(
            season["id"], full_name="Nora", email="nora@co.com", max_interns=2,
        )
        day = validate_success(api.create_interview_day(
            season["id"], create_interview_day_payload(), RECRUITER,
        ), expected_status=201)
        for app, start, end in (
            (app1, "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z"),
            (app2, "2026-06-08T11:15:00Z", "2026-06-08T12:00:00Z"),
        ):
            r = api.book_interview_slot(
                day["id"],
                create_interview_slot_payload(
                    application_id=app["id"], evaluator_id=ev["id"],
                    start_at=start, end_at=end,
                ),
                RECRUITER,
            )
            slot = validate_success(r, expected_status=201)
            r = api.submit_evaluation(
                slot["id"], {"score": 4, "recommendation": "HIRE"},
                make_evaluator_headers(ev["id"]),
            )
            assert r.status_code == 201
        fx.advance_season(season["id"])  # OFFER_PERIOD
        offers = {}
        for key, app in (("one", app1), ("two", app2)):
            r = api.create_offer(
                app["id"], {"weekly_rate_cents": 150000, "duration_weeks": 12},
                RECRUITER,
            )
            offers[key] = validate_success(r, expected_status=201)
        fx.set_clock("2026-07-06T10:00:00Z")
        for offer in offers.values():
            r = api.extend_offer(offer["id"], RECRUITER)
            assert r.status_code == 200
        for key, cand in (("one", c1), ("two", c2)):
            r = api.accept_offer(
                offers[key]["id"], make_candidate_headers(cand["id"]),
            )
            assert r.status_code == 200
        fx.advance_season(season["id"])  # INTERN_ACTIVE
        p1 = validate_success(api.create_intern_project(
            season["id"], {"title": "P1", "capacity": 1}, RECRUITER,
        ), expected_status=201)
        p2 = validate_success(api.create_intern_project(
            season["id"], {"title": "P2", "capacity": 5}, RECRUITER,
        ), expected_status=201)
        r = api.create_project_assignment(
            p1["id"], {"application_id": app1["id"], "mentor_id": men1["id"]},
            RECRUITER,
        )
        assert r.status_code == 201  # P1 seat 0 < 1, Moe load 0 < 1
        # P1 full now.
        resp = api.create_project_assignment(
            p1["id"], {"application_id": app2["id"], "mentor_id": men2["id"]},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_AT_CAPACITY)
        # Moe at capacity.
        resp = api.create_project_assignment(
            p2["id"], {"application_id": app2["id"], "mentor_id": men1["id"]},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_MENTOR_AT_CAPACITY)
        # Nora can take app2 on P2.
        r = api.create_project_assignment(
            p2["id"], {"application_id": app2["id"], "mentor_id": men2["id"]},
            RECRUITER,
        )
        assert r.status_code == 201
        # app1 already assigned.
        resp = api.create_project_assignment(
            p2["id"], {"application_id": app1["id"], "mentor_id": men2["id"]},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_EXISTS)


class TestInternEvaluations:
    def test_final_before_mid_and_duplicate_mid_rejected(self, api):
        """PRD §3.7: "The two types are ordered: submitting the `FINAL`
        evaluation requires a `MID` evaluation to already exist on the same
        assignment, failing with `ERR_MID_EVALUATION_REQUIRED` (HTTP 422)
        otherwise, while the `MID` itself has no such prerequisite." and "At
        most one evaluation of each type exists per assignment — a duplicate
        type is rejected with `ERR_EVALUATION_ALREADY_SUBMITTED` (HTTP 409)".

        Design: Corner/validations/final_before_mid_and_duplicate_mid_rejected
        """
        ctx = fx.setup_intern_active_with_assignment()
        resp = api.submit_intern_evaluation(
            ctx.assignment["id"],
            {"eval_type": "FINAL", "rating": 5, "would_rehire": True},
            make_mentor_headers(ctx.mentor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MID_EVALUATION_REQUIRED)
        resp = api.submit_intern_evaluation(
            ctx.assignment["id"],
            {"eval_type": "MID", "rating": 4, "would_rehire": True},
            make_mentor_headers(ctx.mentor["id"]),
        )
        assert resp.status_code == 201
        resp = api.submit_intern_evaluation(
            ctx.assignment["id"],
            {"eval_type": "MID", "rating": 2, "would_rehire": False},
            make_mentor_headers(ctx.mentor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATION_ALREADY_SUBMITTED)

    def test_intern_evaluation_immutability(self, api):
        """PRD §2.6: "The **InternEvaluation** resource is the single
        exception: it carries only `id` and `created_at`; both `updated_at`
        and `version` are absent from it."

        Design: Corner/entities/intern_evaluation_immutability
        """
        ctx = fx.setup_intern_active_with_assignment()
        resp = api.submit_intern_evaluation(
            ctx.assignment["id"],
            {"eval_type": "MID", "rating": 4, "would_rehire": True},
            make_mentor_headers(ctx.mentor["id"]),
        )
        evaluation = validate_success(resp, expected_status=201)
        fetched = validate_success(
            api.get_intern_evaluation(evaluation["id"], RECRUITER)
        )
        assert "id" in fetched and "created_at" in fetched
        assert "version" not in fetched
        assert "updated_at" not in fetched


class TestReturnOfferDecision:
    def test_return_offer_extended_at_threshold(self, api):
        """PRD §3.7: "The assignment's `return_offer_decision` becomes
        `EXTENDED` when that weighted score is at least 4.00 and the final
        evaluation's `would_rehire` is `true`; otherwise it becomes
        `NO_OFFER`. Whenever the decision lands on `EXTENDED`, the season's
        `return_offers_extended_count` increments by one."

        Design: Corner/calculations/return_offer_extended_at_threshold
        """
        ctx = fx.setup_assignment_with_evals(
            mid_rating=4, final_rating=4, mid_rehire=True, final_rehire=True,
        )
        assignment = validate_success(
            api.get_project_assignment(ctx.assignment["id"], RECRUITER)
        )
        assert assignment["return_offer_decision"] == "EXTENDED"
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["return_offers_extended_count"] == 1

    def test_return_offer_no_offer_below_threshold(self, api):
        """PRD §3.7: "The weighted score combines the assignment's `MID`
        rating counted once with the just-submitted `FINAL` rating counted
        twice, divided by three, and the result is rounded half-up to two
        decimal places. The assignment's `return_offer_decision` becomes
        `EXTENDED` when that weighted score is at least 4.00 and the final
        evaluation's `would_rehire` is `true`; otherwise it becomes
        `NO_OFFER`."

        Design: Corner/calculations/return_offer_no_offer_below_threshold
        """
        ctx = fx.setup_assignment_with_evals(
            mid_rating=3, final_rating=3, mid_rehire=True, final_rehire=True,
            evaluation_overrides={"score": 3, "recommendation": "LEAN_NO"},
        )
        assignment = validate_success(
            api.get_project_assignment(ctx.assignment["id"], RECRUITER)
        )
        assert assignment["return_offer_decision"] == "NO_OFFER"
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["return_offers_extended_count"] == 0

    def test_return_offer_no_offer_without_rehire(self, api):
        """PRD §3.7: "The assignment's `return_offer_decision` becomes
        `EXTENDED` when that weighted score is at least 4.00 and the final
        evaluation's `would_rehire` is `true`; otherwise it becomes
        `NO_OFFER`."

        Design: Corner/calculations/return_offer_no_offer_without_rehire
        """
        ctx = fx.setup_assignment_with_evals(
            mid_rating=5, final_rating=5,
            mid_rehire=False, final_rehire=False,
            evaluation_overrides={"score": 5, "recommendation": "STRONG_HIRE"},
        )
        assignment = validate_success(
            api.get_project_assignment(ctx.assignment["id"], RECRUITER)
        )
        assert assignment["return_offer_decision"] == "NO_OFFER"


class TestAssignmentCompletion:
    def test_complete_before_final_rejected(self, api):
        """PRD §3.7: "Completing the internship requires a final intern
        evaluation to already exist for the assignment
        (`ERR_FINAL_EVALUATION_REQUIRED`, HTTP 422, otherwise)".

        Design: Corner/validations/complete_before_final_rejected
        """
        ctx = fx.setup_intern_active_with_assignment()
        fx.submit_intern_eval(ctx.assignment["id"], ctx.mentor["id"], "MID", 4)
        resp = api.complete_project_assignment(ctx.assignment["id"], RECRUITER)
        validate_error(resp, ApiErrorId.ERR_FINAL_EVALUATION_REQUIRED)

    def test_candidate_is_alumnus_computed(self, api):
        """PRD §3.3: "The record carries an `is_alumnus` flag that begins
        `false` and later turns `true` when the candidate completes an
        internship assignment (§3.7), marking the alumni pipeline."

        Design: Corner/entities/candidate_is_alumnus_computed
        """
        ctx = fx.setup_assignment_with_evals()
        before = validate_success(api.get_candidate(ctx.candidate["id"], RECRUITER))
        assert before["is_alumnus"] is False
        resp = api.complete_project_assignment(ctx.assignment["id"], RECRUITER)
        assert resp.status_code == 200
        after = validate_success(api.get_candidate(ctx.candidate["id"], RECRUITER))
        assert after["is_alumnus"] is True


class TestReturnOfferOutcome:
    def test_record_outcome_on_no_offer_rejected(self, api):
        """PRD §3.7: "Recording is permitted while the assignment is `ACTIVE`
        or `COMPLETED`, but only when `return_offer_decision` is `EXTENDED`
        and `return_offer_outcome` is still `NONE` — any other combination is
        rejected with `ERR_ASSIGNMENT_STATE_FORBIDDEN`."

        Design: Corner/validations/record_outcome_on_no_offer_rejected
        """
        ctx = fx.setup_assignment_with_evals(
            mid_rating=3, final_rating=3, mid_rehire=True, final_rehire=True,
            evaluation_overrides={"score": 3, "recommendation": "LEAN_NO"},
        )
        resp = api.record_return_offer_outcome(
            ctx.assignment["id"], "ACCEPTED", RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_STATE_FORBIDDEN)

    def test_record_outcome_success_then_duplicate_rejected(self, api):
        """PRD §3.7: "The outcome is written once to `return_offer_outcome`,
        and an `ACCEPTED` outcome increments the season's
        `return_offers_accepted_count` by one." and "Recording is permitted
        while the assignment is `ACTIVE` or `COMPLETED`, but only when
        `return_offer_decision` is `EXTENDED` and `return_offer_outcome` is
        still `NONE` — any other combination is rejected with
        `ERR_ASSIGNMENT_STATE_FORBIDDEN`."

        Design: Corner/validations/record_outcome_success_then_duplicate_rejected
        """
        ctx = fx.setup_assignment_with_evals()
        resp = api.record_return_offer_outcome(
            ctx.assignment["id"], "ACCEPTED", RECRUITER,
        )
        data = validate_success(resp)
        assert data["return_offer_outcome"] == "ACCEPTED"
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["return_offers_accepted_count"] == 1
        resp = api.record_return_offer_outcome(
            ctx.assignment["id"], "DECLINED", RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_STATE_FORBIDDEN)
