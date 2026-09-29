"""Offshore bookings, their nominated reviewers, and the review dimension."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    accept_review,
    assert_hours,
    confirm_assignment,
    create_assignment,
    create_assignment_payload,
    create_client,
    create_engagement,
    create_offshore_staff,
    create_partner,
    create_phase,
    create_review_capacity_window_payload,
    create_review_window,
    create_reviewer,
    create_senior,
    offshore_review_world,
    read_assignment,
    read_engagement,
    read_phase,
    read_review_window,
    request_rework,
    schedule_engagement,
    set_clock,
    start_review,
    validate_error,
    validate_success,
)


def _meridian_offshore_world(
    api,
    review_capacity_hours=10.00,
    phase_expected_hours=20.00,
    requires_cpa_licensed=False,
    reviewer_name="Mel Arbogast",
    reviewer_base_hours=40.00,
    reviewer_rate=260.00,
    offshore_cpa_licensed=False,
    offshore_rate=90.00,
):
    """A domestic manager with one August review window plus an offshore senior."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    reviewer = create_reviewer(
        api,
        full_name=reviewer_name,
        base_weekly_cap_hours=reviewer_base_hours,
        hourly_bill_rate=reviewer_rate,
    )
    offshore = create_offshore_staff(
        api,
        full_name="Ravi Menon",
        level="SENIOR",
        base_weekly_cap_hours=40.00,
        hourly_bill_rate=offshore_rate,
        cpa_licensed=offshore_cpa_licensed,
    )
    window = create_review_window(
        api, reviewer["id"], "2026-08-03", review_capacity_hours
    )
    engagement = create_engagement(api, client["id"], partner["id"])
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=phase_expected_hours,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
        required_level="SENIOR",
        required_industry_specialization="MANUFACTURING",
        requires_cpa_licensed=requires_cpa_licensed,
    )
    return {
        "client": client,
        "partner": partner,
        "reviewer": reviewer,
        "offshore": offshore,
        "window": window,
        "engagement": engagement,
        "phase": phase,
    }


