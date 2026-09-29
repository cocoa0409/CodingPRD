"""Blockout assignments: manual creation, the capacity-lock cascade and lifting."""

from test_helpers import (
    BRONZE,
    GOLD,
    UNKNOWN_UUID,
    ApiErrorId,
    BlockoutSource,
    BlockoutStatus,
    DayClass,
    ProgramStatus,
    ReservationStatus,
    assert_day_counters,
    assert_day_posture,
    assert_grant_count_conserved,
    blockout_payload,
    book_reservation,
    build_active_pass,
    build_program,
    clerk_headers,
    create_blockout,
    create_park_day,
    forecast_park_day,
    get_park_day,
    lift_blockout,
    lift_payload,
    program_admin_headers,
    reservation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _assignments(api, **params):
    response = api.list_blockout_assignments(headers=program_admin_headers(), params=params)
    return validate_paginated(response)


def _reservation(api, reservation_id):
    return validate_success(api.get_reservation(reservation_id, headers=clerk_headers()))


class TestAssignmentIsATierByDayPair:
    """An assignment names one tier and one day and is filterable on both."""

    def test_the_collection_filters_independently_on_tier_and_on_day(self, api, default_clock):
        """Each row is a (tier, day) pair, so the two filters intersect.

        PRD: "**Blockout assignments** are the (tier, day) pairs on which a tier has no
        access."

        Design: Corner/entities/blockout_assignment_is_a_tier_by_park_day_junction_row
        """
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        first_day = create_park_day(api, program.id, "2026-08-20")
        second_day = create_park_day(api, program.id, "2026-08-21")
        bronze_on_first = create_blockout(api, program.tier_id("BRONZE"), first_day["id"])
        create_blockout(api, program.tier_id("GOLD"), first_day["id"])
        create_blockout(api, program.tier_id("BRONZE"), second_day["id"])

        assert bronze_on_first["tier_id"] == program.tier_id("BRONZE"), (
            f"the assignment should name the tier, got {bronze_on_first['tier_id']!r}"
        )
        assert bronze_on_first["park_day_id"] == first_day["id"], (
            f"the assignment should name the day, got {bronze_on_first['park_day_id']!r}"
        )
        assert bronze_on_first["source"] == BlockoutSource.MANUAL.value, (
            f"a hand-created assignment records MANUAL, got {bronze_on_first['source']!r}"
        )
        assert bronze_on_first["status"] == BlockoutStatus.ACTIVE.value, (
            f"a new assignment is ACTIVE, got {bronze_on_first['status']!r}"
        )
        assert bronze_on_first["lift_reason"] is None, (
            f"an active assignment leaves lift_reason null, got {bronze_on_first['lift_reason']!r}"
        )

        _, by_tier = _assignments(api, tier_id=program.tier_id("BRONZE"))
        assert by_tier["total_count"] == 2, (
            f"BRONZE is blocked on two days, got {by_tier['total_count']!r}"
        )
        _, by_day = _assignments(api, park_day_id=first_day["id"])
        assert by_day["total_count"] == 2, (
            f"the first day blocks two tiers, got {by_day['total_count']!r}"
        )
        _, by_pair = _assignments(
            api, tier_id=program.tier_id("BRONZE"), park_day_id=first_day["id"]
        )
        assert by_pair["total_count"] == 1, (
            f"the two filters should intersect on one pair, got {by_pair['total_count']!r}"
        )


class TestCapacityLockCascade:
    """Locking a day blocks the low ranks and releases only their reservations."""

    def test_the_lock_blocks_ranks_at_or_below_the_limit_and_cancels_their_bookings(
        self, api, default_clock
    ):
        """Rank 1 is blocked and loses its booking; rank 3 is untouched.

        PRD: "At the first level, for every pass tier of the programme whose `status` is
        `PUBLISHED` and whose `tier_rank` is less than or equal to the programme's
        `capacity_lock_blockout_max_rank` and which does not already have an active
        blockout on this day, the system creates a blockout assignment with `source` set to
        `CAPACITY_ADJUSTED` and `status` set to `ACTIVE`; candidate tiers are processed in
        ascending `tier_rank`, and among tiers of equal rank in ascending `created_at`."

        Design: Corner/state_machines/capacity_lock_blocks_low_ranks_and_cancels_their_reservations
        """
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-09-28")
        bronze_pass = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "lock-bronze@example.com"}
        )
        gold_pass = build_active_pass(
            api, program, tier_name="GOLD", holder_overrides={"email": "lock-gold@example.com"}
        )
        bronze_booking = book_reservation(api, bronze_pass.id, day["id"], "10:00", "13:00")
        gold_booking = book_reservation(api, gold_pass.id, day["id"], "10:00", "13:00")

        locked = forecast_park_day(api, day["id"], 975)

        assert_day_posture(
            locked,
            utilization=0.9750,
            day_class=DayClass.CAPACITY_LOCKED.value,
            slot_capacity=25,
            window_capacity=12,
        )
        rows, meta = _assignments(api, park_day_id=day["id"])
        assert meta["total_count"] == 1, (
            "only the tier at or below the lock rank should be blocked, got "
            f"{meta['total_count']!r} assignments"
        )
        assert rows[0]["tier_id"] == program.tier_id("BRONZE"), (
            "the blocked tier should be the rank-1 tier, got a different tier"
        )
        assert rows[0]["source"] == BlockoutSource.CAPACITY_ADJUSTED.value, (
            f"a cascade-created assignment records CAPACITY_ADJUSTED, got {rows[0]['source']!r}"
        )
        assert rows[0]["status"] == BlockoutStatus.ACTIVE.value, (
            f"the cascade assignment should be ACTIVE, got {rows[0]['status']!r}"
        )
        assert (
            _reservation(api, bronze_booking["id"])["status"]
            == ReservationStatus.CANCELLED_BY_BLOCKOUT.value
        ), "the blocked tier's booking should be cancelled by the blockout"
        assert (
            _reservation(api, gold_booking["id"])["status"] == ReservationStatus.CONFIRMED.value
        ), "the unblocked tier's booking should survive the lock"
        day_row = get_park_day(api, day["id"])
        assert_day_counters(day_row, reserved=1, released=1, remaining=24, grant=2)
        assert_grant_count_conserved(day_row)

    def test_a_locked_day_accepts_no_further_reservations(self, api, default_clock):
        """The lock is the last line of capacity defence.

        PRD: "From this point new reservations on the day are refused with
        `ERR_PARK_DAY_CAPACITY_LOCKED` (HTTP 409)."

        Design: Corner/state_machines/capacity_lock_blocks_low_ranks_and_cancels_their_reservations
        """
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-09-28")
        gold_pass = build_active_pass(
            api, program, tier_name="GOLD", holder_overrides={"email": "lock-gold@example.com"}
        )
        forecast_park_day(api, day["id"], 975)

        response = api.create_reservation(
            reservation_payload(gold_pass.id, day["id"], "10:00", "13:00"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_PARK_DAY_CAPACITY_LOCKED.value, 409)
        assert_day_counters(get_park_day(api, day["id"]), reserved=0, grant=0)


class TestLiftBlockedByCapacityLock:
    """A locked day may not release its blockouts, not even a manual one."""

    def _locked_day_with_a_manual_gold_blockout(self, api):
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-25")
        manual = create_blockout(api, program.tier_id("GOLD"), day["id"])
        locked = forecast_park_day(api, day["id"], 975)
        return program, day, manual, locked

    def test_the_lift_is_refused_while_the_day_class_is_capacity_locked(self, api, default_clock):
        """The cross-entity guard runs after the state guard and refuses the lift.

        PRD: "an assignment that is not in `ACTIVE` is rejected first with
        `ERR_ASSIGNMENT_ALREADY_LIFTED` (HTTP 409); only then is the cross-entity guard
        applied, refusing the lift with `ERR_PARK_DAY_CAPACITY_LOCKED` (HTTP 409) while
        the park day's `day_class` is `CAPACITY_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/blockout_lift_blocked_when_park_day_capacity_locked
        """
        _, day, manual, locked = self._locked_day_with_a_manual_gold_blockout(api)
        assert_day_posture(locked, utilization=0.9750, day_class=DayClass.CAPACITY_LOCKED.value)

        response = api.lift_blockout_assignment(
            manual["id"],
            lift_payload("Marketing wants gold holders back on this date"),
            headers=program_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PARK_DAY_CAPACITY_LOCKED.value, 409)
        still = validate_paginated(
            api.list_blockout_assignments(
                headers=program_admin_headers(), params={"park_day_id": day["id"]}
            )
        )
        rows, meta = still
        assert meta["total_count"] == 2, (
            "the lock cascade should have installed one further blockout, giving two on the day, "
            f"got {meta['total_count']!r}"
        )
        manual_row = next(row for row in rows if row["id"] == manual["id"])
        assert manual_row["status"] == BlockoutStatus.ACTIVE.value, (
            f"the refused lift must leave the assignment ACTIVE, got {manual_row['status']!r}"
        )
        assert manual_row["lift_reason"] is None, (
            f"the refused lift must not record a reason, got {manual_row['lift_reason']!r}"
        )
        _, adjusted_meta = _assignments(
            api, park_day_id=day["id"], source=BlockoutSource.CAPACITY_ADJUSTED.value
        )
        assert adjusted_meta["total_count"] == 1, (
            "only the tier at or below the lock rank should have been blocked, got "
            f"{adjusted_meta['total_count']!r} capacity-driven rows"
        )

    def test_leaving_the_lock_auto_lifts_the_capacity_row_and_frees_the_manual_lift(
        self, api, default_clock
    ):
        """The release touches only the capacity-driven rows; the manual row survives.

        PRD: "every blockout assignment on this day whose `source` is
        `CAPACITY_ADJUSTED` and whose `status` is `ACTIVE` becomes `LIFTED` with its
        `lift_reason` set to the literal string `CAPACITY_RELEASED`, and each such
        assignment's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/blockout_lift_blocked_when_park_day_capacity_locked
        """
        _, day, manual, _ = self._locked_day_with_a_manual_gold_blockout(api)

        released_day = forecast_park_day(api, day["id"], 800)

        assert_day_posture(released_day, day_class=DayClass.STANDARD.value)
        rows, _ = _assignments(api, park_day_id=day["id"])
        auto_row = next(
            row for row in rows if row["source"] == BlockoutSource.CAPACITY_ADJUSTED.value
        )
        assert auto_row["status"] == BlockoutStatus.LIFTED.value, (
            f"the capacity-driven blockout should be LIFTED, got {auto_row['status']!r}"
        )
        assert auto_row["lift_reason"] == "CAPACITY_RELEASED", (
            f"the auto-lift records the literal reason CAPACITY_RELEASED, got {auto_row['lift_reason']!r}"
        )
        manual_row = next(row for row in rows if row["id"] == manual["id"])
        assert manual_row["status"] == BlockoutStatus.ACTIVE.value, (
            f"a manual blockout survives the release, got {manual_row['status']!r}"
        )

        lifted = lift_blockout(
            api, manual["id"], reason="Marketing wants gold holders back on this date"
        )
        assert lifted["status"] == BlockoutStatus.LIFTED.value, (
            f"the manual lift should now succeed, got {lifted['status']!r}"
        )
        assert lifted["lift_reason"] == "Marketing wants gold holders back on this date", (
            f"the lift should record the operator's reason, got {lifted['lift_reason']!r}"
        )


class TestLiftActionRecordsTheReason:
    """The lift endpoint is the only door out of ACTIVE, and it keeps the row."""

    def _blocked_day(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.DESIGN.value)
        day = create_park_day(
            api, program.id, "2026-09-01", capacity_total=1000, forecast_attendance=100
        )
        assignment = create_blockout(api, program.tier_id("BRONZE"), day["id"])
        return program, day, assignment

    def test_the_lift_stores_the_supplied_reason_and_bumps_the_version(self, api, default_clock):
        """The reason travels from the request body into `lift_reason`.

        PRD: "Lifting a blockout moves it `ACTIVE → LIFTED`, records the supplied `reason`
        into `lift_reason`, returns the tier's access to the day for future reservations and
        gate entries, and increments the assignment's `version` by 1."

        Design: Corner/endpoints/blockout_lift_action_endpoint_records_the_reason
        """
        _, _, assignment = self._blocked_day(api)

        lifted = lift_blockout(api, assignment["id"], reason="Capacity released for the promo weekend")

        assert lifted["status"] == BlockoutStatus.LIFTED.value, (
            f"the lift should move the row to LIFTED, got {lifted['status']!r}"
        )
        assert lifted["lift_reason"] == "Capacity released for the promo weekend", (
            f"the operator's reason should be stored verbatim, got {lifted['lift_reason']!r}"
        )
        assert lifted["version"] == assignment["version"] + 1, (
            f"the lift should bump the version once, got {lifted['version']!r}"
        )

    def test_the_lifted_row_leaves_the_active_listing_but_is_not_deleted(self, api, default_clock):
        """A lift is a status move, so the history stays visible unfiltered.

        PRD: "Reviewers can inspect the calendar by filtering the assignment collection on
        `tier_id`, `park_day_id`, `status` or `source`, and the day collection on
        `program_id` or `day_class`."

        Design: Corner/endpoints/blockout_lift_action_endpoint_records_the_reason
        """
        _, day, assignment = self._blocked_day(api)

        lift_blockout(api, assignment["id"], reason="Capacity released for the promo weekend")

        _, active_meta = _assignments(
            api, park_day_id=day["id"], status=BlockoutStatus.ACTIVE.value
        )
        assert active_meta["total_count"] == 0, (
            f"no assignment should remain ACTIVE on the day, got {active_meta['total_count']!r}"
        )
        rows, all_meta = _assignments(api, park_day_id=day["id"])
        assert all_meta["total_count"] == 1, (
            f"the lifted row should still be listed, got {all_meta['total_count']!r}"
        )
        assert rows[0]["source"] == BlockoutSource.MANUAL.value, (
            f"a hand-made blockout keeps source MANUAL after the lift, got {rows[0]['source']!r}"
        )


class TestBothSidesOfTheJunctionMustResolve:
    """The assignment write resolves the tier and the day before storing anything."""

    def _program_with_one_day(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.DESIGN.value)
        day = create_park_day(
            api, program.id, "2026-09-01", capacity_total=1000, forecast_attendance=100
        )
        return program, day

    def test_an_unknown_park_day_or_tier_is_answered_in_the_existence_order(
        self, api, default_clock
    ):
        """The tier resolves before the park day, and each absence has its own code.

        PRD: "Within the existence band, identifiers resolve in this order: pass programme
        (`ERR_PROGRAM_NOT_FOUND`), pass tier (`ERR_TIER_NOT_FOUND`), park day
        (`ERR_PARK_DAY_NOT_FOUND`), passholder (`ERR_PASSHOLDER_NOT_FOUND`), season pass
        (`ERR_PASS_NOT_FOUND`), payment plan (`ERR_PLAN_NOT_FOUND`), installment
        (`ERR_INSTALLMENT_NOT_FOUND`), reservation (`ERR_RESERVATION_NOT_FOUND`), visit
        (`ERR_VISIT_NOT_FOUND`), sharing case (`ERR_CASE_NOT_FOUND`), upgrade order
        (`ERR_UPGRADE_ORDER_NOT_FOUND`), blockout assignment
        (`ERR_ASSIGNMENT_NOT_FOUND`)."

        Design: Corner/endpoints/blockout_assignment_requires_both_referenced_rows_to_exist
        """
        program, day = self._program_with_one_day(api)

        missing_day = api.create_blockout_assignment(
            blockout_payload(program.tier_id("BRONZE"), UNKNOWN_UUID, day["version"]),
            headers=program_admin_headers(),
        )
        validate_error(missing_day, ApiErrorId.ERR_PARK_DAY_NOT_FOUND.value, 404)

        missing_tier = api.create_blockout_assignment(
            blockout_payload(UNKNOWN_UUID, day["id"], day["version"]),
            headers=program_admin_headers(),
        )
        validate_error(missing_tier, ApiErrorId.ERR_TIER_NOT_FOUND.value, 404)

        _, meta = _assignments(api, park_day_id=day["id"])
        assert meta["total_count"] == 0, (
            f"neither refused write should have stored a row, got {meta['total_count']!r}"
        )
        assert get_park_day(api, day["id"])["version"] == day["version"], (
            "a refused assignment must not bump the park day's version"
        )

    def test_when_both_sides_resolve_the_link_is_reachable_from_either_side(
        self, api, default_clock
    ):
        """The accepted write is the only one that touches the day.

        PRD: "A manual creation records `source` as `MANUAL` and `status` as `ACTIVE`,
        leaving `lift_reason` null while the assignment remains active."

        Design: Corner/endpoints/blockout_assignment_requires_both_referenced_rows_to_exist
        """
        program, day = self._program_with_one_day(api)

        assignment = create_blockout(api, program.tier_id("BRONZE"), day["id"])

        assert assignment["tier_id"] == program.tier_id("BRONZE"), (
            f"the row should name the requested tier, got {assignment['tier_id']!r}"
        )
        assert assignment["park_day_id"] == day["id"], (
            f"the row should name the requested day, got {assignment['park_day_id']!r}"
        )
        assert assignment["status"] == BlockoutStatus.ACTIVE.value, (
            f"a fresh assignment is ACTIVE, got {assignment['status']!r}"
        )
        _, by_tier = _assignments(api, tier_id=program.tier_id("BRONZE"))
        assert by_tier["total_count"] == 1, (
            f"the link should be reachable from the tier side, got {by_tier['total_count']!r}"
        )
        _, by_day = _assignments(api, park_day_id=day["id"])
        assert by_day["total_count"] == 1, (
            f"the link should be reachable from the day side, got {by_day['total_count']!r}"
        )
        assert get_park_day(api, day["id"])["version"] == day["version"] + 1, (
            "the accepted assignment should bump the park day's version exactly once"
        )
