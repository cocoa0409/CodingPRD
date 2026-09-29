"""One booking, four derived surfaces, and no settling step between them."""

from __future__ import annotations

from test_helpers import (
    assert_hours,
    assert_pct,
    create_assignment_payload,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_senior,
    read_engagement,
    read_phase,
    read_staff,
    read_workload,
    set_clock,
    validate_success,
)


def _forty_hour_phase_awaiting_one_booking(api):
    """A senior, an untouched forty-hour fieldwork phase, and nothing booked yet."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    senior = create_senior(api)
    engagement = create_engagement(
        api, client["id"], partner["id"], budget_fee_amount=12000.00
    )
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=40.00,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
    )
    return {
        "engagement": engagement,
        "phase": phase,
        "senior": senior,
    }


def _book_twenty_hours(api, world, headers):
    return validate_success(
        api.create_assignment(
            create_assignment_payload(
                world["phase"]["id"],
                world["senior"]["id"],
                start_date="2026-08-03",
                end_date="2026-08-08",
                allocated_hours=20.00,
            ),
            headers,
        ),
        201,
    )


class TestTheCreatingResponseIsAlreadyDerived:
    """The booking's own computed fields arrive with the 201, not on a later read."""

    def test_the_booking_response_carries_its_three_fixed_quantities(
        self, api, manager_headers
    ):
        """Five days, four hours a day and an onshore rate model, all in one response.

        PRD 3.3: "Three derived quantities are fixed at creation. The
        `calendar_day_count` is the whole number of days from `start_date` to
        `end_date`, at least 1. The `daily_hours` figure is `allocated_hours` divided
        by `calendar_day_count`, **rounded half up to two decimals exactly once,
        here**."

        PRD 3.3: "The `rate_model` is derived from the assigned person's
        `service_center`: `ONSHORE_STANDARD` for `DOMESTIC`,
        `OFFSHORE_SHARED_SERVICE` for `OFFSHORE`."

        PRD 3.3: "The booking is created in `PROPOSED` with `fit_score` 0.00, because
        no selector ranked it."

        Design: Corner/consistency_model/booking_response_and_every_dependent_read_are_immediately_consistent
        """

        world = _forty_hour_phase_awaiting_one_booking(api)

        booking = _book_twenty_hours(api, world, manager_headers)

        assert booking["calendar_day_count"] == 5
        assert_hours(booking["daily_hours"], 4.00)
        assert booking["rate_model"] == "ONSHORE_STANDARD"
        assert booking["staffing_status"] == "PROPOSED"
        assert booking["fit_score"] is not None
        assert_pct(booking["fit_score"], 0.00)


class TestThePhaseAndEngagementAreAlreadyRederived:
    """The parent split and the parent-of-parent percentage need no second write."""

    def test_the_phase_reports_the_split_on_the_very_next_read(
        self, api, manager_headers
    ):
        """Twenty staffed, twenty unstaffed, and the status moved off NOT_STAFFED.

        PRD 3.2: "A phase's `staffed_hours` is the sum of `allocated_hours` over its
        bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED` — released
        bookings are excluded — rounded to two decimals. Its `unstaffed_hours` is the
        expected hours minus the staffed hours, floored at 0.00 and rounded to two
        decimals; the two therefore add back to exactly `expected_hours` whenever
        staffing has not overshot."

        PRD 3.2: "`NOT_STAFFED` when staffed hours are exactly 0.00,
        `FULLY_STAFFED` when staffed hours are greater than or equal to expected
        hours (exact equality counts as fully staffed), and `PARTIALLY_STAFFED` in
        every other case."

        Design: Corner/consistency_model/booking_response_and_every_dependent_read_are_immediately_consistent
        """

        world = _forty_hour_phase_awaiting_one_booking(api)
        _book_twenty_hours(api, world, manager_headers)

        phase = read_phase(api, world["phase"]["id"])
        assert_hours(phase["staffed_hours"], 20.00)
        assert_hours(phase["unstaffed_hours"], 20.00)
        assert phase["staffing_status"] == "PARTIALLY_STAFFED"

    def test_the_engagement_reports_completion_and_risk_on_the_next_read(
        self, api, manager_headers
    ):
        """Half the expected hours are staffed, and seventy-three days is still LOW.

        PRD 3.2: "The server sums `expected_hours` across every phase of the
        engagement in any status and rounds to two decimals, sums `staffed_hours` the
        same way, and reports 0.00 when the expected total is 0.00. Otherwise it takes
        the smaller of the staffed total and the expected total, divides by the
        expected total, multiplies by 100 and rounds to two decimals"

        PRD 3.2: "if the engagement's `client_block_count` is 2 or more the band is
        `HIGH`; otherwise, if completion is strictly below 60.00 percent and there are
        30 or fewer days to the deadline the band is `HIGH`; otherwise, if completion
        is strictly below 90.00 percent and there are 60 or fewer days to the deadline
        the band is `MEDIUM`; otherwise the band is `LOW`."

        Design: Corner/consistency_model/booking_response_and_every_dependent_read_are_immediately_consistent
        """

        world = _forty_hour_phase_awaiting_one_booking(api)
        _book_twenty_hours(api, world, manager_headers)

        engagement = read_engagement(api, world["engagement"]["id"])
        assert_pct(engagement["staffing_completion_pct"], 50.00)
        assert engagement["schedule_risk_band"] == "LOW"


