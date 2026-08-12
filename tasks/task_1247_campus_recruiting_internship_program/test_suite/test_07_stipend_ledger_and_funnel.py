"""Stipend ledger, disbursement lifecycle, FK reachability, conversion funnel."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_recruiter_headers, make_candidate_headers, make_evaluator_headers,
    make_mentor_headers, create_interview_day_payload,
    create_interview_slot_payload,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


class TestDisbursementLifecycle:
    def test_disburse_transitive_cascade_status_flip(self, api):
        """PRD §3.6: "disbursing — available to `Recruiter` and
        `RecruitingAdmin`, only while the season is `INTERN_ACTIVE`, and only
        against a disbursement still `RESERVED`
        (`ERR_DISBURSEMENT_STATE_FORBIDDEN`, HTTP 409, otherwise) — moves it
        `RESERVED → DISBURSED`".

        Design: Difficulty/transitive_cascade/disburse_transitive_cascade_depth2
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])  # INTERN_ACTIVE
        disb = fx.get_offer_disbursement(ctx.offer["id"])
        resp = api.disburse_stipend(disb["id"], RECRUITER)
        assert validate_success(resp)["status"] == "DISBURSED"

    def test_disburse_transitive_cascade_ledger_bubble_up(self, api):
        """PRD §3.6: "moves it `RESERVED → DISBURSED`, decrementing the
        season's `stipend_reserved_cents` by the disbursement's `amount_cents`
        and incrementing `stipend_disbursed_cents` by the same amount."

        Design: Difficulty/transitive_cascade/disburse_transitive_cascade_depth2
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])  # INTERN_ACTIVE
        disb = fx.get_offer_disbursement(ctx.offer["id"])
        resp = api.disburse_stipend(disb["id"], RECRUITER)
        assert resp.status_code == 200
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["stipend_reserved_cents"] == 0
        assert season["stipend_disbursed_cents"] == 200000

    def test_disburse_before_intern_active_blocked(self, api):
        """PRD §2.4: "Stipend disbursement, project-assignment creation,
        unassignment, and completion, intern-evaluation submission, and
        return-offer-outcome recording require `INTERN_ACTIVE`."

        Design: Corner/validations/disburse_before_intern_active_blocked
        """
        ctx = fx.setup_accepted_offer()  # season still OFFER_PERIOD
        disb = fx.get_offer_disbursement(ctx.offer["id"])
        resp = api.disburse_stipend(disb["id"], RECRUITER)
        validate_error(resp, ApiErrorId.ERR_SEASON_POSTURE_FORBIDDEN)

    def test_disburse_twice_rejected(self, api):
        """PRD §3.6: "only against a disbursement still `RESERVED`
        (`ERR_DISBURSEMENT_STATE_FORBIDDEN`, HTTP 409, otherwise)".

        Design: Corner/validations/disburse_twice_rejected
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])  # INTERN_ACTIVE
        disb = fx.get_offer_disbursement(ctx.offer["id"])
        resp = api.disburse_stipend(disb["id"], RECRUITER)
        assert resp.status_code == 200
        resp = api.disburse_stipend(disb["id"], RECRUITER)
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_STATE_FORBIDDEN)
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["stipend_disbursed_cents"] == 200000  # no double-move


class TestStipendReservedLedgerCompensation:
    def test_accept_reserves_stipend(self, api):
        """PRD §2.10: "`stipend_reserved_cents` always equals the sum of
        `amount_cents` over all stipend disbursements of the season in
        `RESERVED` status".

        Design: Difficulty/compensating_invariant/stipend_reserved_ledger_compensation
        """
        ctx = fx.setup_accepted_offer()
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["stipend_reserved_cents"] == 200000

    def test_season_close_releases_reservation(self, api, admin_headers):
        """PRD §3.8: "every stipend disbursement of the season still in
        `RESERVED` status moves to `RELEASED`, and each release decrements the
        season's `stipend_reserved_cents` by the disbursement's `amount_cents`
        — reserved-but-undisbursed stipend money returns to the pool at
        close."

        Design: Difficulty/compensating_invariant/stipend_reserved_ledger_compensation
        """
        ctx = fx.setup_accepted_offer()
        fx.advance_season(ctx.season["id"])  # INTERN_ACTIVE
        mid = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert mid["stipend_reserved_cents"] == 200000
        resp = api.close_season(ctx.season["id"], admin_headers)
        assert validate_success(resp)["status"] == "CLOSED"
        end = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert end["stipend_reserved_cents"] == 0
        assert end["stipend_disbursed_cents"] == 0
        disb = fx.get_offer_disbursement(ctx.offer["id"])
        assert disb["status"] == "RELEASED"


