"""Call schedules, assignment booking gates, and the volunteer selector."""
from test_helpers import (
    ApiErrorId,
    add_call_schedule,
    create_assignment,
    create_certified_volunteer,
    create_confidentiality_agreement_payload,
    create_program,
    create_volunteer,
    enroll_participant,
    make_volunteer_headers,
    set_clock,
    setup_calling_environment,
    setup_enrolled_participant,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestScheduleValidation:
    def test_schedule_window_below_minimum_returns_invalid_request(self, api, coordinator_headers):
        """PRD §3.5: "The window is half-open, beginning at `window_start` and ending before `window_end`; the start must be before the end, and the total window must run at least 15 and at most 120 minutes, with malformed specifications rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/schedule_window_below_minimum_returns_invalid_request
        """
        program, participant = setup_enrolled_participant(schedules=())
        resp1 = api.create_call_schedule(
            participant["id"],
            {"weekday": "MON", "window_start": "09:00", "window_end": "09:10"},
            coordinator_headers,
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST, 400)
        resp2 = api.create_call_schedule(
            participant["id"],
            {"weekday": "TUE", "window_start": "10:00", "window_end": "09:00"},
            coordinator_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_duplicate_weekday_schedule_rejected(self, api, coordinator_headers):
        """PRD §3.5: "At most one schedule per participant per weekday may be `ACTIVE` or `PAUSED` at once — a second such schedule for the same weekday is rejected with `ERR_DUPLICATE_SCHEDULE`."
        PRD §3.5: "Schedules start `ACTIVE`; a coordinator may pause one (`ACTIVE` → `PAUSED`), resume it (`PAUSED` → `ACTIVE`), or archive it (from `ACTIVE` or `PAUSED` to `ARCHIVED`, which is terminal and leaves existing assignments untouched)."

        Design: Corner/validations/duplicate_weekday_schedule_rejected
        """
        program, participant = setup_enrolled_participant()
        resp = api.create_call_schedule(
            participant["id"],
            {"weekday": "MON", "window_start": "14:00", "window_end": "15:00"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCHEDULE, 409)
        # Archiving the first schedule frees the weekday.
        schedules = validate_success(
            api.list_call_schedules(participant["id"], coordinator_headers)
        )
        validate_success(api.archive_call_schedule(schedules[0]["id"], coordinator_headers))
        ok = api.create_call_schedule(
            participant["id"],
            {"weekday": "MON", "window_start": "14:00", "window_end": "15:00"},
            coordinator_headers,
        )
        created = validate_success(ok, 201)
        assert created["status"] == "ACTIVE", (
            "ARCHIVED rows do not block the weekday"
        )

    def test_schedule_resume_from_archived_rejected(self, api, coordinator_headers):
        """PRD §3.5: "Schedules start `ACTIVE`; a coordinator may pause one (`ACTIVE` → `PAUSED`), resume it (`PAUSED` → `ACTIVE`), or archive it (from `ACTIVE` or `PAUSED` to `ARCHIVED`, which is terminal and leaves existing assignments untouched)."

        Design: Corner/state_machines/schedule_resume_from_archived_rejected
        """
        program, participant = setup_enrolled_participant()
        schedules = validate_success(
            api.list_call_schedules(participant["id"], coordinator_headers)
        )
        schedule_id = schedules[0]["id"]
        validate_success(api.archive_call_schedule(schedule_id, coordinator_headers))
        resp = api.resume_call_schedule(schedule_id, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        listing = validate_success(
            api.list_call_schedules(participant["id"], coordinator_headers)
        )
        assert listing[0]["status"] == "ARCHIVED"


class TestBookingWindowGates:
    def test_assignment_window_outside_schedule_rejected(self, api, coordinator_headers):
        """PRD §3.5: "the new window must lie inside an `ACTIVE` schedule of the participant for that weekday (`ERR_WINDOW_OUTSIDE_SCHEDULE`) and inside one of the volunteer's availability windows effective on the `scheduled_date` (`ERR_WINDOW_OUTSIDE_AVAILABILITY`)"

        Design: Corner/validations/assignment_window_outside_schedule_rejected
        """
        program, participant, volunteer = setup_calling_environment()
        # 12:00-12:30 fits the volunteer's 08:00-17:00 availability but not the
        # participant's MON 09:00-11:00 schedule.
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "12:00", "window_end": "12:30"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_SCHEDULE, 422)

    def test_assignment_window_outside_availability_rejected(self, api, coordinator_headers):
        """PRD §3.5: "the new window must lie inside an `ACTIVE` schedule of the participant for that weekday (`ERR_WINDOW_OUTSIDE_SCHEDULE`) and inside one of the volunteer's availability windows effective on the `scheduled_date` (`ERR_WINDOW_OUTSIDE_AVAILABILITY`)"

        Design: Corner/validations/assignment_window_outside_availability_rejected
        """
        program, participant, volunteer = setup_calling_environment(
            schedules=(("TUE", "09:00", "11:00"),),
            volunteer_weekdays=("MON",),  # no TUE availability
        )
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-04", "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_AVAILABILITY, 422)

    def test_selector_empty_pool_returns_no_eligible_volunteer(self, api, coordinator_headers):
        """PRD §3.5: "An empty pool is rejected with `ERR_NO_ELIGIBLE_VOLUNTEER` for a direct creation; the same emptiness is absorbed differently by the system-driven uses described in §3.6 and §3.7."

        Design: Corner/validations/selector_empty_pool_returns_no_eligible_volunteer
        """
        program, participant = setup_enrolled_participant()
        # No volunteers exist at all: the selector pool is empty.
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "scheduled_date": "2026-08-03",
             "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_VOLUNTEER, 409)


class TestCoverageDeficient:
    def test_coverage_deficient_tracks_required_frequency(self, api, coordinator_headers):
        """PRD §3.5: "Coverage is measured against the participant's `effective_acuity_tier`: five sessions per week are required for `CRITICAL`, three for `HIGH`, two for `MODERATE`, and one for `LOW`."
        PRD §3.5: "`coverage_deficient` turns true when the planned level falls below the required level, or when a future-dated `SCHEDULED` assignment was cancelled without replacement. It clears back to false only when the planned level again meets the requirement and every `ACTIVE` weekday schedule for the coming seven days has at least one future-dated `SCHEDULED` assignment or an assignment already completed this week."
        PRD §3.5: "Schedules start `ACTIVE`; a coordinator may pause one (`ACTIVE` → `PAUSED`), resume it (`PAUSED` → `ACTIVE`), or archive it (from `ACTIVE` or `PAUSED` to `ARCHIVED`, which is terminal and leaves existing assignments untouched). Every one of these mutations recomputes the participant's `coverage_deficient`."

        Every flag read below follows a schedule mutation — the recompute
        trigger the PRD names — since the PRD pins the flag's condition and
        its schedule-mutation recompute, not a recompute on enrollment or on
        assignment creation.

        Design: Corner/calculations/coverage_deficient_tracks_required_frequency
        """
        create_program()
        # HIGH participant (score 65): 20 age + 25 alone + 10 mobility + 10 chronic.
        high = enroll_participant(
            {"full_name": "Hi P", "date_of_birth": "1941-06-12", "age_band": "AGE_85_PLUS",
             "lives_alone": True, "mobility": "LIMITED", "chronic_conditions_count": 2},
            {"accepts_24h": True},
        )
        assert high["effective_acuity_tier"] == "HIGH", (
            "effective tier falls back to the intake tier while rolling is null"
        )
        add_call_schedule(high["id"], weekday="MON")
        one_sched = validate_success(api.get_participant(high["id"], coordinator_headers))
        assert one_sched["coverage_deficient"] is True, "planned 1 < 3 required for HIGH"
        for weekday in ("TUE", "WED"):
            add_call_schedule(high["id"], weekday=weekday)
        high_after = validate_success(api.get_participant(high["id"], coordinator_headers))
        assert high_after["coverage_deficient"] is True, (
            "planned 3 >= 3 but no future assignments exist yet — both clauses must hold"
        )
        # LOW participant: one schedule + one future assignment clears the flag.
        low = enroll_participant({"full_name": "Lo P"})
        low_sched = add_call_schedule(low["id"], weekday="MON")
        low_mid = validate_success(api.get_participant(low["id"], coordinator_headers))
        assert low_mid["coverage_deficient"] is True, (
            "planned 1 >= 1 but the MON schedule still has no future assignment"
        )
        volunteer = create_certified_volunteer(weekdays=("MON",))
        create_assignment(low["id"], volunteer["id"], "2026-08-03")
        # Pause/resume the schedule: named recompute mutations that leave the
        # planned level at 1 while the future SCHEDULED assignment now covers
        # the coming-7-day MON occurrence.
        validate_success(api.pause_call_schedule(low_sched["id"], coordinator_headers))
        validate_success(api.resume_call_schedule(low_sched["id"], coordinator_headers))
        low_after = validate_success(api.get_participant(low["id"], coordinator_headers))
        assert low_after["coverage_deficient"] is False, (
            "planned 1 >= 1 and the coming-7-day MON schedule has a future SCHEDULED assignment"
        )


class TestSelectorRanking:
    def test_selector_load_ranking_then_created_at_tiebreak(self, api, coordinator_headers):
        """PRD §3.5: "The pool is then ranked by `current_week_minutes` ascending (least-loaded first), then by reliability tier from `GOLD` down through `SILVER` and `BRONZE` to `PROBATION`, then by the volunteer's `created_at` ascending — never by identifier."

        Design: Corner/complexity_layers/selector_load_ranking_then_created_at_tiebreak
        """
        program, participant = setup_enrolled_participant()
        v1 = create_certified_volunteer(weekdays=("MON",),
                                        volunteer_overrides={"full_name": "Vol First"})
        v2 = create_certified_volunteer(weekdays=("MON",),
                                        volunteer_overrides={"full_name": "Vol Second"})
        # Move the clock into the target week so the ranked load is the load of
        # the week being booked (ISO week of 2026-08-03).
        set_clock("2026-08-03T00:00:00Z")
        pick1 = validate_success(api.create_call_assignment(
            {"participant_id": participant["id"], "scheduled_date": "2026-08-03",
             "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        ), 201)
        pick2 = validate_success(api.create_call_assignment(
            {"participant_id": participant["id"], "scheduled_date": "2026-08-03",
             "window_start": "10:00", "window_end": "10:30"},
            coordinator_headers,
        ), 201)
        assert pick1["volunteer_id"] == v1["id"], (
            "load tie 0 == 0 and tier tie SILVER == SILVER: created_at ascending wins"
        )
        assert pick2["volunteer_id"] == v2["id"], (
            "V2's load 0 ranks below V1's 45 (30-minute slot + 15-minute buffer)"
        )
        assert pick1["volunteer_id"] != pick2["volunteer_id"]


class TestAssignmentGatedByParticipantEnrollment:
    def _setup_suspended(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment()
        validate_success(
            api.suspend_participant(participant["id"], {"reason": "vacation"}, coordinator_headers)
        )
        return program, participant, volunteer

    def test_assignment_rejected_while_participant_suspended(self, api, coordinator_headers):
        """PRD §3.5: "Creating one requires the participant to be `ENROLLED` — operations on schedules, assignments, and surveys all demand that status and fail with `ERR_PARTICIPANT_NOT_ENROLLED` otherwise —"

        Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_participant_enrollment
        """
        program, participant, volunteer = self._setup_suspended(api, coordinator_headers)
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ENROLLED, 409)

    def test_assignment_accepted_after_resume(self, api, coordinator_headers):
        """PRD §3.6: "Resumption moves `SUSPENDED` → `ENROLLED` and rebuilds near-term coverage: for each `ACTIVE` call schedule whose next occurrence falls within the coming seven days, one new `REGULAR` assignment is created, its window running from the schedule's `window_start` through thirty minutes later on that occurrence date, staffed by the volunteer selector."
        PRD §3.5: "Creating one requires the participant to be `ENROLLED` — operations on schedules, assignments, and surveys all demand that status and fail with `ERR_PARTICIPANT_NOT_ENROLLED` otherwise —"

        Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_participant_enrollment
        """
        program, participant, volunteer = self._setup_suspended(api, coordinator_headers)
        resumed = validate_success(api.resume_participant(participant["id"], coordinator_headers))
        assert resumed["status"] == "ENROLLED"
        # Resume auto-created the 09:00-09:30 MON 2026-08-03 assignment via the
        # selector, so a manual 10:00 slot is conflict-free (past the 09:45
        # buffered end).
        created = validate_success(api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "10:00", "window_end": "10:30"},
            coordinator_headers,
        ), 201)
        assert created["status"] == "SCHEDULED"


class TestAssignmentGatedByVolunteerConfidentiality:
    def _setup_revoked_agreement(self, api, coordinator_headers, reviewer_headers):
        program, participant, volunteer = setup_calling_environment()
        agreements = validate_success(
            api.list_confidentiality_agreements(volunteer["id"], coordinator_headers)
        )
        agreement_id = [a for a in agreements if a["status"] == "ACTIVE"][0]["id"]
        validate_success(
            api.revoke_confidentiality_agreement(agreement_id, reviewer_headers)
        )
        return program, participant, volunteer

    def test_assignment_rejected_while_agreement_revoked(self, api, coordinator_headers, reviewer_headers):
        """PRD §3.4: "A `QualityReviewer` may revoke an `ACTIVE` agreement (it becomes `REVOKED`; any other state fails with `ERR_INVALID_STATE`), after which the volunteer fails every currency check until a fresh agreement is signed and lapses at the next daily closeout."
        PRD §3.5: "the volunteer must be `ACTIVE` with current training and a current confidentiality agreement (`ERR_VOLUNTEER_NOT_CERTIFIED`, `ERR_CONFIDENTIALITY_NOT_CURRENT`)"

        Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_volunteer_confidentiality
        """
        program, participant, volunteer = self._setup_revoked_agreement(
            api, coordinator_headers, reviewer_headers
        )
        volunteer_after = validate_success(api.get_volunteer(volunteer["id"], coordinator_headers))
        assert volunteer_after["status"] == "ACTIVE", (
            "the gate is agreement currency, not volunteer status"
        )
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_NOT_CURRENT, 409)

    def test_assignment_accepted_after_fresh_signature(self, api, coordinator_headers, reviewer_headers):
        """PRD §3.4: "Exactly one agreement per volunteer is `ACTIVE` at any time — a new signature moves the previously `ACTIVE` agreement to `SUPERSEDED`."
        PRD §3.5: "the volunteer must be `ACTIVE` with current training and a current confidentiality agreement (`ERR_VOLUNTEER_NOT_CERTIFIED`, `ERR_CONFIDENTIALITY_NOT_CURRENT`)"

        Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_volunteer_confidentiality
        """
        program, participant, volunteer = self._setup_revoked_agreement(
            api, coordinator_headers, reviewer_headers
        )
        signed = validate_success(
            api.sign_confidentiality_agreement(
                volunteer["id"], create_confidentiality_agreement_payload(),
                make_volunteer_headers(volunteer["id"]),
            ),
            201,
        )
        assert signed["status"] == "ACTIVE"
        created = validate_success(api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "09:00", "window_end": "09:30"},
            coordinator_headers,
        ), 201)
        assert created["status"] == "SCHEDULED"


