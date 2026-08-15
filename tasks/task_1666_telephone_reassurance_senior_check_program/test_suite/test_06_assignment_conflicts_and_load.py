"""Assignment conflict semantics, weekly load caps, concurrency caps, and
derived-field reconciliation on cancel/reschedule."""
from test_helpers import (
    ApiErrorId,
    add_call_schedule,
    create_assignment,
    create_availability_window_payload,
    create_certified_volunteer,
    create_program,
    create_volunteer,
    enroll_participant,
    get_assignment,
    log_call,
    make_volunteer_headers,
    set_clock,
    setup_calling_environment,
    setup_enrolled_participant,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAvailabilityOverlapSemantics:
    def test_availability_overlap_checks_effective_range_dimension(self, api, coordinator_headers):
        """PRD §3.5: "A new window that overlaps an existing window of the same volunteer on the same weekday — overlap judged under half-open semantics, and only when their effective ranges overlap as well — is rejected with `ERR_AVAILABILITY_OVERLAP`."

        Design: Corner/entities/availability_overlap_checks_effective_range_dimension
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol Av")
        w1 = validate_success(api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="08:00",
                                               window_end="10:00", effective_from="2026-08-01",
                                               effective_to="2026-08-31"),
            coordinator_headers,
        ), 201)
        # Same weekday and overlapping clock times, but disjoint effective
        # ranges (September onward vs August) never collide.
        w2 = validate_success(api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="09:00",
                                               window_end="11:00", effective_from="2026-09-01"),
            coordinator_headers,
        ), 201)
        assert w2["id"] != w1["id"]
        # Overlapping clock times AND overlapping effective ranges: rejected.
        resp = api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="09:00",
                                               window_end="11:00", effective_from="2026-08-15"),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AVAILABILITY_OVERLAP, 409)

    def test_availability_window_touching_endpoint_accepted(self, api, coordinator_headers):
        """PRD §3.5: "A new window that overlaps an existing window of the same volunteer on the same weekday — overlap judged under half-open semantics, and only when their effective ranges overlap as well — is rejected with `ERR_AVAILABILITY_OVERLAP`."
        PRD §3.5: "Availability windows, by contrast, remain half-open with no buffer."

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol A")
        validate_success(api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="08:00",
                                               window_end="10:00"),
            coordinator_headers,
        ), 201)
        # [10:00, 12:00) touches [08:00, 10:00) at the shared endpoint — under
        # half-open semantics that is NOT an overlap.
        w2 = validate_success(api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="10:00",
                                               window_end="12:00"),
            coordinator_headers,
        ), 201)
        assert w2["window_start"] == "10:00"

    def test_availability_window_interior_overlap_and_other_weekday(self, api, coordinator_headers):
        """PRD §3.5: "A new window that overlaps an existing window of the same volunteer on the same weekday — overlap judged under half-open semantics, and only when their effective ranges overlap as well — is rejected with `ERR_AVAILABILITY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
        """
        create_program()
        volunteer = create_volunteer(full_name="Vol A")
        validate_success(api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="08:00",
                                               window_end="10:00"),
            coordinator_headers,
        ), 201)
        validate_success(api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="10:00",
                                               window_end="12:00"),
            coordinator_headers,
        ), 201)
        # 09:59-11:00 intersects both [08:00,10:00) and [10:00,12:00).
        resp = api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="MON", window_start="09:59",
                                               window_end="11:00"),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AVAILABILITY_OVERLAP, 409)
        # The same clock times on a DIFFERENT weekday do not overlap.
        w4 = validate_success(api.create_availability_window(
            volunteer["id"],
            create_availability_window_payload(weekday="TUE", window_start="09:59",
                                               window_end="11:00"),
            coordinator_headers,
        ), 201)
        assert w4["weekday"] == "TUE"


