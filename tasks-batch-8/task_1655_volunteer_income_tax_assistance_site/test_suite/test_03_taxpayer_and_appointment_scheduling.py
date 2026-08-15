"""Taxpayer intake and appointment scheduling: unique SSN tokens, identity
verification terminality, the schema gate, volunteer/capacity/window
geometry, no-show timing, and list pagination."""
from test_helpers import (
    DAY2_END,
    DAY2_START,
    ApiErrorId,
    add_preparer,
    add_screener,
    assert_appointment,
    assert_taxpayer,
    create_appointment_payload,
    create_verified_taxpayer,
    register_taxpayer,
    register_volunteer,
    schedule_appointment,
    setup_certified_site,
    setup_open_site,
    transition_volunteer,
    validate_error,
    validate_paginated,
    validate_success,
    verify_taxpayer,
)


class TestTaxpayerRegistration:
    def test_taxpayer_duplicate_ssn_rejected(self, api):
        """PRD §3.3: "Registering a taxpayer captures `full_name`,
        `ssn_token` — a tokenized stand-in for the Social Security number
        that must be unique across all taxpayers, with collisions rejected as
        `ERR_TAXPAYER_DUPLICATE_SSN` — and `phone`, with optional `email`
        (null when omitted) and `preferred_language` (one of `EN`, `ES`, or
        `OTHER`, defaulting to `EN`)."

        Design: Corner/entities/taxpayer_duplicate_ssn_rejected
        """
        ctx = setup_certified_site()
        first = register_taxpayer(
            ctx.coord_headers, full_name="Tp Dup", ssn_token="SSN-DUP", phone="555-2001"
        )
        assert_taxpayer(first)
        resp = api.create_taxpayer(
            {"full_name": "Tp Dup Two", "ssn_token": "SSN-DUP", "phone": "555-2002"},
            ctx.coord_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_DUPLICATE_SSN)

    def test_taxpayer_preferred_language_default(self, api):
        """PRD §3.3: "Registering a taxpayer captures `full_name`,
        `ssn_token` — a tokenized stand-in for the Social Security number
        that must be unique across all taxpayers, with collisions rejected as
        `ERR_TAXPAYER_DUPLICATE_SSN` — and `phone`, with optional `email`
        (null when omitted) and `preferred_language` (one of `EN`, `ES`, or
        `OTHER`, defaulting to `EN`). A new taxpayer's `identity_status`
        begins as `UNVERIFIED`."

        Design: Corner/entities/taxpayer_preferred_language_default
        """
        ctx = setup_certified_site()
        tp = register_taxpayer(
            ctx.coord_headers, full_name="Tp Lang", ssn_token="SSN-L1", phone="555-2006"
        )
        assert_taxpayer(tp)
        assert tp["preferred_language"] == "EN"
        assert tp["identity_status"] == "UNVERIFIED"

    def test_taxpayer_create_unknown_field_rejected(self, api):
        """PRD §2.8: "4. **Request schema**, on all endpoints: required
        fields must be present, types correct, enum values valid, unknown
        fields rejected, and conditionally required fields supplied"

        Design: Corner/entities/taxpayer_create_unknown_field_rejected
        """
        ctx = setup_certified_site()
        resp = api.create_taxpayer(
            {"full_name": "Tp X", "ssn_token": "SSN-X1", "phone": "555-2003",
             "version": 9},
            ctx.coord_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestIdentityVerification:
    def test_verify_identity_twice_rejected(self, api):
        """PRD §3.3: "`VERIFIED` is terminal: attempting identity
        verification on an already-verified taxpayer is rejected with
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/verify_identity_twice_rejected
        """
        ctx = setup_certified_site()
        tp = register_taxpayer(
            ctx.coord_headers, full_name="Tp V2", ssn_token="SSN-V2", phone="555-2011"
        )
        tp = verify_taxpayer(tp["id"], ctx.coord_headers, "PASSPORT")
        assert tp["identity_status"] == "VERIFIED"

        resp = api.verify_identity(tp["id"], "STATE_ID", ctx.coord_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

        tp = validate_success(api.get_taxpayer(tp["id"], ctx.coord_headers))
        assert tp["identity_status"] == "VERIFIED"
        assert tp["id_document_type"] == "PASSPORT"


class TestAppointmentSchema:
    def test_appointment_missing_required_field_rejected(self, api):
        """PRD §2.8: "4. **Request schema**, on all endpoints: required
        fields must be present, types correct, enum values valid, unknown
        fields rejected, and conditionally required fields supplied"
        PRD §3.3: "Appointment scheduling, again shared by `Screener` and
        `SiteCoordinator`, takes a payload naming the `site_id`, the
        `taxpayer_id`, the assigned `volunteer_id`, the visit's `purpose`
        (one of `INTAKE`, `PREPARATION`, or `FOLLOW_UP`), and the interval
        endpoints `start_at` and `end_at`."

        Design: Corner/entities/appointment_missing_required_field_rejected
        """
        ctx = setup_open_site()
        add_screener(ctx)
        tp = register_taxpayer(
            ctx.scr_headers, full_name="Tp Y", ssn_token="SSN-Y1", phone="555-2004"
        )
        payload = {
            "site_id": ctx.site_id,
            "taxpayer_id": tp["id"],
            "volunteer_id": ctx.coordinator["id"],
            "purpose": "INTAKE",
            "start_at": "2026-08-03T10:00:00Z",
        }
        resp = api.create_appointment(payload, ctx.scr_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestVolunteerActiveGate:
    def test_inactive_volunteer_assignment_rejected(self, api):
        """PRD §3.3: "Two cross-entity gates apply at creation, per the
        pipeline of §2.8: the site must be `CERTIFIED` or `OPEN`
        (`ERR_SITE_NOT_OPEN`), and the assigned volunteer must be `ACTIVE`
        (`ERR_VOLUNTEER_NOT_ACTIVE`)."

        Design: Corner/validations/inactive_volunteer_assignment_rejected
        """
        ctx = setup_open_site()
        add_screener(ctx)
        rob = register_volunteer(
            ctx.site_id, ctx.coord_headers, full_name="Reg Rob", email="rob@x.org"
        )
        assert rob["status"] == "REGISTERED"
        tp = register_taxpayer(
            ctx.scr_headers, full_name="Tp IA", ssn_token="SSN-IA1", phone="555-2021"
        )
        payload = create_appointment_payload(
            ctx.site_id, tp["id"], rob["id"], purpose="INTAKE"
        )
        resp = api.create_appointment(payload, ctx.scr_headers)
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE)


class TestWindowVersusVolunteerGateOrdering:
    def _inactive_preparer_ctx(self):
        """OPEN site whose preparer was activated and then inactivated."""
        ctx = setup_open_site()
        add_screener(ctx)
        prep = add_preparer(ctx)
        ctx.preparer = transition_volunteer(prep["id"], "INACTIVE", ctx.coord_headers)
        tp = create_verified_taxpayer(
            ctx.scr_headers, full_name="Taxpayer Six", ssn_token="SSN-006",
            phone="555-0106", id_document_type="STATE_ID",
        )
        return ctx, tp

    def test_outside_window_and_inactive_volunteer_window_wins(self, api):
        """PRD §2.8: "Every request walks a fixed pipeline of validation
        tiers, and a failure in an earlier tier masks every later tier: the
        error a caller observes always comes from the earliest tier its
        request fails."
        PRD §2.8: "8. **Temporal rules**, on appointment creation and
        rescheduling and on report generation — and here the window rules run
        before the overlap exclusion: appointment window and duration
        violations surface as `ERR_OUTSIDE_SITE_WINDOW` (HTTP 422) before the
        volunteer double-booking exclusion surfaces as
        `ERR_APPOINTMENT_OVERLAP_VOLUNTEER` (HTTP 409)"
        PRD §2.8: "9. **Cross-entity state gates**, on appointment creation
        and lifecycle transitions, on return creation, and on return
        lifecycle transitions: creating an appointment requires the site to
        be `CERTIFIED` or `OPEN` (`ERR_SITE_NOT_OPEN`, HTTP 409) and the
        assigned volunteer to be `ACTIVE` (`ERR_VOLUNTEER_NOT_ACTIVE`, HTTP
        409)"

        Design: Difficulty/priority_pair_validation_conflict/appointment_outside_window_and_inactive_volunteer_rejected
        """
        ctx, tp = self._inactive_preparer_ctx()
        payload = create_appointment_payload(
            ctx.site_id, tp["id"], ctx.preparer["id"], purpose="INTAKE",
            start_at="2026-08-03T18:00:00Z", end_at="2026-08-03T19:00:00Z",
        )
        resp = api.create_appointment(payload, ctx.scr_headers)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SITE_WINDOW)

    def test_inactive_volunteer_in_window_rejected(self, api):
        """PRD §3.3: "Two cross-entity gates apply at creation, per the
        pipeline of §2.8: the site must be `CERTIFIED` or `OPEN`
        (`ERR_SITE_NOT_OPEN`), and the assigned volunteer must be `ACTIVE`
        (`ERR_VOLUNTEER_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/appointment_outside_window_and_inactive_volunteer_rejected
        """
        ctx, tp = self._inactive_preparer_ctx()
        payload = create_appointment_payload(
            ctx.site_id, tp["id"], ctx.preparer["id"], purpose="INTAKE",
        )
        resp = api.create_appointment(payload, ctx.scr_headers)
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE)


