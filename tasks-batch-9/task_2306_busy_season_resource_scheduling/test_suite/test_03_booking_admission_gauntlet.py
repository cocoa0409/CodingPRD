"""Booking a named person: the derived quantities and the admission gates."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_assignment,
    assert_hours,
    assert_pagination_meta,
    assert_pct,
    complete_phase,
    confirm_assignment,
    create_assignment,
    create_assignment_payload,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_senior,
    create_staff_member_payload,
    drive_assignment_to_active,
    drive_engagement_to_in_fieldwork,
    read_assignment,
    read_engagement,
    read_phase,
    report_client_block,
    clear_client_block,
    set_clock,
    start_phase,
    validate_error,
    validate_paginated,
    validate_success,
)


def _meridian_senior_phase(api, expected_hours=45.00, **phase_overrides):
    """Client, partner, senior, engagement and one fieldwork phase."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    senior = create_senior(api)
    engagement = create_engagement(api, client["id"], partner["id"])
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=expected_hours,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
        **phase_overrides,
    )
    return client, partner, senior, engagement, phase


class TestBookingCreation:
    """What the server fixes at creation time for a domestic booking."""

    def test_new_booking_starts_proposed_with_no_review_dimension(
        self, api, manager_headers
    ):
        """A domestic booking needs no review, so that dimension sits idle.

        PRD 3.3: "The booking is created in `PROPOSED` with `fit_score` 0.00,
        because no selector ranked it."

        PRD 3.3: "The `rate_model` is derived from the assigned person's
        `service_center`: `ONSHORE_STANDARD` for `DOMESTIC`,
        `OFFSHORE_SHARED_SERVICE` for `OFFSHORE`."

        PRD 3.5: "`review_status` tracks the review through `NOT_REQUIRED`,
        `PENDING_REVIEW`, `IN_REVIEW`, `REWORK_REQUESTED` and `REVIEW_ACCEPTED`,
        and is initialised at creation to `PENDING_REVIEW` when the `rate_model`
        is `OFFSHORE_SHARED_SERVICE` and to `NOT_REQUIRED` otherwise."

        PRD 3.5: "A booking whose `rate_model` is `ONSHORE_STANDARD` carries
        `review_hours_charged` of 0.00 and leaves `review_capacity_window_id`
        null."

        PRD 2.7: "`version` — an integer that increments by one on every mutation
        of the row."

        Design: Corner/state_machines/assignment_initial_states_are_proposed_and_not_required_for_domestic
        """

        _, _, senior, _, phase = _meridian_senior_phase(api)

        created = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-10",
                    allocated_hours=20.00,
                ),
                manager_headers,
            ),
            201,
        )

        assert_assignment(created)
        assert created["staffing_status"] == "PROPOSED"
        assert created["review_status"] == "NOT_REQUIRED"
        assert created["rate_model"] == "ONSHORE_STANDARD"
        assert_hours(created["review_hours_charged"], 0.00)
        assert created["review_capacity_window_id"] is None
        assert created["review_owner_staff_id"] is None
        assert_pct(created["fit_score"], 0.00)
        assert created["version"] == 1

    def test_confirmation_advances_the_staffing_dimension_only(
        self, api, manager_headers
    ):
        """Confirming moves staffing to CONFIRMED and leaves review alone.

        PRD 3.3: "**Confirmation.** A `SchedulingManager` advances a booking
        `PROPOSED → CONFIRMED`."

        PRD 3.5: "Advancing one dimension never touches the other."

        PRD 3.3: "The `daily_hours` figure is `allocated_hours` divided by
        `calendar_day_count`, **rounded half up to two decimals exactly once,
        here**."

        PRD 3.4: "A person's committed load in one ISO week is the sum, rounded to
        two decimals, over their bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or
        `COMPLETED` of that booking's `daily_hours` multiplied by the number of
        its occupied dates that fall inside that week's seven days; released
        bookings are excluded and review hours never enter this figure at all."

        PRD 2.7: "`version` — an integer that increments by one on every mutation
        of the row."

        Design: Corner/state_machines/confirm_moves_proposed_assignment_to_confirmed
        """

        _, _, senior, engagement, phase = _meridian_senior_phase(api)
        assignment = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=20.00,
        )
        api.schedule_engagement(engagement["id"], manager_headers)

        confirmed = validate_success(
            api.confirm_assignment(assignment["id"], manager_headers)
        )

        assert confirmed["staffing_status"] == "CONFIRMED"
        assert confirmed["review_status"] == "NOT_REQUIRED"
        assert confirmed["calendar_day_count"] == 7
        assert_hours(confirmed["daily_hours"], 2.86)
        assert confirmed["version"] == 2

        workload = validate_success(
            api.get_staff_workload(
                senior["id"], manager_headers, week_start_date="2026-08-03"
            )
        )
        assert_hours(workload["committed_hours"], 20.02)
        assert_hours(workload["effective_weekly_cap_hours"], 50.00)
        assert_hours(workload["remaining_week_hours"], 29.98)

    def test_equal_start_and_end_dates_are_rejected(self, api, manager_headers):
        """A booking must occupy at least one date, so end must be strictly later.

        PRD 2.5: "`end_date` must therefore be strictly later than `start_date`."

        PRD 2.5: "Any violation of this date geometry — a booking whose `end_date`
        is on or before its `start_date`, or a closed window whose end precedes
        its start — is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422)."

        Design: Corner/validations/assignment_with_equal_start_and_end_rejected_as_invalid_date_range
        """

        _, _, senior, _, phase = _meridian_senior_phase(api, expected_hours=20.00)

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-10",
                    end_date="2026-08-10",
                    allocated_hours=5.00,
                ),
                manager_headers,
            ),
            ApiErrorId.INVALID_DATE_RANGE.value,
            422,
        )

        after = read_phase(api, phase["id"])
        assert_hours(after["staffed_hours"], 0.00)
        assert_hours(after["unstaffed_hours"], 20.00)

    def test_booking_listing_pages_with_total_count_and_has_more(
        self, api, manager_headers
    ):
        """Three bookings on one phase are paged two then one.

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."

        PRD 3.3: "Bookings are listable with `engagement_phase_id`,
        `staff_member_id`, `review_owner_staff_id`, `review_capacity_window_id`,
        `superseded_by_assignment_id`, `staffing_status` and `review_status` as
        filters — the last of these being how the supersede chain is walked in
        reverse."

        Design: Corner/entities/assignment_listing_paginates_with_total_count_and_has_more
        """

        _, _, senior, _, phase = _meridian_senior_phase(api)
        for start, end in (
            ("2026-08-03", "2026-08-08"),
            ("2026-08-10", "2026-08-15"),
            ("2026-08-17", "2026-08-22"),
        ):
            create_assignment(
                api,
                phase["id"],
                senior["id"],
                start_date=start,
                end_date=end,
                allocated_hours=5.00,
            )

        first_page, first_meta = validate_paginated(
            api.list_assignments(
                manager_headers, engagement_phase_id=phase["id"], limit=2, offset=0
            )
        )
        assert_pagination_meta(
            first_meta,
            expected_limit=2,
            expected_offset=0,
            expected_total=3,
            expected_has_more=True,
        )
        assert len(first_page) == 2

        second_page, second_meta = validate_paginated(
            api.list_assignments(
                manager_headers, engagement_phase_id=phase["id"], limit=2, offset=2
            )
        )
        assert_pagination_meta(
            second_meta,
            expected_offset=2,
            expected_total=3,
            expected_has_more=False,
        )
        assert len(second_page) == 1

        for row in first_page + second_page:
            assert row["staffing_status"] == "PROPOSED"
            assert_hours(row["allocated_hours"], 5.00)
            assert_hours(row["daily_hours"], 1.00)


