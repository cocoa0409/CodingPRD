"""Leave windows, per-day and per-week ceilings, burnout scores and overtime relief."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    accumulate_prior_week_actuals,
    approve_waiver,
    assert_hours,
    confirm_assignment,
    create_assignment,
    create_assignment_payload,
    create_availability_exception,
    create_availability_exception_payload,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_senior,
    create_workload_waiver_payload,
    read_assignment,
    read_phase,
    read_staff,
    read_waiver,
    read_workload,
    request_waiver,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _meridian_phase(api, expected_hours=20.00, budget_fee_amount=6000.00, **phase_overrides):
    """Client, partner, senior, engagement and one fieldwork phase in August."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    senior = create_senior(api)
    engagement = create_engagement(
        api, client["id"], partner["id"], budget_fee_amount=budget_fee_amount
    )
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=expected_hours,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
        **phase_overrides,
    )
    return client, partner, senior, engagement, phase


class TestAvailabilityExceptions:
    """Leave and training windows, and how a booking meets them."""

    def test_exceptions_may_not_share_a_single_date(self, api, admin_headers, manager_headers):
        """One shared Friday is enough to refuse the second window.

        PRD 3.4: "These records are immutable once written, and they may never
        overlap: a new exception whose closed window shares any date with an
        existing exception of the same person is refused with
        `ERR_EXCEPTION_OVERLAP`, which guarantees that at most one exception ever
        governs a given date."

        PRD 3.4: "Each staff member's exceptions can be read back as a
        sub-resource collection, filterable by `exception_type`."

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/validations/availability_exception_sharing_one_date_rejected_as_overlap
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        senior = create_senior(api)
        create_availability_exception(
            api,
            senior["id"],
            exception_type="PTO",
            start_date="2026-08-05",
            end_date="2026-08-07",
            available_hours_per_day=0.00,
        )

        validate_error(
            api.create_availability_exception(
                create_availability_exception_payload(
                    senior["id"],
                    exception_type="TRAINING",
                    start_date="2026-08-07",
                    end_date="2026-08-10",
                    available_hours_per_day=4.00,
                ),
                admin_headers,
            ),
            ApiErrorId.EXCEPTION_OVERLAP.value,
            409,
        )

        accepted = validate_success(
            api.create_availability_exception(
                create_availability_exception_payload(
                    senior["id"],
                    exception_type="TRAINING",
                    start_date="2026-08-08",
                    end_date="2026-08-10",
                    available_hours_per_day=4.00,
                ),
                admin_headers,
            ),
            201,
        )
        assert accepted["start_date"] == "2026-08-08"
        assert_hours(accepted["available_hours_per_day"], 4.00)

        rows, meta = validate_paginated(
            api.list_staff_availability_exceptions(senior["id"], manager_headers)
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

    def test_booking_across_a_zero_hour_leave_day_is_refused(self, api, manager_headers):
        """Reaching into unpaid-leave dates is refused; stopping short of them is not.

        PRD 3.4: "Separately and earlier on the ladder, if any date the booking
        occupies is governed by an exception whose `available_hours_per_day` is
        0.00, the booking is refused outright with `ERR_STAFF_UNAVAILABLE`."

        PRD 2.5: "A booking's occupation of a staff member's calendar is
        **half-open**: it covers `start_date` through the day before `end_date`,
        and `end_date` itself is never occupied."

        PRD 3.3: "The `daily_hours` figure is `allocated_hours` divided by
        `calendar_day_count`, **rounded half up to two decimals exactly once,
        here**."

        Design: Corner/validations/booking_across_zero_hour_leave_day_rejected_as_staff_unavailable
        """

        _client, _partner, senior, _engagement, phase = _meridian_phase(api)
        create_availability_exception(
            api,
            senior["id"],
            exception_type="PTO",
            start_date="2026-08-05",
            end_date="2026-08-07",
            available_hours_per_day=0.00,
        )

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-03",
                    end_date="2026-08-08",
                    allocated_hours=20.00,
                ),
                manager_headers,
            ),
            ApiErrorId.STAFF_UNAVAILABLE.value,
            409,
        )

        accepted = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-05",
            allocated_hours=5.00,
        )
        assert accepted["calendar_day_count"] == 2
        assert_hours(accepted["daily_hours"], 2.50)

        phase_after = read_phase(api, phase["id"])
        assert_hours(phase_after["staffed_hours"], 5.00)
        assert_hours(phase_after["unstaffed_hours"], 15.00)

    def test_reduced_training_capacity_still_admits_a_booking_that_fits(self, api):
        """A four-hour training day replaces the ten-hour baseline, and 3.57 fits under it.

        PRD 3.4: "If an availability exception covers the date, that exception's
        `available_hours_per_day` **replaces** the baseline rather than reducing
        it."

        PRD 3.4: "A candidate booking is admissible only if, for **every** date it
        occupies, the already-booked hours plus the candidate's own `daily_hours`
        are less than or equal to that date's capacity; exact equality is
        admissible."

        Design: Corner/validations/training_exception_day_admits_a_booking_that_fits_under_it
        """

        _client, _partner, senior, _engagement, phase = _meridian_phase(
            api, expected_hours=30.00, budget_fee_amount=9000.00
        )
        create_availability_exception(
            api,
            senior["id"],
            exception_type="TRAINING",
            start_date="2026-08-03",
            end_date="2026-08-07",
            available_hours_per_day=4.00,
        )

        booking = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=25.00,
        )
        assert booking["calendar_day_count"] == 7
        assert_hours(booking["daily_hours"], 3.57)

        phase_after = read_phase(api, phase["id"])
        assert_hours(phase_after["staffed_hours"], 25.00)
        assert_hours(phase_after["unstaffed_hours"], 5.00)
        assert phase_after["staffing_status"] == "PARTIALLY_STAFFED"


class TestWeeklyGateAndPerDayFlattening:
    """The weekly ceiling and the once-only rounding of the per-day figure."""

    def test_weekly_cap_bites_where_the_daily_capacity_does_not(
        self, api, manager_headers
    ):
        """Three hours a day is comfortable per date yet still overruns the week.

        PRD 3.4: "A candidate booking is admissible only if, for **every** ISO week
        its occupied dates touch, the existing committed load plus the candidate's
        contribution to that week is less than or equal to the person's effective
        weekly cap for that week; exact equality is admissible. A breach in any
        touched week is `ERR_WORKLOAD_CAP_EXCEEDED`."

        PRD 3.4: "`workload_status` is the traffic light over these two figures:
        `GREEN` while `committed_hours_current_week` is at most
        `base_weekly_cap_hours`, `AMBER` when it exceeds `base_weekly_cap_hours`
        but is at most `effective_weekly_cap_hours`, and `RED` when it exceeds
        `effective_weekly_cap_hours`."

        Design: Corner/validations/second_booking_in_same_week_breaches_weekly_cap_but_not_daily_capacity
        """

        _client, _partner, senior, _engagement, phase = _meridian_phase(
            api, expected_hours=60.00, budget_fee_amount=12000.00
        )
        first = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=45.00,
        )
        assert first["calendar_day_count"] == 5
        assert_hours(first["daily_hours"], 9.00)

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-08",
                    end_date="2026-08-10",
                    allocated_hours=6.00,
                ),
                manager_headers,
            ),
            ApiErrorId.WORKLOAD_CAP_EXCEEDED.value,
            409,
        )

        accepted = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-08",
            end_date="2026-08-10",
            allocated_hours=5.00,
        )
        assert_hours(accepted["daily_hours"], 2.50)

        workload = read_workload(api, senior["id"], week_start_date="2026-08-03")
        assert_hours(workload["committed_hours"], 50.00)
        assert_hours(workload["remaining_week_hours"], 0.00)
        assert workload["workload_status"] == "AMBER"

    def test_seven_day_flattening_leaves_two_hundredths_of_weekly_slack(self, api):
        """Fifty hours over seven days commits 49.98, not 50.00.

        PRD 3.3: "Every downstream weekly figure multiplies this already-rounded
        per-day figure by a day count, so a seven-day booking of 50.00 hours
        flattens to 7.14 hours per day and commits 49.98 hours in that week, not
        50.00; recomputing a weekly figure from the raw total instead is a
        different and rejected reading."

        PRD 3.4: "Both variants then apply the same decay weights — the current
        week at full weight, then three-quarters, then one-half, then one-quarter —
        sum the four weighted overages, divide by the total weight of 2.50, and
        round to two decimals."

        PRD 3.4: "`ELEVATED` when it is at least 3.00 and strictly below 6.00 —
        that is, from 3.00 through 5.99 at two-decimal precision"

        Design: Corner/calculations/daily_hours_rounding_leaves_two_hundredths_of_weekly_slack
        """

        _client, _partner, senior, _engagement, phase = _meridian_phase(
            api, expected_hours=50.00, budget_fee_amount=9000.00
        )
        booking = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=50.00,
        )
        confirm_assignment(api, booking["id"])

        workload = read_workload(api, senior["id"], week_start_date="2026-08-03")
        assert_hours(workload["effective_weekly_cap_hours"], 50.00)
        assert_hours(workload["daily_capacity_hours"], 10.00)
        assert_hours(workload["committed_hours"], 49.98)
        assert_hours(workload["remaining_week_hours"], 0.02)
        assert_hours(workload["logged_hours"], 0.00)
        assert_hours(workload["burnout_risk_score_actual"], 0.00)
        assert_hours(workload["burnout_risk_score_committed"], 3.99)
        assert workload["turnover_risk_band"] == "ELEVATED"

        read_back = read_assignment(api, booking["id"])
        assert read_back["calendar_day_count"] == 7
        assert_hours(read_back["daily_hours"], 7.14)
        assert_hours(read_back["allocated_hours"], 50.00)


class TestDailyCapacityBoundary:
    """Exactly ten hours on one date, then one hundredth more."""

    def _saturated_single_date(self, api):
        """A booking that fills 2026-08-05 to the hundredth of its capacity."""

        _client, _partner, senior, _engagement, phase = _meridian_phase(
            api,
            expected_hours=60.00,
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        booking = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-05",
            end_date="2026-08-06",
            allocated_hours=10.00,
        )
        return senior, phase, booking

    def test_one_hundredth_over_the_dates_capacity_is_refused(
        self, api, manager_headers
    ):
        """10.01 against a 10.00 capacity is a per-date breach, not a weekly one.

        PRD 3.4: "A candidate booking is admissible only if, for **every** date it
        occupies, the already-booked hours plus the candidate's own `daily_hours`
        are less than or equal to that date's capacity; exact equality is
        admissible. Failure is `ERR_DAILY_CAPACITY_EXCEEDED`."

        PRD 3.4: "A breach in any touched week is `ERR_WORKLOAD_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/daily_capacity_admits_exact_equality_and_rejects_one_hundredth_over
        """

        senior, phase, _booking = self._saturated_single_date(api)

        error = validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-05",
                    end_date="2026-08-06",
                    allocated_hours=0.01,
                ),
                manager_headers,
            ),
            ApiErrorId.DAILY_CAPACITY_EXCEEDED.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.WORKLOAD_CAP_EXCEEDED.value

        staff_after = read_staff(api, senior["id"])
        assert_hours(staff_after["committed_hours_current_week"], 10.00)

    def test_the_exact_equality_booking_stands_and_owns_the_whole_date(
        self, api, manager_headers
    ):
        """Landing exactly on the capacity figure is admitted and left alone.

        PRD 3.4: "The hours a person may be booked for on one specific calendar
        date start from a baseline: their effective weekly cap for the ISO week
        containing that date, divided by the five standard working days of a week,
        rounded half up to two decimals — the figure surfaced as
        `daily_capacity_hours`."

        PRD 3.4: "exact equality is admissible"

        Design: Difficulty/boundary_precision_check/daily_capacity_admits_exact_equality_and_rejects_one_hundredth_over
        """

        senior, phase, booking = self._saturated_single_date(api)

        assert booking["calendar_day_count"] == 1
        assert_hours(booking["daily_hours"], 10.00)
        assert_hours(read_staff(api, senior["id"])["daily_capacity_hours"], 10.00)

        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-05",
                    end_date="2026-08-06",
                    allocated_hours=0.01,
                ),
                manager_headers,
            ),
            ApiErrorId.DAILY_CAPACITY_EXCEEDED.value,
            409,
        )

        phase_after = read_phase(api, phase["id"])
        assert_hours(phase_after["staffed_hours"], 10.00)
        assert_hours(phase_after["unstaffed_hours"], 50.00)
        assert phase_after["staffing_status"] == "PARTIALLY_STAFFED"


class TestAdjacentAndSharedDates:
    """Abutting intervals never meet; a shared date aggregates."""

    def _abutting_pair(self, api):
        """Two seven-day bookings that touch at 2026-08-10 without overlapping."""

        _client, _partner, senior, _engagement, phase = _meridian_phase(
            api,
            expected_hours=100.00,
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        first = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=35.00,
        )
        second = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-10",
            end_date="2026-08-17",
            allocated_hours=35.00,
        )
        return senior, phase, first, second

    def test_abutting_bookings_never_aggregate_against_each_other(self, api):
        """A booking ending on the Monday and one starting on it both stand.

        PRD 2.5: "Two bookings whose intervals abut, such as one running to a
        given Monday and the next starting on that same Monday, share no date at
        all and never aggregate against each other."

        PRD 3.4: "A person's committed load in one ISO week is the sum, rounded to
        two decimals, over their bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or
        `COMPLETED` of that booking's `daily_hours` multiplied by the number of its
        occupied dates that fall inside that week's seven days; released bookings
        are excluded and review hours never enter this figure at all."

        Design: Difficulty/resource_temporal_overlap/half_open_adjacent_bookings_admitted_but_shared_date_aggregate_rejected
        """

        senior, _phase, first, second = self._abutting_pair(api)

        assert first["calendar_day_count"] == 7
        assert second["calendar_day_count"] == 7
        assert_hours(first["daily_hours"], 5.00)
        assert_hours(second["daily_hours"], 5.00)

        assert_hours(read_staff(api, senior["id"])["committed_hours_current_week"], 35.00)
        later_week = read_workload(api, senior["id"], week_start_date="2026-08-10")
        assert_hours(later_week["committed_hours"], 35.00)

    def test_a_third_booking_sharing_one_date_breaches_that_dates_capacity(
        self, api, manager_headers
    ):
        """Five hours already on 2026-08-10 plus six more is 11.00 against 10.00.

        PRD 3.4: "Against that capacity the server sets the hours already booked on
        the date: the sum, rounded to two decimals, of `daily_hours` over every
        booking of that person in `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED`
        whose half-open occupation includes the date."

        PRD 3.4: "Failure is `ERR_DAILY_CAPACITY_EXCEEDED`. This is an aggregate
        test, not a double-booking ban: two bookings may share dates freely so long
        as their summed per-day hours fit."

        Design: Difficulty/resource_temporal_overlap/half_open_adjacent_bookings_admitted_but_shared_date_aggregate_rejected
        """

        senior, phase, _first, _second = self._abutting_pair(api)

        error = validate_error(
            api.create_assignment(
                create_assignment_payload(
                    phase["id"],
                    senior["id"],
                    start_date="2026-08-10",
                    end_date="2026-08-11",
                    allocated_hours=6.00,
                ),
                manager_headers,
            ),
            ApiErrorId.DAILY_CAPACITY_EXCEEDED.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.WORKLOAD_CAP_EXCEEDED.value

        phase_after = read_phase(api, phase["id"])
        assert_hours(phase_after["staffed_hours"], 70.00)
        assert_hours(phase_after["unstaffed_hours"], 30.00)
        assert phase_after["staffing_status"] == "PARTIALLY_STAFFED"


class TestTurnoverRiskGateAndOvertimeRelief:
    """The one moment the turnover band has teeth, and the relief that lifts it."""

    def test_high_risk_confirmation_needs_relief_for_that_very_week(
        self, api, manager_headers
    ):
        """The allowance is week-scoped: it frees one booking and not its siblings.

        PRD 3.4: "Confirming a booking for somebody whose `turnover_risk_band` is
        `HIGH` is refused with `ERR_TURNOVER_RISK_BLOCK` **unless** an overtime
        allowance with status `APPROVED` exists for that person for the ISO week
        containing the booking's `start_date`."

        PRD 3.4: "A `HIGH` band does not block proposal, activation or time logging
        — only the confirmation step."

        PRD 3.4: "`turnover_risk_band` is banded over the **larger** of the two
        scores, with inclusive lower boundaries: `LOW` when that maximum is strictly
        below 3.00, `ELEVATED` when it is at least 3.00 and strictly below 6.00 —
        that is, from 3.00 through 5.99 at two-decimal precision — and `HIGH` when
        it is at least 6.00."

        PRD 3.4: "Approval moves the allowance `REQUESTED → APPROVED`, stamps the
        deciding operator's `X-User-ID` onto `approved_by_user_id`, recomputes the
        beneficiary's `effective_weekly_cap_hours` and `daily_capacity_hours` for
        that ISO week so the extra hours become spendable, recomputes their
        `workload_status`, and increments the allowance's `version`."

        Design: Corner/validations/confirming_a_high_turnover_risk_booking_needs_an_approved_waiver
        """

        _client, partner, senior, engagement, phase = _meridian_phase(
            api, expected_hours=200.00, budget_fee_amount=40000.00
        )
        weeks = [
            ("2026-08-03", "2026-08-10"),
            ("2026-08-10", "2026-08-17"),
            ("2026-08-17", "2026-08-24"),
            ("2026-08-24", "2026-08-31"),
        ]
        bookings = [
            create_assignment(
                api,
                phase["id"],
                senior["id"],
                start_date=start,
                end_date=end,
                allocated_hours=49.00,
            )
            for start, end in weeks
        ]

        staff_before = read_staff(api, senior["id"])
        assert_hours(staff_before["burnout_risk_score_committed"], 9.00)
        assert staff_before["turnover_risk_band"] == "HIGH"

        validate_error(
            api.confirm_assignment(bookings[3]["id"], manager_headers),
            ApiErrorId.TURNOVER_RISK_BLOCK.value,
            409,
        )

        waiver = request_waiver(
            api,
            senior["id"],
            engagement["id"],
            "2026-08-24",
            3.00,
            justification_note="deadline week",
        )
        assert waiver["status"] == "REQUESTED"

        approved = approve_waiver(api, waiver["id"], partner["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == partner["id"]

        confirmed = validate_success(
            api.confirm_assignment(bookings[3]["id"], manager_headers)
        )
        assert confirmed["staffing_status"] == "CONFIRMED"

        other_week = validate_error(
            api.confirm_assignment(bookings[0]["id"], manager_headers),
            ApiErrorId.TURNOVER_RISK_BLOCK.value,
            409,
        )
        assert other_week["error_id"] == ApiErrorId.TURNOVER_RISK_BLOCK.value

    def test_second_live_request_for_one_week_is_refused(
        self, api, staff_headers_for
    ):
        """A person holds at most one live allowance per Monday.

        PRD 3.4: "A person may not hold two live requests for the same week: a
        second allowance for the same `staff_member_id` and `week_start_date` while
        one is `REQUESTED` or `APPROVED` is refused with `ERR_DUPLICATE_WAIVER`."

        PRD 3.4: "The request is created `REQUESTED` and changes no cap yet."

        Design: Corner/validations/second_open_waiver_for_same_staff_week_rejected
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])

        first = request_waiver(
            api,
            senior["id"],
            engagement["id"],
            "2026-08-03",
            3.00,
            justification_note="peak fieldwork week",
        )

        validate_error(
            api.create_workload_waiver(
                create_workload_waiver_payload(
                    senior["id"],
                    engagement["id"],
                    week_start_date="2026-08-03",
                    extra_hours_allowance=2.00,
                ),
                staff_headers_for(senior["id"]),
            ),
            ApiErrorId.DUPLICATE_WAIVER.value,
            409,
        )

        next_week = validate_success(
            api.create_workload_waiver(
                create_workload_waiver_payload(
                    senior["id"],
                    engagement["id"],
                    week_start_date="2026-08-10",
                    extra_hours_allowance=2.00,
                ),
                staff_headers_for(senior["id"]),
            ),
            201,
        )
        assert next_week["week_start_date"] == "2026-08-10"
        assert next_week["status"] == "REQUESTED"

        untouched = read_waiver(api, first["id"])
        assert untouched["status"] == "REQUESTED"
        assert_hours(untouched["extra_hours_allowance"], 3.00)

    def test_denial_after_approval_is_refused_and_the_cap_survives(
        self, api, partner_headers_for
    ):
        """Approval is final: the partner cannot then deny the same allowance.

        PRD 3.4: "Denial moves the allowance `REQUESTED → DENIED`, likewise stamps
        `approved_by_user_id`, and increments `version`; it changes no cap."

        PRD 3.4: "To it the server adds the allowance: the sum, rounded to two
        decimals, of `extra_hours_allowance` over every overtime allowance for this
        person and this `week_start_date` whose status is `APPROVED`."

        PRD 3.4: "An absolute ceiling of forty percent above contracted hours —
        `base_weekly_cap_hours` multiplied by 1.40, rounded to two decimals — is
        then applied, and `effective_weekly_cap_hours` is the smaller of the raw cap
        plus allowance and that ceiling, rounded to two decimals."

        PRD 3.4: "An approved allowance can also be withdrawn by events rather than
        by a person, always as `APPROVED → EXPIRED` and always recording why in
        `expiry_reason`."

        Design: Corner/state_machines/deny_after_approve_rejected_as_waiver_invalid_state
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])

        waiver = request_waiver(
            api,
            senior["id"],
            engagement["id"],
            "2026-08-03",
            3.00,
            justification_note="Interim testing crunch",
        )
        approve_waiver(api, waiver["id"], partner["id"])

        validate_error(
            api.deny_workload_waiver(waiver["id"], partner_headers_for(partner["id"])),
            ApiErrorId.WAIVER_INVALID_STATE.value,
            409,
        )

        read_back = read_waiver(api, waiver["id"])
        assert read_back["status"] == "APPROVED"
        assert read_back["approved_by_user_id"] == partner["id"]
        assert read_back["expiry_reason"] is None
        assert read_back["version"] == 2

        workload = read_workload(api, senior["id"], week_start_date="2026-08-03")
        assert_hours(workload["approved_waiver_hours"], 3.00)
        assert_hours(workload["effective_weekly_cap_hours"], 53.00)


class TestBurnoutVariantsDiverge:
    """One person, two scores, two directions of travel."""

    def _looking_both_ways(self, api):
        """A heavy logged week behind, two heavier booked weeks ahead."""

        set_clock(api, "2026-07-27T09:00:00Z")
        client = create_client(api, name="Northwind Foods")
        partner = create_partner(api)
        senior = create_senior(api, full_name="Sena Adeyemi")
        prior = accumulate_prior_week_actuals(
            api,
            senior["id"],
            partner["id"],
            client["id"],
            week_start_date="2026-07-27",
            booking_hours=46.00,
            booking_start="2026-07-27",
            booking_end="2026-08-01",
            daily_logs=[
                {"work_date": "2026-07-27", "hours": 12.00},
                {"work_date": "2026-07-28", "hours": 12.00},
                {"work_date": "2026-07-29", "hours": 12.00},
                {"work_date": "2026-07-30", "hours": 10.00},
            ],
            phase_expected_hours=46.00,
            phase_window_start="2026-07-27",
            phase_window_end="2026-08-31",
            engagement_budget=9000.00,
        )

        set_clock(api, "2026-08-03T09:00:00Z")
        forward_phase = create_phase(
            api,
            prior["engagement"]["id"],
            expected_hours=44.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        this_week = create_assignment(
            api,
            forward_phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=44.00,
        )
        next_week = create_assignment(
            api,
            forward_phase["id"],
            senior["id"],
            start_date="2026-08-10",
            end_date="2026-08-17",
            allocated_hours=49.00,
        )
        return senior, this_week, next_week

    def test_the_two_variants_report_different_scores_for_the_same_person(self, api):
        """1.80 looking back, 4.31 looking forward, from one row.

        PRD 3.4: "The retrospective variant, surfaced as
        `burnout_risk_score_actual`, walks *backwards*: week *i* is the week
        starting seven times *i* days before the current week's Monday."

        PRD 3.4: "The forward-looking variant, surfaced as
        `burnout_risk_score_committed`, walks *forwards*: week *i* is the week
        starting seven times *i* days after the current week's Monday, and the
        week's overage is that week's committed load minus `base_weekly_cap_hours`,
        floored at 0.00 and rounded to two decimals."

        PRD 3.4: "The consequence of the two directions is worth internalising:
        somebody who has logged nothing scores 0.00 on the retrospective variant
        however heavily they are booked, while somebody booked well over cap next
        month scores above 0.00 on the forward-looking variant with no logged
        history at all."

        Design: Difficulty/dual_variant_calc/burnout_actual_trailing_vs_committed_forward_diverges_for_same_staff
        """

        senior, _this_week, _next_week = self._looking_both_ways(api)

        workload = read_workload(api, senior["id"])
        assert workload["week_start_date"] == "2026-08-03"
        assert_hours(workload["logged_hours"], 0.00)
        assert_hours(workload["committed_hours"], 44.03)
        assert_hours(workload["burnout_risk_score_actual"], 1.80)
        assert_hours(workload["burnout_risk_score_committed"], 4.31)
        assert (
            workload["burnout_risk_score_committed"]
            != workload["burnout_risk_score_actual"]
        )

    def test_the_prior_week_tier_sets_the_cap_and_the_larger_score_sets_the_band(
        self, api
    ):
        """Last week's 46.00 logged hours shrink this week's cap to 46.00.

        PRD 3.4: "That prior-week logged total divided by the person's
        `base_weekly_cap_hours`, rounded half up to four decimals, is the
        utilisation ratio. The burnout tier follows from it with inclusive upper
        bounds: `GREEN` when utilisation is at most 1.0000, `AMBER` when
        utilisation is greater than 1.0000 and at most 1.2500, `RED` when
        utilisation is greater than 1.2500."

        PRD 3.4: "The counter-intuitive direction is intentional: the harder
        somebody worked last week, the *less* headroom they are given this week."

        PRD 3.4: "`turnover_risk_band` is banded over the **larger** of the two
        scores, with inclusive lower boundaries"

        PRD 3.3: "The `daily_hours` figure is `allocated_hours` divided by
        `calendar_day_count`, **rounded half up to two decimals exactly once,
        here**."

        Design: Difficulty/dual_variant_calc/burnout_actual_trailing_vs_committed_forward_diverges_for_same_staff
        """

        senior, this_week, next_week = self._looking_both_ways(api)

        assert_hours(this_week["daily_hours"], 6.29)
        assert_hours(next_week["daily_hours"], 7.00)

        workload = read_workload(api, senior["id"])
        assert_hours(workload["effective_weekly_cap_hours"], 46.00)
        assert_hours(workload["daily_capacity_hours"], 9.20)
        assert_hours(workload["remaining_week_hours"], 1.97)
        assert workload["workload_status"] == "AMBER"
        assert workload["turnover_risk_band"] == "ELEVATED"


class TestEffectiveCapComposition:
    """Prior-week tier, then the allowance, then the absolute ceiling."""

    def _part_time_senior_with_relief(self, api):
        """A twenty-hour senior who overran last week and holds an eight-hour allowance."""

        set_clock(api, "2026-07-27T09:00:00Z")
        client = create_client(api, name="Halcyon Tooling")
        partner = create_partner(api)
        senior = create_senior(
            api, full_name="Robin Castellanos", base_weekly_cap_hours=20.00
        )
        prior = accumulate_prior_week_actuals(
            api,
            senior["id"],
            partner["id"],
            client["id"],
            week_start_date="2026-07-27",
            booking_hours=22.00,
            booking_start="2026-07-27",
            booking_end="2026-08-01",
            daily_logs=[
                {"work_date": "2026-07-27", "hours": 5.50},
                {"work_date": "2026-07-28", "hours": 5.50},
                {"work_date": "2026-07-29", "hours": 5.50},
                {"work_date": "2026-07-30", "hours": 5.50},
            ],
            phase_expected_hours=22.00,
            phase_window_start="2026-07-27",
            phase_window_end="2026-08-31",
            engagement_budget=9000.00,
        )

        set_clock(api, "2026-08-03T09:00:00Z")
        waiver = request_waiver(
            api,
            senior["id"],
            prior["engagement"]["id"],
            "2026-08-03",
            8.00,
            justification_note="peak filing week",
        )
        approve_waiver(api, waiver["id"], partner["id"])
        return senior, partner, waiver

    def test_the_absolute_ceiling_clamps_the_tier_cap_plus_allowance(self, api):
        """23.00 plus 8.00 is 31.00, but 1.40 times 20.00 caps it at 28.00.

        PRD 3.4: "The raw cap is `base_weekly_cap_hours` multiplied by that tier
        multiplier, rounded to two decimals. To it the server adds the allowance:
        the sum, rounded to two decimals, of `extra_hours_allowance` over every
        overtime allowance for this person and this `week_start_date` whose status
        is `APPROVED`. An absolute ceiling of forty percent above contracted hours
        — `base_weekly_cap_hours` multiplied by 1.40, rounded to two decimals — is
        then applied, and `effective_weekly_cap_hours` is the smaller of the raw cap
        plus allowance and that ceiling, rounded to two decimals."

        PRD 3.4: "The tier supplies a multiplier — a quarter more than contracted
        hours for `GREEN`, fifteen percent more for `AMBER`, and no uplift at all
        for `RED`, so the multipliers are 1.25, 1.15 and 1.00 respectively."

        Design: Difficulty/combinatorial_formula/effective_weekly_cap_combines_prior_week_tier_waiver_allowance_and_ceiling
        """

        senior, partner, waiver = self._part_time_senior_with_relief(api)

        workload = read_workload(api, senior["id"], week_start_date="2026-08-03")
        assert_hours(workload["effective_weekly_cap_hours"], 28.00)
        assert round(float(workload["effective_weekly_cap_hours"]), 2) != 31.00
        assert round(float(workload["effective_weekly_cap_hours"]), 2) != 33.00
        assert_hours(workload["approved_waiver_hours"], 8.00)

        approved = read_waiver(api, waiver["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == partner["id"]

    def test_the_clamped_cap_drives_the_daily_figure_and_the_headroom(self, api):
        """A 28.00 weekly cap divides into 5.60 a day with all of it still free.

        PRD 3.4: "The hours a person may be booked for on one specific calendar
        date start from a baseline: their effective weekly cap for the ISO week
        containing that date, divided by the five standard working days of a week,
        rounded half up to two decimals — the figure surfaced as
        `daily_capacity_hours`."

        PRD 3.4: "`workload_status` is the traffic light over these two figures:
        `GREEN` while `committed_hours_current_week` is at most
        `base_weekly_cap_hours`, `AMBER` when it exceeds `base_weekly_cap_hours`
        but is at most `effective_weekly_cap_hours`, and `RED` when it exceeds
        `effective_weekly_cap_hours`."

        PRD 3.4: "It returns `staff_member_id`, the `week_start_date` it resolved
        to, `committed_hours`, `logged_hours`, `effective_weekly_cap_hours`,
        `daily_capacity_hours`, `approved_waiver_hours`, `remaining_week_hours`,
        `workload_status`, `burnout_risk_score_actual`,
        `burnout_risk_score_committed` and `turnover_risk_band`."

        Design: Difficulty/combinatorial_formula/effective_weekly_cap_combines_prior_week_tier_waiver_allowance_and_ceiling
        """

        senior, _partner, _waiver = self._part_time_senior_with_relief(api)

        workload = read_workload(api, senior["id"], week_start_date="2026-08-03")
        assert_hours(workload["daily_capacity_hours"], 5.60)
        assert_hours(workload["committed_hours"], 0.00)
        assert_hours(workload["remaining_week_hours"], 28.00)
        assert workload["workload_status"] == "GREEN"

        staff_after = read_staff(api, senior["id"])
        assert_hours(staff_after["effective_weekly_cap_hours"], 28.00)
        assert_hours(staff_after["daily_capacity_hours"], 5.60)