class TestVolunteerOverlapHalfOpen:
    def test_adjacent_appointments_do_not_overlap(self, api):
        """PRD §3.3: "Conflict geometry uses half-open intervals: an
        appointment occupies the interval from `start_at` inclusive to
        `end_at` exclusive, so two appointments where one ends exactly when
        the other begins do not overlap."

        Design: Difficulty/resource_temporal_overlap/volunteer_overlap_half_open_semantics
        """
        ctx = setup_open_site()
        add_screener(ctx)
        prep = add_preparer(ctx)
        tp1 = register_taxpayer(ctx.scr_headers, full_name="Tp A",
                                ssn_token="SSN-201", phone="555-1201")
        tp2 = register_taxpayer(ctx.scr_headers, full_name="Tp B",
                                ssn_token="SSN-202", phone="555-1202")

        first = validate_success(
            api.create_appointment(
                create_appointment_payload(ctx.site_id, tp1["id"], prep["id"],
                                           purpose="INTAKE"),
                ctx.scr_headers,
            ),
            201,
        )
        assert_appointment(first)
        second = validate_success(
            api.create_appointment(
                create_appointment_payload(
                    ctx.site_id, tp2["id"], prep["id"], purpose="PREPARATION",
                    start_at="2026-08-03T11:00:00Z", end_at="2026-08-03T12:00:00Z",
                ),
                ctx.scr_headers,
            ),
            201,
        )
        assert_appointment(second)
        assert second["status"] == "SCHEDULED", (
            "an appointment beginning exactly when the other ends does not overlap"
        )

    def test_overlapping_appointment_same_volunteer_rejected(self, api):
        """PRD §3.3: "The volunteer double-booking exclusion rejects the new
        appointment with `ERR_APPOINTMENT_OVERLAP_VOLUNTEER` when any
        existing appointment assigned to the same `volunteer_id`, in
        `SCHEDULED` or `CHECKED_IN` status, overlaps the new interval."

        Design: Difficulty/resource_temporal_overlap/volunteer_overlap_half_open_semantics
        """
        ctx = setup_open_site()
        add_screener(ctx)
        prep = add_preparer(ctx)
        tp1 = register_taxpayer(ctx.scr_headers, full_name="Tp A",
                                ssn_token="SSN-201", phone="555-1201")
        tp3 = register_taxpayer(ctx.scr_headers, full_name="Tp C",
                                ssn_token="SSN-203", phone="555-1203")
        validate_success(
            api.create_appointment(
                create_appointment_payload(ctx.site_id, tp1["id"], prep["id"],
                                           purpose="INTAKE"),
                ctx.scr_headers,
            ),
            201,
        )
        resp = api.create_appointment(
            create_appointment_payload(
                ctx.site_id, tp3["id"], prep["id"], purpose="FOLLOW_UP",
                start_at="2026-08-03T10:30:00Z", end_at="2026-08-03T11:30:00Z",
            ),
            ctx.scr_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OVERLAP_VOLUNTEER)