class TestAssignmentBufferClosedInterval:
    def _setup_with_existing_0930(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment()
        existing = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                                     window_start="09:00", window_end="09:30")
        return program, participant, volunteer, existing

    def test_touching_buffered_endpoint_conflicts(self, api, coordinator_headers):
        """PRD §3.5: "Touching at the buffered endpoint is a conflict: with the default fifteen-minute buffer, an existing 09:00–09:30 assignment occupies through 09:45 inclusive, so a new assignment starting at 09:45 is rejected with `ERR_ASSIGNMENT_WINDOW_CONFLICT`, while one starting at 09:46 is not."

        Design: Difficulty/resource_temporal_overlap/assignment_buffer_closed_interval_conflict
        """
        _program, participant, volunteer, _existing = self._setup_with_existing_0930(
            api, coordinator_headers
        )
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "09:45", "window_end": "10:15"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW_CONFLICT, 409)

    def test_one_minute_past_buffered_endpoint_is_free(self, api, coordinator_headers):
        """PRD §3.5: "Touching at the buffered endpoint is a conflict: with the default fifteen-minute buffer, an existing 09:00–09:30 assignment occupies through 09:45 inclusive, so a new assignment starting at 09:45 is rejected with `ERR_ASSIGNMENT_WINDOW_CONFLICT`, while one starting at 09:46 is not."
        PRD §3.5: "An existing assignment occupies the span from its `window_start` through its `window_end` plus the program's `doc_buffer_minutes`, both bounds inclusive; a new assignment conflicts when its start falls at or before an existing assignment's buffered end while that existing assignment's start falls at or before the new assignment's buffered end — considering only the volunteer's `SCHEDULED` assignments on the same `scheduled_date`."

        Design: Difficulty/resource_temporal_overlap/assignment_buffer_closed_interval_conflict
        """
        _program, participant, volunteer, _existing = self._setup_with_existing_0930(
            api, coordinator_headers
        )
        created = validate_success(api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "09:46", "window_end": "10:16"},
            coordinator_headers,
        ), 201)
        assert created["status"] == "SCHEDULED"


class TestWeeklyLoadInclusiveCap:
    def _setup_load_180(self, api, coordinator_headers):
        """Volunteer capped at 225 weekly minutes with four accepted 30-minute
        slots (180 minutes with buffers) on 2026-08-03..2026-08-06."""
        weekdays = ("MON", "TUE", "WED", "THU", "FRI")
        program, participant = setup_enrolled_participant(
            schedules=tuple((wd, "09:00", "11:00") for wd in weekdays)
        )
        volunteer = create_certified_volunteer(
            weekdays=weekdays, volunteer_overrides={"max_weekly_minutes": 225},
        )
        dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"]
        for date in dates:
            create_assignment(participant["id"], volunteer["id"], date)
        return program, participant, volunteer

    def test_fifth_slot_landing_exactly_on_cap_accepted(self, api, coordinator_headers):
        """PRD §3.5: "Admitting a new or rescheduled assignment requires that `current_week_minutes` plus the new slot's minutes plus its buffer allowance not exceed the volunteer's `max_weekly_minutes` — the bound is inclusive, so landing exactly on the cap is allowed, while anything strictly above is rejected with `ERR_WEEKLY_LOAD_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/weekly_load_inclusive_cap_boundary
        """
        program, participant, volunteer = self._setup_load_180(api, coordinator_headers)
        fifth = validate_success(api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-07", "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        ), 201)
        assert fifth["status"] == "SCHEDULED", (
            "the 5th slot lands at exactly 225 minutes (5 x (30+15)) — the cap is inclusive"
        )
        # Read the derived field from inside the target ISO week.
        set_clock("2026-08-03T08:00:00Z")
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["current_week_minutes"] == 225

    def test_sixth_slot_strictly_above_cap_rejected(self, api, coordinator_headers):
        """PRD §3.5: "Admitting a new or rescheduled assignment requires that `current_week_minutes` plus the new slot's minutes plus its buffer allowance not exceed the volunteer's `max_weekly_minutes` — the bound is inclusive, so landing exactly on the cap is allowed, while anything strictly above is rejected with `ERR_WEEKLY_LOAD_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/weekly_load_inclusive_cap_boundary
        """
        program, participant, volunteer = self._setup_load_180(api, coordinator_headers)
        validate_success(api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-07", "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        ), 201)
        # A further 45 minutes would reach 270 — strictly above 225.
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-07", "window_start": "10:00", "window_end": "10:30"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WEEKLY_LOAD_EXCEEDED, 409)