class TestReviewCapacityWindows:
    """One window per reviewer per week."""

    def test_second_window_for_one_reviewer_week_is_refused(self, api, admin_headers):
        """A different Monday is a different window; the same Monday is not.

        PRD 3.5: "A reviewer may hold at most one window per week: a second window
        for the same `reviewer_staff_id` and `week_start_date` is refused with
        `ERR_DUPLICATE_REVIEW_WINDOW`."

        PRD 3.5: "A new window starts with `committed_review_hours` 0.00 and
        `remaining_review_hours` equal to its `review_capacity_hours`."

        Design: Corner/validations/second_review_window_for_same_reviewer_week_rejected
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        reviewer = create_reviewer(
            api,
            full_name="Mel Arbogast",
            base_weekly_cap_hours=40.00,
            hourly_bill_rate=260.00,
        )
        first = create_review_window(api, reviewer["id"], "2026-08-03", 10.00)
        assert_hours(first["committed_review_hours"], 0.00)
        assert_hours(first["remaining_review_hours"], 10.00)

        validate_error(
            api.create_review_capacity_window(
                create_review_capacity_window_payload(
                    reviewer["id"],
                    week_start_date="2026-08-03",
                    review_capacity_hours=6.00,
                ),
                admin_headers,
            ),
            ApiErrorId.DUPLICATE_REVIEW_WINDOW.value,
            409,
        )

        next_week = validate_success(
            api.create_review_capacity_window(
                create_review_capacity_window_payload(
                    reviewer["id"],
                    week_start_date="2026-08-10",
                    review_capacity_hours=6.00,
                ),
                admin_headers,
            ),
            201,
        )
        assert next_week["week_start_date"] == "2026-08-10"

        untouched = read_review_window(api, first["id"])
        assert_hours(untouched["review_capacity_hours"], 10.00)


class TestReviewOwnerAdmission:
    """Who must be nominated, who may be nominated, and where the charge lands."""

    def test_review_owner_rules_reject_four_distinct_shapes(self, api, manager_headers):
        """Missing, wrongly present, ineligible and windowless each get their own code.

        PRD 3.5: "Exactly those bookings must nominate a `review_owner_staff_id`,
        and exactly the domestic ones must not: a missing review owner on an
        offshore booking and a supplied review owner on a `ONSHORE_STANDARD`
        booking are both refused with `ERR_REVIEW_OWNER_REQUIRED`."

        PRD 3.5: "The nominated person must have `review_capable` true — a
        `MANAGER` or `PARTNER` whose `service_center` is `DOMESTIC` — or the
        request is refused with `ERR_REVIEW_OWNER_NOT_ELIGIBLE`."

        PRD 3.5: "If no such window exists, the write is refused with
        `ERR_REVIEW_WINDOW_MISSING`."

        PRD 3.5: "For an `OFFSHORE_SHARED_SERVICE` booking the charge starts as
        one-fifth of `allocated_hours`, rounded to two decimals, but floored at a
        two-hour minimum review block: the base is the larger of those two
        figures."

        Design: Corner/validations/offshore_review_owner_rules_reject_missing_present_ineligible_and_windowless
        """

        world = _meridian_offshore_world(api, phase_expected_hours=40.00)
        senior = create_senior(api)
        phase_id = world["phase"]["id"]
        reviewer_id = world["reviewer"]["id"]
        offshore_id = world["offshore"]["id"]

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase_id,
                    offshore_id,
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=10.00,
                ),
                manager_headers,
            ),
            ApiErrorId.REVIEW_OWNER_REQUIRED.value,
            422,
        )

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase_id,
                    senior["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=10.00,
                    review_owner_staff_id=reviewer_id,
                ),
                manager_headers,
            ),
            ApiErrorId.REVIEW_OWNER_REQUIRED.value,
            422,
        )

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase_id,
                    offshore_id,
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=10.00,
                    review_owner_staff_id=senior["id"],
                ),
                manager_headers,
            ),
            ApiErrorId.REVIEW_OWNER_NOT_ELIGIBLE.value,
            422,
        )

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase_id,
                    offshore_id,
                    start_date="2026-08-10",
                    end_date="2026-08-15",
                    allocated_hours=10.00,
                    review_owner_staff_id=reviewer_id,
                ),
                manager_headers,
            ),
            ApiErrorId.REVIEW_WINDOW_MISSING.value,
            422,
        )

        accepted = create_assignment(
            api,
            phase_id,
            offshore_id,
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=10.00,
            review_owner_staff_id=reviewer_id,
        )
        assert accepted["review_capacity_window_id"] == world["window"]["id"]
        assert_hours(accepted["review_hours_charged"], 2.00)
        assert accepted["review_status"] == "PENDING_REVIEW"

    def test_six_hour_offshore_booking_charges_the_two_hour_floor(self, api):
        """One fifth of six hours is 1.20, so the two-hour block wins.

        PRD 3.5: "A six-hour booking therefore charges 2.00 review hours, not
        1.20."

        PRD 3.5: "Whether a booking is offshore is not an input: the server derives
        `rate_model` from the assigned person's `service_center`, and a booking of
        an `OFFSHORE` person is `OFFSHORE_SHARED_SERVICE`."

        PRD 3.5: "Thereafter `committed_review_hours` is the sum, rounded to two
        decimals, of `review_hours_charged` over every booking bound to that window
        whose staffing dimension is `PROPOSED`, `CONFIRMED`, `ACTIVE` or
        `COMPLETED` — released bookings are excluded — and `remaining_review_hours`
        is `review_capacity_hours` minus that committed figure, rounded to two
        decimals."

        Design: Corner/calculations/offshore_review_charge_floors_at_minimum_review_block
        """

        world = _meridian_offshore_world(
            api, review_capacity_hours=5.00, phase_expected_hours=12.00
        )

        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["offshore"]["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=6.00,
            review_owner_staff_id=world["reviewer"]["id"],
        )
        assert booking["rate_model"] == "OFFSHORE_SHARED_SERVICE"
        assert booking["review_status"] == "PENDING_REVIEW"
        assert_hours(booking["daily_hours"], 1.20)
        assert_hours(booking["review_hours_charged"], 2.00)
        assert booking["review_capacity_window_id"] == world["window"]["id"]

        window_after = read_review_window(api, world["window"]["id"])
        assert_hours(window_after["committed_review_hours"], 2.00)
        assert_hours(window_after["remaining_review_hours"], 3.00)

    def test_releasing_the_only_booking_frees_the_whole_window(
        self, api, manager_headers
    ):
        """A released booking drops out of its window's committed total.

        PRD 3.5: "Thereafter `committed_review_hours` is the sum, rounded to two
        decimals, of `review_hours_charged` over every booking bound to that window
        whose staffing dimension is `PROPOSED`, `CONFIRMED`, `ACTIVE` or
        `COMPLETED` — released bookings are excluded — and `remaining_review_hours`
        is `review_capacity_hours` minus that committed figure, rounded to two
        decimals."

        PRD 3.2: "A new phase begins at `NOT_STAFFED` with `staffed_hours` 0.00 and
        `unstaffed_hours` equal to its `expected_hours`; creating it refreshes the
        engagement's `staffing_completion_pct` and `schedule_risk_band` and
        increments the engagement's `version`."

        Design: Corner/calculations/review_window_load_excludes_released_assignment
        """

        world = _meridian_offshore_world(api, phase_expected_hours=24.00)
        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["offshore"]["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=20.00,
            review_owner_staff_id=world["reviewer"]["id"],
        )
        assert_hours(booking["review_hours_charged"], 4.00)

        before = read_review_window(api, world["window"]["id"])
        assert_hours(before["committed_review_hours"], 4.00)
        assert_hours(before["remaining_review_hours"], 6.00)

        released = validate_success(
            api.release_assignment(booking["id"], manager_headers)
        )
        assert released["staffing_status"] == "RELEASED"

        after = read_review_window(api, world["window"]["id"])
        assert_hours(after["committed_review_hours"], 0.00)
        assert_hours(after["remaining_review_hours"], 10.00)

        phase_after = read_phase(api, world["phase"]["id"])
        assert_hours(phase_after["staffed_hours"], 0.00)
        assert_hours(phase_after["unstaffed_hours"], 24.00)
        assert phase_after["staffing_status"] == "NOT_STAFFED"


class TestReviewDimensionGates:
    """Opening, sending back and accepting, in the only order allowed."""

    def test_accepting_a_review_that_never_opened_is_refused(
        self, api, partner_headers_for
    ):
        """A booking sitting at PENDING_REVIEW cannot jump to accepted.

        PRD 3.5: "Accepting the review advances it `IN_REVIEW → REVIEW_ACCEPTED`
        and likewise requires the acting `X-User-ID` to differ from the booking's
        `staff_member_id`."

        PRD 3.5: "`review_status` tracks the review through `NOT_REQUIRED`,
        `PENDING_REVIEW`, `IN_REVIEW`, `REWORK_REQUESTED` and `REVIEW_ACCEPTED`,
        and is initialised at creation to `PENDING_REVIEW` when the `rate_model` is
        `OFFSHORE_SHARED_SERVICE` and to `NOT_REQUIRED` otherwise."

        PRD 2.10: "`ERR_REVIEW_INVALID_STATE` for a booking's review dimension
        (including `NOT_REQUIRED` and `REVIEW_ACCEPTED` lockdown)"

        Design: Corner/state_machines/accept_review_from_pending_review_rejected_as_review_invalid_state
        """

        world = _meridian_offshore_world(
            api,
            phase_expected_hours=45.00,
            requires_cpa_licensed=True,
            reviewer_name="Dana Whitfield",
            reviewer_base_hours=45.00,
            offshore_cpa_licensed=True,
            offshore_rate=95.00,
        )
        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["offshore"]["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=20.00,
            review_owner_staff_id=world["reviewer"]["id"],
        )

        validate_error(
            api.accept_review(
                booking["id"], partner_headers_for(world["reviewer"]["id"])
            ),
            ApiErrorId.REVIEW_INVALID_STATE.value,
            409,
        )

        read_back = read_assignment(api, booking["id"])
        assert read_back["review_status"] == "PENDING_REVIEW"
        assert read_back["rate_model"] == "OFFSHORE_SHARED_SERVICE"
        assert_hours(read_back["review_hours_charged"], 4.00)
        assert read_back["review_capacity_window_id"] == world["window"]["id"]

        window_after = read_review_window(api, world["window"]["id"])
        assert_hours(window_after["committed_review_hours"], 4.00)
        assert_hours(window_after["remaining_review_hours"], 6.00)

    def test_third_rework_request_is_refused_at_the_cycle_limit(
        self, api, partner_headers_for
    ):
        """Two round trips are allowed; the third request is not.

        PRD 3.5: "It is permitted only while `rework_cycles` is strictly below two,
        so a booking may go round the rework loop at most twice; a third attempt is
        refused with `ERR_REWORK_LIMIT_EXCEEDED`."

        PRD 3.5: "On success `rework_cycles` rises by one, `review_hours_charged`
        is recomputed with the extra hour charged to the **same**
        `review_capacity_window_id`, the window's `committed_review_hours` and
        `remaining_review_hours` are recomputed, and the booking's `version`
        increments."

        PRD 3.5: "To that base the server adds one hour for each rework cycle the
        booking has accumulated, and rounds the total to two decimals to obtain
        `review_hours_charged`."

        Design: Corner/validations/third_rework_request_rejected_at_the_cycle_limit
        """

        world = _meridian_offshore_world(api, phase_expected_hours=20.00)
        reviewer_id = world["reviewer"]["id"]
        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["offshore"]["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=10.00,
            review_owner_staff_id=reviewer_id,
        )
        schedule_engagement(api, world["engagement"]["id"])
        confirm_assignment(api, booking["id"])

        start_review(api, booking["id"], reviewer_id)
        request_rework(api, booking["id"], reviewer_id, reason_note="sampling not documented")
        start_review(api, booking["id"], reviewer_id)
        second = request_rework(
            api, booking["id"], reviewer_id, reason_note="tickmarks still missing"
        )
        assert second["rework_cycles"] == 2
        start_review(api, booking["id"], reviewer_id)

        validate_error(
            api.request_rework(
                booking["id"],
                partner_headers_for(reviewer_id),
                reason_note="third pass",
            ),
            ApiErrorId.REWORK_LIMIT_EXCEEDED.value,
            409,
        )

        window_after = read_review_window(api, world["window"]["id"])
        assert_hours(window_after["committed_review_hours"], 4.00)
        assert_hours(window_after["remaining_review_hours"], 6.00)

        accepted = accept_review(api, booking["id"], reviewer_id)
        assert accepted["review_status"] == "REVIEW_ACCEPTED"
        assert accepted["rework_cycles"] == 2


class TestReviewCycleLeavesStaffingAlone:
    """Four review-dimension calls on one confirmed booking."""

    def _cycled_booking(self, api):
        """An offshore booking taken round the rework loop once and then accepted."""

        world = offshore_review_world(
            api,
            review_windows=[
                {"week_start_date": "2026-08-24", "review_capacity_hours": 6.00}
            ],
        )
        reviewer_id = world["reviewer"]["id"]
        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["offshore"]["id"],
            start_date="2026-08-28",
            end_date="2026-08-31",
            allocated_hours=6.00,
            review_owner_staff_id=reviewer_id,
        )
        confirm_assignment(api, booking["id"])
        start_review(api, booking["id"], reviewer_id)
        request_rework(
            api,
            booking["id"],
            reviewer_id,
            reason_note="sampling documentation incomplete",
        )
        start_review(api, booking["id"], reviewer_id)
        accept_review(api, booking["id"], reviewer_id)
        return world, booking

    def test_the_review_dimension_cycles_while_the_staffing_dimension_holds(self, api):
        """Four review calls end at REVIEW_ACCEPTED and leave CONFIRMED standing.

        PRD 3.5: "A booking carries two entirely independent status dimensions."

        PRD 3.5: "Advancing one dimension never touches the other."

        PRD 3.5: "The cycle `IN_REVIEW → REWORK_REQUESTED → IN_REVIEW` may thus
        close twice before the ceiling bites."

        PRD 3.5: "Both transitions increment the booking's `version` and leave
        `staffing_status` untouched."

        Design: Difficulty/non_linear_state_machine/assignment_review_dimension_cycles_while_staffing_dimension_holds
        """

        world, booking = self._cycled_booking(api)

        read_back = read_assignment(api, booking["id"])
        assert read_back["review_status"] == "REVIEW_ACCEPTED"
        assert read_back["staffing_status"] == "CONFIRMED"
        assert read_back["rework_cycles"] == 1

        phase_after = read_phase(api, world["phase"]["id"])
        assert phase_after["staffing_status"] == "FULLY_STAFFED"
        assert_hours(phase_after["staffed_hours"], 6.00)

        assert read_engagement(api, world["engagement"]["id"])["status"] == "SETUP"

    def test_one_rework_round_adds_exactly_one_hour_to_the_same_window(self, api):
        """The floor of 2.00 plus one cycle is 3.00, all of it in the one bucket.

        PRD 3.5: "To that base the server adds one hour for each rework cycle the
        booking has accumulated, and rounds the total to two decimals to obtain
        `review_hours_charged`."

        PRD 3.5: "On success `rework_cycles` rises by one, `review_hours_charged`
        is recomputed with the extra hour charged to the **same**
        `review_capacity_window_id`, the window's `committed_review_hours` and
        `remaining_review_hours` are recomputed, and the booking's `version`
        increments."

        PRD 3.5: "and a booking of an `OFFSHORE` person is
        `OFFSHORE_SHARED_SERVICE`"

        Design: Difficulty/non_linear_state_machine/assignment_review_dimension_cycles_while_staffing_dimension_holds
        """

        world, booking = self._cycled_booking(api)
        window = world["review_windows"][0]

        read_back = read_assignment(api, booking["id"])
        assert read_back["rate_model"] == "OFFSHORE_SHARED_SERVICE"
        assert_hours(read_back["review_hours_charged"], 3.00)
        assert read_back["review_capacity_window_id"] == window["id"]

        window_after = read_review_window(api, window["id"])
        assert_hours(window_after["committed_review_hours"], 3.00)
        assert_hours(window_after["remaining_review_hours"], 3.00)


class TestReviewCapacityBoundary:
    """Exactly three review hours in a three-hour window, then one more."""

    def _window_filled_to_the_brim(self, api):
        """A booking whose charge, after one rework, equals its window's capacity."""

        world = offshore_review_world(
            api,
            review_windows=[
                {"week_start_date": "2026-08-24", "review_capacity_hours": 3.00}
            ],
        )
        reviewer_id = world["reviewer"]["id"]
        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["offshore"]["id"],
            start_date="2026-08-28",
            end_date="2026-08-31",
            allocated_hours=6.00,
            review_owner_staff_id=reviewer_id,
        )
        confirm_assignment(api, booking["id"])
        start_review(api, booking["id"], reviewer_id)
        request_rework(
            api, booking["id"], reviewer_id, reason_note="tie-out schedule missing"
        )
        start_review(api, booking["id"], reviewer_id)
        return world, booking

    def test_the_next_rework_block_is_refused_on_capacity_not_on_cycles(
        self, api, partner_headers_for
    ):
        """Landing on 3.00 was fine; the fourth hour has nowhere to go.

        PRD 3.5: "If the window exists but its `committed_review_hours` plus this
        booking's charge would exceed its `review_capacity_hours`, the write is
        refused with `ERR_REVIEW_CAPACITY_EXCEEDED`; landing exactly on the
        capacity figure is admissible."

        PRD 3.5: "It is also permitted only if the recomputed charge — the base plus
        one hour for the incremented cycle count — keeps the bound window's
        `committed_review_hours` at or below its `review_capacity_hours`; otherwise
        the request is refused with `ERR_REVIEW_CAPACITY_EXCEEDED`."

        PRD 3.5: "It is permitted only while `rework_cycles` is strictly below two,
        so a booking may go round the rework loop at most twice; a third attempt is
        refused with `ERR_REWORK_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/review_capacity_admits_exact_equality_and_rejects_next_rework_block
        """

        world, booking = self._window_filled_to_the_brim(api)
        window = world["review_windows"][0]

        at_capacity = read_assignment(api, booking["id"])
        assert_hours(at_capacity["review_hours_charged"], 3.00)
        assert_hours(
            read_review_window(api, window["id"])["remaining_review_hours"], 0.00
        )

        error = validate_error(
            api.request_rework(
                booking["id"],
                partner_headers_for(world["reviewer"]["id"]),
                reason_note="still incomplete",
            ),
            ApiErrorId.REVIEW_CAPACITY_EXCEEDED.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.REWORK_LIMIT_EXCEEDED.value

    def test_the_refused_rework_charges_nothing_and_leaves_the_review_open(
        self, api, partner_headers_for
    ):
        """The cycle count, the charge and the window are all exactly as before.

        PRD 3.5: "Sending work back advances the review `IN_REVIEW →
        REWORK_REQUESTED` with an optional `reason_note`, and it costs the reviewer
        real capacity."

        PRD 3.5: "Opening a review advances it `PENDING_REVIEW → IN_REVIEW`, or
        reopens it `REWORK_REQUESTED → IN_REVIEW` after a rework round; in either
        case the booking's `staffing_status` must be `CONFIRMED` or `ACTIVE`, and
        when opening from `PENDING_REVIEW` the acting `X-User-ID` must additionally
        differ from the booking's `staff_member_id`."

        PRD 2.9: "**The first check that fails determines the response, and no
        later check is evaluated.**"

        Design: Difficulty/boundary_precision_check/review_capacity_admits_exact_equality_and_rejects_next_rework_block
        """

        world, booking = self._window_filled_to_the_brim(api)
        window = world["review_windows"][0]

        validate_error(
            api.request_rework(
                booking["id"],
                partner_headers_for(world["reviewer"]["id"]),
                reason_note="still incomplete",
            ),
            ApiErrorId.REVIEW_CAPACITY_EXCEEDED.value,
            409,
        )

        read_back = read_assignment(api, booking["id"])
        assert read_back["rework_cycles"] == 1
        assert read_back["review_status"] == "IN_REVIEW"
        assert_hours(read_back["review_hours_charged"], 3.00)

        window_after = read_review_window(api, window["id"])
        assert_hours(window_after["committed_review_hours"], 3.00)
        assert_hours(window_after["remaining_review_hours"], 0.00)


class TestChargeBucketIsTheLastWorkedDay:
    """A booking ending on a Monday charges the week before it."""

    def _spanning_booking(self, api):
        """One offshore booking over Friday to Sunday with a window either side."""

        world = offshore_review_world(
            api,
            review_windows=[
                {"week_start_date": "2026-08-24", "review_capacity_hours": 10.00},
                {"week_start_date": "2026-08-31", "review_capacity_hours": 10.00},
            ],
        )
        booking = create_assignment(
            api,
            world["phase"]["id"],
            world["offshore"]["id"],
            start_date="2026-08-28",
            end_date="2026-08-31",
            allocated_hours=6.00,
            review_owner_staff_id=world["reviewer"]["id"],
        )
        return world, booking

    def test_the_charge_binds_to_the_week_of_the_last_worked_day(self, api):
        """The end_date Monday is never occupied, so the earlier window takes it.

        PRD 3.5: "The whole charge lands in exactly **one** weekly bucket, and the
        bucket is keyed by the booking's **last worked day** — `end_date` minus one
        day — regardless of how many ISO weeks the booking spans."

        PRD 3.5: "The `review_capacity_window_id` is the window whose
        `reviewer_staff_id` equals the booking's `review_owner_staff_id` and whose
        `week_start_date` is the Monday on or before that last worked day; the
        uniqueness rule above guarantees at most one such window."

        PRD 2.5: "The *last worked day* of a booking is `end_date` minus one day,
        and the number of occupied dates — the booking's `calendar_day_count` — is
        the whole number of days from `start_date` to `end_date`, which is at least
        1."

        Design: Difficulty/resource_temporal_overlap/offshore_review_charge_lands_in_iso_week_of_last_worked_day
        """

        world, booking = self._spanning_booking(api)
        earlier, later = world["review_windows"]

        assert booking["rate_model"] == "OFFSHORE_SHARED_SERVICE"
        assert booking["calendar_day_count"] == 3
        assert_hours(booking["daily_hours"], 2.00)
        assert_hours(booking["review_hours_charged"], 2.00)
        assert booking["review_capacity_window_id"] == earlier["id"]
        assert booking["review_capacity_window_id"] != later["id"]
        assert booking["review_status"] == "PENDING_REVIEW"

    def test_the_other_week_is_left_completely_untouched(self, api):
        """All 2.00 hours sit in the 2026-08-24 window and none in the 2026-08-31 one.

        PRD 3.5: "The whole charge lands in exactly **one** weekly bucket, and the
        bucket is keyed by the booking's **last worked day** — `end_date` minus one
        day — regardless of how many ISO weeks the booking spans."

        PRD 3.5: "Thereafter `committed_review_hours` is the sum, rounded to two
        decimals, of `review_hours_charged` over every booking bound to that window
        whose staffing dimension is `PROPOSED`, `CONFIRMED`, `ACTIVE` or
        `COMPLETED` — released bookings are excluded — and `remaining_review_hours`
        is `review_capacity_hours` minus that committed figure, rounded to two
        decimals."

        Design: Difficulty/resource_temporal_overlap/offshore_review_charge_lands_in_iso_week_of_last_worked_day
        """

        world, _booking = self._spanning_booking(api)
        earlier, later = world["review_windows"]

        earlier_after = read_review_window(api, earlier["id"])
        assert_hours(earlier_after["committed_review_hours"], 2.00)
        assert_hours(earlier_after["remaining_review_hours"], 8.00)

        later_after = read_review_window(api, later["id"])
        assert_hours(later_after["committed_review_hours"], 0.00)
        assert_hours(later_after["remaining_review_hours"], 10.00)
