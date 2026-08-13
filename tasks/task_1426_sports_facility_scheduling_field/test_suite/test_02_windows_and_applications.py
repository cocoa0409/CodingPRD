"""Allocation-window lifecycle, application intake validation, the review
info-loop, and the window-state dependency of the allocation run."""
from test_helpers import (
    ApiErrorId,
    assert_permit_application,
    close_allocation_window,
    create_allocation_window,
    create_application_payload,
    get_application,
    get_permit_for_application,
    make_org_coordinator_headers,
    run_allocation,
    set_clock,
    setup_awarded_permit,
    setup_open_season,
    submit_application,
    validate_error,
    validate_success,
)


class TestWindowOpenClose:
    def test_window_open_before_opens_at_rejected(self, api, athletics_admin_headers):
        """PRD §3.4: "An administrator opens a `SCHEDULED` window only once the
        logical clock has reached `opens_at`; opening earlier fails with
        `ERR_WINDOW_NOT_YET_OPEN`, and opening, closing, or running allocation on a
        window in the wrong state fails with `ERR_INVALID_WINDOW_STATE`."

        The logical clock (2026-08-01T09:00) sits before opens_at (2026-08-05), so the
        open is rejected and the window stays SCHEDULED.

        Design: Corner/state_machines/window_open_before_opens_at_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        window = create_allocation_window(opens_at="2026-08-05T00:00:00Z")
        res = api.open_allocation_window(window["id"], athletics_admin_headers)
        validate_error(res, ApiErrorId.ERR_WINDOW_NOT_YET_OPEN)
        after = validate_success(
            api.get_allocation_window(window["id"], athletics_admin_headers), 200)
        assert after["status"] == "SCHEDULED"

    def test_window_close_sweeps_submitted_applications(self, api, athletics_admin_headers):
        """PRD §3.4: "Closing an `OPEN` window sweeps every application still
        `SUBMITTED` under that window into `UNDER_REVIEW` within the same request,
        each application's `version` incrementing as it moves."
        PRD §3.4: "The owning coordinator may also withdraw an application from
        `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, or `WAITLISTED`, landing it in the
        terminal `WITHDRAWN` state."

        The sweep is conditional on the child's state: the already-WITHDRAWN second
        application is untouched.

        Design: Corner/state_machines/window_close_sweeps_submitted_applications
        """
        ctx = setup_open_season(publish_schedule=False)
        org_id = ctx["organization"]["id"]
        app1 = submit_application(ctx["window"]["id"], ctx["facility"]["id"], org_id)
        app2 = submit_application(ctx["window"]["id"], ctx["facility"]["id"], org_id,
                                  event_date="2026-08-11")
        withdrawn = validate_success(api.withdraw_application(
            app2["id"], make_org_coordinator_headers(org_id)), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        validate_success(api.close_allocation_window(ctx["window"]["id"],
                                                     athletics_admin_headers), 200)
        after1 = get_application(app1["id"])
        after2 = get_application(app2["id"])
        assert after1["status"] == "UNDER_REVIEW", "close must sweep SUBMITTED applications"
        assert after2["status"] == "WITHDRAWN", "sweep must skip non-SUBMITTED applications"

    def test_run_allocation_twice_rejected(self, api, athletics_admin_headers):
        """PRD §3.4: "An administrator opens a `SCHEDULED` window only once the
        logical clock has reached `opens_at`; opening earlier fails with
        `ERR_WINDOW_NOT_YET_OPEN`, and opening, closing, or running allocation on a
        window in the wrong state fails with `ERR_INVALID_WINDOW_STATE`."
        PRD §3.5: "Each affected facility's `weekly_prime_hours_used` is recomputed,
        every created or mutated entity's `version` increments, and the run leaves the
        window `ALLOCATED`, a terminal state."

        A second run against the terminal ALLOCATED window is rejected and no
        duplicate permit is produced.

        Design: Corner/state_machines/run_allocation_twice_rejected
        """
        ctx = setup_awarded_permit()
        assert get_application(ctx["application"]["id"])["status"] == "AWARDED"
        res = api.run_allocation(ctx["window"]["id"], athletics_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW_STATE)
        permits = validate_success(api.list_permits(
            athletics_admin_headers,
            params={"application_id": ctx["application"]["id"]}), 200)
        assert len(permits) == 1, "rejected second run must not duplicate the award"


class TestApplicationIntakeValidation:
    def test_application_missing_required_field_returns_invalid_request(
            self, api, org_coordinator_headers):
        """PRD §2.8: "The body must parse, all required input fields must be present,
        every enum value must be among its declared members, and every integer must
        lie inside its declared range — otherwise `ERR_INVALID_REQUEST` (400)."
        PRD §3.4: "While a window is `OPEN` — submissions at any other time fail with
        `ERR_WINDOW_NOT_OPEN` — an `OrgCoordinator` files an application naming the
        `window_id`, the requested `facility_id`, the `event_date` as a YYYY-MM-DD
        calendar date, `start_minute` and `end_minute` as minutes from midnight
        forming the half-open slot of §2.9, an `event_type` of `LEAGUE_GAME`,
        `LEAGUE_PRACTICE`, `TOURNAMENT`, or `SPECIAL_EVENT`, an optional
        `wants_lights` flag that defaults to false, and a `headcount` of at least 1."

        Omitting facility_id fails at intake and nothing is persisted.

        Design: Corner/entities/application_missing_required_field_returns_invalid_request
        """
        ctx = setup_open_season(publish_schedule=False)
        org_id = ctx["organization"]["id"]
        payload = create_application_payload(ctx["window"]["id"], None)
        del payload["facility_id"]
        res = api.create_permit_application(payload, make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        persisted = validate_success(api.list_permit_applications(
            org_coordinator_headers, params={"window_id": ctx["window"]["id"]}), 200)
        assert persisted == [], "rejected application must not be persisted"

    def test_application_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.8: "The body must parse, all required input fields must be present,
        every enum value must be among its declared members, and every integer must
        lie inside its declared range — otherwise `ERR_INVALID_REQUEST` (400)."
        PRD §3.4: "While a window is `OPEN` — submissions at any other time fail with
        `ERR_WINDOW_NOT_OPEN` — an `OrgCoordinator` files an application naming the
        `window_id`, the requested `facility_id`, the `event_date` as a YYYY-MM-DD
        calendar date, `start_minute` and `end_minute` as minutes from midnight
        forming the half-open slot of §2.9, an `event_type` of `LEAGUE_GAME`,
        `LEAGUE_PRACTICE`, `TOURNAMENT`, or `SPECIAL_EVENT`, an optional
        `wants_lights` flag that defaults to false, and a `headcount` of at least 1."

        event_type SCRIMMAGE is outside the declared enum.

        Design: Corner/entities/application_invalid_enum_returns_invalid_request
        """
        ctx = setup_open_season(publish_schedule=False)
        org_id = ctx["organization"]["id"]
        payload = create_application_payload(
            ctx["window"]["id"], ctx["facility"]["id"], event_type="SCRIMMAGE")
        res = api.create_permit_application(payload, make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_application_outside_open_window_rejected(self, api):
        """PRD §3.4: "While a window is `OPEN` — submissions at any other time fail
        with `ERR_WINDOW_NOT_OPEN` — an `OrgCoordinator` files an application naming
        the `window_id`, the requested `facility_id`, the `event_date` as a YYYY-MM-DD
        calendar date, `start_minute` and `end_minute` as minutes from midnight
        forming the half-open slot of §2.9, an `event_type` of `LEAGUE_GAME`,
        `LEAGUE_PRACTICE`, `TOURNAMENT`, or `SPECIAL_EVENT`, an optional
        `wants_lights` flag that defaults to false, and a `headcount` of at least 1."

        The target window is still SCHEDULED (never opened).

        Design: Corner/validations/application_outside_open_window_rejected
        """
        ctx = setup_open_season(publish_schedule=False)
        # A second window that is never opened stays SCHEDULED.
        scheduled_window = create_allocation_window(season_code="2026-WINTER")
        org_id = ctx["organization"]["id"]
        payload = create_application_payload(
            scheduled_window["id"], ctx["facility"]["id"])
        res = api.create_permit_application(payload, make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_WINDOW_NOT_OPEN)

    def test_headcount_over_capacity_rejected(self, api):
        """PRD §3.4: "A requested slot starting at or before the logical clock is
        rejected with `ERR_SLOT_IN_PAST`, a `headcount` above the facility's
        `capacity` with `ERR_HEADCOUNT_EXCEEDS_CAPACITY`, and a `CLOSED` facility with
        `ERR_FACILITY_CLOSED`."
        PRD §3.2: "Administrators register each facility with a `name`; a
        `facility_class` of `DIAMOND`, `RECTANGLE`, or `MULTIPURPOSE`; a `has_lights`
        flag indicating whether a lights grid exists; a `capacity` of at least 1,
        which is the occupancy safety limit enforced at application time; a
        `weekly_prime_hour_cap` of at least 1 per §2.9; and a
        `nightly_light_block_cap` of at least 1 bounding the cost-recovery budget for
        lights per date."

        headcount 121 against capacity 120 fails the occupancy safety gate.

        Design: Corner/validations/headcount_over_capacity_rejected
        """
        ctx = setup_open_season(publish_schedule=False)
        org_id = ctx["organization"]["id"]
        payload = create_application_payload(
            ctx["window"]["id"], ctx["facility"]["id"], headcount=121)
        res = api.create_permit_application(payload, make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_HEADCOUNT_EXCEEDS_CAPACITY)

    def test_slot_in_past_rejected(self, api):
        """PRD §3.4: "A requested slot starting at or before the logical clock is
        rejected with `ERR_SLOT_IN_PAST`, a `headcount` above the facility's
        `capacity` with `ERR_HEADCOUNT_EXCEEDS_CAPACITY`, and a `CLOSED` facility with
        `ERR_FACILITY_CLOSED`."

        With the clock at 2026-08-10T09:00, a slot on 2026-08-05 starts before it even
        though the window is OPEN.

        Design: Corner/errors/slot_in_past_rejected
        """
        ctx = setup_open_season(publish_schedule=False)
        set_clock("2026-08-10T09:00:00Z")
        org_id = ctx["organization"]["id"]
        payload = create_application_payload(
            ctx["window"]["id"], ctx["facility"]["id"], event_date="2026-08-05")
        res = api.create_permit_application(payload, make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_SLOT_IN_PAST)

    def test_invalid_time_range_rejected(self, api):
        """PRD §3.4: "The `start_minute` must lie between 0 and 1439, the `end_minute`
        must be strictly later than `start_minute` and no greater than 1440, and the
        slot must last at least 30 minutes and at most 480 minutes; violations are
        rejected with `ERR_INVALID_TIME_RANGE`."

        The zero-length slot (end_minute == start_minute == 1200) is rejected.

        Design: Corner/errors/invalid_time_range_rejected
        """
        ctx = setup_open_season(publish_schedule=False)
        org_id = ctx["organization"]["id"]
        payload = create_application_payload(
            ctx["window"]["id"], ctx["facility"]["id"],
            start_minute=1200, end_minute=1200)
        res = api.create_permit_application(payload, make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_INVALID_TIME_RANGE)


class TestAwardRequiresClosedWindow:
    def test_run_allocation_while_open_rejected(self, api, athletics_admin_headers):
        """PRD §3.5: "Running allocation on a `CLOSED` window — which requires a
        `PUBLISHED` fee schedule to exist, failing with `ERR_INVALID_SCHEDULE_STATE`
        otherwise — walks every application of the window that is in `UNDER_REVIEW` in
        a deterministic order: `final_score` descending, with ties broken by earlier
        `created_at`."
        PRD §3.4: "An administrator opens a `SCHEDULED` window only once the logical
        clock has reached `opens_at`; opening earlier fails with
        `ERR_WINDOW_NOT_YET_OPEN`, and opening, closing, or running allocation on a
        window in the wrong state fails with `ERR_INVALID_WINDOW_STATE`."

        The run requires the CLOSED window state; while OPEN it is rejected and the
        application (still SUBMITTED — the sweep happens only on close) is untouched.

        Design: Difficulty/cross_entity_state_dependency/application_award_requires_window_closed
        """
        ctx = setup_open_season()
        org_id = ctx["organization"]["id"]
        application = submit_application(
            ctx["window"]["id"], ctx["facility"]["id"], org_id)
        res = api.run_allocation(ctx["window"]["id"], athletics_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW_STATE)
        after = get_application(application["id"])
        assert after["status"] == "SUBMITTED", \
            "rejected run must not sweep or decide the application"

    def test_close_then_run_awards_application(self, api, athletics_admin_headers):
        """PRD §3.5: "An application passing every gate is awarded, and the award fans
        out into several records at once. The system creates a Permit in `RESERVED`
        status with `fee_schedule_id` pinned to the currently `PUBLISHED` schedule,
        computes the provisional fee quote of §3.6 onto the permit, and decides lights
        per the grid rules of §2.9 — a buffer conflict or a breached nightly cap never
        blocks the award itself; the permit is simply awarded with `lights_approved`
        false and `lights_minutes_quoted` 0."
        PRD §3.5: "Each affected facility's `weekly_prime_hours_used` is recomputed,
        every created or mutated entity's `version` increments, and the run leaves the
        window `ALLOCATED`, a terminal state."

        After close sweeps the application to UNDER_REVIEW, the run awards it: window
        ALLOCATED, application AWARDED, permit RESERVED with the pinned schedule.

        Design: Difficulty/cross_entity_state_dependency/application_award_requires_window_closed
        """
        ctx = setup_open_season()
        org_id = ctx["organization"]["id"]
        application = submit_application(
            ctx["window"]["id"], ctx["facility"]["id"], org_id)
        close_allocation_window(ctx["window"]["id"])
        assert get_application(application["id"])["status"] == "UNDER_REVIEW"
        window = run_allocation(ctx["window"]["id"])
        assert window["status"] == "ALLOCATED"
        after = get_application(application["id"])
        assert_permit_application(after)
        assert after["status"] == "AWARDED"
        permit = get_permit_for_application(application["id"])
        assert permit["status"] == "RESERVED"
        assert permit["fee_schedule_id"] == ctx["schedule"]["id"]


class TestInfoRequestCycle:
    def test_info_request_cycle_traversed_twice(self, api, athletics_admin_headers):
        """PRD §3.4: "An administrator reviewing an `UNDER_REVIEW` application may
        push it to `NEEDS_INFO` with a `note`, which is recorded as the application's
        `decision_note`; this is only possible while the parent window is `CLOSED`.
        The owning coordinator then answers with a `response_note`, returning the
        application `NEEDS_INFO` → `UNDER_REVIEW`, and the loop may repeat without
        limit."

        Two full request-info/respond loops traverse NEEDS_INFO → UNDER_REVIEW twice
        without terminating the application.

        Design: Difficulty/non_linear_state_machine/application_info_request_cycle_twice
        """
        ctx = setup_open_season()
        org_id = ctx["organization"]["id"]
        application = submit_application(
            ctx["window"]["id"], ctx["facility"]["id"], org_id)
        close_allocation_window(ctx["window"]["id"])
        app_id = application["id"]
        coordinator = make_org_coordinator_headers(org_id)

        first = validate_success(api.request_info(
            app_id, {"note": "Need roster proof"}, athletics_admin_headers), 200)
        assert first["status"] == "NEEDS_INFO"
        assert first["decision_note"] == "Need roster proof"
        second = validate_success(api.respond_to_info(
            app_id, {"response_note": "Roster attached"}, coordinator), 200)
        assert second["status"] == "UNDER_REVIEW"

        third = validate_success(api.request_info(
            app_id, {"note": "Need insurance cert"}, athletics_admin_headers), 200)
        assert third["status"] == "NEEDS_INFO"
        assert third["decision_note"] == "Need insurance cert"
        fourth = validate_success(api.respond_to_info(
            app_id, {"response_note": "Cert attached"}, coordinator), 200)
        assert fourth["status"] == "UNDER_REVIEW", \
            "the info loop must be re-traversable without terminating the application"

    def test_info_loop_then_allocation_still_awards(self, api, athletics_admin_headers):
        """PRD §3.4: "The owning coordinator then answers with a `response_note`,
        returning the application `NEEDS_INFO` → `UNDER_REVIEW`, and the loop may
        repeat without limit."
        PRD §3.5: "Running allocation on a `CLOSED` window — which requires a
        `PUBLISHED` fee schedule to exist, failing with `ERR_INVALID_SCHEDULE_STATE`
        otherwise — walks every application of the window that is in `UNDER_REVIEW` in
        a deterministic order: `final_score` descending, with ties broken by earlier
        `created_at`."

        The cyclic review path still exits to AWARDED at the allocation run.

        Design: Difficulty/non_linear_state_machine/application_info_request_cycle_twice
        """
        ctx = setup_open_season()
        org_id = ctx["organization"]["id"]
        application = submit_application(
            ctx["window"]["id"], ctx["facility"]["id"], org_id)
        close_allocation_window(ctx["window"]["id"])
        app_id = application["id"]
        coordinator = make_org_coordinator_headers(org_id)
        for note, response in (("Need roster proof", "Roster attached"),
                               ("Need insurance cert", "Cert attached")):
            validate_success(api.request_info(app_id, {"note": note},
                                              athletics_admin_headers), 200)
            validate_success(api.respond_to_info(app_id, {"response_note": response},
                                                 coordinator), 200)
        run_allocation(ctx["window"]["id"])
        after = get_application(app_id)
        assert after["status"] == "AWARDED", \
            "two info loops must not terminate award eligibility"


class TestWithdrawRules:
    def test_withdraw_awarded_application_rejected(self, api, athletics_admin_headers):
        """PRD §3.4: "The owning coordinator may also withdraw an application from
        `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, or `WAITLISTED`, landing it in the
        terminal `WITHDRAWN` state."
        PRD §3.4: "Acting on an application that is not in the expected from-state —
        requesting information from a `SUBMITTED` application, say — fails with
        `ERR_INVALID_APPLICATION_STATE`, and a coordinator acting on another
        organization's application fails with `ERR_FORBIDDEN_ORG_OWNERSHIP`."

        AWARDED is terminal for the application: the withdraw is rejected and the
        application remains AWARDED.

        Design: Corner/state_machines/withdraw_awarded_application_rejected
        """
        ctx = setup_awarded_permit()
        org_id = ctx["organization"]["id"]
        app_id = ctx["application"]["id"]
        assert ctx["application"]["status"] == "AWARDED"
        res = api.withdraw_application(app_id, make_org_coordinator_headers(org_id))
        validate_error(res, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
        after = get_application(app_id)
        assert after["status"] == "AWARDED", "rejected withdraw must not move the application"