class TestTemporalConflictBeatsCapacityConstraint:
    def _setup_conflict_and_overload(self, api, coordinator_headers):
        """Five accepted slots (load exactly 225 at the 225 cap); the 6th
        request both overlaps under buffer-inclusive semantics and would push
        the week to 270."""
        weekdays = ("MON", "TUE", "WED", "THU", "FRI")
        program, participant = setup_enrolled_participant(
            schedules=tuple((wd, "09:00", "11:00") for wd in weekdays)
        )
        volunteer = create_certified_volunteer(
            weekdays=weekdays, volunteer_overrides={"max_weekly_minutes": 225},
        )
        for date in ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]:
            create_assignment(participant["id"], volunteer["id"], date)
        return program, participant, volunteer

    def test_conflict_error_wins_over_load_error(self, api, coordinator_headers):
        """PRD §2.6: "Requests are validated against a fixed, thirteen-step order, and a failure at any step surfaces before later checks are evaluated."
        PRD §2.6: "9. Temporal rules: future-dated call logs (`ERR_FUTURE_DATED_CALL_LOG`), escalation step deadlines (`ERR_ESCALATION_STEP_NOT_DUE`), offer expiry (`ERR_OFFER_NOT_OPEN`), availability-window overlap (`ERR_AVAILABILITY_OVERLAP`), buffer-inclusive assignment conflicts (`ERR_ASSIGNMENT_WINDOW_CONFLICT`), and window containment (`ERR_WINDOW_OUTSIDE_SCHEDULE`, `ERR_WINDOW_OUTSIDE_AVAILABILITY`)."
        PRD §2.6: "11. Aggregate constraints: the capacity admission branch (`ERR_CAPACITY_REACHED`), volunteer weekly load (`ERR_WEEKLY_LOAD_EXCEEDED`), the concurrency cap (`ERR_MAX_ASSIGNMENTS_REACHED`), one active or paused schedule per participant per weekday (`ERR_DUPLICATE_SCHEDULE`), one survey per participant per period (`ERR_SURVEY_PERIOD_DUPLICATE`), and a non-empty eligible-volunteer pool (`ERR_NO_ELIGIBLE_VOLUNTEER`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_conflict_beats_capacity_constraint
        """
        program, participant, volunteer = self._setup_conflict_and_overload(api, coordinator_headers)
        # 09:15 start vs the existing 09:00-09:30 slot (buffered through 09:45)
        # is a step-9 conflict; the week reaching 270 is a step-11 breach.
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-07", "window_start": "09:15", "window_end": "09:45"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW_CONFLICT, 409)

    def test_conflicting_assignment_is_not_persisted(self, api, coordinator_headers):
        """PRD §2.6: "Requests are validated against a fixed, thirteen-step order, and a failure at any step surfaces before later checks are evaluated."
        PRD §3.5: "A created assignment lands in `SCHEDULED` with `version` 1, and the volunteer's `current_week_minutes` is recomputed."

        Design: Difficulty/priority_pair_validation_conflict/temporal_conflict_beats_capacity_constraint
        """
        program, participant, volunteer = self._setup_conflict_and_overload(api, coordinator_headers)
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-07", "window_start": "09:15", "window_end": "09:45"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW_CONFLICT, 409)
        data, meta = validate_paginated(api.list_call_assignments(coordinator_headers))
        assert meta["total_count"] == 5, "the rejected sixth booking persists nothing"
        assert all(a["status"] == "SCHEDULED" for a in data)


