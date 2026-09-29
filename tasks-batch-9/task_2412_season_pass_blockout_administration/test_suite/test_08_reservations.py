"""Reserving a crowded day: the guard ladder, the two slot budgets and cancellation."""

from test_helpers import (
    BRONZE,
    ApiErrorId,
    BillingStatus,
    DayClass,
    PassStatus,
    PaymentMode,
    ProgramStatus,
    ReservationStatus,
    assert_day_counters,
    assert_day_posture,
    assert_grant_count_conserved,
    assert_hhmm_equals,
    book_reservation,
    build_active_pass,
    build_pending_pass,
    build_peak_day,
    build_plan,
    build_program,
    cancel_reservation,
    clerk_headers,
    create_park_day,
    get_park_day,
    get_pass,
    plan_installments,
    process_pass,
    reservation_payload,
    run_billing,
    set_clock,
    settle_installment,
    validate_error,
    validate_paginated,
    validate_success,
)


def _holder_pass(api, program, email, *, processed=True):
    overrides = {"full_name": f"Holder {email}", "email": email}
    builder = build_active_pass if processed else build_pending_pass
    return builder(api, program, tier_name="BRONZE", holder_overrides=overrides)


def _confirmed_on_day(api, park_day_id):
    response = api.list_reservations(
        headers=clerk_headers(),
        params={"park_day_id": park_day_id, "status": ReservationStatus.CONFIRMED.value},
    )
    return validate_paginated(response)