class TestSkillProfileGates:
    """Grade, specialisation and licence, and the order they fire in."""

    def test_each_eligibility_gate_reports_its_own_code(self, api, admin_headers, manager_headers):
        """Three separate mismatches, then all three at once.

        PRD 3.3: "The person's `level` must equal the phase's `required_level`
        exactly — a `MANAGER` cannot fill a `SENIOR` slot any more than a `STAFF`
        can — and a mismatch is `ERR_LEVEL_MISMATCH`."

        PRD 3.3: "If the phase's `required_industry_specialization` is non-null,
        the person's `industry_specialization` must equal it, or the request is
        `ERR_SPECIALIZATION_MISMATCH`; when the phase leaves that field null, any
        specialisation is acceptable."

        PRD 3.3: "If the phase's `requires_cpa_licensed` is true, the person's
        `cpa_licensed` must be true, or the request is `ERR_LICENSURE_REQUIRED`;
        when the flag is false, licensure is irrelevant."

        PRD 2.9: "**The first check that fails determines the response, and no
        later check is evaluated.**"

        Design: Corner/validations/eligibility_gates_reject_level_then_specialization_then_licence
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        licensed_senior = create_senior(api)
        unlicensed_senior = validate_success(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Dana Kirsch",
                    level="SENIOR",
                    service_center="DOMESTIC",
                    industry_specialization="MANUFACTURING",
                    cpa_licensed=False,
                    base_weekly_cap_hours=40.00,
                    hourly_bill_rate=165.00,
                ),
                admin_headers,
            ),
            201,
        )
        engagement = create_engagement(api, client["id"], partner["id"])

        def phase(phase_type, level, specialization, cpa):
            return create_phase(
                api,
                engagement["id"],
                phase_type=phase_type,
                expected_hours=20.00,
                window_start_date="2026-08-03",
                window_end_date="2026-08-31",
                required_level=level,
                required_industry_specialization=specialization,
                requires_cpa_licensed=cpa,
            )

        wrong_level = phase("REVIEW", "MANAGER", "MANUFACTURING", False)
        wrong_specialization = phase("INTERIM", "SENIOR", "FINANCIAL_SERVICES", False)
        needs_licence = phase("FIELDWORK", "SENIOR", "MANUFACTURING", True)
        all_three_wrong = phase("WRAP_UP", "MANAGER", "FINANCIAL_SERVICES", True)

        cases = (
            (wrong_level, licensed_senior, ApiErrorId.LEVEL_MISMATCH.value),
            (
                wrong_specialization,
                licensed_senior,
                ApiErrorId.SPECIALIZATION_MISMATCH.value,
            ),
            (needs_licence, unlicensed_senior, ApiErrorId.LICENSURE_REQUIRED.value),
            (all_three_wrong, unlicensed_senior, ApiErrorId.LEVEL_MISMATCH.value),
        )
        for target_phase, candidate, expected_error in cases:
            validate_error(
                api.create_assignment(
                    create_assignment_payload(
                        target_phase["id"],
                        candidate["id"],
                        start_date="2026-08-03",
                        end_date="2026-08-08",
                        allocated_hours=5.00,
                    ),
                    manager_headers,
                ),
                expected_error,
                422,
            )

        for target_phase in (
            wrong_level,
            wrong_specialization,
            needs_licence,
            all_three_wrong,
        ):
            assert_hours(read_phase(api, target_phase["id"])["staffed_hours"], 0.00)


class TestWindowContainment:
    """The booking must sit inside its phase's closed window."""

    def test_booking_must_sit_inside_the_phase_window(self, api, manager_headers):
        """Both edges are refused; a last worked day on the closing date is fine.

        PRD 3.3: "The booking must sit inside its phase's closed window:
        `window_start_date` must be on or before `start_date`, and the booking's
        last worked day — `end_date` minus one day — must be on or before
        `window_end_date`. A booking that starts before the window opens or whose
        last worked day falls after the window closes is refused with
        `ERR_ASSIGNMENT_OUTSIDE_PHASE_WINDOW`."

        Design: Corner/validations/booking_outside_phase_window_rejected_on_both_edges
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=20.00,
            window_start_date="2026-08-10",
            window_end_date="2026-08-21",
        )

        for start, end in (("2026-08-03", "2026-08-15"), ("2026-08-17", "2026-08-24")):
            validate_error(
                api.create_assignment(
                    create_assignment_payload(
                        phase["id"],
                        senior["id"],
                        start_date=start,
                        end_date=end,
                        allocated_hours=10.00,
                    ),
                    manager_headers,
                ),
                ApiErrorId.ASSIGNMENT_OUTSIDE_PHASE_WINDOW.value,
                422,
            )

        accepted = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-17",
                    end_date="2026-08-22",
                    allocated_hours=10.00,
                ),
                manager_headers,
            ),
            201,
        )
        assert accepted["calendar_day_count"] == 5
        assert_hours(accepted["daily_hours"], 2.00)


class TestBlockedEngagementRefusesStaffing:
    """A CLIENT_BLOCKED engagement accepts no staffing write."""

    def _blocked_world(self, api):
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=45.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=45.00,
        )
        drive_engagement_to_in_fieldwork(api, engagement["id"])
        report_client_block(api, engagement["id"], "client closed its books late")
        return partner, senior, engagement, phase

    def test_blocked_engagement_refuses_a_new_booking(self, api, manager_headers):
        """The container gate fires before anything about the booking is judged.

        PRD 3.3: "The engagement owning the phase must be `SETUP`, `SCHEDULED` or
        `IN_FIELDWORK`; a `CLIENT_BLOCKED` or `DELIVERED` engagement accepts no
        staffing write at all and refuses with `ERR_ENGAGEMENT_BLOCKED`."

        PRD 3.8: "The first hop releases work: every booking whose phase belongs
        to this engagement and whose `staffing_status` is `PROPOSED` or
        `CONFIRMED` moves to `RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_rejected_while_owning_engagement_client_blocked
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        _, senior, engagement, phase = self._blocked_world(api)
        assert read_engagement(api, engagement["id"])["status"] == "CLIENT_BLOCKED"

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-10",
                    end_date="2026-08-17",
                    allocated_hours=20.00,
                ),
                manager_headers,
            ),
            ApiErrorId.ENGAGEMENT_BLOCKED.value,
            409,
        )

        after = read_phase(api, phase["id"])
        assert_hours(after["staffed_hours"], 0.00)
        assert after["staffing_status"] == "NOT_STAFFED"

    def test_identical_retry_succeeds_once_the_block_clears(self, api, manager_headers):
        """Clearing the block restores the engagement, not the released booking.

        PRD 3.8: "Clearing it returns the engagement to the status recorded in
        `pre_block_status` — `CLIENT_BLOCKED → IN_FIELDWORK` when the stored value
        was `IN_FIELDWORK`, and `CLIENT_BLOCKED → SCHEDULED` when it was
        `SCHEDULED`."

        PRD 3.8: "Crucially, **released bookings are not restored** by clearing a
        block; re-staffing is an explicit new booking, which is the whole point of
        the cascade being compensating rather than reversible."

        PRD 3.2: "A phase's `staffed_hours` is the sum of `allocated_hours` over
        its bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED` —
        released bookings are excluded — rounded to two decimals."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_rejected_while_owning_engagement_client_blocked
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        partner, senior, engagement, phase = self._blocked_world(api)

        payload = create_assignment_payload(
            phase["id"],
            senior["id"],
            start_date="2026-08-10",
            end_date="2026-08-17",
            allocated_hours=20.00,
        )
        validate_error(
            api.create_assignment(payload, manager_headers),
            ApiErrorId.ENGAGEMENT_BLOCKED.value,
            409,
        )

        clear_client_block(api, engagement["id"], partner["id"])
        assert read_engagement(api, engagement["id"])["status"] == "IN_FIELDWORK"

        retried = validate_success(
            api.create_assignment(payload, manager_headers), 201
        )
        assert retried["staffing_status"] == "PROPOSED"
        assert retried["calendar_day_count"] == 7
        assert_hours(retried["daily_hours"], 2.86)

        after_phase = read_phase(api, phase["id"])
        assert_hours(after_phase["staffed_hours"], 20.00)
        assert_hours(after_phase["unstaffed_hours"], 25.00)
        assert after_phase["staffing_status"] == "PARTIALLY_STAFFED"
        assert_pct(
            read_engagement(api, engagement["id"])["staffing_completion_pct"], 44.44
        )


