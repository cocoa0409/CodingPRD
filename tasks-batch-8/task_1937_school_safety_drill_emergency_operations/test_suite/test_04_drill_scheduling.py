"""Drill scheduling: creation rules, scheduling conflicts, start gates, and
site drill-counter bookkeeping."""
from test_helpers import (
    ApiErrorId,
    assert_drill_counter_sum,
    assert_drill_event,
    create_drill_payload,
    create_drill_requirement,
    get_drill,
    get_site,
    schedule_drill,
    set_clock,
    setup_active_eop_site,
    setup_site_with_requirement,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDrillCreation:
    def test_drill_initial_state_scheduled(self, api, officer_headers):
        """PRD: "Upon creation the drill's `status` is set to `SCHEDULED`, all roster counters (`roster_total`, `unaccounted_count`, `accounted_count`, `released_count`) initialize to zero, the site's drill counters recompute, and any ComplianceReport at the site in `DRAFT` status whose period contains the drill's `scheduled_date` transitions to `STALE`."

        Design: Corner/state_machines/drill_initial_state_scheduled
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        resp = api.create_drill_event(
            create_drill_payload(site_id=ctx["site"]["id"],
                                 announcement_mode="ANNOUNCED"),
            officer_headers,
        )
        drill = validate_success(resp, 201)
        assert_drill_event(drill)
        assert drill["status"] == "SCHEDULED"
        assert drill["roster_total"] == 0
        assert drill["unaccounted_count"] == 0
        assert drill["accounted_count"] == 0
        assert drill["released_count"] == 0
        assert drill["announcement_mode"] == "ANNOUNCED"

    def test_drill_create_invalid_enum_returns_invalid_request(
            self, api, officer_headers):
        """PRD: "(4) input validation — required fields present, types correct, enum members valid, date and datetime formats valid, unknown top-level fields rejected, and conditional requirements enforced (such as `return_reason` required when `decision` is `RETURN`), else `ERR_VALIDATION`"

        Design: Corner/entities/drill_create_invalid_enum_returns_invalid_request
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        resp = api.create_drill_event(
            create_drill_payload(site_id=ctx["site"]["id"],
                                 drill_type="FIREDRILL"),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_requirement_not_configured_rejected(self, api, officer_headers):
        """PRD: "First, a DrillTypeRequirement must exist for the combination of site and drill type; otherwise the creation is rejected with `ERR_REQUIREMENT_NOT_CONFIGURED`."

        Design: Corner/errors/requirement_not_configured_rejected
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        resp = api.create_drill_event(
            create_drill_payload(site_id=ctx["site"]["id"],
                                 drill_type="LOCKDOWN"),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_CONFIGURED)

    def test_drill_outside_academic_year_rejected(self, api, officer_headers):
        """PRD: "A `SchoolSafetyOfficer` schedules a **DrillEvent** by specifying the `site_id`, the `drill_type`, a `scheduled_date` that must lie within the site's academic year (bounded by `academic_year_start` and `academic_year_end`, inclusive; a date outside is rejected with `ERR_OUTSIDE_ACADEMIC_YEAR`), a `scheduled_start_time` in 24-hour HH:MM format, and a `duration_minutes` (at least 1) defining the planned length."

        Design: Corner/validations/drill_outside_academic_year_rejected
        """
        ctx = setup_site_with_requirement(site_name="Harborview Middle",
                                          enrollment_count=700)
        resp = api.create_drill_event(
            create_drill_payload(site_id=ctx["site"]["id"],
                                 scheduled_date="2027-07-15"),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_ACADEMIC_YEAR)

    def test_auditor_cannot_schedule_drill_returns_forbidden(
            self, api, auditor_headers):
        """PRD: "A request whose role is not listed as authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: POST /drill-events is authorized for SchoolSafetyOfficer only.

        Design: Corner/rbac/auditor_cannot_schedule_drill_returns_forbidden
        """
        ctx = setup_site_with_requirement(site_name="Harborview Middle",
                                          enrollment_count=700)
        resp = api.create_drill_event(
            create_drill_payload(site_id=ctx["site"]["id"]), auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestDrillHalfOpenOverlap:
    def test_drill_half_open_adjacent_interval_allowed(self, api):
        """PRD: "Second, the drill's half-open time interval — beginning at `scheduled_start_time` and extending `duration_minutes` — must not overlap any other drill at the same site that is in `SCHEDULED` or `IN_PROGRESS` status. Two drills whose intervals merely touch (one ends exactly when the other begins) do not overlap. An actual overlap is rejected with `ERR_DRILL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/drill_half_open_overlap_adjacency
        """
        site_ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                               enrollment_count=850,
                                               requirement_overrides={
                                                   "min_spacing_days": 0})
        site_id = site_ctx["site"]["id"]
        create_drill_requirement(site_id, drill_type="LOCKDOWN",
                                 min_spacing_days=0, target_evac_seconds=240)

        drill_a = schedule_drill(site_id, drill_type="FIRE",
                                 scheduled_date="2026-09-15",
                                 scheduled_start_time="09:00",
                                 duration_minutes=30)
        assert drill_a["status"] == "SCHEDULED"

        # [09:30, 10:00) touches [09:00, 09:30) exactly — allowed.
        drill_b = schedule_drill(site_id, drill_type="LOCKDOWN",
                                 scheduled_date="2026-09-15",
                                 scheduled_start_time="09:30",
                                 duration_minutes=30)
        assert drill_b["status"] == "SCHEDULED", (
            "Adjacent (touching) half-open intervals must not overlap")

        site = get_site(site_id)
        assert site["drills_scheduled_count"] == 2
        assert_drill_counter_sum(site, 2)

    def test_drill_half_open_intersecting_interval_rejected(self, api,
                                                            officer_headers):
        """PRD: "Second, the drill's half-open time interval — beginning at `scheduled_start_time` and extending `duration_minutes` — must not overlap any other drill at the same site that is in `SCHEDULED` or `IN_PROGRESS` status. Two drills whose intervals merely touch (one ends exactly when the other begins) do not overlap. An actual overlap is rejected with `ERR_DRILL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/drill_half_open_overlap_adjacency
        """
        site_ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                               enrollment_count=850,
                                               requirement_overrides={
                                                   "min_spacing_days": 0})
        site_id = site_ctx["site"]["id"]
        create_drill_requirement(site_id, drill_type="LOCKDOWN",
                                 min_spacing_days=0, target_evac_seconds=240)

        schedule_drill(site_id, drill_type="FIRE", scheduled_date="2026-09-15",
                       scheduled_start_time="09:00", duration_minutes=30)
        schedule_drill(site_id, drill_type="LOCKDOWN",
                       scheduled_date="2026-09-15", scheduled_start_time="09:30",
                       duration_minutes=30)

        # [09:29, 09:59) intersects both existing intervals — rejected.
        resp = api.create_drill_event(
            create_drill_payload(site_id=site_id, drill_type="LOCKDOWN",
                                 scheduled_date="2026-09-15",
                                 scheduled_start_time="09:29",
                                 duration_minutes=30),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRILL_OVERLAP)

        site = get_site(site_id)
        assert site["drills_scheduled_count"] == 2, (
            "The rejected overlapping drill must not be persisted")


class TestDrillStartGates:
    def test_no_active_eop_blocks_start(self, api, officer_headers):
        """PRD: "Starting requires that logical today equals the drill's `scheduled_date` (else `ERR_DRILL_NOT_TODAY`) and that the site has an EmergencyOperationsPlan in `ACTIVE` status (else `ERR_NO_ACTIVE_EOP`)."

        Design: Corner/validations/no_active_eop_blocks_start
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        set_clock("2026-09-15T09:00:00Z")

        resp = api.start_drill(drill["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_EOP)

        current = get_drill(drill["id"])
        assert current["status"] == "SCHEDULED"

    def test_drill_not_today_rejected(self, api, officer_headers):
        """PRD: "Starting requires that logical today equals the drill's `scheduled_date` (else `ERR_DRILL_NOT_TODAY`) and that the site has an EmergencyOperationsPlan in `ACTIVE` status (else `ERR_NO_ACTIVE_EOP`)."

        Design: Corner/validations/drill_not_today_rejected
        """
        ctx = setup_active_eop_site(site_name="Cedar Grove High",
                                    enrollment_count=1200)
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        # Wrong day, but BEFORE the scheduled date so the MISSED sweep cannot fire.
        set_clock("2026-09-14T08:00:00Z")

        resp = api.start_drill(drill["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_DRILL_NOT_TODAY)

        current = get_drill(drill["id"])
        assert current["status"] == "SCHEDULED"

    def test_safety_gate_beats_temporal_gate_on_start_error(self, api,
                                                            officer_headers):
        """PRD: "When multiple validation rules apply to a single request, the system evaluates them in a strict priority order, and the first failing rule determines the error response."
        PRD: "(6) safety gates — active-EOP, accommodation-plan, pickup-verification, and roster-completeness gates, each with its own error ID; (7) temporal gates — academic-year containment and day-of-drill checks"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_drill_start
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        # No plan exists at the site (safety failure) AND logical today is the
        # wrong day (temporal failure): priority 6 must beat priority 7.
        set_clock("2026-09-14T08:00:00Z")

        resp = api.start_drill(drill["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_EOP)

    def test_safety_gate_beats_temporal_gate_on_start_state_unchanged(
            self, api, officer_headers):
        """PRD: "Starting moves the drill from `SCHEDULED` to `IN_PROGRESS`, stamps `actual_start_at` with the logical timestamp, and records `conducted_by_user_id` from the `X-User-ID` header."
        PRD: "(5) state validity — the target resource must be in a state from which the requested transition exists, else `ERR_INVALID_STATE`; (6) safety gates — active-EOP, accommodation-plan, pickup-verification, and roster-completeness gates, each with its own error ID; (7) temporal gates — academic-year containment and day-of-drill checks"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_drill_start
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        set_clock("2026-09-14T08:00:00Z")

        resp = api.start_drill(drill["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_EOP)

        current = get_drill(drill["id"])
        assert current["status"] == "SCHEDULED", (
            "A start rejected at the safety gate must leave the drill SCHEDULED")
        assert current.get("actual_start_at") in (None, ""), (
            "actual_start_at must not be stamped by a rejected start")


class TestDrillCounterBuckets:
    def test_drill_status_bucket_conservation_counters(self, api,
                                                       officer_headers):
        """PRD: "`drills_scheduled_count` counts drills in `SCHEDULED` or `IN_PROGRESS` status. `drills_completed_count` counts drills in `COMPLETED` or `CLOSED` status. `drills_missed_count` counts drills in `MISSED` status. `drills_cancelled_count` counts drills in `CANCELLED` status."
        PRD: "Cancellation is available while a drill is `SCHEDULED`. Cancelling moves it to `CANCELLED` (terminal), optionally recording a `reason`."

        Design: Difficulty/compensating_invariant/drill_status_bucket_conservation
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        site_id = ctx["site"]["id"]
        schedule_drill(site_id, scheduled_date="2026-09-15")
        drill_b = schedule_drill(site_id, scheduled_date="2026-09-16")

        resp = api.cancel_drill(drill_b["id"], {"reason": "Weather closure"},
                                officer_headers)
        cancelled = validate_success(resp, 200)
        assert cancelled["status"] == "CANCELLED"

        site = get_site(site_id)
        assert site["drills_scheduled_count"] == 1
        assert site["drills_cancelled_count"] == 1
        assert site["drills_completed_count"] == 0
        assert site["drills_missed_count"] == 0

    def test_drill_status_bucket_conservation_invariant(self, api,
                                                        officer_headers):
        """PRD: "The four counters always sum to the total number of drills ever created in scope — no delete endpoint exists, so scheduling then cancelling moves one unit between buckets without drift."

        Design: Difficulty/compensating_invariant/drill_status_bucket_conservation
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        site_id = ctx["site"]["id"]
        schedule_drill(site_id, scheduled_date="2026-09-15")
        drill_b = schedule_drill(site_id, scheduled_date="2026-09-16")
        api.cancel_drill(drill_b["id"], {"reason": "Weather closure"},
                         officer_headers)

        site = get_site(site_id)
        assert_drill_counter_sum(site, 2)

    def test_cancel_missed_drill_returns_invalid_state(self, api,
                                                       officer_headers):
        """PRD: "Cancellation is available while a drill is `SCHEDULED`. Cancelling moves it to `CANCELLED` (terminal), optionally recording a `reason`."
        PRD: "if logical today passes a drill's `scheduled_date` while the drill is still `SCHEDULED` or `IN_PROGRESS`, the drill transitions to `MISSED`."

        Design: Corner/state_machines/cancel_missed_drill_returns_invalid_state
        """
        ctx = setup_site_with_requirement(site_name="Harborview Middle",
                                          enrollment_count=700)
        site_id = ctx["site"]["id"]
        drill = schedule_drill(site_id, scheduled_date="2026-09-10")
        set_clock("2026-09-11T00:00:00Z")

        current = get_drill(drill["id"])
        assert current["status"] == "MISSED"

        resp = api.cancel_drill(drill["id"], {}, officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_drill(drill["id"])
        assert after["status"] == "MISSED", (
            "A MISSED drill is terminal and must not move to CANCELLED")
        site = get_site(site_id)
        assert site["drills_missed_count"] == 1


class TestImmediateConsistencyAndListing:
    def test_immediate_visibility_after_mutation(self, api):
        """PRD: "Upon creation the drill's `status` is set to `SCHEDULED`, all roster counters (`roster_total`, `unaccounted_count`, `accounted_count`, `released_count`) initialize to zero, the site's drill counters recompute, and any ComplianceReport at the site in `DRAFT` status whose period contains the drill's `scheduled_date` transitions to `STALE`."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        ctx = setup_site_with_requirement(site_name="Maplewood K-8",
                                          enrollment_count=850)
        drill = schedule_drill(ctx["site"]["id"], scheduled_date="2026-09-15")
        assert drill["status"] == "SCHEDULED"

        site = get_site(ctx["site"]["id"])
        assert site["drills_scheduled_count"] == 1, (
            "An immediate read must already reflect the created drill")

    def test_drill_list_filter_and_pagination(self, api, officer_headers):
        """PRD: "The drill list for a site supports filtering by `status` and `drill_type`, as well as date-range filtering via `scheduled_date_from` and `scheduled_date_to` to narrow results to drills whose `scheduled_date` falls within the supplied bounds."
        PRD: "The `meta` object of every list response includes four fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/drill_list_filter_and_pagination
        """
        ctx = setup_site_with_requirement(
            site_name="Harborview Middle", enrollment_count=700,
            requirement_overrides={"required_per_year": 4,
                                   "min_spacing_days": 0})
        site_id = ctx["site"]["id"]
        schedule_drill(site_id, scheduled_date="2026-09-15")
        schedule_drill(site_id, scheduled_date="2026-09-16")
        drill_c = schedule_drill(site_id, scheduled_date="2026-09-17")
        cancel = api.cancel_drill(drill_c["id"], {}, officer_headers)
        validate_success(cancel, 200)

        filtered, meta = validate_paginated(api.list_drill_events(
            site_id, officer_headers, params={"status": "CANCELLED"}))
        assert meta["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["id"] == drill_c["id"]
        assert filtered[0]["status"] == "CANCELLED"

        page1, meta1 = validate_paginated(api.list_drill_events(
            site_id, officer_headers, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page3, meta3 = validate_paginated(api.list_drill_events(
            site_id, officer_headers, params={"limit": 1, "offset": 2}))
        assert len(page3) == 1
        assert meta3["total_count"] == 3
        assert meta3["has_more"] is False
