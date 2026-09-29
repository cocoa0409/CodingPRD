"""Client blocks, independence restrictions, and the compensations they trigger."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_hours,
    assert_pct,
    clear_client_block,
    confirm_assignment,
    create_approved_waiver,
    create_assignment,
    create_assignment_payload,
    create_client,
    create_engagement,
    create_independence_restriction_payload,
    create_partner,
    create_phase,
    create_restriction,
    create_senior,
    drive_assignment_to_active,
    drive_engagement_to_in_fieldwork,
    read_assignment,
    read_engagement,
    read_phase,
    read_restriction,
    read_staff,
    read_waiver,
    read_workload,
    report_client_block,
    schedule_engagement,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _staffed_engagement(api, expected_hours=45.00, allocated_hours=45.00):
    """One senior booked for the whole of one fieldwork phase, still PROPOSED."""

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
    )
    assignment = create_assignment(
        api,
        phase["id"],
        senior["id"],
        start_date="2026-08-03",
        end_date="2026-08-10",
        allocated_hours=allocated_hours,
    )
    return {
        "client": client,
        "partner": partner,
        "senior": senior,
        "engagement": engagement,
        "phase": phase,
        "assignment": assignment,
    }


class TestClientBlockCascade:
    """Four hops, each caused by the one before it."""

    def _relieved_world(self, api):
        world = _staffed_engagement(api)
        world["waiver"] = create_approved_waiver(
            api,
            world["senior"]["id"],
            world["engagement"]["id"],
            world["partner"]["id"],
            "2026-08-03",
            6.00,
        )
        drive_engagement_to_in_fieldwork(api, world["engagement"]["id"])
        return world

    def test_the_block_releases_the_work_and_relaxes_the_person(self, api):
        """Hop one drops the booking; hop two rebuilds every workload figure.

        PRD 3.8: "An engagement that is `SCHEDULED` or `IN_FIELDWORK` moves to
        `CLIENT_BLOCKED`, the status it held immediately before is stored in
        `pre_block_status`, and `client_block_count` rises by one."

        PRD 3.8: "The first hop releases work: every booking whose phase belongs to
        this engagement and whose `staffing_status` is `PROPOSED` or `CONFIRMED`
        moves to `RELEASED`. The second hop is caused by those releases: for each
        affected person the server recomputes `committed_hours_current_week`,
        `workload_status`, `burnout_risk_score_committed` and `turnover_risk_band`."

        Design: Difficulty/transitive_cascade/client_block_releases_assignment_relaxes_workload_then_expires_waiver
        """

        world = self._relieved_world(api)

        before = read_staff(api, world["senior"]["id"])
        assert_hours(before["effective_weekly_cap_hours"], 56.00)
        assert_hours(before["daily_capacity_hours"], 11.20)
        assert_hours(before["committed_hours_current_week"], 45.01)
        assert before["workload_status"] == "AMBER"

        blocked = report_client_block(
            api, world["engagement"]["id"], "client readiness slipped two weeks"
        )
        assert blocked["status"] == "CLIENT_BLOCKED"
        assert blocked["pre_block_status"] == "IN_FIELDWORK"
        assert blocked["client_block_count"] == 1

        assert read_assignment(api, world["assignment"]["id"])["staffing_status"] == (
            "RELEASED"
        )

        after = read_staff(api, world["senior"]["id"])
        assert_hours(after["committed_hours_current_week"], 0.00)
        assert after["workload_status"] == "GREEN"
        assert_hours(after["burnout_risk_score_committed"], 0.00)
        assert after["turnover_risk_band"] == "LOW"

    def test_the_relaxed_load_expires_the_allowance_and_shrinks_the_cap(self, api):
        """Hop three withdraws the unjustified relief; hop four repays its headroom.

        PRD 3.8: "The third hop is caused by the second: for each person whose
        recomputed `committed_hours_current_week` has fallen back to at most their
        `base_weekly_cap_hours` — that is, whose overtime relief is no longer
        justified — every overtime allowance of theirs on this engagement with
        status `APPROVED` moves to `EXPIRED` with `expiry_reason` set to
        `ENGAGEMENT_BLOCKED`. The fourth hop is caused by the third: each expiry
        recomputes that person's `effective_weekly_cap_hours` and
        `daily_capacity_hours`, dropping the withdrawn allowance."

        PRD 3.8: "Alongside the cascade, every phase of the engagement has its
        `staffed_hours`, `unstaffed_hours` and `staffing_status` re-derived, the
        engagement's `staffing_completion_pct` and `schedule_risk_band` are
        recomputed, and the engagement's `version` increments."

        Design: Difficulty/transitive_cascade/client_block_releases_assignment_relaxes_workload_then_expires_waiver
        """

        world = self._relieved_world(api)
        assert read_waiver(api, world["waiver"]["id"])["status"] == "APPROVED"

        report_client_block(
            api, world["engagement"]["id"], "client readiness slipped two weeks"
        )

        expired = read_waiver(api, world["waiver"]["id"])
        assert expired["status"] == "EXPIRED"
        assert expired["expiry_reason"] == "ENGAGEMENT_BLOCKED"

        after = read_staff(api, world["senior"]["id"])
        assert_hours(after["effective_weekly_cap_hours"], 50.00)
        assert_hours(after["daily_capacity_hours"], 10.00)

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["staffing_status"] == "NOT_STAFFED"
        assert_hours(phase_after["staffed_hours"], 0.00)
        assert_hours(phase_after["unstaffed_hours"], 45.00)
        assert_pct(
            read_engagement(api, world["engagement"]["id"])["staffing_completion_pct"],
            0.00,
        )


class TestClearingTheBlockReentersTheStateItLeft:
    """The engagement goes back to where it was, not forward and not one step short."""

    def test_the_stored_pre_block_status_decides_the_return_route(
        self, api, manager_headers
    ):
        """Blocked out of IN_FIELDWORK, so the clear lands on IN_FIELDWORK.

        PRD 3.8: "Clearing it returns the engagement to the status recorded in
        `pre_block_status` — `CLIENT_BLOCKED → IN_FIELDWORK` when the stored value
        was `IN_FIELDWORK`, and `CLIENT_BLOCKED → SCHEDULED` when it was
        `SCHEDULED`. Both branches behave identically otherwise: `pre_block_status`
        is set back to null, `schedule_risk_band` is recomputed, and the
        engagement's `version` increments."

        Design: Difficulty/non_linear_state_machine/engagement_reenters_in_fieldwork_from_client_blocked_via_pre_block_status
        """

        world = _staffed_engagement(api)
        drive_engagement_to_in_fieldwork(api, world["engagement"]["id"])

        blocked = validate_success(
            api.report_client_block(
                world["engagement"]["id"],
                manager_headers,
                reason_note="client trial balance not ready",
                blocked_until_date="2026-08-17",
            )
        )
        assert blocked["status"] == "CLIENT_BLOCKED"
        assert blocked["pre_block_status"] == "IN_FIELDWORK"
        assert read_assignment(api, world["assignment"]["id"])["staffing_status"] == (
            "RELEASED"
        )
        assert read_phase(api, world["phase"]["id"])["staffing_status"] == "NOT_STAFFED"

        cleared = clear_client_block(
            api, world["engagement"]["id"], world["partner"]["id"]
        )
        assert cleared["status"] == "IN_FIELDWORK"
        assert cleared["pre_block_status"] is None
        assert cleared["client_block_count"] == 1

    def test_the_return_trip_restores_nothing_so_re_staffing_is_explicit(
        self, api, manager_headers
    ):
        """The released booking stays released; a brand new booking fills the phase.

        PRD 3.8: "Crucially, **released bookings are not restored** by clearing a
        block; re-staffing is an explicit new booking, which is the whole point of
        the cascade being compensating rather than reversible."

        PRD 3.3: "The `daily_hours` figure is `allocated_hours` divided by
        `calendar_day_count`, **rounded half up to two decimals exactly once,
        here**."

        Design: Difficulty/non_linear_state_machine/engagement_reenters_in_fieldwork_from_client_blocked_via_pre_block_status
        """

        world = _staffed_engagement(api)
        drive_engagement_to_in_fieldwork(api, world["engagement"]["id"])
        report_client_block(
            api,
            world["engagement"]["id"],
            "client trial balance not ready",
            blocked_until_date="2026-08-17",
        )
        clear_client_block(api, world["engagement"]["id"], world["partner"]["id"])

        assert read_assignment(api, world["assignment"]["id"])["staffing_status"] == (
            "RELEASED"
        )

        replacement = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    world["phase"]["id"],
                    world["senior"]["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-10",
                    allocated_hours=45.00,
                ),
                manager_headers,
            ),
            201,
        )
        assert replacement["staffing_status"] == "PROPOSED"
        assert_hours(replacement["daily_hours"], 6.43)

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["staffing_status"] == "FULLY_STAFFED"
        assert_hours(phase_after["staffed_hours"], 45.00)
        assert_hours(phase_after["unstaffed_hours"], 0.00)

        engagement_after = read_engagement(api, world["engagement"]["id"])
        assert engagement_after["client_block_count"] == 1
        assert_pct(engagement_after["staffing_completion_pct"], 100.00)
        assert engagement_after["schedule_risk_band"] == "LOW"


class TestSecondBlockPinsTheRiskBand:
    """Two blocks on one engagement outrank every other risk branch."""

    def test_a_second_block_alone_forces_the_high_band(self, api):
        """A well-inside deadline cannot rescue a twice-blocked engagement.

        PRD 3.2: "The branches are evaluated top to bottom and **the first match
        wins**: if the engagement's `client_block_count` is 2 or more the band is
        `HIGH`; otherwise, if completion is strictly below 60.00 percent and there
        are 30 or fewer days to the deadline the band is `HIGH`; otherwise, if
        completion is strictly below 90.00 percent and there are 60 or fewer days
        to the deadline the band is `MEDIUM`; otherwise the band is `LOW`."

        PRD 3.8: "Note the interaction with §3.2: two client blocks on one
        engagement pin its `schedule_risk_band` to `HIGH` permanently."

        Design: Corner/calculations/schedule_risk_high_from_second_client_block_alone
        """

        set_clock(api, "2026-08-05T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=20.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=20.00,
        )
        drive_engagement_to_in_fieldwork(api, engagement["id"])
        report_client_block(api, engagement["id"], "Trial balance not yet delivered")
        cleared = clear_client_block(api, engagement["id"], partner["id"])
        assert cleared["client_block_count"] == 1

        blocked_again = report_client_block(
            api, engagement["id"], "Trial balance still not delivered"
        )
        assert blocked_again["status"] == "CLIENT_BLOCKED"
        assert blocked_again["pre_block_status"] == "IN_FIELDWORK"
        assert blocked_again["client_block_count"] == 2
        assert_pct(blocked_again["staffing_completion_pct"], 0.00)
        assert blocked_again["schedule_risk_band"] == "HIGH"


class TestIndependenceRestrictionCascade:
    """Imposing a restriction unwinds the work it conflicts with."""

    def _restricted_world(self, api):
        world = _staffed_engagement(api)
        schedule_engagement(api, world["engagement"]["id"])
        world["restriction"] = create_restriction(
            api,
            world["client"]["id"],
            world["senior"]["id"],
            restriction_type="FINANCIAL_INTEREST",
            effective_start_date="2026-08-05",
            effective_end_date="2026-08-20",
        )
        return world

    def test_the_new_restriction_releases_the_intersecting_booking(self, api):
        """One shared date between the window and the occupied dates is enough.

        PRD 3.8: "The first hop releases: every booking with `staffing_status`
        `PROPOSED` or `CONFIRMED` whose `staff_member_id` is this person, whose
        phase belongs to an engagement for this client, and whose occupied dates
        share any date with the restriction's closed window, moves to `RELEASED`;
        the count of bookings released is recorded on the restriction as
        `released_assignment_count`."

        PRD 3.8: "A newly created restriction takes `status` `ACTIVE` immediately,
        with `released_assignment_count` starting at 0."

        Design: Difficulty/transitive_cascade/independence_restriction_release_downgrades_phase_and_reverts_engagement
        """

        world = self._restricted_world(api)

        assert world["restriction"]["status"] == "ACTIVE"
        assert world["restriction"]["released_assignment_count"] == 1
        assert read_assignment(api, world["assignment"]["id"])["staffing_status"] == (
            "RELEASED"
        )

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["staffing_status"] == "NOT_STAFFED"
        assert_hours(phase_after["staffed_hours"], 0.00)
        assert_hours(phase_after["unstaffed_hours"], 45.00)

    def test_the_phase_downgrade_bubbles_the_engagement_back_to_setup(self, api):
        """Nobody asked the engagement to move, and it moves anyway.

        PRD 3.8: "The third hop is caused by the second: when the downgrades leave
        every phase of an engagement at `NOT_STAFFED` while that engagement is
        `SCHEDULED`, the engagement reverts `SCHEDULED → SETUP`."

        PRD 2.8: "When the last non-released booking on a phase disappears the
        phase falls to `NOT_STAFFED`, and when *every* phase of an engagement sits
        at `NOT_STAFFED` while the engagement itself is `SCHEDULED`, the engagement
        reverts to `SETUP`."

        Design: Difficulty/transitive_cascade/independence_restriction_release_downgrades_phase_and_reverts_engagement
        """

        world = self._restricted_world(api)

        engagement_after = read_engagement(api, world["engagement"]["id"])
        assert engagement_after["status"] == "SETUP"
        assert_pct(engagement_after["staffing_completion_pct"], 0.00)
        assert engagement_after["schedule_risk_band"] == "LOW"

        staff_after = read_staff(api, world["senior"]["id"])
        assert_hours(staff_after["committed_hours_current_week"], 0.00)
        assert staff_after["workload_status"] == "GREEN"


class TestRestrictionLifecycle:
    """One live restriction per pair, and one lift per restriction."""

    def test_lifting_an_already_lifted_restriction_is_refused(self, api, officer_headers):
        """LIFTED is terminal, so the second lift is not a silent no-op.

        PRD 3.8: "The same officer may lift a restriction, moving it `ACTIVE →
        LIFTED` and incrementing its `version`; `LIFTED` is terminal, and lifting an
        already-lifted restriction is refused with `ERR_RESTRICTION_INVALID_STATE`."

        Design: Corner/state_machines/second_lift_of_same_restriction_rejected_as_idempotency_guard
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        senior = create_senior(api)
        restriction = create_restriction(
            api,
            client["id"],
            senior["id"],
            restriction_type="FINANCIAL_INTEREST",
            effective_start_date="2026-08-01",
            effective_end_date="2026-12-31",
        )
        lifted = validate_success(
            api.lift_independence_restriction(restriction["id"], officer_headers)
        )
        assert lifted["status"] == "LIFTED"

        validate_error(
            api.lift_independence_restriction(restriction["id"], officer_headers),
            ApiErrorId.RESTRICTION_INVALID_STATE.value,
            409,
        )

        after = read_restriction(api, restriction["id"])
        assert after["status"] == "LIFTED"
        assert after["released_assignment_count"] == 0
        assert after["version"] == 2

    def test_a_second_live_restriction_for_the_same_pair_is_refused(
        self, api, officer_headers
    ):
        """A different type and a later window do not make it a different bar.

        PRD 3.8: "Only one restriction may be `ACTIVE` for a given client and person
        at a time; a duplicate is refused with `ERR_DUPLICATE_RESTRICTION`."

        Design: Corner/validations/second_active_restriction_for_same_client_staff_rejected
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        senior = create_senior(api)
        first = create_restriction(
            api,
            client["id"],
            senior["id"],
            restriction_type="FINANCIAL_INTEREST",
            effective_start_date="2026-08-01",
            effective_end_date="2026-12-31",
        )

        validate_error(
            api.create_independence_restriction(
                create_independence_restriction_payload(
                    client["id"],
                    senior["id"],
                    restriction_type="EMPLOYMENT_NEGOTIATION",
                    effective_start_date="2026-09-01",
                    effective_end_date="2026-11-30",
                ),
                officer_headers,
            ),
            ApiErrorId.DUPLICATE_RESTRICTION.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_independence_restrictions(officer_headers, client_id=client["id"])
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

        after = read_restriction(api, first["id"])
        assert after["status"] == "ACTIVE"
        assert after["restriction_type"] == "FINANCIAL_INTEREST"
        assert after["released_assignment_count"] == 0


class TestSafetyOutranksTheFiscalGate:
    """A request that breaks two rules reports the higher one."""

    def _doubly_offending_world(self, api):
        world = _staffed_engagement(api)
        drive_assignment_to_active(
            api,
            world["engagement"]["id"],
            world["phase"]["id"],
            world["assignment"]["id"],
        )
        world["restriction"] = create_restriction(
            api,
            world["client"]["id"],
            world["senior"]["id"],
            restriction_type="FINANCIAL_INTEREST",
            effective_start_date="2026-08-10",
            effective_end_date="2026-08-20",
        )
        world["second_phase"] = create_phase(
            api,
            world["engagement"]["id"],
            phase_type="REVIEW",
            expected_hours=60.00,
            window_start_date="2026-08-10",
            window_end_date="2026-08-31",
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        return world

    def test_the_independence_bar_is_reported_and_not_the_weekly_cap(
        self, api, manager_headers
    ):
        """Fifty-one point zero three committed hours against a fifty-hour cap, unreported.

        PRD 2.9: "Validations are evaluated in a single, strictly ordered ladder.
        **The first check that fails determines the response, and no later check is
        evaluated.**"

        PRD 2.9: "No conflicting active independence restriction —
        `ERR_INDEPENDENCE_RESTRICTED`. This guards booking creation, confirmation,
        reassignment and auto-staffing."

        PRD 2.9: "Per-week effective cap — `ERR_WORKLOAD_CAP_EXCEEDED`. Booking
        creation, reassignment and auto-staffing."

        Design: Difficulty/priority_pair_validation_conflict/independence_safety_priority_14_beats_workload_fiscal_priority_33
        """

        world = self._doubly_offending_world(api)

        error = validate_error(
            api.create_assignment(
                create_assignment_payload(
                    world["second_phase"]["id"],
                    world["senior"]["id"],
                    start_date="2026-08-10",
                    end_date="2026-08-17",
                    allocated_hours=51.00,
                ),
                manager_headers,
            ),
            ApiErrorId.INDEPENDENCE_RESTRICTED.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.WORKLOAD_CAP_EXCEEDED.value

    def test_the_refused_booking_leaves_every_aggregate_untouched(
        self, api, manager_headers
    ):
        """No row written, no counter moved, and the restriction released nothing.

        PRD 3.8: "Creation is not passive — it unwinds conflicting work immediately,
        in a three-hop cascade."

        PRD 3.4: "A person's committed load in one ISO week is the sum, rounded to
        two decimals, over their bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or
        `COMPLETED` of that booking's `daily_hours` multiplied by the number of its
        occupied dates that fall inside that week's seven days; released bookings
        are excluded and review hours never enter this figure at all."

        Design: Difficulty/priority_pair_validation_conflict/independence_safety_priority_14_beats_workload_fiscal_priority_33
        """

        world = self._doubly_offending_world(api)

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    world["second_phase"]["id"],
                    world["senior"]["id"],
                    start_date="2026-08-10",
                    end_date="2026-08-17",
                    allocated_hours=51.00,
                ),
                manager_headers,
            ),
            ApiErrorId.INDEPENDENCE_RESTRICTED.value,
            409,
        )

        assert read_restriction(api, world["restriction"]["id"])[
            "released_assignment_count"
        ] == 0

        rows, meta = validate_paginated(
            api.list_assignments(
                manager_headers, engagement_phase_id=world["second_phase"]["id"]
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

        phase_after = read_phase(api, world["second_phase"]["id"])
        assert phase_after["staffing_status"] == "NOT_STAFFED"
        assert_hours(phase_after["staffed_hours"], 0.00)

        assert_hours(
            read_staff(api, world["senior"]["id"])["committed_hours_current_week"], 45.01
        )


class TestReleaseLeavesNoResidue:
    """Releasing one booking reverses exactly that booking's footprint."""

    def _confirmed_booking(self, api):
        world = _staffed_engagement(api)
        confirm_assignment(api, world["assignment"]["id"])
        return world

    def test_the_person_returns_to_their_pre_booking_numbers(self, api, manager_headers):
        """Committed hours, both burnout scores and the caps land back where they began.

        PRD 3.4: "`workload_status` is the traffic light over these two figures:
        `GREEN` while `committed_hours_current_week` is at most
        `base_weekly_cap_hours`, `AMBER` when it exceeds `base_weekly_cap_hours` but
        is at most `effective_weekly_cap_hours`, and `RED` when it exceeds
        `effective_weekly_cap_hours`."

        PRD 3.4: "It returns `staff_member_id`, the `week_start_date` it resolved
        to, `committed_hours`, `logged_hours`, `effective_weekly_cap_hours`,
        `daily_capacity_hours`, `approved_waiver_hours`, `remaining_week_hours`,
        `workload_status`, `burnout_risk_score_actual`,
        `burnout_risk_score_committed` and `turnover_risk_band`."

        Design: Difficulty/compensating_invariant/release_restores_committed_hours_and_realization_without_drift
        """

        world = self._confirmed_booking(api)

        before = read_staff(api, world["senior"]["id"])
        assert_hours(before["committed_hours_current_week"], 45.01)
        assert before["workload_status"] == "AMBER"
        assert_hours(before["burnout_risk_score_committed"], 2.00)

        released = validate_success(
            api.release_assignment(
                world["assignment"]["id"],
                manager_headers,
                reason_note="client deferred fieldwork to September",
            )
        )
        assert released["staffing_status"] == "RELEASED"
        assert released["review_status"] == "NOT_REQUIRED"

        after = read_staff(api, world["senior"]["id"])
        assert_hours(after["committed_hours_current_week"], 0.00)
        assert after["workload_status"] == "GREEN"
        assert_hours(after["burnout_risk_score_committed"], 0.00)
        assert_hours(after["burnout_risk_score_actual"], 0.00)
        assert after["turnover_risk_band"] == "LOW"
        assert_hours(after["effective_weekly_cap_hours"], 50.00)
        assert_hours(after["daily_capacity_hours"], 10.00)

        workload = read_workload(api, world["senior"]["id"])
        assert_hours(workload["committed_hours"], 0.00)
        assert_hours(workload["remaining_week_hours"], 50.00)

    def test_the_phase_and_the_engagement_return_to_their_pre_booking_numbers(
        self, api, manager_headers
    ):
        """The provisional fee analysis unwinds along with the staffing figures.

        PRD 3.9: "The **provisional** variant, surfaced as
        `realization_pct_provisional`, values what has been *booked*. Its input is
        every booking on this engagement's phases whose `staffing_status` is
        `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED`; released bookings are
        excluded."

        PRD 3.9: "Both variants report 0.00 when their standard value is 0.00, with
        no division performed."

        Design: Difficulty/compensating_invariant/release_restores_committed_hours_and_realization_without_drift
        """

        world = self._confirmed_booking(api)

        before_phase = read_phase(api, world["phase"]["id"])
        assert before_phase["staffing_status"] == "FULLY_STAFFED"
        before_engagement = read_engagement(api, world["engagement"]["id"])
        assert_pct(before_engagement["staffing_completion_pct"], 100.00)
        assert_pct(before_engagement["realization_pct_provisional"], 74.07)

        validate_success(
            api.release_assignment(
                world["assignment"]["id"],
                manager_headers,
                reason_note="client deferred fieldwork to September",
            )
        )

        phase_after = read_phase(api, world["phase"]["id"])
        assert_hours(phase_after["staffed_hours"], 0.00)
        assert_hours(phase_after["unstaffed_hours"], 45.00)
        assert phase_after["staffing_status"] == "NOT_STAFFED"

        engagement_after = read_engagement(api, world["engagement"]["id"])
        assert_pct(engagement_after["staffing_completion_pct"], 0.00)
        assert_pct(engagement_after["realization_pct_provisional"], 0.00)
        assert engagement_after["status"] == "SETUP"