class TestActivationNeedsAnInProgressPhase:
    """A confirmed booking cannot be activated on a phase nobody started."""

    def _confirmed_world(self, api):
        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=45.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        assignment = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=45.00,
        )
        drive_engagement_to_in_fieldwork(api, engagement["id"])
        confirm_assignment(api, assignment["id"])
        return engagement, phase, assignment

    def test_activation_before_the_phase_starts_reports_phase_not_in_progress(
        self, api, manager_headers
    ):
        """CONFIRMED is a legal from-state, so the phase is what blocks the move.

        PRD 3.3: "**Activation.** A confirmed booking becomes chargeable when the
        manager advances it `CONFIRMED → ACTIVE`. This requires the owning phase
        to be `IN_PROGRESS`; otherwise the request is refused with
        `ERR_PHASE_NOT_IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/assignment_activate_rejected_until_owning_phase_in_progress
        """

        _, phase, assignment = self._confirmed_world(api)
        assert read_phase(api, phase["id"])["staffing_status"] == "FULLY_STAFFED"

        error = validate_error(
            api.activate_assignment(assignment["id"], manager_headers),
            ApiErrorId.PHASE_NOT_IN_PROGRESS.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ASSIGNMENT_INVALID_STATE.value

        assert read_assignment(api, assignment["id"])["staffing_status"] == "CONFIRMED"

    def test_activation_succeeds_once_the_phase_is_in_progress(
        self, api, manager_headers
    ):
        """Starting the phase is the only thing the booking was waiting for.

        PRD 3.7: "**Starting a phase.** A `SchedulingManager` starts a phase that
        is `PARTIALLY_STAFFED` or `FULLY_STAFFED`, advancing it to `IN_PROGRESS`,
        provided the owning engagement is `IN_FIELDWORK` and at least one booking
        on the phase is `CONFIRMED`."

        PRD 3.3: "Activation is what makes time entries loggable against the
        booking, and it increments the booking's `version`."

        Design: Difficulty/cross_entity_state_dependency/assignment_activate_rejected_until_owning_phase_in_progress
        """

        _, phase, assignment = self._confirmed_world(api)
        validate_error(
            api.activate_assignment(assignment["id"], manager_headers),
            ApiErrorId.PHASE_NOT_IN_PROGRESS.value,
            409,
        )

        started = start_phase(api, phase["id"])
        assert started["staffing_status"] == "IN_PROGRESS"

        activated = validate_success(
            api.activate_assignment(assignment["id"], manager_headers)
        )
        assert activated["staffing_status"] == "ACTIVE"
        assert_hours(read_phase(api, phase["id"])["staffed_hours"], 45.00)


class TestCompletePhaseOutranksWindowContainment:
    """A terminal phase is reported before the booking's dates are judged."""

    def _completed_phase_world(self, api):
        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=45.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        assignment = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=45.00,
        )
        drive_assignment_to_active(api, engagement["id"], phase["id"], assignment["id"])
        complete_phase(api, phase["id"])
        return senior, phase, assignment

    def test_completed_phase_reports_phase_invalid_state_not_a_window_breach(
        self, api, manager_headers
    ):
        """Both rules are violated, and the phase-state rule sits higher.

        PRD 3.3: "The booking's phase must not be `COMPLETE`, or the request is
        refused with `ERR_PHASE_INVALID_STATE`."

        PRD 2.9: "**The first check that fails determines the response, and no
        later check is evaluated.**"

        PRD 2.9: "11. The target row is in a state its requested transition
        allows, including terminal-state lockdown — the invalid-state family
        described in §2.10. This guards every state-transition operation, plus
        booking creation (whose target phase must not be `COMPLETE`) and
        time-entry creation (whose target booking must be `ACTIVE` or
        `COMPLETED`)."

        Design: Difficulty/priority_pair_validation_conflict/phase_state_priority_11_beats_window_temporal_priority_29
        """

        senior, phase, _ = self._completed_phase_world(api)

        error = validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-09-01",
                    end_date="2026-09-08",
                    allocated_hours=10.00,
                ),
                manager_headers,
            ),
            ApiErrorId.PHASE_INVALID_STATE.value,
            409,
        )
        assert (
            error["error_id"] != ApiErrorId.ASSIGNMENT_OUTSIDE_PHASE_WINDOW.value
        )

    def test_rejected_booking_leaves_the_completed_phase_untouched(
        self, api, manager_headers
    ):
        """Nothing is written, so the phase keeps its completed footprint.

        PRD 3.7: "On success every `ACTIVE` booking on the phase advances
        `ACTIVE → COMPLETED` and increments its own `version`, the engagement's
        `realization_pct_provisional` and `realization_pct_final` are both
        recomputed, and the phase's `version` increments. `COMPLETE` is terminal
        for a phase."

        PRD 3.2: "A phase's `staffed_hours` is the sum of `allocated_hours` over
        its bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED` —
        released bookings are excluded — rounded to two decimals."

        Design: Difficulty/priority_pair_validation_conflict/phase_state_priority_11_beats_window_temporal_priority_29
        """

        senior, phase, assignment = self._completed_phase_world(api)

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-09-01",
                    end_date="2026-09-08",
                    allocated_hours=10.00,
                ),
                manager_headers,
            ),
            ApiErrorId.PHASE_INVALID_STATE.value,
            409,
        )

        after_phase = read_phase(api, phase["id"])
        assert after_phase["staffing_status"] == "COMPLETE"
        assert_hours(after_phase["staffed_hours"], 45.00)
        assert read_assignment(api, assignment["id"])["staffing_status"] == "COMPLETED"

        _, meta = validate_paginated(
            api.list_assignments(manager_headers, engagement_phase_id=phase["id"])
        )
        assert meta["total_count"] == 1