class TestStationCapacityBoundary:
    def _capacity_one_site(self):
        ctx = setup_open_site(name="Kiosk VITA", station_capacity=1, goal_returns=10)
        add_screener(ctx)
        prep = add_preparer(ctx)
        tps = [
            register_taxpayer(ctx.scr_headers, full_name=f"Tp {tag}",
                              ssn_token=f"SSN-30{i}", phone=f"555-130{i}")
            for i, tag in enumerate(("A", "B", "C"), start=1)
        ]
        return ctx, prep, tps

    def test_overlapping_appointment_at_capacity_rejected(self, api):
        """PRD §3.3: "The station-capacity ceiling counts the site's existing
        appointments in `SCHEDULED` or `CHECKED_IN` that overlap the new
        interval; when that count has already reached `station_capacity`, the
        appointment is rejected with `ERR_SITE_CAPACITY_FULL` — a count
        exactly one below capacity means the new appointment takes the site's
        last remaining slot."

        Design: Difficulty/resource_temporal_overlap/site_station_capacity_boundary
        """
        ctx, prep, tps = self._capacity_one_site()
        validate_success(
            api.create_appointment(
                create_appointment_payload(ctx.site_id, tps[0]["id"], prep["id"],
                                           purpose="INTAKE"),
                ctx.scr_headers,
            ),
            201,
        )
        resp = api.create_appointment(
            create_appointment_payload(
                ctx.site_id, tps[1]["id"], ctx.coordinator["id"],
                purpose="PREPARATION",
                start_at="2026-08-03T10:30:00Z", end_at="2026-08-03T11:30:00Z",
            ),
            ctx.scr_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_FULL)

    def test_adjacent_appointment_at_capacity_allowed(self, api):
        """PRD §3.3: "Conflict geometry uses half-open intervals: an
        appointment occupies the interval from `start_at` inclusive to
        `end_at` exclusive, so two appointments where one ends exactly when
        the other begins do not overlap."
        PRD §3.3: "The station-capacity ceiling counts the site's existing
        appointments in `SCHEDULED` or `CHECKED_IN` that overlap the new
        interval; when that count has already reached `station_capacity`, the
        appointment is rejected with `ERR_SITE_CAPACITY_FULL`"

        Design: Difficulty/resource_temporal_overlap/site_station_capacity_boundary
        """
        ctx, prep, tps = self._capacity_one_site()
        validate_success(
            api.create_appointment(
                create_appointment_payload(ctx.site_id, tps[0]["id"], prep["id"],
                                           purpose="INTAKE"),
                ctx.scr_headers,
            ),
            201,
        )
        adjacent = validate_success(
            api.create_appointment(
                create_appointment_payload(
                    ctx.site_id, tps[2]["id"], ctx.coordinator["id"],
                    purpose="FOLLOW_UP",
                    start_at="2026-08-03T11:00:00Z", end_at="2026-08-03T12:00:00Z",
                ),
                ctx.scr_headers,
            ),
            201,
        )
        assert_appointment(adjacent)
        assert adjacent["status"] == "SCHEDULED", (
            "the adjacent interval's overlap set is empty, below the capacity ceiling"
        )