class TestSafetyBeatsTemporalOnAssignment:
    """Volunteer IN_TRAINING with no records, no agreement, and no
    availability: the safety gate (step 8) must surface before the temporal
    coverage gates (step 9)."""

    def _setup_untrained_volunteer(self, api, coordinator_headers):
        program, participant = setup_enrolled_participant()
        volunteer = create_volunteer(full_name="Vol S")
        validate_success(api.begin_training(volunteer["id"], coordinator_headers))
        return program, participant, volunteer

    def test_certification_error_beats_window_errors(self, api, coordinator_headers):
        """PRD §2.6: "Requests are validated against a fixed, thirteen-step order, and a failure at any step surfaces before later checks are evaluated."
        PRD §2.6: "8. Safety gates: emergency-contact requirements on approval (`ERR_EMERGENCY_CONTACT_REQUIRED`, `ERR_NO_24H_CONTACT`), training and confidentiality currency on certification, reactivation, and assignment creation (`ERR_VOLUNTEER_NOT_CERTIFIED`, `ERR_CONFIDENTIALITY_NOT_CURRENT`), and the immediate-danger field triplet on call logs (`ERR_SAFETY_FIELDS_REQUIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_certification_beats_temporal_window
        """
        program, participant, volunteer = self._setup_untrained_volunteer(api, coordinator_headers)
        # 18:00-18:30 lies outside the participant's 09:00-11:00 schedule AND
        # outside every availability window — both step-9 errors are eligible
        # but must not win over the step-8 safety gate.
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "18:00", "window_end": "18:30"},
            coordinator_headers,
        )
        # The volunteer fails both safety clauses (not ACTIVE with current
        # training; no current agreement). The PRD lists the two step-8 errors
        # in the order (ERR_VOLUNTEER_NOT_CERTIFIED, ERR_CONFIDENTIALITY_NOT_CURRENT)
        # without pinning which of the two reports when both fail — the pinned
        # claim under test is that a safety-gate error beats every step-9 one.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_VOLUNTEER_NOT_CERTIFIED, ApiErrorId.ERR_CONFIDENTIALITY_NOT_CURRENT],
        )
        assert resp.status_code == 409

    def test_no_assignment_persisted_when_safety_gate_fires(self, api, coordinator_headers):
        """PRD §2.6: "Requests are validated against a fixed, thirteen-step order, and a failure at any step surfaces before later checks are evaluated."
        PRD §3.5: "A created assignment lands in `SCHEDULED` with `version` 1, and the volunteer's `current_week_minutes` is recomputed."

        Design: Difficulty/priority_pair_validation_conflict/safety_certification_beats_temporal_window
        """
        program, participant, volunteer = self._setup_untrained_volunteer(api, coordinator_headers)
        resp = api.create_call_assignment(
            {"participant_id": participant["id"], "volunteer_id": volunteer["id"],
             "scheduled_date": "2026-08-03", "window_start": "18:00", "window_end": "18:30"},
            coordinator_headers,
        )
        assert resp.status_code == 409
        error_id = resp.json()["data"]["error_id"]
        assert error_id in ("ERR_VOLUNTEER_NOT_CERTIFIED", "ERR_CONFIDENTIALITY_NOT_CURRENT"), (
            f"expected a safety-gate error, got {error_id}"
        )
        assert error_id not in ("ERR_WINDOW_OUTSIDE_SCHEDULE", "ERR_WINDOW_OUTSIDE_AVAILABILITY",
                                "ERR_ASSIGNMENT_WINDOW_CONFLICT"), (
            "step-9 temporal errors were eligible but must not win"
        )
        data, meta = validate_paginated(
            api.list_call_assignments(coordinator_headers,
                                      params={"participant_id": participant["id"]})
        )
        assert meta["total_count"] == 0, "a rejected booking persists nothing"