class TestTheStaffMembersWeekIsAlreadyLoaded:
    """The computed weekly read and the roster row agree with each other at once."""

    def test_the_workload_read_shows_the_commitment_and_the_headroom(
        self, api, manager_headers
    ):
        """Twenty committed against a fifty-hour cap leaves thirty, with nothing logged.

        PRD 3.4: "A person's committed load in one ISO week is the sum, rounded to two
        decimals, over their bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or
        `COMPLETED` of that booking's `daily_hours` multiplied by the number of its
        occupied dates that fall inside that week's seven days; released bookings are
        excluded and review hours never enter this figure at all."

        PRD 3.4: "It returns `staff_member_id`, the `week_start_date` it resolved to,
        `committed_hours`, `logged_hours`, `effective_weekly_cap_hours`,
        `daily_capacity_hours`, `approved_waiver_hours`, `remaining_week_hours`,
        `workload_status`, `burnout_risk_score_actual`,
        `burnout_risk_score_committed` and `turnover_risk_band`."

        Design: Corner/consistency_model/booking_response_and_every_dependent_read_are_immediately_consistent
        """

        world = _forty_hour_phase_awaiting_one_booking(api)
        _book_twenty_hours(api, world, manager_headers)

        workload = read_workload(api, world["senior"]["id"], "2026-08-03")
        assert workload["week_start_date"] == "2026-08-03"
        assert_hours(workload["committed_hours"], 20.00)
        assert_hours(workload["logged_hours"], 0.00)
        assert_hours(workload["remaining_week_hours"], 30.00)

    def test_the_roster_row_agrees_with_the_workload_read(self, api, manager_headers):
        """The same twenty hours, the same fifty-hour cap, and a green traffic light.

        PRD 3.4: "The burnout tier follows from it with inclusive upper bounds:
        `GREEN` when utilisation is at most 1.0000, `AMBER` when utilisation is
        greater than 1.0000 and at most 1.2500, `RED` when utilisation is greater
        than 1.2500. The tier supplies a multiplier — a quarter more than contracted
        hours for `GREEN`, fifteen percent more for `AMBER`, and no uplift at all for
        `RED`, so the multipliers are 1.25, 1.15 and 1.00 respectively."

        PRD 3.4: "The raw cap is `base_weekly_cap_hours` multiplied by that tier
        multiplier, rounded to two decimals. To it the server adds the allowance: the
        sum, rounded to two decimals, of `extra_hours_allowance` over every overtime
        allowance for this person and this `week_start_date` whose status is
        `APPROVED`. An absolute ceiling of forty percent above contracted hours —
        `base_weekly_cap_hours` multiplied by 1.40, rounded to two decimals — is then
        applied, and `effective_weekly_cap_hours` is the smaller of the raw cap plus
        allowance and that ceiling, rounded to two decimals."

        PRD 3.4: "`committed_hours_current_week` is that figure for the ISO week
        containing the current date."

        PRD 3.4: "`workload_status` is the traffic light over these two figures:
        `GREEN` while `committed_hours_current_week` is at most
        `base_weekly_cap_hours`, `AMBER` when it exceeds `base_weekly_cap_hours` but
        is at most `effective_weekly_cap_hours`, and `RED` when it exceeds
        `effective_weekly_cap_hours`."

        Design: Corner/consistency_model/booking_response_and_every_dependent_read_are_immediately_consistent
        """

        world = _forty_hour_phase_awaiting_one_booking(api)
        _book_twenty_hours(api, world, manager_headers)

        workload = read_workload(api, world["senior"]["id"], "2026-08-03")
        staff = read_staff(api, world["senior"]["id"])

        assert_hours(staff["committed_hours_current_week"], 20.00)
        assert_hours(staff["effective_weekly_cap_hours"], 50.00)
        assert staff["workload_status"] == "GREEN"
        assert_hours(
            staff["effective_weekly_cap_hours"], workload["effective_weekly_cap_hours"]
        )
