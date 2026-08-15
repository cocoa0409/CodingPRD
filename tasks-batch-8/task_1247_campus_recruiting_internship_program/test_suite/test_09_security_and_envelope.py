"""Auth, RBAC denials, entity-backed ownership, envelope and priority rules."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    make_recruiter_headers, make_candidate_headers, make_evaluator_headers,
    make_mentor_headers, make_anonymous_headers,
    create_season_payload, create_candidate_payload,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose
        `X-User-Role` is not one of these declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.create_season(
            create_season_payload(shortlist_score_threshold=50), headers=None,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbacDenials:
    def test_candidate_cannot_screen(self, api):
        """PRD §2.1: "A request whose role is not listed among an endpoint's
        authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)".
        PRD §4: `POST /campus-recruiting/applications/{id}/screen` is
        authorized for Recruiter only.

        Design: Corner/rbac/candidate_cannot_screen
        """
        ctx = fx.setup_open_season_with_application()
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(ctx.season["id"])  # SELECTION
        resp = api.screen_application(
            ctx.application["id"], "SHORTLIST",
            make_candidate_headers(ctx.candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_recruiter_cannot_advance_season(self, api):
        """PRD §3.1: "Advancing it is an explicit, admin-only action that
        moves the season one epoch per call along the chain `DRAFT → OPEN →
        SELECTION → OFFER_PERIOD → INTERN_ACTIVE`".

        Design: Corner/rbac/recruiter_cannot_advance_season
        """
        season = fx.create_season()
        fx.create_school(season["id"])
        resp = api.advance_season(season["id"], RECRUITER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_evaluator_cannot_create_offer(self, api):
        """PRD §4: `POST /campus-recruiting/applications/{id}/offers` is
        authorized for Recruiter only; PRD §2.1: "A request whose role is not
        listed among an endpoint's authorized roles is rejected with
        `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/evaluator_cannot_create_offer
        """
        ctx = fx.setup_offer_period_with_draft_offer()
        resp = api.create_offer(
            ctx.application["id"],
            {"weekly_rate_cents": 150000, "duration_weeks": 12},
            make_evaluator_headers(ctx.evaluator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_mentor_cannot_submit_interview_evaluation(self, api):
        """PRD §2.1: "An evaluator may submit or revise an interview
        evaluation only for a slot whose `evaluator_id` equals `X-User-ID`."
        PRD §4: `POST /campus-recruiting/interview-slots/{id}/evaluations` is
        authorized for Evaluator only; the Mentor role is rejected even when
        `X-User-ID` equals the slot's evaluator.

        Design: Corner/rbac/mentor_cannot_submit_interview_evaluation
        """
        ctx = fx.setup_interview_scheduled()
        resp = api.submit_evaluation(
            ctx.slot["id"], {"score": 4, "recommendation": "HIRE"},
            make_mentor_headers(ctx.evaluator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_anonymous_cannot_list_seasons(self, api):
        """PRD §2.1: "the `Anonymous` role is admitted on exactly one
        operation, candidate self-registration, and nowhere else."

        Design: Corner/rbac/anonymous_cannot_list_seasons
        """
        resp = api.list_seasons(make_anonymous_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestEntityBackedOwnership:
    def test_candidate_cannot_accept_others_offer(self, api):
        """PRD §2.1: "withdrawing an application and accepting or declining
        an offer require `X-User-ID` to equal the underlying application's
        `candidate_id`".

        Design: Corner/rbac/candidate_cannot_accept_others_offer
        """
        ctx = fx.setup_extended_offer()
        other = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        resp = api.accept_offer(
            ctx.offer["id"], make_candidate_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_evaluator_cannot_score_others_slot(self, api):
        """PRD §2.1: "An evaluator may submit or revise an interview
        evaluation only for a slot whose `evaluator_id` equals `X-User-ID`."

        Design: Corner/rbac/evaluator_cannot_score_others_slot
        """
        ctx = fx.setup_interview_scheduled()
        other = fx.create_employee(
            ctx.season["id"], full_name="Olive", email="ol@co.com",
        )
        resp = api.submit_evaluation(
            ctx.slot["id"], {"score": 4, "recommendation": "HIRE"},
            make_evaluator_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_mentor_cannot_evaluate_others_assignment(self, api):
        """PRD §2.1: "A mentor may submit an intern evaluation only for a
        project assignment whose `mentor_id` equals `X-User-ID`".

        Design: Corner/rbac/mentor_cannot_evaluate_others_assignment
        """
        ctx = fx.setup_intern_active_with_assignment()
        other = fx.create_employee(
            ctx.season["id"], full_name="Nora", email="nora@co.com",
        )
        resp = api.submit_intern_evaluation(
            ctx.assignment["id"],
            {"eval_type": "MID", "rating": 4, "would_rehire": True},
            make_mentor_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestEnvelopeAndExistence:
    def test_offer_get_not_found_returns_404(self, api):
        """PRD §2.7: "The first path identifier that does not correspond to
        an existing resource aborts the request with `ERR_NOT_FOUND`
        (HTTP 404)".

        Design: Corner/entities/offer_get_not_found_returns_404
        """
        resp = api.get_offer(NON_EXISTENT_UUID, RECRUITER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_candidate_create_extra_field_input_ignored(self, api, anonymous_headers):
        """PRD §2.6: "`id` (string): a unique, server-minted UUID, with no
        type prefix." and "`version` (integer): a system-managed integer that
        increments by one with every modification of the resource" — the
        client cannot supply either.

        Design: Corner/entities/candidate_create_extra_field_input_ignored
        """
        payload = create_candidate_payload()
        payload["id"] = "11111111-1111-4111-8111-111111111111"
        payload["version"] = 99
        resp = api.create_candidate(payload, anonymous_headers)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != "11111111-1111-4111-8111-111111111111"
        assert data["version"] == 1


class TestValidationPriority:
    def test_priority_existence_beats_shape(self, api):
        """PRD §2.11: "(4) left-to-right path existence; (5) request body
        shape — required fields present, types valid, enum members recognized,
        and ranges honored". PRD §2.11: "An earlier failure masks every later
        check: the response carries the error of the first failed rule only."

        Design: Corner/validations/priority_existence_beats_shape
        """
        resp = api.screen_application(NON_EXISTENT_UUID, "MAYBE", RECRUITER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_priority_shape_beats_state(self, api):
        """PRD §2.11: "(5) request body shape — required fields present, types
        valid, enum members recognized, and ranges honored ...; (9) entity
        state gates (application, offer, interview day, slot, campus event,
        disbursement, project, assignment); ... An earlier failure masks every
        later check: the response carries the error of the first failed rule
        only."

        Design: Corner/validations/priority_shape_beats_state
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        cand = fx.create_candidate()
        app = fx.submit_application(season["id"], cand["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        r = api.screen_application(app["id"], "REJECT", RECRUITER)
        assert r.status_code == 200  # SCREENED_OUT
        resp = api.screen_application(app["id"], "MAYBE", RECRUITER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestSchoolTargetOcc:
    def test_occ_school_target_stale_version(self, api, admin_headers):
        """PRD §2.9: "Patching a school target's configuration through
        `PATCH /campus-recruiting/school-targets/{id}` requires
        `expected_school_target_version` to match the school target's current
        `version`. ... a mismatched version is rejected with
        `ERR_STALE_SCHOOL_TARGET_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_school_target_stale_version
        """
        season = fx.create_season(shortlist_score_threshold=50)
        school = fx.create_school(season["id"])
        v1 = school["version"]
        resp = api.patch_school_target(
            school["id"], {"tier": "CORE", "expected_school_target_version": v1},
            admin_headers,
        )
        data = validate_success(resp)
        assert data["version"] == v1 + 1
        assert data["tier"] == "CORE"
        resp = api.patch_school_target(
            school["id"],
            {"application_cap": 5, "expected_school_target_version": v1},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SCHOOL_TARGET_VERSION)
        after = validate_success(api.get_school_target(school["id"], RECRUITER))
        assert after["application_cap"] == 10  # losing write discarded
