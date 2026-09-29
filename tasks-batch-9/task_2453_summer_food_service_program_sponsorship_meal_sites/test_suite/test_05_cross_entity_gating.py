"""Cross-entity gating and interval-overlap rules.

Two families of rule are exercised here. First, an operation that is legal against its own record
may still be refused because a *different* record moved: a service day that is still `PLANNED`
cannot be opened once its site is suspended, and a claim that is still `DRAFT` cannot be submitted
once its sponsor's budget has fallen out of an approved state. Second, the two interval rules the
PRD deliberately gives opposite closure: meal service windows on a service day are half-open and
demand a 60-minute rest interval, while a monitor's windows on one date are closed intervals that
collide the instant they touch.
"""

from test_helpers import (
    ApiErrorId,
    assert_meal_claim,
    assert_meal_service_day,
    assert_monitoring_visit,
    assert_site,
    assert_sponsor_budget,
    assert_status,
    create_critical_finding_visit,
    create_meal_service_day_payload,
    create_monitoring_visit_payload,
    create_planned_day,
    decide_budget,
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    meal_service,
    open_day_payload,
    set_clock,
    setup_june_claim_scenario,
    setup_program_baseline,
    submit_budget,
    submit_claim_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER_HEADERS = make_state_agency_reviewer_headers()

# A service date that already lies in the past once the clock is moved to 2026-06-20, so the
# suspension cascade — which only reaches days on or after the current logical clock date — leaves
# the day in PLANNED and the open attempt reaches the site gate.
PAST_SERVICE_DATE = "2026-06-15"
SUSPENSION_CLOCK = "2026-06-20T08:00:00Z"
LUNCH_WINDOW = {"service_start": "11:30", "service_end": "12:30"}


def _baseline_with_past_planned_day():
    """Approved, operating, LUNCH-only site plus one PLANNED day dated before the clock."""
    scenario = setup_program_baseline()
    site = scenario["site"]
    set_clock(SUSPENSION_CLOCK)
    day = create_planned_day(
        site["id"],
        PAST_SERVICE_DATE,
        [meal_service(meal_type="LUNCH", planned_meals=120, **LUNCH_WINDOW)],
    )
    return scenario, site, day


def _open_attempt(api, day, site_id):
    return api.open_meal_service_day(
        day["id"],
        open_day_payload({"LUNCH": 120}, "2026-06-20T07:30:00Z"),
        make_site_supervisor_headers(site_id),
    )


class TestServiceDayOpenGatedBySiteSuspension:
    """MealServiceDay -> Site: opening a planned day depends on the site's approval axis."""

    def test_open_day_rejected_while_site_suspended_by_critical_finding(self, api):
        """PRD §3.6: "The site must have cleared review, so a site in `PENDING_REVIEW` or `DENIED` produces `ERR_SITE_NOT_APPROVED` and a site in `SUSPENDED` produces `ERR_SITE_SUSPENDED`; the site's `operating_status` must be `OPERATING`, or the attempt reports `ERR_SITE_NOT_OPERATING`."

        Design: Difficulty/cross_entity_state_dependency/service_day_open_blocked_by_suspended_site
        """
        scenario, site, day = _baseline_with_past_planned_day()

        # A CRITICAL visit finding suspends the site without touching the day.
        create_critical_finding_visit(
            site["id"], scheduled_date="2026-06-20", conduct_clock=None
        )

        suspended_site = validate_success(api.get_site(site["id"], REVIEWER_HEADERS))
        assert_site(suspended_site)
        assert_status(suspended_site, "SUSPENDED", "approval_status")
        assert suspended_site["claim_hold"] is True, (
            "the suspension cascade must raise claim_hold on the site"
        )
        assert_status(suspended_site, "OPERATING", "operating_status")

        day_before = validate_success(
            api.get_meal_service_day(day["id"], REVIEWER_HEADERS)
        )
        assert_status(day_before, "PLANNED")

        response = _open_attempt(api, day, site["id"])
        validate_error(response, ApiErrorId.ERR_SITE_SUSPENDED.value)

        day_after = validate_success(
            api.get_meal_service_day(day["id"], REVIEWER_HEADERS)
        )
        assert_meal_service_day(day_after)
        assert_status(day_after, "PLANNED")
        assert day_after["production_counts"] is None, (
            "a rejected open must leave production_counts as the null a planned day carries, "
            f"got {day_after['production_counts']!r}"
        )
        assert day_after["food_received_at"] is None, (
            "a rejected open must not stamp food_received_at, "
            f"got {day_after['food_received_at']!r}"
        )
        assert day_after["version"] == day_before["version"], (
            "a rejected open mutates nothing, so the day's version must not advance"
        )

    def test_suspension_cascade_leaves_past_dated_planned_day_but_open_is_blocked(self, api):
        """PRD §3.5: "Then every service day of the site whose `status` is `PLANNED` and whose `service_date` is on or after the current logical clock date moves to `VOIDED` with `void_reason` set to the literal string `SITE_SUSPENDED`, along with every service day currently in `OPEN` regardless of its date, and `voided_day_count` grows by one for each day voided."

        Design: Difficulty/cross_entity_state_dependency/service_day_open_blocked_by_suspended_site
        """
        scenario, site, day = _baseline_with_past_planned_day()

        suspended_site = validate_success(
            api.decide_site_approval(
                site["id"],
                {"decision": "SUSPENDED", "reason": "Meals served outside the approved window."},
                REVIEWER_HEADERS,
            )
        )
        assert_site(suspended_site)
        assert_status(suspended_site, "SUSPENDED", "approval_status")
        assert suspended_site["voided_day_count"] == 0, (
            "the 2026-06-15 day predates the logical clock date, so the suspension cascade must "
            f"skip it, got voided_day_count {suspended_site['voided_day_count']}"
        )

        surviving_day = validate_success(
            api.get_meal_service_day(day["id"], REVIEWER_HEADERS)
        )
        assert_status(surviving_day, "PLANNED")
        assert surviving_day.get("void_reason") is None, (
            "a day the cascade skipped must not carry a void_reason"
        )

        response = _open_attempt(api, day, site["id"])
        validate_error(response, ApiErrorId.ERR_SITE_SUSPENDED.value)

        still_planned = validate_success(
            api.get_meal_service_day(day["id"], REVIEWER_HEADERS)
        )
        assert_status(still_planned, "PLANNED")

    def test_open_day_succeeds_after_suspended_site_is_reinstated(self, api):
        """PRD §3.5: "Reinstatement moves a `SUSPENDED` site back to `APPROVED`. A decision of `REINSTATED` requests it, and a decision of `APPROVED` recorded against a suspended site is treated as the same reinstatement request."

        Design: Difficulty/cross_entity_state_dependency/service_day_open_blocked_by_suspended_site
        """
        scenario, site, day = _baseline_with_past_planned_day()

        validate_success(
            api.decide_site_approval(
                site["id"],
                {"decision": "SUSPENDED", "reason": "Meals served outside the approved window."},
                REVIEWER_HEADERS,
            )
        )
        blocked = _open_attempt(api, day, site["id"])
        validate_error(blocked, ApiErrorId.ERR_SITE_SUSPENDED.value)

        reinstated = validate_success(
            api.decide_site_approval(site["id"], {"decision": "REINSTATED"}, REVIEWER_HEADERS)
        )
        assert_site(reinstated)
        assert_status(reinstated, "APPROVED", "approval_status")
        assert reinstated["claim_hold"] is False, "reinstatement must clear the site's claim hold"
        assert_status(reinstated, "OPERATING", "operating_status")

        opened = validate_success(_open_attempt(api, day, site["id"]))
        assert_meal_service_day(opened)
        assert_status(opened, "OPEN")
        assert opened["production_counts"] == {"LUNCH": 120}, (
            "opening stores the supplied production_counts, "
            f"got {opened['production_counts']!r}"
        )
        # The PRD says opening "stores both supplied values" without pinning how a client-supplied
        # instant is rendered back, so the instant is asserted rather than its exact serialization.
        assert opened["food_received_at"].startswith("2026-06-20T07:30:00"), (
            "opening stores the supplied food_received_at, "
            f"got {opened['food_received_at']!r}"
        )


class TestClaimSubmitGatedByBudgetState:
    """MealClaim -> SponsorBudget: submitting depends on the budget's current status."""

    def test_claim_submit_rejected_after_budget_amendment_revision_requested(self, api):
        """PRD §3.2: "The same decision against an `AMENDMENT_PENDING` budget also requires a `reason`, stores it in `decision_reason`, moves the budget to `REVISION_REQUESTED` — and additionally clears both `approved_operating_cost_cents` and `approved_admin_cost_cents` back to null, which is the material difference between the two revision branches: a rejected amendment withdraws the ceilings, while a first-round revision request never had ceilings to withdraw."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_by_budget_revision_requested
        """
        scenario = setup_june_claim_scenario()
        sponsor = scenario["sponsor"]
        claim = scenario["claim"]
        sponsor_headers = make_sponsor_admin_headers(sponsor["id"])

        amendment = submit_budget(scenario["budget"])
        assert_status(amendment, "AMENDMENT_PENDING")

        revised = decide_budget(
            scenario["budget"]["id"],
            decision="REVISION_REQUESTED",
            reason="The amended operating line is not supported by the revised meal projection.",
        )
        assert_sponsor_budget(revised)
        assert_status(revised, "REVISION_REQUESTED")
        assert revised["revision_round"] == 0, (
            "a revision request on an amendment does not advance revision_round, "
            f"got {revised['revision_round']}"
        )
        assert revised["approved_operating_cost_cents"] is None, (
            "the rejected amendment must withdraw approved_operating_cost_cents, "
            f"got {revised['approved_operating_cost_cents']!r}"
        )
        assert revised["approved_admin_cost_cents"] is None, (
            "the rejected amendment must withdraw approved_admin_cost_cents, "
            f"got {revised['approved_admin_cost_cents']!r}"
        )

        before = validate_success(api.get_meal_claim(claim["id"], sponsor_headers))
        assert_status(before, "DRAFT")

        response = api.submit_meal_claim(
            claim["id"],
            submit_claim_payload(
                claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=1_000
            ),
            sponsor_headers,
        )
        validate_error(response, ApiErrorId.ERR_BUDGET_NOT_APPROVED.value)

        unchanged = validate_success(api.get_meal_claim(claim["id"], sponsor_headers))
        assert_meal_claim(unchanged)
        assert_status(unchanged, "DRAFT")
        assert unchanged["submitted_at"] is None, (
            "a refused submission must not stamp submitted_at, "
            f"got {unchanged['submitted_at']!r}"
        )
        assert unchanged["version"] == before["version"], (
            "a refused submission mutates nothing, so the claim's version must not advance"
        )

    def test_claim_submit_accepted_while_budget_amendment_pending(self, api):
        """PRD §3.8: "The sponsor's budget for the claim's program year must be in `status` `APPROVED` or `AMENDMENT_PENDING`, or the attempt reports `ERR_BUDGET_NOT_APPROVED` — note that a budget under amendment still supports claiming, so the sponsor is not locked out while an amendment is pending."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_by_budget_revision_requested
        """
        scenario = setup_june_claim_scenario()
        claim = scenario["claim"]
        sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

        amendment = submit_budget(scenario["budget"])
        assert_sponsor_budget(amendment)
        assert_status(amendment, "AMENDMENT_PENDING")
        assert amendment["approved_operating_cost_cents"] == 4_500_000, (
            "an amendment under review leaves the previously approved operating ceiling in force, "
            f"got {amendment['approved_operating_cost_cents']!r}"
        )
        assert amendment["approved_admin_cost_cents"] == 700_000, (
            "an amendment under review leaves the previously approved admin ceiling in force, "
            f"got {amendment['approved_admin_cost_cents']!r}"
        )

        submitted = validate_success(
            api.submit_meal_claim(
                claim["id"],
                submit_claim_payload(
                    claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=1_000
                ),
                sponsor_headers,
            )
        )
        assert_meal_claim(submitted)
        assert_status(submitted, "SUBMITTED")
        assert submitted["is_late"] is False, (
            "a June claim submitted on 2026-07-06 is inside its 2026-08-31 filing window"
        )
        assert submitted["meals_rate_value_cents"] == 22_114, (
            "47 rural self-prep lunches at 470.50 cents round half-up to 22114 cents, "
            f"got {submitted['meals_rate_value_cents']}"
        )
        assert submitted["preliminary_reimbursement_cents"] == 23_114, (
            "the preliminary figure is the meals value plus the claimed admin cost with no caps, "
            f"got {submitted['preliminary_reimbursement_cents']}"
        )


class TestMealServiceWindowSeparation:
    """Meal service windows are half-open and demand a 60-minute rest interval."""

    @staticmethod
    def _two_meal_type_baseline():
        scenario = setup_program_baseline(
            site_overrides={"approved_meal_types": ["LUNCH", "PM_SNACK"]}
        )
        return scenario, scenario["site"]

    @staticmethod
    def _day_payload(site_id, service_date, snack_start, snack_end):
        return create_meal_service_day_payload(
            site_id,
            service_date,
            [
                meal_service(meal_type="LUNCH", planned_meals=150, **LUNCH_WINDOW),
                meal_service(
                    meal_type="PM_SNACK",
                    planned_meals=100,
                    service_start=snack_start,
                    service_end=snack_end,
                ),
            ],
        )

    def test_meal_service_windows_with_exactly_sixty_minute_gap_are_accepted(self, api):
        """PRD §3.6: "Each window is treated as a half-open interval that includes its `service_start` and excludes its `service_end`, no two windows may overlap, and when the windows are put in ascending order of `service_start`, the gap between the end of one window and the start of the next must be at least 60 minutes."

        Design: Difficulty/resource_temporal_overlap/meal_service_windows_half_open_require_sixty_minute_gap
        """
        scenario, site = self._two_meal_type_baseline()

        day = validate_success(
            api.create_meal_service_day(
                self._day_payload(site["id"], "2026-06-08", "13:30", "14:00"),
                make_site_supervisor_headers(site["id"]),
            ),
            201,
        )
        assert_meal_service_day(day)
        assert_status(day, "PLANNED")
        assert len(day["meal_services"]) == 2, (
            f"both planned services must be stored, got {day['meal_services']!r}"
        )
        windows = {
            service["meal_type"]: (service["service_start"], service["service_end"])
            for service in day["meal_services"]
        }
        assert windows["LUNCH"] == ("11:30", "12:30"), (
            f"the lunch window must be stored as supplied, got {windows.get('LUNCH')!r}"
        )
        assert windows["PM_SNACK"] == ("13:30", "14:00"), (
            "a snack starting exactly 60 minutes after lunch ends must be stored as supplied, "
            f"got {windows.get('PM_SNACK')!r}"
        )

    def test_meal_service_windows_with_thirty_minute_gap_are_rejected(self, api):
        """PRD §3.6: "Each window is treated as a half-open interval that includes its `service_start` and excludes its `service_end`, no two windows may overlap, and when the windows are put in ascending order of `service_start`, the gap between the end of one window and the start of the next must be at least 60 minutes."

        Design: Difficulty/resource_temporal_overlap/meal_service_windows_half_open_require_sixty_minute_gap
        """
        scenario, site = self._two_meal_type_baseline()
        supervisor_headers = make_site_supervisor_headers(site["id"])

        accepted = validate_success(
            api.create_meal_service_day(
                self._day_payload(site["id"], "2026-06-08", "13:30", "14:00"),
                supervisor_headers,
            ),
            201,
        )
        assert_status(accepted, "PLANNED")

        response = api.create_meal_service_day(
            self._day_payload(site["id"], "2026-06-09", "13:00", "13:30"),
            supervisor_headers,
        )
        validate_error(response, ApiErrorId.ERR_MEAL_SERVICE_WINDOW_CONFLICT.value)

        days, meta = validate_paginated(
            api.list_meal_service_days(REVIEWER_HEADERS, params={"site_id": site["id"]})
        )
        assert meta["total_count"] == 1, (
            "the rejected 2026-06-09 day must not be persisted, "
            f"got total_count {meta['total_count']}"
        )
        assert [record["service_date"] for record in days] == ["2026-06-08"], (
            f"only the accepted day may survive, got {[d['service_date'] for d in days]}"
        )

    def test_abutting_meal_service_windows_are_rejected(self, api):
        """PRD §3.6: "A gap of exactly 60 minutes is accepted; two windows that merely abut, with no gap at all, are rejected, as is any genuine overlap. Every one of these failures reports `ERR_MEAL_SERVICE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/meal_service_windows_half_open_require_sixty_minute_gap
        """
        scenario, site = self._two_meal_type_baseline()

        response = api.create_meal_service_day(
            self._day_payload(site["id"], "2026-06-08", "12:30", "13:00"),
            make_site_supervisor_headers(site["id"]),
        )
        validate_error(response, ApiErrorId.ERR_MEAL_SERVICE_WINDOW_CONFLICT.value)

        _, meta = validate_paginated(
            api.list_meal_service_days(REVIEWER_HEADERS, params={"site_id": site["id"]})
        )
        assert meta["total_count"] == 0, (
            "a snack window abutting the lunch window leaves nothing persisted, "
            f"got total_count {meta['total_count']}"
        )


class TestMonitorVisitWindowCollision:
    """A monitor's windows on one date are closed intervals, so touching endpoints collide."""

    MONITOR = "mon_1"
    VISIT_DATE = "2026-06-10"

    def _two_site_baseline(self):
        scenario = setup_program_baseline(site_count=2)
        return scenario, scenario["sites"][0], scenario["sites"][1]

    def _schedule(self, api, site_id, window_start, window_end):
        return api.create_monitoring_visit(
            create_monitoring_visit_payload(
                site_id,
                self.MONITOR,
                visit_type="FIRST_WEEK",
                scheduled_date=self.VISIT_DATE,
                window_start=window_start,
                window_end=window_end,
            ),
            make_field_monitor_headers(self.MONITOR),
        )

    def _list_visits(self, api):
        return validate_paginated(
            api.list_monitoring_visits(
                REVIEWER_HEADERS,
                params={"monitor_user_id": self.MONITOR, "scheduled_date": self.VISIT_DATE},
            )
        )

    def test_monitor_visit_window_touching_previous_end_is_rejected(self, api):
        """PRD §3.7: "A monitor's windows on one `scheduled_date` are treated as **closed** intervals that include both `window_start` and `window_end`, with no buffer between them: two windows collide when they share any instant at all, so a window beginning at exactly the moment another one ends is rejected, and the collision is reported as `ERR_MONITOR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/monitor_visit_windows_closed_intervals_collide_at_touching_endpoints
        """
        scenario, site_a, site_b = self._two_site_baseline()

        first = validate_success(self._schedule(api, site_a["id"], "09:00", "11:00"), 201)
        assert_monitoring_visit(first)
        assert_status(first, "SCHEDULED")

        response = self._schedule(api, site_b["id"], "11:00", "12:00")
        validate_error(response, ApiErrorId.ERR_MONITOR_SCHEDULE_CONFLICT.value)

        visits, meta = self._list_visits(api)
        assert meta["total_count"] == 1, (
            "the colliding 11:00-12:00 visit must not be persisted, "
            f"got total_count {meta['total_count']}"
        )
        assert [visit["window_start"] for visit in visits] == ["09:00"], (
            f"only the original window may survive, got {[v['window_start'] for v in visits]}"
        )

    def test_monitor_visit_window_one_minute_after_previous_end_is_accepted(self, api):
        """PRD §3.7: "Note the deliberate contrast with meal service windows on a service day, which are half-open and additionally demand a 60-minute gap — a monitor's back-to-back windows fail for touching, whereas meal services fail unless they are a full hour apart."

        Design: Difficulty/resource_temporal_overlap/monitor_visit_windows_closed_intervals_collide_at_touching_endpoints
        """
        scenario, site_a, site_b = self._two_site_baseline()

        validate_success(self._schedule(api, site_a["id"], "09:00", "11:00"), 201)
        validate_error(
            self._schedule(api, site_b["id"], "11:00", "12:00"),
            ApiErrorId.ERR_MONITOR_SCHEDULE_CONFLICT.value,
        )

        accepted = validate_success(self._schedule(api, site_b["id"], "11:01", "12:00"), 201)
        assert_monitoring_visit(accepted)
        assert_status(accepted, "SCHEDULED")
        assert accepted["window_start"] == "11:01", (
            f"the accepted window must start at 11:01, got {accepted['window_start']!r}"
        )
        assert accepted["window_end"] == "12:00", (
            f"the accepted window must end at 12:00, got {accepted['window_end']!r}"
        )
        assert accepted["monitor_user_id"] == self.MONITOR, (
            "the visit must be recorded against the scheduling monitor, "
            f"got {accepted['monitor_user_id']!r}"
        )

        _, meta = self._list_visits(api)
        assert meta["total_count"] == 2, (
            "the monitor holds the original visit plus the one-minute-later window, "
            f"got total_count {meta['total_count']}"
        )
