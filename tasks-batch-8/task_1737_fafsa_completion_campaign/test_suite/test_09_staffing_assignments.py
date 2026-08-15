"""Staffing: coverage variants, double-booking, hours accrual, confirm gates,
check-in, and the no-show suspension contagion (PRD §2.1, §3.2, §3.7, §3.8)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    accept_assignment,
    add_school,
    complete_running_event,
    confirm_assignment,
    coord,
    create_assignment,
    create_cleared_staff,
    create_confirmed_assignment,
    create_event,
    create_open_campaign,
    create_staff,
    enroll_school,
    get_event,
    get_staff,
    make_staff_member_headers,
    publish_event,
    set_clock,
    setup_campaign_with_school,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaffingCoverageVariants:
    def _setup(self, api):
        """DRAFT event (required_expert_count 1, languages [es]) with one
        EXPERT assignment in ACCEPTED — never confirmed."""
        campaign, school = setup_campaign_with_school()
        event = create_event(
            school,
            title="FAFSA Night",
            start_time="2026-09-10T15:00:00Z",
            end_time="2026-09-10T18:00:00Z",
            capacity=40,
            cost_estimate_cents=5_000,
            required_expert_count=1,
            supported_languages=["es"],
        )
        staff = create_cleared_staff(
            campaign,
            capabilities=["EVENT_STAFF", "AID_EXPERT"],
            languages=["es"],
            full_name="Expert Eve",
        )
        assignment = create_assignment(school, event["id"], staff, role="EXPERT")
        accept_assignment(assignment["id"], staff)
        return event

    def test_committed_block_counts_confirmed_only(self, api):
        """PRD §3.7: "the `committed` block counts only `CONFIRMED`
        assignments" — with the sole EXPERT assignment merely ACCEPTED, the
        committed view reports no coverage.

        Design: Difficulty/dual_variant_calc/event_staffing_coverage_committed_vs_pipeline_variants
        """
        event = self._setup(api)
        coverage = get_event(event["id"])["staffing_coverage"]
        committed = coverage["committed"]
        assert committed["expert_ratio"] == pytest.approx(0.0, abs=1e-9)
        assert committed["staff_count"] == 0
        assert committed["language_complete"] is False

    def test_pipeline_block_optimistically_counts_accepted(self, api):
        """PRD §3.7: "the `pipeline` block optimistically counts `ACCEPTED` and
        `CONFIRMED` together. Each block reports `expert_ratio` — confirmed (or
        pipeline) `EXPERT` assignments divided by the larger of
        `required_expert_count` and one, rounded half-up to two decimals —
        `staff_count` of qualifying assignments of any role, and
        `language_complete`, true when every language in `supported_languages`
        is held by at least one qualifying assignee."

        Design: Difficulty/dual_variant_calc/event_staffing_coverage_committed_vs_pipeline_variants
        """
        event = self._setup(api)
        coverage = get_event(event["id"])["staffing_coverage"]
        pipeline = coverage["pipeline"]
        assert pipeline["expert_ratio"] == pytest.approx(1.0, abs=1e-9)
        assert pipeline["staff_count"] == 1
        assert pipeline["language_complete"] is True
        # The same assignment data drives two divergent variant readings.
        assert coverage["committed"]["expert_ratio"] != pipeline["expert_ratio"]


class TestStaffDoubleBooking:
    def _setup(self, api):
        """Staff with three ACCEPTED assignments: E1 10-12, E2 12-14 (touching
        E1), E3 11-13 (overlapping both)."""
        campaign, school = setup_campaign_with_school()
        ev1 = create_event(school, title="E1")  # 2026-09-10 10:00-12:00
        ev2 = create_event(
            school,
            title="E2",
            start_time="2026-09-10T12:00:00Z",
            end_time="2026-09-10T14:00:00Z",
        )
        ev3 = create_event(
            school,
            title="E3",
            start_time="2026-09-10T11:00:00Z",
            end_time="2026-09-10T13:00:00Z",
        )
        staff = create_cleared_staff(campaign)
        a1 = accept_assignment(
            create_assignment(school, ev1["id"], staff)["id"], staff
        )
        a2 = accept_assignment(
            create_assignment(school, ev2["id"], staff)["id"], staff
        )
        a3 = accept_assignment(
            create_assignment(school, ev3["id"], staff)["id"], staff
        )
        return school, staff, (a1, a2, a3)

    def test_touching_endpoints_allowed_on_half_open_windows(self, api):
        """PRD §3.8: "Overlap is judged on half-open windows: two windows
        conflict when each starts before the other ends, and windows that
        merely touch endpoints do not conflict."

        Design: Difficulty/resource_temporal_overlap/staff_double_booking_half_open_adjacency
        """
        school, staff, (a1, a2, _a3) = self._setup(api)
        confirm_assignment(school, a1["id"])
        resp = api.confirm_assignment(a2["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "CONFIRMED", (
            "E2 starts exactly when E1 ends — half-open adjacency is allowed"
        )
        staff = get_staff(staff["id"])
        assert staff["confirmed_hours_total"] == pytest.approx(4.0, abs=1e-9), (
            f"two confirmed 2-hour assignments must accrue 4.0 hours, got "
            f"{staff['confirmed_hours_total']}"
        )

    def test_overlapping_window_rejected_at_confirm(self, api):
        """PRD §3.8: "the double-booking check runs again against the member's
        current `CONFIRMED` and `CHECKED_IN` commitments, since schedules may
        have moved since the invitation" — an 11:00-13:00 window overlaps both
        confirmed windows and is rejected.

        Design: Difficulty/resource_temporal_overlap/staff_double_booking_half_open_adjacency
        """
        school, staff, (a1, a2, a3) = self._setup(api)
        confirm_assignment(school, a1["id"])
        confirm_assignment(school, a2["id"])

        resp = api.confirm_assignment(a3["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_STAFF_DOUBLE_BOOKED)
        assert get_staff(staff["id"])["confirmed_hours_total"] == pytest.approx(
            4.0, abs=1e-9
        ), "the rejected confirm must not accrue hours"

    def test_double_booking_also_fires_at_assignment_create(self, api):
        """PRD §3.8: "a pre-check rejects a staff member whose existing
        `CONFIRMED` or `CHECKED_IN` commitments overlap the event's window
        (`ERR_STAFF_DOUBLE_BOOKED`)."

        Design: Corner/complexity_layers/create_assignment_overlap_precheck
        """
        campaign, school = setup_campaign_with_school()
        ev1 = create_event(school, title="E1")  # 10:00-12:00
        ev2 = create_event(
            school,
            title="E2",
            start_time="2026-09-10T11:00:00Z",
            end_time="2026-09-10T13:00:00Z",
        )
        staff = create_cleared_staff(campaign)
        create_confirmed_assignment(school, ev1["id"], staff)

        resp = api.create_staff_assignment(
            {
                "event_id": ev2["id"],
                "staff_profile_id": staff["id"],
                "assigned_role": "VOLUNTEER",
            },
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_STAFF_DOUBLE_BOOKED)
        resp = api.list_staff_assignments(
            coord(school), params={"event_id": ev2["id"]}
        )
        _data, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, "no INVITED row may persist"


class TestConfirmedHoursRoundTrip:
    def _setup(self, api):
        campaign, school = setup_campaign_with_school()
        event = create_event(
            school,
            title="E1",
            start_time="2026-09-10T10:00:00Z",
            end_time="2026-09-10T13:00:00Z",  # 3.0 hours
        )
        staff = create_cleared_staff(campaign)
        assignment = accept_assignment(
            create_assignment(school, event["id"], staff)["id"], staff
        )
        return school, staff, assignment

    def test_confirm_accrues_duration_hours(self, api):
        """PRD §3.8: "Confirmation accrues `duration_hours` — the event's
        window length in hours, computed as the difference between `end_time`
        and `start_time` in seconds divided by 3600 and rounded half-up to two
        decimal places — onto `confirmed_hours_total`."

        Design: Difficulty/compensating_invariant/staff_hours_confirm_cancel_roundtrip
        """
        school, staff, assignment = self._setup(api)
        assert get_staff(staff["id"])["confirmed_hours_total"] == pytest.approx(
            0.0, abs=1e-9
        )
        confirm_assignment(school, assignment["id"])
        staff = get_staff(staff["id"])
        assert staff["confirmed_hours_total"] == pytest.approx(3.0, abs=1e-9), (
            f"a 3-hour window must accrue exactly 3.0 hours, got "
            f"{staff['confirmed_hours_total']}"
        )

    def test_cancel_releases_exactly_the_accrued_hours(self, api):
        """PRD §3.2: "confirming an assignment adds its `duration_hours`, and
        cancelling that same confirmed assignment subtracts the identical
        amount, returning `confirmed_hours_total` to its pre-confirm value to
        the cent of an hour."

        Design: Difficulty/compensating_invariant/staff_hours_confirm_cancel_roundtrip
        """
        school, staff, assignment = self._setup(api)
        confirm_assignment(school, assignment["id"])
        assert get_staff(staff["id"])["confirmed_hours_total"] == pytest.approx(
            3.0, abs=1e-9
        )

        resp = api.cancel_assignment(assignment["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "CANCELLED"
        staff = get_staff(staff["id"])
        assert staff["confirmed_hours_total"] == pytest.approx(0.0, abs=1e-9), (
            "the confirm/cancel round trip must leave zero residue"
        )


class TestConfirmGates:
    def test_state_error_beats_background_check_on_confirm(self, api):
        """PRD §2.9: "The server evaluates checks in the following fixed order,
        and the first failure wins" — "5. State permission: the target entity
        is in a state that permits the operation" runs before "6. Business
        safety: consent scope for the operation (`ERR_CONSENT_REQUIRED`) and
        background-check clearance before confirming staff
        (`ERR_BACKGROUND_CHECK_NOT_CLEARED`)." Confirming a CANCELLED
        assignment therefore reports the state error even when the staff
        member's background check has since expired.

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_background_safety
        """
        campaign, school = setup_campaign_with_school()
        event = create_event(school, title="E1")
        staff = create_cleared_staff(campaign)
        assignment = create_confirmed_assignment(school, event["id"], staff)
        api.cancel_assignment(assignment["id"], coord(school))
        api.record_background_check(staff["id"], "EXPIRED", ADMIN)

        resp = api.confirm_assignment(assignment["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED)
        assert resp.status_code == 409, (
            "the state gate (step 5) must win over the background gate "
            "(step 6): expected ERR_ASSIGNMENT_NOT_ACCEPTED, not "
            "ERR_BACKGROUND_CHECK_NOT_CLEARED"
        )

    def test_background_check_gate_fires_in_isolation(self, api):
        """PRD §3.8: "The coordinator then confirms an `ACCEPTED` assignment
        (otherwise `ERR_ASSIGNMENT_NOT_ACCEPTED`) after two gates: the member's
        `background_check_status` must be `CLEARED`
        (`ERR_BACKGROUND_CHECK_NOT_CLEARED`)".

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_background_safety
        """
        campaign, school = setup_campaign_with_school()
        event = create_event(school, title="E1")
        # Background check never recorded: the profile stays PENDING.
        staff = create_staff(campaign)
        assignment = accept_assignment(
            create_assignment(school, event["id"], staff)["id"], staff
        )
        resp = api.confirm_assignment(assignment["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_CHECK_NOT_CLEARED)

    def test_cross_campaign_reference_beats_double_booking(self, api):
        """PRD §2.9: "The server evaluates checks in the following fixed order,
        and the first failure wins" — "7. Cross-campaign referential integrity:
        referenced entities belong to one campaign
        (`ERR_CROSS_CAMPAIGN_REFERENCE`)" runs before "8. Temporal sanity and
        overlap: event window well-formedness (`ERR_EVENT_WINDOW_INVALID`),
        future-start requirements (`ERR_EVENT_IN_PAST`), staff double-booking
        (`ERR_STAFF_DOUBLE_BOOKED`), and the venue buffer
        (`ERR_EVENT_OVERLAP_BUFFER`).".

        Design: Difficulty/priority_pair_validation_conflict/assignment_referential_beats_double_booking_temporal
        """
        campaign_a = create_open_campaign(name="CA")
        school_a = enroll_school(add_school(campaign_a, name="A HS"))
        campaign_b = create_open_campaign(name="CB")
        school_b = enroll_school(
            add_school(
                campaign_b, name="B HS", district_code="D02", school_code="SC0B"
            )
        )
        ev_a = create_event(school_a, title="A1")  # 10:00-12:00
        ev_b = create_event(
            school_b,
            title="B1",
            start_time="2026-09-10T11:00:00Z",
            end_time="2026-09-10T13:00:00Z",  # overlaps A1
        )
        staff = create_cleared_staff(campaign_a)
        create_confirmed_assignment(school_a, ev_a["id"], staff)

        resp = api.create_staff_assignment(
            {
                "event_id": ev_b["id"],
                "staff_profile_id": staff["id"],
                "assigned_role": "VOLUNTEER",
            },
            coord(school_b),
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_CAMPAIGN_REFERENCE)
        assert resp.status_code == 422, (
            "referential integrity (step 7) must beat the temporal check "
            "(step 8): expected ERR_CROSS_CAMPAIGN_REFERENCE, not "
            "ERR_STAFF_DOUBLE_BOOKED"
        )

    def test_cross_campaign_reference_fires_without_any_overlap(self, api):
        """PRD §3.8: "the staff member and event must belong to the same
        campaign (`ERR_CROSS_CAMPAIGN_REFERENCE`)" — the referential rejection
        stands on its own even when no temporal overlap exists.

        Design: Difficulty/priority_pair_validation_conflict/assignment_referential_beats_double_booking_temporal
        """
        campaign_a = create_open_campaign(name="CA")
        enroll_school(add_school(campaign_a, name="A HS"))
        campaign_b = create_open_campaign(name="CB")
        school_b = enroll_school(
            add_school(
                campaign_b, name="B HS", district_code="D02", school_code="SC0B"
            )
        )
        ev_b = create_event(
            school_b,
            title="B1",
            start_time="2026-09-11T10:00:00Z",
            end_time="2026-09-11T12:00:00Z",
        )
        staff = create_cleared_staff(campaign_a)  # belongs to campaign A only

        resp = api.create_staff_assignment(
            {
                "event_id": ev_b["id"],
                "staff_profile_id": staff["id"],
                "assigned_role": "VOLUNTEER",
            },
            coord(school_b),
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_CAMPAIGN_REFERENCE)


class TestAssignmentCapabilityAndOwnership:
    def test_expert_assignment_requires_aid_expert_capability(self, api):
        """PRD §3.8: "an `EXPERT` assignment requires the `AID_EXPERT`
        capability (`ERR_STAFF_LACKS_CAPABILITY`)".

        Design: Corner/errors/expert_assignment_requires_aid_expert_capability
        """
        campaign, school = setup_campaign_with_school()
        event = create_event(school, title="E1")
        staff = create_staff(campaign)  # capabilities: [EVENT_STAFF]

        resp = api.create_staff_assignment(
            {
                "event_id": event["id"],
                "staff_profile_id": staff["id"],
                "assigned_role": "EXPERT",
            },
            coord(school),
        )
        validate_error(resp, ApiErrorId.ERR_STAFF_LACKS_CAPABILITY)

        resp = api.create_staff_assignment(
            {
                "event_id": event["id"],
                "staff_profile_id": staff["id"],
                "assigned_role": "VOLUNTEER",
            },
            coord(school),
        )
        assignment = validate_success(resp, 201)
        assert assignment["status"] == "INVITED"

    def test_staff_member_cannot_accept_others_assignment(self, api):
        """PRD §2.1: "When `X-User-Role` is `StaffMember`, `X-User-ID` is the
        `id` of the acting `StaffProfile`; an assignment response is only valid
        when the assignment's `staff_profile_id` equals `X-User-ID`, otherwise
        the request fails with `ERR_OWNERSHIP_VIOLATION`."

        Design: Corner/rbac/staff_member_cannot_accept_others_assignment
        """
        campaign, school = setup_campaign_with_school()
        event = create_event(school, title="E1")
        staff_x = create_staff(campaign, full_name="Vol X")
        staff_y = create_staff(campaign, full_name="Vol Y")
        assignment = create_assignment(school, event["id"], staff_x)

        resp = api.accept_assignment(
            assignment["id"], make_staff_member_headers(staff_y["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
        resp = api.get_staff_assignment(assignment["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "INVITED", (
            "the rejected accept must leave the assignment INVITED"
        )

        resp = api.accept_assignment(
            assignment["id"], make_staff_member_headers(staff_x["id"])
        )
        assert validate_success(resp, 200)["status"] == "ACCEPTED"


class TestCheckIn:
    def _setup(self, api):
        campaign, school = setup_campaign_with_school()
        event = create_event(school, title="E1")  # 2026-09-10 10:00-12:00
        staff = create_cleared_staff(campaign)
        assignment = create_confirmed_assignment(school, event["id"], staff)
        publish_event(school, event["id"])
        return school, event, assignment

    def test_check_in_rejected_before_event_in_progress(self, api):
        """PRD §3.8: "Once the parent event is `IN_PROGRESS`, the coordinator
        checks confirmed staff in, moving `CONFIRMED` to the terminal
        `CHECKED_IN` (wrong assignment state: `ERR_ASSIGNMENT_NOT_CONFIRMED`;
        event not running: `ERR_EVENT_NOT_IN_PROGRESS`)."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_in_progress
        """
        school, _event, assignment = self._setup(api)
        resp = api.check_in_assignment(assignment["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_IN_PROGRESS)

    def test_check_in_succeeds_once_clock_crosses_start(self, api):
        """PRD §2.5: "A published completion event moves from `PUBLISHED` to
        `IN_PROGRESS` once the clock reaches or passes its `start_time`."
        PRD §3.8: "Once the parent event is `IN_PROGRESS`, the coordinator
        checks confirmed staff in, moving `CONFIRMED` to the terminal
        `CHECKED_IN`".

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_in_progress
        """
        school, event, assignment = self._setup(api)
        set_clock("2026-09-10T11:00:00Z")
        assert get_event(event["id"])["status"] == "IN_PROGRESS"
        resp = api.check_in_assignment(assignment["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "CHECKED_IN"


class TestNoShowSuspensionContagion:
    def test_second_no_show_suspends_and_cancels_future_assignments(self, api):
        """PRD §3.7: "every `CONFIRMED` assignment that never checked in is
        marked `NO_SHOW`, releasing its hours from `confirmed_hours_total`,
        incrementing the staff member's `no_show_count`".
        PRD §3.2: "when an event completion marks a no-show that brings
        `no_show_count` to the campaign's `no_show_limit` or more, the profile
        flips from `ACTIVE` — or directly from `OVERLOADED` — to `SUSPENDED`,
        and the suspension is contagious: every `INVITED`, `ACCEPTED`, or
        `CONFIRMED` assignment that staff member holds on events whose
        `start_time` is still in the future is cancelled, with confirmed hours
        released."

        Design: Corner/complexity_layers/no_show_threshold_suspension_with_contagion
        """
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"no_show_limit": 2}
        )
        events = [
            create_event(
                school,
                title=f"E{i}",
                start_time=f"2026-09-{9 + i}T10:00:00Z",
                end_time=f"2026-09-{9 + i}T12:00:00Z",
            )
            for i in (1, 2, 3)  # Sep 10, 11, 12
        ]
        staff = create_cleared_staff(campaign)
        assignments = [
            create_confirmed_assignment(school, event["id"], staff)
            for event in events
        ]
        for event in events:
            publish_event(school, event["id"])
        assert get_staff(staff["id"])["confirmed_hours_total"] == pytest.approx(
            6.0, abs=1e-9
        )

        # First completion: one no-show, still below the limit.
        complete_running_event(school, events[0]["id"], 900, "2026-09-10T11:00:00Z")
        staff = get_staff(staff["id"])
        assert staff["no_show_count"] == 1
        assert staff["status"] == "ACTIVE", "1 < no_show_limit 2: no flip yet"
        assert staff["confirmed_hours_total"] == pytest.approx(4.0, abs=1e-9)

        # Second completion: the limit is reached -> SUSPENDED + contagion.
        complete_running_event(school, events[1]["id"], 900, "2026-09-11T11:00:00Z")
        staff = get_staff(staff["id"])
        assert staff["no_show_count"] == 2
        assert staff["status"] == "SUSPENDED"

        resp = api.get_staff_assignment(assignments[2]["id"], coord(school))
        assert validate_success(resp, 200)["status"] == "CANCELLED", (
            "the future confirmed assignment must be cancelled by contagion"
        )
        assert staff["confirmed_hours_total"] == pytest.approx(0.0, abs=1e-9), (
            "contagion releases the cancelled assignment's confirmed hours"
        )
