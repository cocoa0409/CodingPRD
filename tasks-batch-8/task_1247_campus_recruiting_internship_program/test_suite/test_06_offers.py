"""Offers: drafting, dual-variant deadlines, stipend math, lifecycle, OCC."""
from datetime import datetime

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_recruiter_headers, make_candidate_headers, make_evaluator_headers,
    create_offer_payload, create_interview_day_payload,
    create_interview_slot_payload,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


def _instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison.

    The PRD pins the deadline *instant*, not the fractional-digit rendering,
    so deadline assertions compare parsed instants (both `...:00Z` and
    `...:00.000Z` denote the same instant)."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _drive_to_decision_pending(api, season_id, app_id, evaluator):
    """Screen SHORTLIST -> book slot -> submit evaluation => DECISION_PENDING."""
    r = api.screen_application(app_id, "SHORTLIST", RECRUITER)
    assert r.status_code == 200, f"Setup failed: screen -> {r.text}"
    day = validate_success(api.create_interview_day(
        season_id, create_interview_day_payload(), RECRUITER,
    ), expected_status=201)
    r = api.book_interview_slot(
        day["id"],
        create_interview_slot_payload(
            application_id=app_id, evaluator_id=evaluator["id"],
        ),
        RECRUITER,
    )
    slot = validate_success(r, expected_status=201)
    r = api.submit_evaluation(
        slot["id"], {"score": 4, "recommendation": "HIRE"},
        make_evaluator_headers(evaluator["id"]),
    )
    assert r.status_code == 201, f"Setup failed: evaluation -> {r.text}"


class TestOfferCreation:
    def test_offer_create_requires_decision_pending(self, api):
        """PRD §3.6: "a `Recruiter` drafts an offer against a
        `DECISION_PENDING` application — drafting against any other
        application status is rejected with
        `ERR_APPLICATION_STATE_FORBIDDEN`".

        Design: Difficulty/cross_entity_state_dependency/offer_create_requires_decision_pending
        """
        ctx = fx.setup_selection_with_shortlisted()
        resp = api.create_offer(
            ctx.application["id"], create_offer_payload(), RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_STATE_FORBIDDEN)

    def test_offer_create_rejection_persists_no_offer(self, api):
        """PRD §3.6: "a `Recruiter` drafts an offer against a
        `DECISION_PENDING` application — drafting against any other
        application status is rejected with `ERR_APPLICATION_STATE_FORBIDDEN`"
        and "the per-application offer listing therefore holds zero or one
        element".

        Design: Difficulty/cross_entity_state_dependency/offer_create_requires_decision_pending
        """
        ctx = fx.setup_selection_with_shortlisted()
        resp = api.create_offer(
            ctx.application["id"], create_offer_payload(), RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_STATE_FORBIDDEN)
        listing, meta = validate_paginated(
            api.list_application_offers(ctx.application["id"], RECRUITER)
        )
        assert listing == []
        assert meta["total_count"] == 0

    def test_duplicate_offer_rejected(self, api):
        """PRD §3.6: "There is at most one offer per application: a second
        drafting attempt fails with `ERR_OFFER_ALREADY_EXISTS` (HTTP 409)".

        Design: Corner/validations/duplicate_offer_rejected
        """
        ctx = fx.setup_offer_period_with_draft_offer()
        resp = api.create_offer(
            ctx.application["id"],
            create_offer_payload(weekly_rate_cents=160000, duration_weeks=10),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_ALREADY_EXISTS)


