"""Season epoch lifecycle: creation defaults, advance gates, close cascades."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_recruiter_headers, make_candidate_headers, make_evaluator_headers,
    create_season_payload,
)
from test_helpers import fixtures as fx


RECRUITER = make_recruiter_headers()


class TestSeasonCreation:
    def test_season_create_defaults_and_initial_state(self, api, admin_headers):
        """PRD §3.1: "`exploding_offer_hours_default` is the offer lifetime in
        hours applied when a school has no override and defaults to 72;
        `deadline_policy_mode` selects the deadline variant and defaults to
        `WALL_CLOCK`, with `BUSINESS_HOURS` as the alternative;
        `max_extension_hours` caps the cumulative deadline-extension hours any
        single offer may receive and defaults to 72."
        PRD §3.1: "A new season begins in `DRAFT`."
        PRD §2.10: "Every one of these counters and totals starts at zero (or
        `false`) when its owning resource is created."

        Design: Corner/entities/season_create_defaults_and_initial_state
        """
        resp = api.create_season(
            create_season_payload(shortlist_score_threshold=50),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["exploding_offer_hours_default"] == 72
        assert data["deadline_policy_mode"] == "WALL_CLOCK"
        assert data["max_extension_hours"] == 72
        assert data["stipend_reserved_cents"] == 0
        assert data["stipend_disbursed_cents"] == 0
        assert data["applications_total_count"] == 0

    def test_season_create_missing_required_field(self, api, admin_headers):
        """PRD §2.11: "(5) request body shape — required fields present, types
        valid, enum members recognized, and ranges honored (interview scores
        and intern ratings are integers between 1 and 5 inclusive; capacities
        and hour fields are at least 1; cent amounts are at least 0 with the
        weekly pay rate strictly positive; an interval's end is strictly later
        than its start; relocation distance and prior-internship counts are at
        least 0), with violations rejected as `ERR_VALIDATION` (HTTP 400)".
        PRD §3.1: the administrator creates a season with a human-readable
        `name` and its full temporal skeleton.

        Design: Corner/entities/season_create_missing_required_field
        """
        payload = create_season_payload(shortlist_score_threshold=50)
        del payload["name"]
        resp = api.create_season(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestSeasonAdvance:
    def test_season_advance_happy_path(self, api, admin_headers):
        """PRD §3.1: "leaving `DRAFT` requires at least one school target in
        `ACTIVE` status".

        Design: Corner/state_machines/season_advance_happy_path
        """
        season = fx.create_season(shortlist_score_threshold=50)
        fx.create_school(season["id"])
        resp = api.advance_season(season["id"], admin_headers)
        data = validate_success(resp)
        assert data["status"] == "OPEN"

    def test_advance_draft_without_schools_blocked(self, api, admin_headers):
        """PRD §3.1: "leaving `DRAFT` requires at least one school target in
        `ACTIVE` status"; violations are "enforced with
        `ERR_SEASON_ADVANCE_BLOCKED` (HTTP 409)".

        Design: Corner/state_machines/advance_draft_without_schools_blocked
        """
        season = fx.create_season(shortlist_score_threshold=50)
        resp = api.advance_season(season["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_ADVANCE_BLOCKED)
        after = validate_success(api.get_season(season["id"], RECRUITER))
        assert after["status"] == "DRAFT"

    def test_advance_open_at_close_instant_blocked(self, api, admin_headers):
        """PRD §3.1: "leaving `OPEN` requires the logical clock to read
        strictly later than `application_close_at`".

        Design: Corner/state_machines/advance_open_at_close_instant_blocked
        """
        season = fx.create_season(shortlist_score_threshold=50)
        fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-20T00:00:00Z")  # exactly application_close_at
        resp = api.advance_season(season["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_ADVANCE_BLOCKED)

    def test_advance_open_after_close_instant_succeeds(self, api, admin_headers):
        """PRD §3.1: "leaving `OPEN` requires the logical clock to read
        strictly later than `application_close_at`"; one second past the close
        instant satisfies the strict inequality.

        Design: Corner/state_machines/advance_open_at_close_instant_blocked
        """
        season = fx.create_season(shortlist_score_threshold=50)
        fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-20T00:00:01Z")  # one second past close
        resp = api.advance_season(season["id"], admin_headers)
        assert validate_success(resp)["status"] == "SELECTION"

    def test_advance_selection_with_submitted_blocked(self, api, admin_headers):
        """PRD §3.1: "leaving `SELECTION` requires that no application in the
        season still sits in `SUBMITTED`".

        Design: Corner/state_machines/advance_selection_with_submitted_blocked
        """
        ctx = fx.setup_open_season_with_application()
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(ctx.season["id"])  # -> SELECTION
        resp = api.advance_season(ctx.season["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_ADVANCE_BLOCKED)

    def test_advance_selection_after_screening_succeeds(self, api, admin_headers):
        """PRD §3.1: "leaving `SELECTION` requires that no application in the
        season still sits in `SUBMITTED`"; once the only application is
        screened the gate releases.

        Design: Corner/state_machines/advance_selection_with_submitted_blocked
        """
        ctx = fx.setup_selection_with_shortlisted()
        resp = api.advance_season(ctx.season["id"], admin_headers)
        assert validate_success(resp)["status"] == "OFFER_PERIOD"

    def test_advance_offer_period_with_extended_offer_blocked(
        self, api, admin_headers
    ):
        """PRD §3.1: "leaving `OFFER_PERIOD` requires that no offer belonging
        to the season remains `EXTENDED`".

        Design: Corner/state_machines/advance_offer_period_with_extended_offer_blocked
        """
        ctx = fx.setup_extended_offer()
        resp = api.advance_season(ctx.season["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_ADVANCE_BLOCKED)

    def test_advance_offer_period_after_accept_succeeds(self, api, admin_headers):
        """PRD §3.1: "leaving `OFFER_PERIOD` requires that no offer belonging
        to the season remains `EXTENDED`"; accepting the only extended offer
        clears the gate.

        Design: Corner/state_machines/advance_offer_period_with_extended_offer_blocked
        """
        ctx = fx.setup_accepted_offer()
        resp = api.advance_season(ctx.season["id"], admin_headers)
        assert validate_success(resp)["status"] == "INTERN_ACTIVE"


class TestSeasonClose:
    def test_close_with_active_assignment_blocked(self, api, admin_headers):
        """PRD §3.8: "every project assignment in the season must have left
        `ACTIVE` — completed or unassigned — otherwise the close is rejected
        with `ERR_SEASON_CLOSE_BLOCKED` (HTTP 409)".

        Design: Corner/state_machines/close_with_active_assignment_blocked
        """
        ctx = fx.setup_intern_active_with_assignment()
        resp = api.close_season(ctx.season["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_CLOSE_BLOCKED)

    def test_close_after_unassign_succeeds(self, api, admin_headers):
        """PRD §3.8: "every project assignment in the season must have left
        `ACTIVE` — completed or unassigned — otherwise the close is rejected
        with `ERR_SEASON_CLOSE_BLOCKED` (HTTP 409)"; unassigning the only
        assignment satisfies the gate.

        Design: Corner/state_machines/close_with_active_assignment_blocked
        """
        ctx = fx.setup_intern_active_with_assignment()
        resp = api.unassign_project_assignment(ctx.assignment["id"], RECRUITER)
        assert resp.status_code == 200
        resp = api.close_season(ctx.season["id"], admin_headers)
        assert validate_success(resp)["status"] == "CLOSED"

    def test_close_cascade_expires_extended_offer(self, api, admin_headers):
        """PRD §3.8: "Every offer belonging to the season that is still
        `EXTENDED` moves to `EXPIRED`, and each such flip conditionally moves
        its application `OFFER_PENDING → EXPIRED` (only when the application
        is currently `OFFER_PENDING`)."

        Design: Corner/state_machines/close_cascade_expires_extended_offer
        """
        season = fx.create_season(shortlist_score_threshold=10)
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])  # OPEN
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
        day = None
        r = api.create_interview_day(
            season["id"],
            {"window_start_at": "2026-06-08T09:00:00Z",
             "window_end_at": "2026-06-08T17:00:00Z", "capacity": 5},
            RECRUITER,
        )
        assert r.status_code == 201
        day = get_success_data(r)
        slots = {}
        for app, start, end in (
            (app1, "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z"),
            (app2, "2026-06-08T11:15:00Z", "2026-06-08T12:00:00Z"),
        ):
            r = api.book_interview_slot(
                day["id"],
                {"application_id": app["id"], "evaluator_id": ev["id"],
                 "start_at": start, "end_at": end},
                RECRUITER,
            )
            assert r.status_code == 201
            slots[app["id"]] = get_success_data(r)
            r = api.submit_evaluation(
                slots[app["id"]]["id"], {"score": 4, "recommendation": "HIRE"},
                make_evaluator_headers(ev["id"]),
            )
            assert r.status_code == 201
        fx.advance_season(season["id"])  # OFFER_PERIOD
        r = api.create_offer(
            app1["id"], {"weekly_rate_cents": 150000, "duration_weeks": 12},
            RECRUITER,
        )
        assert r.status_code == 201
        off1 = get_success_data(r)
        r = api.create_offer(
            app2["id"], {"weekly_rate_cents": 150000, "duration_weeks": 12},
            RECRUITER,
        )
        assert r.status_code == 201
        off2 = get_success_data(r)
        fx.set_clock("2026-07-06T10:00:00Z")
        r = api.extend_offer(off1["id"], RECRUITER)
        assert r.status_code == 200
        r = api.accept_offer(off1["id"], make_candidate_headers(c1["id"]))
        assert r.status_code == 200
        fx.advance_season(season["id"])  # INTERN_ACTIVE (no EXTENDED offers)
        # Extend offer B during INTERN_ACTIVE (posture permits).
        fx.set_clock("2026-07-15T10:00:00Z")
        r = api.extend_offer(off2["id"], RECRUITER)
        assert r.status_code == 200
        # No ACTIVE assignments exist, so the close gate passes.
        resp = api.close_season(season["id"], admin_headers)
        assert validate_success(resp)["status"] == "CLOSED"
        offer2 = validate_success(api.get_offer(off2["id"], RECRUITER))
        assert offer2["status"] == "EXPIRED"
        app2_after = validate_success(api.get_application(app2["id"], RECRUITER))
        assert app2_after["status"] == "EXPIRED"

    def test_close_leaves_accepted_offer_untouched(self, api, admin_headers):
        """PRD §3.8: "Every offer belonging to the season that is still
        `EXTENDED` moves to `EXPIRED`" — the sweep is conditional on
        `EXTENDED`; an already-`ACCEPTED` offer and its `ACCEPTED` application
        survive the close unchanged.

        Design: Corner/state_machines/close_cascade_expires_extended_offer
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])  # INTERN_ACTIVE
        resp = api.close_season(ctx.season["id"], admin_headers)
        assert validate_success(resp)["status"] == "CLOSED"
        offer = validate_success(api.get_offer(ctx.offer["id"], RECRUITER))
        assert offer["status"] == "ACCEPTED"
        app = validate_success(
            api.get_application(ctx.application["id"], RECRUITER)
        )
        assert app["status"] == "ACCEPTED"