class TestReservationStateCheckPrecedesSlotBudget:
    """A pass that is not active is refused before the window budget is consulted."""

    def _crowded_day(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-10")
        first = _holder_pass(api, program, "slot-a@example.com")
        second = _holder_pass(api, program, "slot-b@example.com")
        book_reservation(api, first.id, day["id"], "09:00", "12:00")
        book_reservation(api, second.id, day["id"], "09:00", "12:00")
        third = _holder_pass(api, program, "slot-c@example.com", processed=False)
        return program, day, third

    def test_an_unprocessed_pass_meets_the_state_error_not_the_slot_error(self, api, default_clock):
        """Rung three of the ladder fires before rung thirteen is evaluated.

        PRD: "3. A pass whose `pass_status` is not `ACTIVE` is refused with
        `ERR_PASS_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/reservation_state_error_precedes_slot_capacity_error
        """
        _, day, third = self._crowded_day(api)

        response = api.create_reservation(
            reservation_payload(third.id, day["id"], "10:00", "13:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_PASS_NOT_ACTIVE.value, 409)
        day_row = get_park_day(api, day["id"])
        assert_day_posture(
            day_row, day_class=DayClass.PEAK.value, slot_capacity=4, window_capacity=2
        )
        assert_day_counters(day_row, reserved=2, released=0, grant=2)

    def test_the_same_request_meets_the_slot_error_once_the_pass_is_active(self, api, default_clock):
        """With the state rung cleared, the overlapping-window budget answers.

        PRD: "Finally, the window check: the number of `CONFIRMED` reservations on that
        day whose own half-open interval from `arrival_window_start` up to but not
        including `arrival_window_end` overlaps the requested interval, if it has already
        reached the day's `window_slot_capacity`, is refused with
        `ERR_RESERVATION_SLOT_FULL` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/reservation_state_error_precedes_slot_capacity_error
        """
        _, day, third = self._crowded_day(api)
        process_pass(api, third.id)

        response = api.create_reservation(
            reservation_payload(third.id, day["id"], "10:00", "13:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_RESERVATION_SLOT_FULL.value, 422)


class TestOverlappingHalfOpenWindows:
    """Only mutually overlapping windows compete for the window budget."""

    def _day_with_two_bookings(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-10")
        first = _holder_pass(api, program, "win-a@example.com")
        second = _holder_pass(api, program, "win-b@example.com")
        book_reservation(api, first.id, day["id"], "09:00", "12:00")
        book_reservation(api, second.id, day["id"], "10:00", "13:00")
        return program, day

    def test_a_third_overlapping_window_is_refused_while_the_day_still_has_slots(
        self, api, default_clock
    ):
        """The band is full at two even though the day as a whole offers four slots.

        PRD: "This is a distinct budget from the day-level one: a day can have slots
        left overall while the mid-morning band is already full."

        Design: Difficulty/resource_temporal_overlap/park_day_slot_capacity_counts_only_overlapping_half_open_windows
        """
        program, day = self._day_with_two_bookings(api)
        third = _holder_pass(api, program, "win-c@example.com")

        response = api.create_reservation(
            reservation_payload(third.id, day["id"], "11:00", "14:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_RESERVATION_SLOT_FULL.value, 422)
        assert_day_counters(get_park_day(api, day["id"]), reserved=2, grant=2)

    def test_an_abutting_window_does_not_overlap_and_is_confirmed(self, api, default_clock):
        """A window starting exactly when another ends is outside it.

        PRD: "Two windows overlap when each begins strictly before the other ends."

        Design: Difficulty/resource_temporal_overlap/park_day_slot_capacity_counts_only_overlapping_half_open_windows
        """
        program, day = self._day_with_two_bookings(api)
        third = _holder_pass(api, program, "win-c@example.com")
        api.create_reservation(
            reservation_payload(third.id, day["id"], "11:00", "14:00"), headers=clerk_headers()
        )
        fourth = _holder_pass(api, program, "win-d@example.com")

        created = validate_success(
            api.create_reservation(
                reservation_payload(fourth.id, day["id"], "13:00", "16:00"), headers=clerk_headers()
            ),
            201,
        )

        assert created["status"] == ReservationStatus.CONFIRMED.value, (
            f"the abutting window should be confirmed, got {created['status']!r}"
        )
        assert_hhmm_equals(created["arrival_window_start"], "13:00")
        day_row = get_park_day(api, day["id"])
        assert_day_counters(day_row, reserved=3, remaining=1, released=0, grant=3)
        assert_grant_count_conserved(day_row)
        _, meta = _confirmed_on_day(api, day["id"])
        assert meta["total_count"] == 3, (
            f"three bookings should stand on the day, got {meta['total_count']!r}"
        )


class TestDelinquentBillingBlocksReservation:
    """The billing dimension gates scarce capacity even while access is fine."""

    def _delinquent_world(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-09-20")
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        run_billing(api, program.id, "2026-09-15")
        return program, day, pass_ctx, plan_ctx

    def test_a_delinquent_pass_cannot_book_although_its_access_state_is_active(
        self, api, default_clock
    ):
        """Rung four of the ladder answers, not the access-state rung above it.

        PRD: "4. A pass whose `billing_status` is `DELINQUENT` or `DEFAULTED` is refused
        with `ERR_PASS_BILLING_NOT_CURRENT` (HTTP 409) — the park does not hand out
        scarce capacity to a guest who is behind on payments."

        Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_pass_billing_delinquent
        """
        _, day, pass_ctx, _ = self._delinquent_world(api)
        pass_row = get_pass(api, pass_ctx.id)
        assert pass_row["pass_status"] == PassStatus.ACTIVE.value, (
            "the access dimension should still be ACTIVE for this scenario to be meaningful"
        )

        response = api.create_reservation(
            reservation_payload(pass_ctx.id, day["id"], "10:00", "13:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_PASS_BILLING_NOT_CURRENT.value, 409)
        assert_day_counters(get_park_day(api, day["id"]), reserved=0, grant=0)

    def test_settling_the_missed_installment_restores_the_right_to_book(self, api, default_clock):
        """Curing the arrears returns the billing dimension to PLAN_CURRENT.

        PRD: "If the settlement was of the last remaining `MISSED` installment, so that
        the active plan's `missed_count` has returned to 0, the pass's `billing_status`
        moves `DELINQUENT → PLAN_CURRENT` and its `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_pass_billing_delinquent
        """
        _, day, pass_ctx, plan_ctx = self._delinquent_world(api)
        missed = [
            row for row in plan_installments(api, plan_ctx.id) if row["status"] == "MISSED"
        ]
        settle_installment(api, missed[0]["id"], 2625)

        assert get_pass(api, pass_ctx.id)["billing_status"] == BillingStatus.PLAN_CURRENT.value, (
            "settling the only missed installment should return the pass to PLAN_CURRENT"
        )
        created = validate_success(
            api.create_reservation(
                reservation_payload(pass_ctx.id, day["id"], "10:00", "13:00"), headers=clerk_headers()
            ),
            201,
        )
        assert created["status"] == ReservationStatus.CONFIRMED.value, (
            f"the booking should now be confirmed, got {created['status']!r}"
        )
        assert_day_counters(get_park_day(api, day["id"]), reserved=1, grant=1)


class TestCancellationConservesSlotUnits:
    """A voluntary cancellation returns the slot but never the audit counter."""

    def test_cancelling_returns_the_slot_and_leaves_grant_count_alone(self, api, default_clock):
        """The released unit moves counters without touching the monotonic total.

        PRD: "It drives `CONFIRMED → CANCELLED_BY_HOLDER`, drops the day's
        `reserved_count` by one, raises its `released_count` by one, recomputes
        `remaining_slot_count`, leaves `grant_count` untouched, and increments the
        reservation's `version` by 1."

        Design: Difficulty/compensating_invariant/reservation_cancel_conserves_park_day_slot_units
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-10")
        pass_ctx = _holder_pass(api, program, "cancel-a@example.com")
        reservation = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        before = get_park_day(api, day["id"])
        assert_day_posture(before, slot_capacity=4)
        assert_day_counters(before, reserved=1, released=0, remaining=3, grant=1)

        cancelled = cancel_reservation(api, reservation["id"])

        assert cancelled["status"] == ReservationStatus.CANCELLED_BY_HOLDER.value, (
            f"a voluntary cancellation should record CANCELLED_BY_HOLDER, got {cancelled['status']!r}"
        )
        after = get_park_day(api, day["id"])
        assert_day_counters(
            after, reserved=0, released=1, redeemed=0, no_show=0, remaining=4, grant=1
        )
        assert_grant_count_conserved(after)

    def test_a_slot_cannot_be_returned_twice(self, api, default_clock):
        """Only a confirmed reservation is cancellable.

        PRD: "A reservation whose `status` is anything other than `CONFIRMED` is refused
        with `ERR_RESERVATION_NOT_CANCELLABLE` (HTTP 409)."

        Design: Difficulty/compensating_invariant/reservation_cancel_conserves_park_day_slot_units
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-10")
        pass_ctx = _holder_pass(api, program, "cancel-a@example.com")
        reservation = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        cancel_reservation(api, reservation["id"])

        response = api.cancel_reservation(reservation["id"], headers=clerk_headers())

        validate_error(response, ApiErrorId.ERR_RESERVATION_NOT_CANCELLABLE.value, 409)
        assert_day_counters(get_park_day(api, day["id"]), reserved=0, released=1, grant=1)


class TestPastDatedDaysCannotBeReserved:
    """The past-date guard is measured against the logical clock, not the wall."""

    def _two_days_and_a_pass(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        early = create_park_day(api, program.id, "2026-09-10")
        today = create_park_day(api, program.id, "2026-09-20")
        pass_ctx = _holder_pass(api, program, "past-a@example.com")
        set_clock(api, "2026-09-20T08:00:00Z")
        return program, early, today, pass_ctx

    def test_a_day_before_the_clock_is_refused(self, api, default_clock):
        """Once the clock has passed the day, the day is no longer bookable.

        PRD: "7. A park day whose `calendar_date` falls strictly before the logical clock's
        current date is refused with `ERR_PARK_DAY_IN_PAST` (HTTP 422)."

        Design: Corner/validations/reservation_for_a_past_park_day_is_rejected
        """
        _, early, _, pass_ctx = self._two_days_and_a_pass(api)

        response = api.create_reservation(
            reservation_payload(pass_ctx.id, early["id"], "09:00", "12:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_PARK_DAY_IN_PAST.value, 422)
        assert_day_counters(get_park_day(api, early["id"]), reserved=0, grant=0)

    def test_the_clock_s_own_day_is_still_bookable(self, api, default_clock):
        """The comparison is strict, so today is not yet in the past.

        PRD: "A new reservation opens in `status` `CONFIRMED`, leaves `redeemed_visit_id`
        null, raises the day's `reserved_count` by one, raises the day's monotonic
        `grant_count` by one, and recomputes `remaining_slot_count`."

        Design: Corner/validations/reservation_for_a_past_park_day_is_rejected
        """
        _, _, today, pass_ctx = self._two_days_and_a_pass(api)

        created = validate_success(
            api.create_reservation(
                reservation_payload(pass_ctx.id, today["id"], "09:00", "12:00"),
                headers=clerk_headers(),
            ),
            201,
        )

        assert created["status"] == ReservationStatus.CONFIRMED.value, (
            f"the clock's own day should still be reservable, got {created['status']!r}"
        )
        assert created["redeemed_visit_id"] is None, (
            f"a fresh booking has redeemed nothing, got {created['redeemed_visit_id']!r}"
        )
        assert_day_counters(get_park_day(api, today["id"]), reserved=1, grant=1)


class TestArrivalWindowMustBeNonEmpty:
    """A half-open window with no width describes no arrival at all."""

    def _day_and_pass(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-09-15")
        pass_ctx = _holder_pass(api, program, "window-a@example.com")
        return program, day, pass_ctx

    def test_an_end_equal_to_or_before_the_start_is_refused(self, api, default_clock):
        """Both the zero-width window and the inverted one are refused.

        PRD: "An `arrival_window_end` at or before `arrival_window_start`, which would
        describe an empty window, is refused with `ERR_ARRIVAL_WINDOW_INVALID` (HTTP 422)."

        Design: Corner/validations/reservation_with_empty_arrival_window_is_rejected
        """
        _, day, pass_ctx = self._day_and_pass(api)

        empty = api.create_reservation(
            reservation_payload(pass_ctx.id, day["id"], "11:00", "11:00"), headers=clerk_headers()
        )
        inverted = api.create_reservation(
            reservation_payload(pass_ctx.id, day["id"], "11:00", "10:00"), headers=clerk_headers()
        )

        validate_error(empty, ApiErrorId.ERR_ARRIVAL_WINDOW_INVALID.value, 422)
        validate_error(inverted, ApiErrorId.ERR_ARRIVAL_WINDOW_INVALID.value, 422)
        assert_day_counters(get_park_day(api, day["id"]), reserved=0, grant=0)

    def test_a_one_minute_window_is_wide_enough(self, api, default_clock):
        """Any positive width satisfies the half-open definition.

        PRD: "The window is half-open: the start instant is inside it and the end instant
        is outside it."

        Design: Corner/validations/reservation_with_empty_arrival_window_is_rejected
        """
        _, day, pass_ctx = self._day_and_pass(api)
        api.create_reservation(
            reservation_payload(pass_ctx.id, day["id"], "11:00", "11:00"), headers=clerk_headers()
        )

        created = validate_success(
            api.create_reservation(
                reservation_payload(pass_ctx.id, day["id"], "10:00", "10:01"),
                headers=clerk_headers(),
            ),
            201,
        )

        assert created["status"] == ReservationStatus.CONFIRMED.value, (
            f"a one-minute window should be accepted, got {created['status']!r}"
        )
        assert_hhmm_equals(created["arrival_window_start"], "10:00")
        assert_hhmm_equals(created["arrival_window_end"], "10:01")
        day_row = get_park_day(api, day["id"])
        assert_day_counters(day_row, reserved=1, grant=1)
        assert_grant_count_conserved(day_row)


class TestPeakQuotaIsCountedAcrossTheCalendar:
    """The tier quota is a season-wide budget, not a per-day one."""

    def _three_peak_days(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        days = [
            build_peak_day(api, program.id, calendar_date)
            for calendar_date in ("2026-09-10", "2026-09-11", "2026-09-12")
        ]
        pass_ctx = _holder_pass(api, program, "quota-a@example.com")
        first = book_reservation(api, pass_ctx.id, days[0]["id"], "09:00", "12:00")
        book_reservation(api, pass_ctx.id, days[1]["id"], "09:00", "12:00")
        return program, days, pass_ctx, first

    def test_the_third_peak_booking_exceeds_a_quota_of_two(self, api, default_clock):
        """Each booking is legal on its own day, yet the third breaks the budget.

        PRD: "11. A pass whose count of `CONFIRMED` reservations on park days classified
        `PEAK` or `CAPACITY_LOCKED`, taken over days whose `calendar_date` falls on or after
        the logical clock's current date, has already reached its tier's
        `peak_reservation_quota` is refused with `ERR_RESERVATION_QUOTA_EXCEEDED` (HTTP
        422)."

        Design: Corner/validations/peak_day_reservation_quota_is_an_aggregate_across_days
        """
        _, days, pass_ctx, _ = self._three_peak_days(api)

        response = api.create_reservation(
            reservation_payload(pass_ctx.id, days[2]["id"], "09:00", "12:00"),
            headers=clerk_headers(),
        )

        validate_error(response, ApiErrorId.ERR_RESERVATION_QUOTA_EXCEEDED.value, 422)
        third_row = get_park_day(api, days[2]["id"])
        assert_day_posture(third_row, day_class=DayClass.PEAK.value, slot_capacity=4)
        assert_day_counters(third_row, reserved=0, remaining=4, grant=0)

    def test_cancelling_one_booking_frees_the_quota_again(self, api, default_clock):
        """Only confirmed rows count, so a cancellation returns the budget.

        PRD: "`CANCELLED_BY_HOLDER` means the guest or the clerk gave the slot back
        voluntarily."

        Design: Corner/validations/peak_day_reservation_quota_is_an_aggregate_across_days
        """
        _, days, pass_ctx, first = self._three_peak_days(api)

        cancel_reservation(api, first["id"])

        created = validate_success(
            api.create_reservation(
                reservation_payload(pass_ctx.id, days[2]["id"], "09:00", "12:00"),
                headers=clerk_headers(),
            ),
            201,
        )
        assert created["status"] == ReservationStatus.CONFIRMED.value, (
            f"the freed quota should admit the third booking, got {created['status']!r}"
        )
        assert_day_counters(get_park_day(api, days[2]["id"]), reserved=1, grant=1)


class TestDayMustBelongToThePassProgramme:
    """A pass may only reserve days on its own programme's calendar."""

    def _two_programmes(self, api):
        first = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        first_day = create_park_day(api, first.id, "2026-09-15")
        pass_ctx = _holder_pass(api, first, "mismatch-a@example.com")
        second = build_program(
            api,
            tiers=(BRONZE,),
            status=ProgramStatus.SEASON_ACTIVE.value,
            season_year=2027,
            park_name="Harbor Bay",
        )
        second_day = create_park_day(api, second.id, "2026-09-15")
        return first_day, second_day, pass_ctx

    def test_a_day_from_another_programme_is_refused(self, api, default_clock):
        """Nothing but the referential mismatch can fail this call.

        PRD: "6. A park day whose `program_id` differs from the pass's `program_id` is
        refused with `ERR_PARK_DAY_PROGRAM_MISMATCH`."

        Design: Corner/validations/park_day_from_another_program_cannot_be_reserved
        """
        _, second_day, pass_ctx = self._two_programmes(api)

        response = api.create_reservation(
            reservation_payload(pass_ctx.id, second_day["id"], "09:00", "12:00"),
            headers=clerk_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PARK_DAY_PROGRAM_MISMATCH.value, 422)
        assert_day_counters(get_park_day(api, second_day["id"]), reserved=0, grant=0)

    def test_the_identical_call_against_its_own_calendar_succeeds(self, api, default_clock):
        """With the reference corrected the booking lands and moves the counters.

        PRD: "A new reservation opens in `status` `CONFIRMED`, leaves `redeemed_visit_id`
        null, raises the day's `reserved_count` by one, raises the day's monotonic
        `grant_count` by one, and recomputes `remaining_slot_count`."

        Design: Corner/validations/park_day_from_another_program_cannot_be_reserved
        """
        first_day, _, pass_ctx = self._two_programmes(api)

        created = validate_success(
            api.create_reservation(
                reservation_payload(pass_ctx.id, first_day["id"], "09:00", "12:00"),
                headers=clerk_headers(),
            ),
            201,
        )

        assert created["status"] == ReservationStatus.CONFIRMED.value, (
            f"the booking on its own programme's day should be confirmed, got {created['status']!r}"
        )
        day_row = get_park_day(api, first_day["id"])
        assert_day_counters(day_row, reserved=1, remaining=99, grant=1)
        assert_grant_count_conserved(day_row)


class TestReservationSucceedsWhenEveryRuleIsSatisfied:
    """The positive control for the whole ladder."""

    def test_a_clean_booking_returns_confirmed_and_moves_exactly_one_slot_unit(
        self, api, default_clock
    ):
        """An active, paid-up pass books its first window on an unblocked peak day.

        PRD: "A new reservation opens in `status` `CONFIRMED`, leaves `redeemed_visit_id`
        null, raises the day's `reserved_count` by one, raises the day's monotonic
        `grant_count` by one, and recomputes `remaining_slot_count`."

        Design: Corner/validations/reservation_succeeds_when_every_rule_is_satisfied
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-15")
        pass_ctx = _holder_pass(api, program, "clean-a@example.com")

        created = validate_success(
            api.create_reservation(
                reservation_payload(pass_ctx.id, day["id"], "10:00", "13:00"),
                headers=clerk_headers(),
            ),
            201,
        )

        assert created["status"] == ReservationStatus.CONFIRMED.value, (
            f"a clean booking should be CONFIRMED, got {created['status']!r}"
        )
        assert_hhmm_equals(created["arrival_window_start"], "10:00")
        assert_hhmm_equals(created["arrival_window_end"], "13:00")
        assert created["redeemed_visit_id"] is None, (
            f"nothing has been redeemed yet, got {created['redeemed_visit_id']!r}"
        )
        day_row = get_park_day(api, day["id"])
        assert_day_counters(day_row, reserved=1, released=0, remaining=3, grant=1)
        assert_grant_count_conserved(day_row)
        _, meta = _confirmed_on_day(api, day["id"])
        assert meta["total_count"] == 1, (
            f"exactly one confirmed booking should stand, got {meta['total_count']!r}"
        )

    def test_booking_leaves_both_pass_dimensions_untouched(self, api, default_clock):
        """A reservation is a calendar event, not a billing or access event.

        PRD: "The **billing dimension**, `billing_status`, takes the values `UNBILLED`,
        `PLAN_CURRENT`, `DELINQUENT`, `DEFAULTED` and `PAID_IN_FULL`, has no terminal state
        at all, and moves only on plan enrolment, installment settlement, billing runs and
        reinstatement — never on a gate or access event."

        Design: Corner/validations/reservation_succeeds_when_every_rule_is_satisfied
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-15")
        pass_ctx = _holder_pass(api, program, "clean-a@example.com")

        book_reservation(api, pass_ctx.id, day["id"], "10:00", "13:00")

        pass_row = get_pass(api, pass_ctx.id)
        assert pass_row["pass_status"] == PassStatus.ACTIVE.value, (
            f"booking must not move the access dimension, got {pass_row['pass_status']!r}"
        )
        assert pass_row["billing_status"] == BillingStatus.PAID_IN_FULL.value, (
            f"booking must not move the billing dimension, got {pass_row['billing_status']!r}"
        )
        assert pass_row["visit_count"] == 0, (
            f"a booking is not an entry, got visit_count {pass_row['visit_count']!r}"
        )


class TestCancelIsConditionalOnTheConfirmedStatus:
    """The guest's own cancel works once and only once."""

    def _standard_day_booking(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(
            api, program.id, "2026-09-01", capacity_total=1000, forecast_attendance=100
        )
        pass_ctx = _holder_pass(api, program, "own-cancel@example.com")
        reservation = book_reservation(
            api, pass_ctx.id, day["id"], "09:00", "12:00", headers=pass_ctx.headers
        )
        return day, pass_ctx, reservation

    def test_the_owning_guest_cancels_and_the_day_takes_the_slot_back(self, api, default_clock):
        """The first cancel is the guest's own write and it moves three counters.

        PRD: "Voluntary cancellation is available to a `PassOfficeClerk` or to the owning
        `Passholder` and takes no request body."

        Design: Corner/endpoints/reservation_cancel_is_allowed_only_while_confirmed
        """
        day, pass_ctx, reservation = self._standard_day_booking(api)
        assert_day_posture(get_park_day(api, day["id"]), slot_capacity=100)

        cancelled = cancel_reservation(api, reservation["id"], headers=pass_ctx.headers)

        assert cancelled["status"] == ReservationStatus.CANCELLED_BY_HOLDER.value, (
            f"the guest's cancel should record CANCELLED_BY_HOLDER, got {cancelled['status']!r}"
        )
        assert_day_counters(
            get_park_day(api, day["id"]), reserved=0, released=1, remaining=100, grant=1
        )

    def test_the_second_cancel_is_refused_and_moves_no_counter(self, api, default_clock):
        """A row already out of CONFIRMED cannot be cancelled again.

        PRD: "A reservation whose `status` is anything other than `CONFIRMED` is refused
        with `ERR_RESERVATION_NOT_CANCELLABLE` (HTTP 409)."

        Design: Corner/endpoints/reservation_cancel_is_allowed_only_while_confirmed
        """
        day, pass_ctx, reservation = self._standard_day_booking(api)
        cancel_reservation(api, reservation["id"], headers=pass_ctx.headers)

        response = api.cancel_reservation(reservation["id"], headers=pass_ctx.headers)

        validate_error(response, ApiErrorId.ERR_RESERVATION_NOT_CANCELLABLE.value, 409)
        assert_day_counters(
            get_park_day(api, day["id"]), reserved=0, released=1, remaining=100, grant=1
        )