class TestExplodingDeadlineVariants:
    def _two_seasons_with_offers(self, api):
        """Season A WALL_CLOCK and season B BUSINESS_HOURS, each with a school
        override of 16 exploding hours, each with one application driven to
        DECISION_PENDING, advanced to OFFER_PERIOD, and a DRAFT offer."""
        out = {}
        for key, mode in (("A", "WALL_CLOCK"), ("B", "BUSINESS_HOURS")):
            season = fx.create_season(deadline_policy_mode=mode)
            school = fx.create_school(
                season["id"], exploding_offer_hours_override=16,
            )
            fx.advance_season(season["id"])  # OPEN
            fx.set_clock("2026-05-15T00:00:00Z")
            cand = fx.create_candidate(
                email=f"{key.lower()}@x.com", full_name=f"Candidate {key}",
            )
            app = fx.submit_application(season["id"], cand["id"], school["id"])
            fx.set_clock("2026-05-21T00:00:00Z")
            fx.advance_season(season["id"])  # SELECTION
            ev = fx.create_employee(
                season["id"], email=f"ev{key.lower()}@co.com",
                full_name=f"Eve {key}",
            )
            _drive_to_decision_pending(api, season["id"], app["id"], ev)
            fx.advance_season(season["id"])  # OFFER_PERIOD
            r = api.create_offer(
                app["id"],
                {"weekly_rate_cents": 150000, "duration_weeks": 12},
                RECRUITER,
            )
            offer = validate_success(r, expected_status=201)
            out[key] = dict(season=season, offer=offer, cand=cand)
        return out

    def test_wall_clock_deadline_is_straight_hour_addition(self, api):
        """PRD §3.6: "Under `WALL_CLOCK`, `deadline_at` is simply
        `extended_at` plus the pinned policy hours — nights and weekends
        count." Also: "Extension then pins `policy_hours_snapshot` to the
        school's `exploding_offer_hours_override` when one is set".

        Design: Difficulty/dual_variant_calc/exploding_deadline_wall_clock_vs_business_hours
        """
        ctxs = self._two_seasons_with_offers(api)
        fx.set_clock("2026-07-10T16:00:00Z")  # Friday 16:00 UTC
        resp = api.extend_offer(ctxs["A"]["offer"]["id"], RECRUITER)
        offer = validate_success(resp)
        # 16h straight from Friday 16:00Z -> Saturday 08:00Z.
        assert _instant(offer["deadline_at"]) == _instant("2026-07-11T08:00:00Z")
        assert offer["policy_hours_snapshot"] == 16

    def test_business_hours_deadline_counts_only_business_seconds(self, api):
        """PRD §3.6: "Under `BUSINESS_HOURS`, `deadline_at` is the earliest
        instant at which the number of seconds from `extended_at` up to and
        including that instant that fall inside business hours equals the
        pinned hours expressed in seconds, where business hours are Monday
        through Friday, from 09:00:00 UTC up to but not including 17:00:00
        UTC".

        Design: Difficulty/dual_variant_calc/exploding_deadline_wall_clock_vs_business_hours
        """
        ctxs = self._two_seasons_with_offers(api)
        fx.set_clock("2026-07-10T16:00:00Z")  # Friday 16:00 UTC
        resp_a = api.extend_offer(ctxs["A"]["offer"]["id"], RECRUITER)
        dl_a = validate_success(resp_a)["deadline_at"]
        resp_b = api.extend_offer(ctxs["B"]["offer"]["id"], RECRUITER)
        offer_b = validate_success(resp_b)
        # 1h Friday + 8h Monday + 7h Tuesday = 16 business hours.
        assert _instant(offer_b["deadline_at"]) == _instant("2026-07-14T16:00:00Z")
        assert offer_b["policy_hours_snapshot"] == 16
        assert _instant(offer_b["deadline_at"]) != _instant(dl_a)


