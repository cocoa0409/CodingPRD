"""Sitting engagements: quote vs settlement variants, confirm gauntlet (coop,
safety, overlap, selector), cancellation notice boundaries, settlement gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_household, create_coop, create_plan, create_subscription,
    create_engagement, quote_engagement, confirm_engagement,
    create_published_route, list_engagement_stops,
    setup_household_with_grade_b_coop, setup_quoted_engagement,
    setup_confirmed_engagement, set_logical_clock,
    make_customer_headers, make_service_tech_headers,
    install_coop, proof_coop_once, add_route_stop_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestQuoteVsSettlement:
    def _setup_confirmed_with_subscription(self, api):
        household, coop = setup_household_with_grade_b_coop()
        plan = create_plan(plan_code="SITPLAN", monthly_fee_cents=2900,
                           sitting_discount_pct=0.10)
        create_subscription(household, plan["id"], "2026-06-01T00:00:00Z")
        route = create_published_route("tech-9", "2026-07-10T00:00:00Z", "URBAN", 4)
        engagement = create_engagement(household, coop,
                                       "2026-07-10T00:00:00Z", "2026-07-11T00:00:00Z")
        return household, coop, route, engagement

    def test_quote_prices_all_nights_forward_looking(self, api):
        """PRD §3.6: "The quote is forward-looking: it assumes every planned
        stop will be served. It multiplies the night count by the 5000-cent
        daily rate, then by one plus the `sitting_surcharge_pct` of the seasonal
        window covering `start_date` in the household's zone (one plus zero when
        none covers it), then by one minus the household's `ACTIVE` subscription
        plan's `sitting_discount_pct` (one minus zero without an active
        subscription), rounding half up to whole cents once at the end."

        Design: Difficulty/dual_variant_calc/sitting_quote_vs_settlement_divergence
        """
        household, coop, route, engagement = self._setup_confirmed_with_subscription(api)
        quoted = quote_engagement(engagement["id"])
        # 1 night * 5000 * (1+0) * (1-0.10) = 4500
        assert quoted["quoted_price_cents"] == 4500
        assert quoted["status"] == "QUOTED"
        assert quoted["final_price_cents"] is None

    def test_skipped_stop_contributes_zero_to_settlement(self, api):
        """PRD §3.6: "Where the quote was forward-looking, the settlement is a
        chronological replay: the engagement's stops are processed in
        `planned_start` ascending order with `created_at` ascending as the
        tie-break, and each `DONE` stop contributes a day rate of the 5000-cent
        daily rate multiplied by one plus the `sitting_surcharge_pct` of the
        seasonal window covering that stop's date in its route's zone, the
        per-day rate rounded half up to whole cents before being added to the
        running total; `SKIPPED` and `REMOVED` stops contribute nothing."
        PRD §3.6: "Settlement therefore comes out below the quote whenever any
        stop went unserved."

        Design: Difficulty/dual_variant_calc/sitting_quote_vs_settlement_divergence
        """
        household, coop, route, engagement = self._setup_confirmed_with_subscription(api)
        quote_engagement(engagement["id"])
        engagement = confirm_engagement(engagement["id"], household)
        stops = list_engagement_stops(engagement["id"])
        assert len(stops) == 1
        validate_success(api.skip_route_stop(
            stops[0]["id"], make_service_tech_headers("tech-9"),
            {"reason": "gate locked"}), 200)

        settled = validate_success(api.settle_engagement(engagement["id"], BILLING), 200)
        assert settled["status"] == "COMPLETED"
        assert settled["final_price_cents"] == 0, "sole stop SKIPPED contributes 0"
        assert settled["final_price_cents"] != settled["quoted_price_cents"] == 4500


class TestConfirmCoopGate:
    def _planned_coop_quoted_engagement(self, api):
        household = create_household(name="H XDep1", address="12 Hen Ln")
        coop = create_coop(household, 6, site_label="raw")
        engagement = create_engagement(household, coop,
                                       "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")
        quote_engagement(engagement["id"])
        return household, coop, engagement

    def test_confirm_with_planned_coop_rejected(self, api):
        """PRD §3.4: "Every other visit type requires the coop to be
        `INSTALLED`, as does confirming a sitting engagement; violations are
        rejected with `ERR_COOP_NOT_INSTALLED`."

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_requires_coop_installed
        """
        household, coop, engagement = self._planned_coop_quoted_engagement(api)
        res = api.confirm_engagement(engagement["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_COOP_NOT_INSTALLED)
        after = validate_success(api.get_sitting_engagement(engagement["id"], DISPATCHER), 200)
        assert after["status"] == "QUOTED"

    def test_installed_but_unproofed_coop_passes_coop_gate_only(self, api):
        """PRD §3.6: "Confirmation is the engagement's gauntlet, run by a
        `Customer` or `PlatformAdmin`, and its checks are evaluated in the
        global order of §2.8: the engagement must be `QUOTED` (else
        `ERR_ENGAGEMENT_NOT_QUOTED`); the coop must be `INSTALLED` (else
        `ERR_COOP_NOT_INSTALLED`); the predator-safety gate requires the coop's
        `predator_grade` to be `B` or `A` (else `ERR_PREDATOR_GRADE_INSUFFICIENT`);
        and the date-occupancy check treats each non-`CANCELLED` engagement of
        the same household as occupying the **closed** interval from its
        `start_date` through its `end_date`, both bounds inclusive."
        PRD §3.4: "When a `SETUP_INSTALL` visit completes, the coop moves from
        `PLANNED` to `INSTALLED`."

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_requires_coop_installed
        """
        household, coop, engagement = self._planned_coop_quoted_engagement(api)
        install_coop(household, coop, date="2026-06-01")

        res = api.confirm_engagement(engagement["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_PREDATOR_GRADE_INSUFFICIENT)
        after = validate_success(api.get_sitting_engagement(engagement["id"], DISPATCHER), 200)
        assert after["status"] == "QUOTED", "coop gate passed; the safety gate now rejects"


class TestClosedIntervalOverlap:
    def test_sharing_the_final_day_conflicts(self, api):
        """PRD §3.6: "the date-occupancy check treats each non-`CANCELLED`
        engagement of the same household as occupying the **closed** interval
        from its `start_date` through its `end_date`, both bounds inclusive,
        rejecting the new engagement with `ERR_ENGAGEMENT_DATE_OVERLAP` when
        its start falls on or before an existing engagement's end while its own
        end falls on or after that engagement's start."
        PRD §3.6: "Back-to-back bookings are fine — a start exactly one day
        after an existing engagement's end does not overlap — but sharing even
        the final day of an existing engagement is a conflict."

        Design: Difficulty/resource_temporal_overlap/engagement_closed_interval_overlap
        """
        household, coop = setup_household_with_grade_b_coop()
        create_published_route("tech-9", "2026-08-01T00:00:00Z", "URBAN", 4)
        create_published_route("tech-9", "2026-08-02T00:00:00Z", "URBAN", 4)
        eng_a = create_engagement(household, coop, "2026-08-01T00:00:00Z",
                                  "2026-08-03T00:00:00Z")
        quote_engagement(eng_a["id"])
        confirm_engagement(eng_a["id"], household)

        eng_b = create_engagement(household, coop, "2026-08-03T00:00:00Z",
                                  "2026-08-05T00:00:00Z")
        quote_engagement(eng_b["id"])
        res = api.confirm_engagement(eng_b["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_ENGAGEMENT_DATE_OVERLAP)
        after = validate_success(api.get_sitting_engagement(eng_b["id"], DISPATCHER), 200)
        assert after["status"] == "QUOTED"

    def test_start_one_day_after_end_is_allowed(self, api):
        """PRD §3.6: "Back-to-back bookings are fine — a start exactly one day
        after an existing engagement's end does not overlap — but sharing even
        the final day of an existing engagement is a conflict."

        Design: Difficulty/resource_temporal_overlap/engagement_closed_interval_overlap
        """
        household, coop = setup_household_with_grade_b_coop()
        create_published_route("tech-9", "2026-08-01T00:00:00Z", "URBAN", 4)
        create_published_route("tech-9", "2026-08-02T00:00:00Z", "URBAN", 4)
        route_4 = create_published_route("tech-9", "2026-08-04T00:00:00Z", "URBAN", 4)
        create_published_route("tech-9", "2026-08-05T00:00:00Z", "URBAN", 4)
        eng_a = create_engagement(household, coop, "2026-08-01T00:00:00Z",
                                  "2026-08-03T00:00:00Z")
        quote_engagement(eng_a["id"])
        confirm_engagement(eng_a["id"], household)

        eng_c = create_engagement(household, coop, "2026-08-04T00:00:00Z",
                                  "2026-08-06T00:00:00Z", daily_window_start="10:00")
        quote_engagement(eng_c["id"])
        confirmed = validate_success(api.confirm_engagement(
            eng_c["id"], make_customer_headers(household["id"])), 200)
        assert confirmed["status"] == "CONFIRMED", "start == A.end + 1 day is back-to-back"

        route_4_after = validate_success(api.get_sitting_route(route_4["id"], DISPATCHER), 200)
        assert route_4_after["committed_stops"] == 1, "C's 08-04 stop landed"


class TestSafetyBeatsTemporal:
    def _setup_pair(self, api):
        """Household with grade-B coop_b and INSTALLED grade-NONE coop_n;
        engagement A on coop_b 08-01 -> 08-03 CONFIRMED; engagement B on coop_n
        08-02 -> 08-05 QUOTED (dates overlap A on 08-02/08-03)."""
        household = create_household(name="H Prio2", address="9 Hen Ln")
        coop_b = create_coop(household, 6, site_label="proofed")
        install_coop(household, coop_b, date="2026-06-01")
        proof_coop_once(household, coop_b, date="2026-06-02")
        coop_n = create_coop(household, 4, site_label="unproofed")
        install_coop(household, coop_n, date="2026-06-03")

        route_1 = create_published_route("tech-9", "2026-08-01T00:00:00Z", "URBAN", 4)
        route_2 = create_published_route("tech-9", "2026-08-02T00:00:00Z", "URBAN", 4)
        eng_a = create_engagement(household, coop_b, "2026-08-01T00:00:00Z",
                                  "2026-08-03T00:00:00Z")
        quote_engagement(eng_a["id"])
        confirm_engagement(eng_a["id"], household)

        eng_b = create_engagement(household, coop_n, "2026-08-02T00:00:00Z",
                                  "2026-08-05T00:00:00Z")
        quote_engagement(eng_b["id"])
        return household, coop_n, route_2, eng_b

    def test_safety_error_surfaces_when_both_gates_fail(self, api):
        """PRD §2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed order so the surfaced error is
        deterministic."
        PRD §2.8: "9. **Predator safety gate.** Sitting confirmation requires
        the coop's `predator_grade` to be `B` or `A`; failure yields
        `ERR_PREDATOR_GRADE_INSUFFICIENT`."
        PRD §2.10: "Several operations in this domain mutate more than one
        resource inside a single request, and all such cascades are **atomic**:
        either the primary transition and every derived transition commit
        together, or the request fails and nothing changes."

        Design: Difficulty/priority_pair_validation_conflict/engagement_confirm_safety_beats_temporal
        """
        household, coop_n, route_2, eng_b = self._setup_pair(api)
        route_2_before = validate_success(api.get_sitting_route(route_2["id"], DISPATCHER), 200)

        res = api.confirm_engagement(eng_b["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_PREDATOR_GRADE_INSUFFICIENT)

        after = validate_success(api.get_sitting_engagement(eng_b["id"], DISPATCHER), 200)
        assert after["status"] == "QUOTED", "confirm is atomic"
        assert list_engagement_stops(eng_b["id"]) == [], "no stops created on failure"
        route_2_after = validate_success(api.get_sitting_route(route_2["id"], DISPATCHER), 200)
        assert route_2_after["committed_stops"] == route_2_before["committed_stops"], (
            "failed confirm added no stop to the 08-02 route")

    def test_temporal_error_surfaces_once_safety_passes(self, api):
        """PRD §2.8: "10. **Temporal windows.** The logical-clock and calendar
        rules: no scheduling in the past (`ERR_SCHEDULE_IN_PAST`), no
        closed-interval engagement overlap (`ERR_ENGAGEMENT_DATE_OVERLAP`), no
        per-zone seasonal-window overlap (`ERR_SEASONAL_WINDOW_OVERLAP`), no
        buffered technician collision (`ERR_TECH_SCHEDULE_CONFLICT`), no
        buffered stop collision (`ERR_STOP_TIME_CONFLICT`), and no overlapping
        invoice periods per household (`ERR_INVOICE_PERIOD_OVERLAP`)."
        PRD §3.4: "When a `PREDATOR_PROOFING` visit completes on an installed
        coop, the predator grade climbs one rung — `NONE` to `B`, `B` to `A`,
        and `A` to `A` (further proofing of a top-grade coop changes nothing
        but remains permitted)."

        Design: Difficulty/priority_pair_validation_conflict/engagement_confirm_safety_beats_temporal
        """
        household, coop_n, route_2, eng_b = self._setup_pair(api)
        proof_coop_once(household, coop_n, date="2026-06-04")

        res = api.confirm_engagement(eng_b["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_ENGAGEMENT_DATE_OVERLAP)
        after = validate_success(api.get_sitting_engagement(eng_b["id"], DISPATCHER), 200)
        assert after["status"] == "QUOTED"


class TestCancellationNoticeBoundary:
    def _confirmed_engagement_aug1(self, api):
        household, coop = setup_household_with_grade_b_coop()
        create_published_route("tech-9", "2026-08-01T00:00:00Z", "URBAN", 4)
        engagement = create_engagement(household, coop, "2026-08-01T00:00:00Z",
                                       "2026-08-02T00:00:00Z")
        quoted = quote_engagement(engagement["id"])
        assert quoted["quoted_price_cents"] == 5000, "1 night * 5000, no discount"
        engagement = confirm_engagement(engagement["id"], household)
        return household, engagement

    def test_exactly_seventy_two_hours_notice_is_free(self, api):
        """PRD §3.6: "The notice is the number of hours — fractional hours
        allowed — from the current logical clock time to `start_date`. At least
        72 hours of notice means no fee; at least 24 but under 72 hours means a
        fee of 25 percent of `quoted_price_cents`, rounded half up to whole
        cents; under 24 hours means 50 percent, likewise rounded. The
        boundaries are exact: exactly 72.0 hours is free, and exactly 24.0
        hours lands in the 25-percent tier."

        Design: Difficulty/boundary_precision_check/cancellation_notice_exactly_72h_zero_fee
        """
        household, engagement = self._confirmed_engagement_aug1(api)
        set_logical_clock("2026-07-29T00:00:00Z")  # exactly 72.0 h before 2026-08-01
        cancelled = validate_success(api.cancel_engagement(
            engagement["id"], make_customer_headers(household["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 0

    def test_exactly_twenty_four_hours_notice_lands_in_25pct_tier(self, api):
        """PRD §3.6: "The boundaries are exact: exactly 72.0 hours is free, and
        exactly 24.0 hours lands in the 25-percent tier."
        PRD §3.6: "At least 72 hours of notice means no fee; at least 24 but
        under 72 hours means a fee of 25 percent of `quoted_price_cents`,
        rounded half up to whole cents; under 24 hours means 50 percent,
        likewise rounded."

        Design: Difficulty/boundary_precision_check/cancellation_notice_exactly_72h_zero_fee
        """
        household, engagement = self._confirmed_engagement_aug1(api)
        set_logical_clock("2026-07-31T00:00:00Z")  # exactly 24.0 h before 2026-08-01
        cancelled = validate_success(api.cancel_engagement(
            engagement["id"], make_customer_headers(household["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 1250, (
            "round_half_up(5000 * 0.25)")


class TestConfirmAndSettleGates:
    def test_second_quote_rejected(self, api):
        """PRD §3.6: "A `Dispatcher` produces the quote, moving the engagement
        from `REQUESTED` to `QUOTED` (quoting from any other state yields
        `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/engagement_quote_twice_rejected
        """
        household = create_household(name="H Q2", address="32 Hen Ln")
        coop = create_coop(household, 4)
        engagement = create_engagement(household, coop, "2026-09-01T00:00:00Z",
                                       "2026-09-02T00:00:00Z")
        quote_engagement(engagement["id"])
        res = api.quote_engagement(engagement["id"], DISPATCHER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_sitting_engagement(engagement["id"], DISPATCHER), 200)
        assert after["status"] == "QUOTED"

    def test_settle_with_pending_stops_rejected(self, api):
        """PRD §3.6: "Settlement is the bookend to the quote, performed by a
        `BillingAdmin` once the engagement is `CONFIRMED` (else
        `ERR_ENGAGEMENT_NOT_CONFIRMED`) and every one of its stops is terminal —
        `DONE`, `SKIPPED`, or `REMOVED` — since any still-`PENDING` stop rejects
        the settle with `ERR_STOPS_OUTSTANDING`."
        PRD §3.6: "The result is stored as `quoted_price_cents`, which remains
        null until the engagement is quoted; likewise `final_price_cents` and
        `settled_at` stay null until settlement, and `cancelled_at` stays null
        unless the engagement is cancelled."

        Design: Corner/state_machines/settle_with_pending_stops_rejected
        """
        household, coop, routes, engagement = setup_confirmed_engagement()
        res = api.settle_engagement(engagement["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_STOPS_OUTSTANDING)
        after = validate_success(api.get_sitting_engagement(engagement["id"], DISPATCHER), 200)
        assert after["status"] == "CONFIRMED"
        assert after["final_price_cents"] is None

    def test_zero_night_engagement_rejected(self, api):
        """PRD §3.6: "The engagement's length in nights is the whole-day
        difference between `end_date` and `start_date` and must be at least 1
        and at most 30 nights; violations are rejected with
        `ERR_ENGAGEMENT_DURATION_INVALID` (HTTP 400) at the business-constraint
        stage, not the request-shape stage."

        Design: Corner/validations/engagement_zero_nights_rejected
        """
        household = create_household(name="H Zero", address="44 Hen Ln")
        coop = create_coop(household, 4)
        res = api.create_sitting_engagement(
            {"household_id": household["id"], "coop_site_id": coop["id"],
             "start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-01T00:00:00Z",
             "daily_window_start": "08:00"},
            make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_ENGAGEMENT_DURATION_INVALID)

    def test_confirm_without_route_for_every_night_rejected_atomically(self, api):
        """PRD §3.6: "If **any** stop date has an empty candidate set, the
        entire confirm is rejected with `ERR_NO_ROUTE_AVAILABLE` and is atomic:
        no stops are created and the engagement remains `QUOTED`."

        Design: Corner/validations/confirm_without_any_route_rejected_atomically
        """
        household, coop = setup_household_with_grade_b_coop()
        route = create_published_route("tech-9", "2026-09-10T00:00:00Z", "URBAN", 4)
        engagement = create_engagement(household, coop, "2026-09-10T00:00:00Z",
                                       "2026-09-12T00:00:00Z")
        quote_engagement(engagement["id"])

        res = api.confirm_engagement(engagement["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_NO_ROUTE_AVAILABLE)

        after = validate_success(api.get_sitting_engagement(engagement["id"], DISPATCHER), 200)
        assert after["status"] == "QUOTED"
        route_after = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert route_after["committed_stops"] == 0, "atomic: the night-1 stop was not created"


class TestRouteSelectorRanking:
    def test_tiebreak_by_created_at_then_ranking_by_committed(self, api):
        """PRD §3.6: "For a given date, an eligible route has `route_date` equal
        to that date, `zone_code` equal to the household's zone, status
        `PUBLISHED`, `committed_stops` strictly below `max_stops`, and no
        buffered conflict: comparing the new window against each existing
        `PENDING` or `DONE` stop on the route, a conflict exists unless the new
        window starts at least 30 minutes after the existing stop ends or ends
        at least 30 minutes before it starts — touching at exactly 30 minutes
        is allowed, one minute closer conflicts."
        PRD §3.6: "Among eligible routes the selector ranks by `committed_stops`
        ascending, breaking ties by route `created_at` ascending."

        Design: Corner/calculations/route_selector_ranking_and_tiebreak
        """
        household1, coop1 = setup_household_with_grade_b_coop(name="H Sel1", address="36 Hen Ln")
        household2, coop2 = setup_household_with_grade_b_coop(name="H Sel2", address="37 Hen Ln")

        route_early = create_published_route("tech-9", "2026-08-01T00:00:00Z", "URBAN", 4)
        route_late = create_published_route("tech-8", "2026-08-01T00:00:00Z", "URBAN", 4)

        eng1 = create_engagement(household1, coop1, "2026-08-01T00:00:00Z",
                                 "2026-08-02T00:00:00Z", daily_window_start="08:00")
        quote_engagement(eng1["id"])
        confirm_engagement(eng1["id"], household1)
        eng1_stops = list_engagement_stops(eng1["id"])
        assert eng1_stops[0]["route_id"] == route_early["id"], (
            "committed tie 0 == 0 broken by created_at ascending")

        early_now = validate_success(api.get_sitting_route(route_early["id"], DISPATCHER), 200)
        added = validate_success(api.add_route_stop(
            route_early["id"],
            add_route_stop_payload(eng1["id"], early_now["version"],
                                   planned_start="2026-08-01T12:00:00Z",
                                   planned_end="2026-08-01T13:00:00Z"),
            DISPATCHER), 201)
        assert added["status"] == "PENDING"

        eng2 = create_engagement(household2, coop2, "2026-08-01T00:00:00Z",
                                 "2026-08-02T00:00:00Z", daily_window_start="08:00")
        quote_engagement(eng2["id"])
        confirm_engagement(eng2["id"], household2)
        eng2_stops = list_engagement_stops(eng2["id"])
        assert eng2_stops[0]["route_id"] == route_late["id"], (
            "the earlier route is buffer-blocked at 08:00; the later route is the eligible one")

        late_after = validate_success(api.get_sitting_route(route_late["id"], DISPATCHER), 200)
        assert late_after["committed_stops"] == 1