class TestReverseReachability:
    def test_fk_reverse_reachability_subresources(self, api):
        """PRD §4 lists `GET /campus-recruiting/school-targets/{id}/applications`
        ("List applications from one school target"),
        `GET /campus-recruiting/candidates/{id}/applications` ("List a
        candidate's applications across seasons"), and
        `GET /campus-recruiting/offers/{id}/stipend-disbursements` ("List
        disbursements of an offer (zero or one element)").

        Design: Corner/endpoints/fk_reverse_reachability_subresources
        """
        ctx = fx.setup_accepted_offer()
        resp = api.list_school_target_applications(ctx.school["id"], RECRUITER)
        data, _ = validate_paginated(resp)
        assert data[0]["id"] == ctx.application["id"]
        resp = api.list_candidate_applications(
            ctx.candidate["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        data, _ = validate_paginated(resp)
        assert data[0]["id"] == ctx.application["id"]
        disb = fx.get_offer_disbursement(ctx.offer["id"])
        assert disb["amount_cents"] == 200000
        assert disb["offer_id"] == ctx.offer["id"]


class TestConversionSummary:
    def test_conversion_summary_computed_read(self, api):
        """PRD §3.8: "The `conversion_rate_provisional` is the season's
        `return_offers_accepted_count` divided by its `offers_accepted_count`,
        rounded half-up to four decimal places; the `conversion_rate_final`
        divides the same numerator by `completed_assignments_count` instead,
        likewise rounded half-up to four decimal places. Either rate reports 0
        when its own denominator is 0."

        Design: Corner/endpoints/conversion_summary_computed_read
        """
        ctx = fx.setup_accepted_offer()
        resp = api.get_conversion_summary(ctx.season["id"], RECRUITER)
        data = validate_success(resp)
        assert data["applications_total_count"] == 1
        assert data["offers_extended_count"] == 1
        assert data["offers_accepted_count"] == 1
        assert data["completed_assignments_count"] == 0
        assert data["return_offers_extended_count"] == 0
        assert data["return_offers_accepted_count"] == 0
        assert data["stipend_reserved_cents"] == 200000
        assert data["stipend_disbursed_cents"] == 0
        assert data["conversion_rate_provisional"] == 0  # 0/1
        assert data["conversion_rate_final"] == 0  # empty denominator rule

    def test_conversion_rates_divergent_denominators(self, api):
        """PRD §3.8: "Because the final rate's denominator counts only interns
        who finished their assignments — never more than the set of all
        accepted offers — the final rate is always at least the provisional
        one, and the two differ whenever any accepted intern has not yet
        completed an assignment."

        Design: Corner/endpoints/conversion_rates_divergent_denominators
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
            season["id"], full_name="Moe", email="moe@co.com",
        )
        men2 = fx.create_employee(
            season["id"], full_name="Nora", email="nora@co.com",
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
        for key, app in (("A", app1), ("B", app2)):
            r = api.create_offer(
                app["id"], {"weekly_rate_cents": 150000, "duration_weeks": 12},
                RECRUITER,
            )
            offers[key] = validate_success(r, expected_status=201)
        fx.set_clock("2026-07-06T10:00:00Z")
        for offer in offers.values():
            r = api.extend_offer(offer["id"], RECRUITER)
            assert r.status_code == 200
        for key, cand in (("A", c1), ("B", c2)):
            r = api.accept_offer(
                offers[key]["id"], make_candidate_headers(cand["id"]),
            )
            assert r.status_code == 200
        fx.advance_season(season["id"])  # INTERN_ACTIVE
        proj = validate_success(api.create_intern_project(
            season["id"], {"title": "Project P", "capacity": 2}, RECRUITER,
        ), expected_status=201)
        asg = {}
        for key, app, men in (("A", app1, men1), ("B", app2, men2)):
            r = api.create_project_assignment(
                proj["id"],
                {"application_id": app["id"], "mentor_id": men["id"]},
                RECRUITER,
            )
            asg[key] = validate_success(r, expected_status=201)
        # A: MID 4 + FINAL 4 with rehire -> EXTENDED; record ACCEPTED; complete.
        for et in ("MID", "FINAL"):
            r = api.submit_intern_evaluation(
                asg["A"]["id"],
                {"eval_type": et, "rating": 4, "would_rehire": True},
                make_mentor_headers(men1["id"]),
            )
            assert r.status_code == 201
        r = api.record_return_offer_outcome(asg["A"]["id"], "ACCEPTED", RECRUITER)
        assert r.status_code == 200
        r = api.complete_project_assignment(asg["A"]["id"], RECRUITER)
        assert r.status_code == 200
        # B stays ACTIVE (accepted but not completed).
        resp = api.get_conversion_summary(season["id"], RECRUITER)
        data = validate_success(resp)
        assert data["offers_accepted_count"] == 2
        assert data["completed_assignments_count"] == 1
        assert data["conversion_rate_provisional"] == 0.5  # 1/2
        assert data["conversion_rate_final"] == 1.0  # 1/1
        assert data["conversion_rate_final"] != data["conversion_rate_provisional"]


class TestImmediateConsistency:
    def test_immediate_consistency_on_accept(self, api):
        """PRD §3.6: "A successful acceptance moves the offer `EXTENDED →
        ACCEPTED` and fires a two-level cascade: a stipend disbursement is
        created in `RESERVED` status with its `amount_cents` copied from the
        offer's `stipend_amount_cents` — immutable thereafter, and unique per
        offer, so the per-offer disbursement listing holds zero or one element
        and the disbursement's `offer_id` ties it back — and the season's
        `stipend_reserved_cents` increments by that amount; meanwhile the
        application moves `OFFER_PENDING → ACCEPTED`, which increments the
        season's `offers_accepted_count` by one."

        Design: Corner/consistency_model/immediate_consistency_on_accept
        """
        ctx = fx.setup_extended_offer()
        resp = api.accept_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "ACCEPTED"
        assert data["stipend_amount_cents"] == 200000
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["offers_accepted_count"] == 1
        assert season["stipend_reserved_cents"] == 200000