class TestConcurrencyCap:
    def test_eleventh_concurrent_assignment_returns_max_reached(self, api, coordinator_headers):
        """PRD §3.5: "Separately, the volunteer's count of future-dated `SCHEDULED` assignments must be below their `max_concurrent_assignments` tier cap; at the cap, creation fails with `ERR_MAX_ASSIGNMENTS_REACHED`."
        PRD §3.4: "The tier in turn sets `max_concurrent_assignments`: 12 for `GOLD`, 10 for `SILVER`, 8 for `BRONZE`, and 4 for `PROBATION`."

        Design: Corner/validations/eleventh_concurrent_assignment_returns_max_reached
        """
        create_program(total_capacity=10, max_reserve_slots=0)
        m1 = enroll_participant({"full_name": "MC1"})
        for wd in ("MON", "TUE", "WED"):
            add_call_schedule(m1["id"], weekday=wd)
        m2 = enroll_participant({"full_name": "MC2"})
        for wd in ("MON", "TUE"):
            add_call_schedule(m2["id"], weekday=wd, window_start="11:00", window_end="13:00")
        m3 = enroll_participant({"full_name": "MC3"})
        for wd in ("MON", "TUE"):
            add_call_schedule(m3["id"], weekday=wd, window_start="13:00", window_end="15:00")
        # SILVER tier (no history) caps future-dated SCHEDULED at 10.
        volunteer = create_certified_volunteer(
            weekdays=("MON", "TUE", "WED"),
            volunteer_overrides={"max_weekly_minutes": 600},
        )
        slots = [
            (m1, "2026-08-03", "09:00"), (m1, "2026-08-03", "10:00"),
            (m2, "2026-08-03", "11:00"), (m2, "2026-08-03", "12:00"),
            (m3, "2026-08-03", "13:00"),
            (m1, "2026-08-04", "09:00"), (m1, "2026-08-04", "10:00"),
            (m2, "2026-08-04", "11:00"), (m2, "2026-08-04", "12:00"),
            (m3, "2026-08-04", "13:00"),
        ]
        for p, date, start in slots:
            create_assignment(p["id"], volunteer["id"], date, window_start=start,
                              window_end=f"{start[:2]}:30")
        # The 11th concurrent slot: weekly load would be 495 <= 600, so the
        # concurrency cap — not the load cap — is the binding constraint.
        resp = api.create_call_assignment(
            {"participant_id": m1["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-05", "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MAX_ASSIGNMENTS_REACHED, 409)


class TestCancelReconciliation:
    def test_cancel_completed_assignment_rejected(self, api, coordinator_headers):
        """PRD §3.7: "Each log is bound to its `assignment_id`, and exactly one log exists per assignment: the log is append-only, the first log moves the assignment out of `SCHEDULED`, and a second attempt fails the state gate."
        PRD §3.5: "Plain cancellation by a coordinator moves a `SCHEDULED` assignment to `CANCELLED` with `cancel_reason` `MANUAL` and recomputes the volunteer's `current_week_minutes` and the participant's `coverage_deficient`."

        Design: Corner/state_machines/cancel_completed_assignment_rejected
        """
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        set_clock("2026-08-03T10:00:00Z")
        log_call(assignment["id"], volunteer["id"], "2026-08-03T09:05:00Z", "REACHED_OK",
                 duration_seconds=200)
        err = api.cancel_call_assignment(assignment["id"], coordinator_headers)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, 409)
        err2 = api.create_call_log(
            assignment["id"],
            {"called_at": "2026-08-03T09:30:00Z", "duration_seconds": 10,
             "outcome": "NO_ANSWER"},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(err2, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_assignment(assignment["id"])
        assert after["status"] == "COMPLETED"
        logs, meta = validate_paginated(
            api.list_call_logs(assignment["id"], coordinator_headers)
        )
        assert meta["total_count"] == 1, "the append-only log is untouched"

    def test_cancel_reconciles_derived_weekly_load_immediately(self, api, coordinator_headers):
        """PRD §2.5: "Consistency is immediate: a mutation recomputes every derived field it touches — counters, flags, tiers, deadlines — within the same request, and the response reflects the final state."
        PRD §3.5: "A volunteer's `current_week_minutes` sums, over their assignments whose `scheduled_date` falls in the current ISO week (weeks begin Monday) and whose status is `SCHEDULED`, `COMPLETED`, or `UNREACHED`, the window length in minutes plus one `doc_buffer_minutes` allowance each; `CANCELLED` and `EXPIRED` rows contribute nothing."

        Design: Corner/complexity_layers/cancel_reconciles_derived_weekly_load_immediately
        """
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        # Read the derived field from inside the assignment's ISO week.
        set_clock("2026-08-03T08:00:00Z")
        before = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert before["current_week_minutes"] == 45, "30-minute slot + 15-minute buffer"
        validate_success(api.cancel_call_assignment(assignment["id"], coordinator_headers))
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["current_week_minutes"] == 0, (
            "the very next read reflects the removal — no batch lag"
        )

    def test_weekly_load_counts_terminal_showed_up_rows(self, api, coordinator_headers):
        """PRD §3.5: "A volunteer's `current_week_minutes` sums, over their assignments whose `scheduled_date` falls in the current ISO week (weeks begin Monday) and whose status is `SCHEDULED`, `COMPLETED`, or `UNREACHED`, the window length in minutes plus one `doc_buffer_minutes` allowance each; `CANCELLED` and `EXPIRED` rows contribute nothing."

        Design: Corner/calculations/weekly_load_counts_terminal_showed_up_rows
        """
        program, participant, volunteer = setup_calling_environment(
            schedules=(("MON", "09:00", "11:00"), ("TUE", "09:00", "11:00"),
                       ("WED", "09:00", "11:00")),
            volunteer_weekdays=("MON", "TUE", "WED"),
        )
        z1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        z2 = create_assignment(participant["id"], volunteer["id"], "2026-08-04")
        z3 = create_assignment(participant["id"], volunteer["id"], "2026-08-05")
        set_clock("2026-08-05T12:00:00Z")
        log_call(z1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "REACHED_OK",
                 duration_seconds=200)
        log_call(z2["id"], volunteer["id"], "2026-08-04T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        validate_success(api.cancel_call_assignment(z3["id"], coordinator_headers))
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["current_week_minutes"] == 90, (
            "COMPLETED 45 + UNREACHED 45 + CANCELLED 0 for ISO week 2026-08-03..2026-08-09"
        )


class TestSuspendCascadeLoad:
    def test_suspend_cancels_future_assignments_and_reconciles_load(self, api, coordinator_headers):
        """PRD §3.6: "Suspension by a `ProgramCoordinator` moves `ENROLLED` → `SUSPENDED` with a `reason`: every `SCHEDULED` assignment is cancelled with `cancel_reason` `PARTICIPANT_SUSPEND`, each cancellation recomputing the affected volunteer's `current_week_minutes` and the participant's `coverage_deficient` (which turns true because future coverage was removed)."
        PRD §3.5: "A volunteer's `current_week_minutes` sums, over their assignments whose `scheduled_date` falls in the current ISO week (weeks begin Monday) and whose status is `SCHEDULED`, `COMPLETED`, or `UNREACHED`, the window length in minutes plus one `doc_buffer_minutes` allowance each; `CANCELLED` and `EXPIRED` rows contribute nothing."

        Design: Corner/state_machines/suspend_cancels_future_assignments_and_reconciles_load
        """
        program, participant, volunteer = setup_calling_environment()
        a_past = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        a1 = create_assignment(participant["id"], volunteer["id"], "2026-08-10")
        a2 = create_assignment(participant["id"], volunteer["id"], "2026-08-17")
        set_clock("2026-08-03T10:00:00Z")
        log_call(a_past["id"], volunteer["id"], "2026-08-03T09:05:00Z", "REACHED_OK",
                 duration_seconds=200)
        suspended = validate_success(
            api.suspend_participant(participant["id"], {"reason": "hospitalized"}, coordinator_headers)
        )
        assert suspended["status"] == "SUSPENDED"
        c1 = get_assignment(a1["id"])
        c2 = get_assignment(a2["id"])
        assert c1["status"] == "CANCELLED" and c1["cancel_reason"] == "PARTICIPANT_SUSPEND"
        assert c2["status"] == "CANCELLED" and c2["cancel_reason"] == "PARTICIPANT_SUSPEND"
        past = get_assignment(a_past["id"])
        assert past["status"] == "COMPLETED", "terminal rows are not touched by the cascade"
        # In the current ISO week (2026-08-03..09) only the COMPLETED row
        # remains; CANCELLED rows contribute nothing wherever they fall.
        volunteer_after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert volunteer_after["current_week_minutes"] == 45


class TestRescheduleConservation:
    def _setup_reschedulable(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment(
            schedules=(("MON", "09:00", "11:00"), ("WED", "09:00", "11:00")),
            volunteer_weekdays=("MON", "WED"),
        )
        a1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        # Observe the load from inside the assignment's ISO week.
        set_clock("2026-08-03T08:00:00Z")
        return program, participant, volunteer, a1

    def test_same_week_reschedule_conserves_weekly_minutes(self, api, coordinator_headers):
        """PRD §3.5: "A volunteer's `current_week_minutes` sums, over their assignments whose `scheduled_date` falls in the current ISO week (weeks begin Monday) and whose status is `SCHEDULED`, `COMPLETED`, or `UNREACHED`, the window length in minutes plus one `doc_buffer_minutes` allowance each; `CANCELLED` and `EXPIRED` rows contribute nothing."
        PRD §3.5: "Rescheduling supersedes rather than edits. The coordinator supplies `new_scheduled_date`, `new_window_start`, and `new_window_end`; the original assignment is cancelled with `cancel_reason` `RESCHEDULED` and its `version` incremented, and a fresh assignment is created carrying `rescheduled_from_id` pointing at the original, with every create-time check — schedule containment, availability, conflict, load, caps — re-applied to the new window."

        Design: Difficulty/compensating_invariant/weekly_load_conserved_across_same_week_reschedule
        """
        program, participant, volunteer, a1 = self._setup_reschedulable(api, coordinator_headers)
        before = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert before["current_week_minutes"] == 45
        validate_success(api.reschedule_call_assignment(
            a1["id"],
            {"new_scheduled_date": "2026-08-05", "new_window_start": "09:00",
             "new_window_end": "09:30"},
            coordinator_headers,
        ), 201)
        after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert after["current_week_minutes"] == 45, (
            "cancel+create conserves weekly minutes within the same ISO week "
            "(2026-08-03 and 2026-08-05 share the week)"
        )

    def test_reschedule_marks_original_and_links_replacement(self, api, coordinator_headers):
        """PRD §3.5: "Rescheduling supersedes rather than edits. The coordinator supplies `new_scheduled_date`, `new_window_start`, and `new_window_end`; the original assignment is cancelled with `cancel_reason` `RESCHEDULED` and its `version` incremented, and a fresh assignment is created carrying `rescheduled_from_id` pointing at the original, with every create-time check — schedule containment, availability, conflict, load, caps — re-applied to the new window."
        PRD §3.5: "Because the original row is no longer `SCHEDULED`, attempting to reschedule that same row a second time fails the state precondition."

        Design: Difficulty/compensating_invariant/weekly_load_conserved_across_same_week_reschedule
        """
        program, participant, volunteer, a1 = self._setup_reschedulable(api, coordinator_headers)
        replacement = validate_success(api.reschedule_call_assignment(
            a1["id"],
            {"new_scheduled_date": "2026-08-05", "new_window_start": "09:00",
             "new_window_end": "09:30"},
            coordinator_headers,
        ), 201)
        assert replacement["status"] == "SCHEDULED"
        assert replacement["rescheduled_from_id"] == a1["id"]
        original = get_assignment(a1["id"])
        assert original["status"] == "CANCELLED"
        assert original["cancel_reason"] == "RESCHEDULED"
        # A second reschedule of the same row fails the state precondition.
        err = api.reschedule_call_assignment(
            a1["id"],
            {"new_scheduled_date": "2026-08-06", "new_window_start": "09:00",
             "new_window_end": "09:30"},
            coordinator_headers,
        )
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, 409)


class TestAssignmentListFilters:
    def test_assignment_list_filter_combination(self, api, coordinator_headers):
        """PRD §3.5: "Assignment lists can be filtered by `participant_id`, `volunteer_id`, `escalation_id`, `rescheduled_from_id`, `status`, or `scheduled_date`."
        PRD §2.3: "The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/assignment_list_filter_combination
        """
        create_program()
        p1 = enroll_participant({"full_name": "LF1"})
        add_call_schedule(p1["id"], weekday="MON")
        p2 = enroll_participant({"full_name": "LF2"})
        add_call_schedule(p2["id"], weekday="MON")
        volunteer = create_certified_volunteer(weekdays=("MON",))
        a1 = create_assignment(p1["id"], volunteer["id"], "2026-08-03",
                               window_start="09:00", window_end="09:30")
        create_assignment(p2["id"], volunteer["id"], "2026-08-03",
                          window_start="10:00", window_end="10:30")
        validate_success(api.cancel_call_assignment(a1["id"], coordinator_headers))
        data1, meta1 = validate_paginated(api.list_call_assignments(
            coordinator_headers,
            params={"participant_id": p1["id"], "status": "CANCELLED"},
        ))
        assert meta1["total_count"] == 1
        assert data1[0]["id"] == a1["id"]
        data2, meta2 = validate_paginated(api.list_call_assignments(
            coordinator_headers,
            params={"participant_id": p1["id"], "status": "SCHEDULED"},
        ))
        assert meta2["total_count"] == 0
        assert data2 == []
        data3, meta3 = validate_paginated(api.list_call_assignments(
            coordinator_headers, params={"volunteer_id": volunteer["id"]},
        ))
        assert meta3["total_count"] == 2, "filters compose with the pagination envelope"