class TestNoShowTiming:
    def test_no_show_before_start_rejected(self, api):
        """PRD §3.3: "Marking an appointment `NO_SHOW` from `SCHEDULED` is
        allowed only once the current logical time has reached its
        `start_at`; an early no-show is rejected with `ERR_INVALID_TRANSITION`."
        PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter."

        Design: Corner/state_machines/no_show_before_start_rejected
        """
        ctx = setup_open_site()
        add_screener(ctx)
        prep = add_preparer(ctx)
        tp = register_taxpayer(ctx.scr_headers, full_name="Tp NS",
                               ssn_token="SSN-NS1", phone="555-2010")
        appt = schedule_appointment(ctx, tp["id"], prep["id"], purpose="INTAKE")
        assert appt["status"] == "SCHEDULED"

        resp = api.transition_appointment(appt["id"], "NO_SHOW", ctx.scr_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

        appt = validate_success(api.get_appointment(appt["id"], ctx.scr_headers))
        assert appt["status"] == "SCHEDULED", (
            "the startup clock has not reached the 2026-08-03 start"
        )


class TestAppointmentPagination:
    def test_pagination_limit_offset_interaction(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of
        100. The `offset` parameter specifies how many items to skip and
        defaults to 0. Unless otherwise specified, every list endpoint
        returns its resources sorted by creation timestamp in ascending order"
        PRD §2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/endpoints/pagination_limit_offset_interaction
        """
        ctx = setup_open_site()
        add_screener(ctx)
        prep = add_preparer(ctx)
        tp1 = register_taxpayer(ctx.scr_headers, full_name="Tp P1",
                                ssn_token="SSN-PG1", phone="555-2025")
        tp2 = register_taxpayer(ctx.scr_headers, full_name="Tp P2",
                                ssn_token="SSN-PG2", phone="555-2026")
        appt1 = schedule_appointment(ctx, tp1["id"], prep["id"], purpose="INTAKE")
        appt2 = schedule_appointment(ctx, tp2["id"], prep["id"],
                                     start_at=DAY2_START, end_at=DAY2_END)

        page1, meta1 = validate_paginated(
            api.list_appointments(
                ctx.scr_headers,
                params={"site_id": ctx.site_id, "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1
        assert page1[0]["id"] == appt1["id"], "created_at ascending order"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_appointments(
                ctx.scr_headers,
                params={"site_id": ctx.site_id, "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert page2[0]["id"] == appt2["id"]
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