class TestOfferComputations:
    def test_stipend_tiered_formula_mode_a_cap_binds(self, api):
        """PRD §3.6: "The regional base is 300000 cents for a `METRO` school,
        200000 for `REGIONAL`, and 100000 for `REMOTE`. A distance bonus of
        150000 cents applies when the application's `relocation_distance_miles`
        is at least 1500 miles; failing that, 75000 cents when it is at least
        500 miles; otherwise nothing. A surcharge of 50000 cents applies when
        the school is both `METRO` and `CORE` tier. `stipend_amount_cents` is
        the sum of base, distance bonus, and surcharge, capped at 400000
        cents".

        Design: Difficulty/combinatorial_formula/stipend_tiered_formula_mode_a
        """
        season = fx.create_season()
        school = fx.create_school(
            season["id"], school_name="MetroU", tier="CORE",
            stipend_region="METRO",
        )
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        cand = fx.create_candidate()
        app = fx.submit_application(
            season["id"], cand["id"], school["id"],
            relocation_distance_miles=1600,
        )
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])
        ev = fx.create_employee(season["id"], calibrated=True)
        _drive_to_decision_pending(api, season["id"], app["id"], ev)
        fx.advance_season(season["id"])  # OFFER_PERIOD
        r = api.create_offer(
            app["id"], {"weekly_rate_cents": 150000, "duration_weeks": 12},
            RECRUITER,
        )
        offer = validate_success(r, expected_status=201)
        fx.set_clock("2026-07-06T10:00:00Z")
        resp = api.extend_offer(offer["id"], RECRUITER)
        # min(400000, 300000 + 150000 + 50000) = 400000; the cap binds.
        assert validate_success(resp)["stipend_amount_cents"] == 400000

    def test_stipend_distance_band_boundary(self, api):
        """PRD §3.6: "A distance bonus of 150000 cents applies when the
        application's `relocation_distance_miles` is at least 1500 miles;
        failing that, 75000 cents when it is at least 500 miles; otherwise
        nothing."

        Design: Corner/calculations/stipend_distance_band_boundary
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])  # REGIONAL TARGET
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        cand = fx.create_candidate()
        app = fx.submit_application(
            season["id"], cand["id"], school["id"],
            relocation_distance_miles=1499,
        )
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])
        ev = fx.create_employee(season["id"])
        _drive_to_decision_pending(api, season["id"], app["id"], ev)
        fx.advance_season(season["id"])  # OFFER_PERIOD
        r = api.create_offer(
            app["id"], {"weekly_rate_cents": 150000, "duration_weeks": 12},
            RECRUITER,
        )
        offer = validate_success(r, expected_status=201)
        fx.set_clock("2026-07-06T10:00:00Z")
        resp = api.extend_offer(offer["id"], RECRUITER)
        # 1499 < 1500 -> mid band: 200000 + 75000 + 0 = 275000.
        assert validate_success(resp)["stipend_amount_cents"] == 275000

    def test_stipend_regional_base_without_bonus(self, api):
        """PRD §3.6: "The regional base is 300000 cents for a `METRO` school,
        200000 for `REGIONAL`, and 100000 for `REMOTE`. A distance bonus of
        150000 cents applies when the application's `relocation_distance_miles`
        is at least 1500 miles; failing that, 75000 cents when it is at least
        500 miles; otherwise nothing. A surcharge of 50000 cents applies when
        the school is both `METRO` and `CORE` tier."

        Design: Difficulty/combinatorial_formula/stipend_tiered_formula_mode_a
        """
        ctx = fx.setup_extended_offer()
        # REGIONAL TARGET school, 100 miles: 200000 + 0 + 0.
        assert ctx.offer["stipend_amount_cents"] == 200000

    def test_offer_total_comp_rounding_order_mode_b(self, api):
        """PRD §3.6: "`total_comp_cents` is then the sum of the two
        already-rounded components — the rounding is pinned per component
        first and the two integer-cent results are summed, never rounded once
        at the end." PRD §2.8: "Total compensation rounds each component
        half-up to integer cents individually before summing (§3.6); the two
        roundings are deliberately per-component rather than applied once to
        the final sum."

        Design: Difficulty/combinatorial_formula/offer_total_comp_rounding_order_mode_b
        """
        ctx = fx.setup_offer_period_with_draft_offer(
            offer_overrides={
                "weekly_rate_cents": 100004, "duration_weeks": 1,
                "sign_on_bonus_cents": 14,
            },
        )
        # REGIONAL mult 1.10: round_half_up(100004*1*1.10)=110004
        # plus round_half_up(14*1.10)=15 -> 110019 (not 110020).
        assert ctx.offer["total_comp_cents"] == 110019
        assert ctx.offer["total_comp_cents"] != 110020

    def test_offer_total_comp_recomputed_on_revision(self, api):
        """PRD §3.6: "The figure is recomputed on every terms revision and
        again at extension." Also: "The salary component is the weekly rate
        multiplied by the number of weeks multiplied by the multiplier,
        rounded half-up to integer cents; the bonus component is the sign-on
        bonus multiplied by the multiplier, likewise rounded half-up to
        integer cents."

        Design: Difficulty/combinatorial_formula/offer_total_comp_rounding_order_mode_b
        """
        ctx = fx.setup_offer_period_with_draft_offer()
        resp = api.revise_offer(
            ctx.offer["id"],
            {"weekly_rate_cents": 160000,
             "expected_offer_version": ctx.offer["version"]},
            RECRUITER,
        )
        data = validate_success(resp)
        # round_half_up(160000*12*1.10)=2112000 + round_half_up(0*1.10)=0.
        assert data["total_comp_cents"] == 2112000
        assert data["version"] == ctx.offer["version"] + 1


class TestOfferRenegotiationCycle:
    def test_decline_reverts_application_to_decision_pending(self, api):
        """PRD §3.6: "**Decline** moves the offer `EXTENDED → DECLINED` and
        conditionally cascades the application `OFFER_PENDING →
        DECISION_PENDING` — only when the application is currently
        `OFFER_PENDING`."

        Design: Difficulty/non_linear_state_machine/offer_renegotiation_cycle
        """
        ctx = fx.setup_extended_offer()
        resp = api.decline_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        assert validate_success(resp)["status"] == "DECLINED"
        app = validate_success(
            api.get_application(ctx.application["id"], RECRUITER)
        )
        assert app["status"] == "DECISION_PENDING"

    def test_full_cycle_reextend_recomputes_deadline_and_counts(self, api):
        """PRD §3.6: "The cycle `DRAFT → EXTENDED → DECLINED → DRAFT` is what
        makes re-negotiation possible after a candidate balks." Also:
        "Extension then pins `policy_hours_snapshot` ..., stamps `extended_at`
        with the current instant; computes `deadline_at` from the deadline
        policy; ... moves the application `DECISION_PENDING → OFFER_PENDING`;
        and increments the season's `offers_extended_count` by one."

        Design: Difficulty/non_linear_state_machine/offer_renegotiation_cycle
        """
        ctx = fx.setup_extended_offer(extend_at="2026-07-06T10:00:00Z")
        resp = api.decline_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        declined = validate_success(resp)
        resp = api.revise_offer(
            ctx.offer["id"],
            {"weekly_rate_cents": 160000,
             "expected_offer_version": declined["version"]},
            RECRUITER,
        )
        assert validate_success(resp)["status"] == "DRAFT"
        resp = api.extend_offer(ctx.offer["id"], RECRUITER)
        extended2 = validate_success(resp)
        assert extended2["status"] == "EXTENDED"
        # Default WALL_CLOCK 72h from 2026-07-06T10:00:00Z.
        assert _instant(extended2["deadline_at"]) == _instant("2026-07-09T10:00:00Z")
        app = validate_success(
            api.get_application(ctx.application["id"], RECRUITER)
        )
        assert app["status"] == "OFFER_PENDING"
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["offers_extended_count"] == 2


class TestOfferAccept:
    def test_accept_transitive_cascade_link1_offer_and_application(self, api):
        """PRD §3.6: "A successful acceptance moves the offer `EXTENDED →
        ACCEPTED` and fires a two-level cascade: a stipend disbursement is
        created in `RESERVED` status with its `amount_cents` copied from the
        offer's `stipend_amount_cents` — immutable thereafter, and unique per
        offer, so the per-offer disbursement listing holds zero or one element
        and the disbursement's `offer_id` ties it back — and the season's
        `stipend_reserved_cents` increments by that amount; meanwhile the
        application moves `OFFER_PENDING → ACCEPTED`, which increments the
        season's `offers_accepted_count` by one."

        Design: Difficulty/transitive_cascade/accept_transitive_cascade_depth3
        """
        ctx = fx.setup_extended_offer()
        fx.set_clock("2026-07-07T10:00:00Z")
        resp = api.accept_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        assert validate_success(resp)["status"] == "ACCEPTED"
        app = validate_success(
            api.get_application(ctx.application["id"], RECRUITER)
        )
        assert app["status"] == "ACCEPTED"
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["offers_accepted_count"] == 1

    def test_accept_transitive_cascade_stipend_ledger_bubble(self, api):
        """PRD §3.6: "a stipend disbursement is created in `RESERVED` status
        with its `amount_cents` copied from the offer's
        `stipend_amount_cents` — immutable thereafter, and unique per offer,
        so the per-offer disbursement listing holds zero or one element and
        the disbursement's `offer_id` ties it back — and the season's
        `stipend_reserved_cents` increments by that amount".

        Design: Difficulty/transitive_cascade/accept_transitive_cascade_depth3
        """
        ctx = fx.setup_extended_offer()
        fx.set_clock("2026-07-07T10:00:00Z")
        resp = api.accept_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        assert resp.status_code == 200
        season = validate_success(api.get_season(ctx.season["id"], RECRUITER))
        assert season["stipend_reserved_cents"] == 200000
        disb = fx.get_offer_disbursement(ctx.offer["id"])
        assert disb["status"] == "RESERVED"
        assert disb["amount_cents"] == 200000  # REGIONAL 200000 + 0 + 0
        assert disb["offer_id"] == ctx.offer["id"]


class TestOfferDeadlineBoundary:
    def _two_extended_offers(self, api):
        """Season OFFER_PERIOD; two applications each with an offer extended
        at 2026-07-06T10:00:00Z (72h WALL_CLOCK deadline 2026-07-09T10:00:00Z)."""
        season = fx.create_season()
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
        day = validate_success(api.create_interview_day(
            season["id"], create_interview_day_payload(), RECRUITER,
        ), expected_status=201)
        for app, start, end, score, rec in (
            (app1, "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z", 4, "HIRE"),
            (app2, "2026-06-08T11:15:00Z", "2026-06-08T12:00:00Z", 3, "LEAN_NO"),
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
                slot["id"], {"score": score, "recommendation": rec},
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
        return dict(season=season, offers=offers, c1=c1, c2=c2,
                    app1=app1, app2=app2)

    def test_accept_at_exact_deadline_succeeds(self, api):
        """PRD §3.6: "The accept boundary is inclusive in both variants:
        acceptance succeeds when it arrives at or before `deadline_at`."

        Design: Difficulty/boundary_precision_check/offer_deadline_inclusive_boundary
        """
        ctx = self._two_extended_offers(api)
        fx.set_clock("2026-07-09T10:00:00Z")  # exactly deadline_at
        resp = api.accept_offer(
            ctx["offers"]["one"]["id"],
            make_candidate_headers(ctx["c1"]["id"]),
        )
        assert validate_success(resp)["status"] == "ACCEPTED"

    def test_accept_one_second_past_deadline_flips_expired(self, api):
        """PRD §3.6: "if the clock reads strictly later than `deadline_at`,
        the offer first flips `EXTENDED → EXPIRED` (with the conditional
        application cascade described below) and the request fails with
        `ERR_OFFER_EXPIRED` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/offer_deadline_inclusive_boundary
        """
        ctx = self._two_extended_offers(api)
        fx.set_clock("2026-07-09T10:00:01Z")  # one second past deadline
        resp = api.accept_offer(
            ctx["offers"]["two"]["id"],
            make_candidate_headers(ctx["c2"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
        offer = validate_success(
            api.get_offer(ctx["offers"]["two"]["id"], RECRUITER)
        )
        assert offer["status"] == "EXPIRED"
        app = validate_success(
            api.get_application(ctx["app2"]["id"], RECRUITER)
        )
        assert app["status"] == "EXPIRED"


class TestAcceptValidationOrdering:
    def test_accept_expired_offer_state_beats_fiscal(self, api):
        """PRD §2.11: "An earlier failure masks every later check: the
        response carries the error of the first failed rule only." and "(9)
        entity state gates (application, offer, interview day, slot, campus
        event, disbursement, project, assignment); ... and finally (13) the
        fiscal stipend-budget check, which is always evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/accept_expired_offer_state_beats_fiscal
        """
        # Budget 100 < REGIONAL stipend 200000, so the fiscal check would
        # fail too; but the offer is already EXPIRED, so the state gate wins.
        ctx = fx.setup_extended_offer(
            shortlist_overrides={"stipend_budget_cents": 100},
        )
        fx.set_clock("2026-07-10T10:00:00Z")  # past deadline
        resp = api.expire_offer(ctx.offer["id"], RECRUITER)
        assert resp.status_code == 200  # now EXPIRED
        resp = api.accept_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_STATE_FORBIDDEN)

    def test_accept_expired_offer_leaves_offer_expired(self, api):
        """PRD §3.6: "Every post-draft disposition of an offer — acceptance,
        decline, rescission, expiry, and deadline extension — requires the
        offer to be `EXTENDED`; attempting any of them against an offer in
        any other status is rejected with `ERR_OFFER_STATE_FORBIDDEN`."

        Design: Difficulty/priority_pair_validation_conflict/accept_expired_offer_state_beats_fiscal
        """
        ctx = fx.setup_extended_offer(
            shortlist_overrides={"stipend_budget_cents": 100},
        )
        fx.set_clock("2026-07-10T10:00:00Z")
        resp = api.expire_offer(ctx.offer["id"], RECRUITER)
        assert resp.status_code == 200
        resp = api.accept_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_STATE_FORBIDDEN)
        offer = validate_success(api.get_offer(ctx.offer["id"], RECRUITER))
        assert offer["status"] == "EXPIRED"


class TestStipendBudgetGate:
    def test_stipend_budget_equality_then_excess(self, api):
        """PRD §3.6: "the season's `stipend_reserved_cents` plus the offer's
        `stipend_amount_cents` must not exceed `stipend_budget_cents`, with
        equality permitted, else `ERR_STIPEND_BUDGET_EXCEEDED` (HTTP 422)".

        Design: Corner/calculations/stipend_budget_equality_then_excess
        """
        season = fx.create_season(stipend_budget_cents=200000)
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        app1 = fx.submit_application(season["id"], c1["id"], school["id"])
        app2 = fx.submit_application(season["id"], c2["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])
        for app in (app1, app2):
            r = api.screen_application(app["id"], "SHORTLIST", RECRUITER)
            assert r.status_code == 200
        ev = fx.create_employee(season["id"])
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
        fx.set_clock("2026-07-07T10:00:00Z")
        resp = api.accept_offer(
            offers["one"]["id"], make_candidate_headers(c1["id"]),
        )
        assert validate_success(resp)["status"] == "ACCEPTED"  # 0+200000 == budget
        resp = api.accept_offer(
            offers["two"]["id"], make_candidate_headers(c2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STIPEND_BUDGET_EXCEEDED)


class TestOfferDeadlineManagement:
    def test_extension_cap_boundary(self, api, admin_headers):
        """PRD §3.6: "The grant accumulates into `extension_hours_granted`,
        and the running total plus the new grant must not exceed the season's
        `max_extension_hours` — equality is permitted — failing with
        `ERR_EXTENSION_CAP_EXCEEDED` (HTTP 422) beyond the cap. The granted
        hours shift `deadline_at` later by exactly that many whole hours on
        the wall clock, regardless of whether the season's policy mode is
        `WALL_CLOCK` or `BUSINESS_HOURS`."

        Design: Corner/calculations/extension_cap_boundary
        """
        ctx = fx.setup_extended_offer(extend_at="2026-07-06T10:00:00Z")
        resp = api.extend_offer_deadline(ctx.offer["id"], 72, admin_headers)
        data = validate_success(resp)
        assert data["extension_hours_granted"] == 72
        assert _instant(data["deadline_at"]) == _instant("2026-07-12T10:00:00Z")
        resp = api.extend_offer_deadline(ctx.offer["id"], 1, admin_headers)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_CAP_EXCEEDED)

    def test_expire_before_deadline_rejected(self, api):
        """PRD §3.6: "calling the sweep while the deadline has not yet passed
        — the clock reading at or before `deadline_at` — is rejected with
        `ERR_OFFER_NOT_YET_EXPIRED` (HTTP 422)".

        Design: Corner/state_machines/expire_before_deadline_rejected
        """
        ctx = fx.setup_extended_offer(extend_at="2026-07-06T10:00:00Z")
        fx.set_clock("2026-07-07T00:00:00Z")  # before deadline
        resp = api.expire_offer(ctx.offer["id"], RECRUITER)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_YET_EXPIRED)

    def test_offer_extend_outside_offer_window(self, api):
        """PRD §3.6: "the logical clock must read within the offer window —
        at or after `offer_window_open_at` and at or before
        `offer_window_close_at`, both inclusive — failing with
        `ERR_OFFER_WINDOW_CLOSED` (HTTP 422) outside it".

        Design: Corner/validations/offer_extend_outside_offer_window
        """
        ctx = fx.setup_offer_period_with_draft_offer()
        fx.set_clock("2026-06-20T00:00:00Z")  # before offer window opens
        resp = api.extend_offer(ctx.offer["id"], RECRUITER)
        validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_CLOSED)


class TestOfferDispositions:
    def test_rescind_reverts_application_to_decision_pending(self, api):
        """PRD §3.6: "Rescinding — available to `Recruiter` and
        `RecruitingAdmin` alike, and not posture-gated — moves an `EXTENDED`
        offer to `RESCINDED` with the same conditional application cascade
        back to `DECISION_PENDING`".

        Design: Corner/state_machines/rescind_reverts_application_to_decision_pending
        """
        ctx = fx.setup_extended_offer()
        resp = api.rescind_offer(ctx.offer["id"], RECRUITER)
        assert validate_success(resp)["status"] == "RESCINDED"
        app = validate_success(
            api.get_application(ctx.application["id"], RECRUITER)
        )
        assert app["status"] == "DECISION_PENDING"

    def test_offer_terminal_lockdown_decline_accepted(self, api):
        """PRD §3.6: "Every post-draft disposition of an offer — acceptance,
        decline, rescission, expiry, and deadline extension — requires the
        offer to be `EXTENDED`; attempting any of them against an offer in
        any other status is rejected with `ERR_OFFER_STATE_FORBIDDEN`."

        Design: Corner/state_machines/offer_terminal_lockdown_decline_accepted
        """
        ctx = fx.setup_accepted_offer()
        resp = api.decline_offer(
            ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_STATE_FORBIDDEN)
        offer = validate_success(api.get_offer(ctx.offer["id"], RECRUITER))
        assert offer["status"] == "ACCEPTED"


class TestOfferOcc:
    def test_occ_offer_terms_stale_version(self, api):
        """PRD §2.9: "Revising an offer's terms through
        `PUT /campus-recruiting/offers/{id}` requires the request to carry
        `expected_offer_version` holding the `version` of the offer as the
        client last observed it. If the value does not match the offer's
        current `version` — because another writer has already revised the
        terms, or a decline-and-revise cycle has advanced the version since
        the client's last read — the request is rejected with
        `ERR_STALE_OFFER_VERSION` (HTTP 412), preventing the client from
        silently superseding terms it has not observed."

        Design: Corner/complexity_layers/occ_offer_terms_stale_version
        """
        ctx = fx.setup_decision_pending()
        resp = api.create_offer(
            ctx.application["id"], create_offer_payload(), RECRUITER,
        )
        offer = validate_success(resp, expected_status=201)
        v1 = offer["version"]
        resp = api.revise_offer(
            offer["id"],
            {"weekly_rate_cents": 160000, "expected_offer_version": v1},
            RECRUITER,
        )
        data = validate_success(resp)
        assert data["version"] == v1 + 1
        assert data["total_comp_cents"] == 2112000  # 160000*12*1.10 + 0
        resp = api.revise_offer(
            offer["id"],
            {"duration_weeks": 10, "expected_offer_version": v1},
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_OFFER_VERSION)
