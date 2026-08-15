"""Call logs: validation, streak arithmetic, escalation arming, rolling acuity."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_call_log,
    create_assignment,
    create_call_log_payload,
    get_assignment,
    log_call,
    make_volunteer_headers,
    set_clock,
    setup_calling_environment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCallLogValidation:
    def test_log_invalid_enum_outcome_rejected(self, api, coordinator_headers):
        """PRD §2.6: "Independently of this ordering, a malformed payload — a missing required field, an unknown field, an invalid enum value, a `window_start` that is not before its `window_end`, or an out-of-range value — is rejected with `ERR_INVALID_REQUEST`."
        PRD §3.7: "The log carries `called_at` (which must not be after the logical clock, failing with `ERR_FUTURE_DATED_CALL_LOG` otherwise), `duration_seconds` (zero or more), the `outcome` (`REACHED_OK`, `REACHED_CONCERN`, `NO_ANSWER`, `BUSY`, `REFUSED`, or `WRONG_NUMBER`), a `concern_level` (default `NONE`; otherwise `ROUTINE`, `URGENT`, or `IMMEDIATE_DANGER`)"

        Design: Corner/validations/log_invalid_enum_outcome_rejected
        """
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        set_clock("2026-08-03T10:00:00Z")
        resp = api.create_call_log(
            assignment["id"],
            create_call_log_payload(called_at="2026-08-03T09:05:00Z",
                                    duration_seconds=10, outcome="HUNG_UP"),
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        after = get_assignment(assignment["id"])
        assert after["status"] == "SCHEDULED", "an invalid payload mutates nothing"

    def test_future_dated_call_log_rejected(self, api, coordinator_headers):
        """PRD §3.7: "The log carries `called_at` (which must not be after the logical clock, failing with `ERR_FUTURE_DATED_CALL_LOG` otherwise)"

        Design: Corner/validations/future_dated_call_log_rejected
        """
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        # The clock is still at the 2026-08-01T00:00:00Z default; the log's
        # called_at is after it.
        resp = api.create_call_log(
            assignment["id"],
            create_call_log_payload(called_at="2026-08-03T09:05:00Z",
                                    duration_seconds=10, outcome="REACHED_OK"),
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FUTURE_DATED_CALL_LOG, 422)

    def test_safety_fields_required_direct_on_valid_assignment(self, api, coordinator_headers):
        """PRD §3.7: "When `concern_level` is `IMMEDIATE_DANGER`, three fields become mandatory together: `follow_up_needed` must be true, `supervisor_notified` must be true, and `follow_up_plan` must be non-empty — the triplet failing with `ERR_SAFETY_FIELDS_REQUIRED`."

        Design: Corner/errors/safety_fields_required_direct_on_valid_assignment
        """
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        set_clock("2026-08-03T10:00:00Z")
        # Live SCHEDULED assignment (no state shadow): the safety triplet is
        # the observable gate.
        resp = api.create_call_log(
            assignment["id"],
            {"called_at": "2026-08-03T09:05:00Z", "duration_seconds": 300,
             "outcome": "REACHED_CONCERN", "concern_level": "IMMEDIATE_DANGER",
             "concern_categories": ["SAFETY"]},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SAFETY_FIELDS_REQUIRED, 422)
        after = get_assignment(assignment["id"])
        assert after["status"] == "SCHEDULED", (
            "the rejected log leaves no partial state — no streak change, no escalation"
        )
        participant_after = validate_success(
            api.get_participant(participant["id"], coordinator_headers)
        )
        assert participant_after["consecutive_no_answer_count"] == 0
        assert participant_after.get("open_escalation_id") is None


class TestMissingAuth:
    def test_missing_auth_headers_returns_unauthenticated(self, api, coordinator_headers):
        """PRD §2.6: "1. Authentication: the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role, otherwise `ERR_UNAUTHENTICATED`."
        PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        program = validate_success(api.create_program(
            {"name": "AAA", "total_capacity": 10, "current_policy_version": "v2026.1"},
            coordinator_headers,
        ), 201)
        resp = api.get_program(program["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestConcernFlag:
    def test_call_log_concern_flag_computed_two_ways(self, api, coordinator_headers):
        """PRD §3.7: "The `concern_flag` is computed — true exactly when the outcome is `REACHED_CONCERN` or the `concern_level` is anything other than `NONE`."

        Design: Corner/entities/call_log_concern_flag_computed_two_ways
        """
        program, participant, volunteer = setup_calling_environment()
        a1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="09:00", window_end="09:30")
        a2 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="10:00", window_end="10:30")
        set_clock("2026-08-03T11:00:00Z")
        log1 = log_call(a1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "REACHED_CONCERN",
                        duration_seconds=100)
        assert_call_log(log1)
        assert log1["concern_flag"] is True, (
            "outcome REACHED_CONCERN alone suffices (concern_level defaulted NONE)"
        )
        log2 = log_call(a2["id"], volunteer["id"], "2026-08-03T10:05:00Z", "REACHED_OK",
                        duration_seconds=100, concern_level="ROUTINE",
                        concern_categories=["MOOD"])
        assert log2["concern_flag"] is True, (
            "concern_level ROUTINE on a REACHED_OK outcome also flags"
        )


class TestStreakReset:
    def test_no_answer_streak_reset_on_reached(self, api, coordinator_headers):
        """PRD §3.7: "A log of `REACHED_OK`, `REACHED_CONCERN`, or `REFUSED` moves the assignment to `COMPLETED` and resets the streak to zero. A log of `NO_ANSWER`, `BUSY`, or `WRONG_NUMBER` moves the assignment to `UNREACHED` — which still counts as showed-up for the volunteer's reliability, since the miss is participant-side — and increments the streak by one."

        Design: Corner/calculations/no_answer_streak_reset_on_reached
        """
        program, participant, volunteer = setup_calling_environment(
            schedules=(("MON", "09:00", "11:00"), ("TUE", "09:00", "11:00"),
                       ("WED", "09:00", "11:00")),
            volunteer_weekdays=("MON", "TUE", "WED"),
        )
        q1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="09:00", window_end="09:30")
        q2 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="10:00", window_end="10:30")
        q3 = create_assignment(participant["id"], volunteer["id"], "2026-08-04")
        q4 = create_assignment(participant["id"], volunteer["id"], "2026-08-05")
        set_clock("2026-08-05T12:00:00Z")
        log_call(q1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        log_call(q2["id"], volunteer["id"], "2026-08-03T10:05:00Z", "BUSY",
                 duration_seconds=0)
        log_call(q3["id"], volunteer["id"], "2026-08-04T09:05:00Z", "REACHED_OK",
                 duration_seconds=120)
        log_call(q4["id"], volunteer["id"], "2026-08-05T09:05:00Z", "WRONG_NUMBER",
                 duration_seconds=0)
        after = validate_success(api.get_participant(participant["id"], coordinator_headers))
        # NA -> 1, BUSY -> 2, REACHED_OK -> reset 0, WRONG_NUMBER -> 1.
        assert after["consecutive_no_answer_count"] == 1
        assert after.get("open_escalation_id") is None, (
            "the streak never reached the threshold of 3, so no escalation opened"
        )


class TestImmediateConsistency:
    def test_immediate_read_after_write_visibility(self, api, coordinator_headers):
        """PRD §2.5: "Consistency is immediate: a mutation recomputes every derived field it touches — counters, flags, tiers, deadlines — within the same request, and the response reflects the final state."
        PRD §3.7: "A log of `NO_ANSWER`, `BUSY`, or `WRONG_NUMBER` moves the assignment to `UNREACHED` — which still counts as showed-up for the volunteer's reliability, since the miss is participant-side — and increments the streak by one."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        assert assignment["status"] == "SCHEDULED", (
            "the create response reflects the committed state"
        )
        set_clock("2026-08-03T10:00:00Z")
        log_call(assignment["id"], volunteer["id"], "2026-08-03T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        after_assignment = get_assignment(assignment["id"])
        assert after_assignment["status"] == "UNREACHED"
        after_participant = validate_success(
            api.get_participant(participant["id"], coordinator_headers)
        )
        assert after_participant["consecutive_no_answer_count"] == 1, (
            "the streak mutation is visible on the immediately following read"
        )


class TestNoAnswerStreakThreshold:
    def _setup_three_assignments(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment()
        n1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        n2 = create_assignment(participant["id"], volunteer["id"], "2026-08-10")
        n3 = create_assignment(participant["id"], volunteer["id"], "2026-08-17")
        return program, participant, volunteer, (n1, n2, n3)

    def test_first_two_misses_open_no_escalation(self, api, coordinator_headers):
        """PRD §3.7: "when an increment raises `consecutive_no_answer_count` to at least the program's `no_answer_threshold` (three by default) and the participant's `open_escalation_id` is null, the system opens an escalation with `trigger_type` `NO_ANSWER_PROTOCOL` at stage `STEP_1_RETRY`, points `open_escalation_id` at it, and creates a retry assignment whose `source` is `ESCALATION_RETRY`, whose thirty-minute window starts at the logged `called_at` on that same date, staffed through the volunteer selector and linked back through `escalation_id`."

        Design: Difficulty/boundary_precision_check/no_answer_streak_triggers_at_third_log
        """
        program, participant, volunteer, (n1, n2, n3) = self._setup_three_assignments(
            api, coordinator_headers
        )
        set_clock("2026-08-03T10:00:00Z")
        log_call(n1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        mid = validate_success(api.get_participant(participant["id"], coordinator_headers))
        assert mid["consecutive_no_answer_count"] == 1
        assert mid.get("open_escalation_id") is None
        set_clock("2026-08-10T10:00:00Z")
        log_call(n2["id"], volunteer["id"], "2026-08-10T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        mid2 = validate_success(api.get_participant(participant["id"], coordinator_headers))
        assert mid2["consecutive_no_answer_count"] == 2
        assert mid2.get("open_escalation_id") is None, (
            "threshold 3 NOT reached — no escalation below the boundary"
        )

    def test_third_consecutive_miss_opens_escalation(self, api, coordinator_headers):
        """PRD §3.7: "when an increment raises `consecutive_no_answer_count` to at least the program's `no_answer_threshold` (three by default) and the participant's `open_escalation_id` is null, the system opens an escalation with `trigger_type` `NO_ANSWER_PROTOCOL` at stage `STEP_1_RETRY`, points `open_escalation_id` at it, and creates a retry assignment whose `source` is `ESCALATION_RETRY`, whose thirty-minute window starts at the logged `called_at` on that same date, staffed through the volunteer selector and linked back through `escalation_id`."

        Design: Difficulty/boundary_precision_check/no_answer_streak_triggers_at_third_log
        """
        program, participant, volunteer, (n1, n2, n3) = self._setup_three_assignments(
            api, coordinator_headers
        )
        set_clock("2026-08-03T10:00:00Z")
        log_call(n1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        set_clock("2026-08-10T10:00:00Z")
        log_call(n2["id"], volunteer["id"], "2026-08-10T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        set_clock("2026-08-17T10:00:00Z")
        log_call(n3["id"], volunteer["id"], "2026-08-17T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        after = validate_success(api.get_participant(participant["id"], coordinator_headers))
        assert after["consecutive_no_answer_count"] == 3, (
            "the 2->3 increment trips the inclusive >= 3 boundary"
        )
        escalation_id = after.get("open_escalation_id")
        assert escalation_id, "the third miss opens the no-answer-protocol escalation"
        escalation = validate_success(api.get_escalation(escalation_id, coordinator_headers))
        assert escalation["stage"] == "STEP_1_RETRY"
        assert escalation["trigger_type"] == "NO_ANSWER_PROTOCOL"
        assert escalation.get("retry_assignment_id"), (
            "the selector found the certified volunteer for the 30-minute retry window"
        )


class TestStatePreconditionBeatsSafetyFields:
    def _setup_cancelled_assignment(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        validate_success(api.cancel_call_assignment(assignment["id"], coordinator_headers))
        return program, participant, volunteer, assignment

    def _danger_log_missing_fields(self, api, assignment_id, volunteer_id):
        return api.create_call_log(
            assignment_id,
            {"called_at": "2026-08-03T09:05:00Z", "duration_seconds": 60,
             "outcome": "REACHED_CONCERN", "concern_level": "IMMEDIATE_DANGER",
             "concern_categories": ["SAFETY"]},
            make_volunteer_headers(volunteer_id),
        )

    def test_state_error_wins_over_safety_fields_error(self, api, coordinator_headers):
        """PRD §2.6: "Requests are validated against a fixed, thirteen-step order, and a failure at any step surfaces before later checks are evaluated."
        PRD §2.6: "6. State validity: the target resource is in a valid from-state for the requested transition, otherwise the state-family error `ERR_INVALID_STATE` — or its specialized siblings `ERR_OFFER_NOT_OPEN`, `ERR_NO_OPEN_ESCALATION`, or `ERR_PARTICIPANT_NOT_ENROLLED` where those apply."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_safety_fields
        """
        program, participant, volunteer, assignment = self._setup_cancelled_assignment(
            api, coordinator_headers
        )
        resp = self._danger_log_missing_fields(api, assignment["id"], volunteer["id"])
        # The assignment is CANCELLED (step 6) and the payload also lacks the
        # IMMEDIATE_DANGER triplet (step 8): step 6 fires first.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_rejected_log_leaves_cancelled_assignment_untouched(self, api, coordinator_headers):
        """PRD §2.6: "Requests are validated against a fixed, thirteen-step order, and a failure at any step surfaces before later checks are evaluated."
        PRD §3.7: "Each log is bound to its `assignment_id`, and exactly one log exists per assignment: the log is append-only, the first log moves the assignment out of `SCHEDULED`, and a second attempt fails the state gate."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_safety_fields
        """
        program, participant, volunteer, assignment = self._setup_cancelled_assignment(
            api, coordinator_headers
        )
        resp = self._danger_log_missing_fields(api, assignment["id"], volunteer["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_assignment(assignment["id"])
        assert after["status"] == "CANCELLED"
        logs, meta = validate_paginated(
            api.list_call_logs(assignment["id"], coordinator_headers)
        )
        assert meta["total_count"] == 0, "no log was persisted by the rejected request"


class TestAcuityIntakeVsRollingBlend:
    """Same participant: static intake score 55 (MODERATE) versus rolling blend
    68.5 (HIGH) after a closeout over 3 concern logs, 4 no-answer logs and 1
    auto-opened escalation in the trailing 30 days."""

    def _setup_and_run_closeout(self, api, coordinator_headers):
        # max_weekly_minutes 600 (the PRD-permitted maximum): the seven 30-minute
        # bookings plus the auto-created retry all land in the same ISO week
        # (8 x 45 = 360), so the setup passes whether an implementation reads
        # the §3.5 load check over the clock's current ISO week (the field
        # definition) or over the week of the scheduled_date being booked —
        # the PRD names the field in the rule without pinning which week a
        # future-dated booking is charged to.
        program, participant, volunteer = setup_calling_environment(
            schedules=(("MON", "09:00", "11:00"), ("TUE", "09:00", "11:00"),
                       ("WED", "09:00", "11:00"), ("THU", "09:00", "11:00")),
            volunteer_weekdays=("MON", "TUE", "WED", "THU"),
            participant_overrides={
                "full_name": "Mod A", "date_of_birth": "1946-03-12",
                "age_band": "AGE_75_84", "lives_alone": True, "mobility": "LIMITED",
                "chronic_conditions_count": 2,
            },
            program_overrides={"total_capacity": 20},
            volunteer_overrides={"max_weekly_minutes": 600},
        )
        assignments = {}
        for key, date, start in [
            ("a1", "2026-08-03", "09:00"), ("a2", "2026-08-03", "10:00"),
            ("a3", "2026-08-04", "09:00"), ("a4", "2026-08-04", "10:00"),
            ("a5", "2026-08-05", "09:00"), ("a6", "2026-08-05", "10:00"),
            ("a7", "2026-08-06", "09:00"),
        ]:
            assignments[key] = create_assignment(
                participant["id"], volunteer["id"], date,
                window_start=start, window_end=f"{start[:2]}:30",
            )
        set_clock("2026-08-03T11:00:00Z")
        log_call(assignments["a1"]["id"], volunteer["id"], "2026-08-03T09:05:00Z",
                 "REACHED_CONCERN", duration_seconds=300, concern_level="ROUTINE",
                 concern_categories=["MOOD"])
        log_call(assignments["a2"]["id"], volunteer["id"], "2026-08-03T10:05:00Z",
                 "NO_ANSWER", duration_seconds=0)
        set_clock("2026-08-04T11:00:00Z")
        log_call(assignments["a3"]["id"], volunteer["id"], "2026-08-04T09:05:00Z",
                 "NO_ANSWER", duration_seconds=0)
        # The third consecutive miss arms the no-answer protocol escalation.
        log_call(assignments["a4"]["id"], volunteer["id"], "2026-08-04T10:05:00Z",
                 "NO_ANSWER", duration_seconds=0)
        set_clock("2026-08-05T11:00:00Z")
        log_call(assignments["a5"]["id"], volunteer["id"], "2026-08-05T09:05:00Z",
                 "NO_ANSWER", duration_seconds=0)
        log_call(assignments["a6"]["id"], volunteer["id"], "2026-08-05T10:05:00Z",
                 "REACHED_CONCERN", duration_seconds=240, concern_level="ROUTINE",
                 concern_categories=["NUTRITION"])
        set_clock("2026-08-06T10:00:00Z")
        log_call(assignments["a7"]["id"], volunteer["id"], "2026-08-06T09:05:00Z",
                 "REACHED_CONCERN", duration_seconds=240, concern_level="ROUTINE",
                 concern_categories=["HEALTH"])
        set_clock("2026-08-10T08:00:00Z")
        validate_success(api.daily_closeout(program["id"], coordinator_headers))
        return program, participant, volunteer

    def test_intake_score_static_and_rolling_blend_computed(self, api, coordinator_headers):
        """PRD §3.2: "This intake computation runs at review submission and is never recomputed afterwards; `last_status_change_at` is stamped at the transition."
        PRD §3.9: "`rolling_acuity_score` blends the static and the observed: seventy percent of the intake `acuity_score` plus thirty percent of the signal, rounded half-up to one decimal place."
        PRD §3.9: "Four counts feed the signal — logs in the window with `concern_flag` true, weighted 15 each; logs with outcome `NO_ANSWER`, `BUSY`, or `WRONG_NUMBER`, weighted 10 each; the participant's escalations with `opened_at` in the window, weighted 25 each; and the participant's referrals with `submitted_at` in the window, weighted 10 each — and the signal itself is that weighted sum, capped at 100."

        Design: Difficulty/dual_variant_calc/acuity_intake_static_vs_rolling_outcome_blend
        """
        program, participant, volunteer = self._setup_and_run_closeout(api, coordinator_headers)
        after = validate_success(api.get_participant(participant["id"], coordinator_headers))
        assert after["acuity_score"] == 55, (
            "intake variant is static: 10 age + 25 alone + 10 mobility + 10 chronic"
        )
        assert after["acuity_tier"] == "MODERATE"
        # signal = min(100, 3*15 + 4*10 + 1*25 + 0*10) = 100
        # rolling = round_half_up(0.7*55 + 0.3*100, 1) = 68.5
        assert after["rolling_acuity_score"] == pytest.approx(68.5, abs=0.01)
        assert after["rolling_acuity_tier"] == "HIGH"

    def test_effective_tier_takes_more_severe_of_the_two(self, api, coordinator_headers):
        """PRD §3.9: "`effective_acuity_tier` is the more severe of the two tiers under the ordering from `LOW` through `MODERATE` and `HIGH` to `CRITICAL`; until the first post-enrollment closeout produces a rolling value, the rolling fields are null and the effective tier simply equals the intake tier."
        PRD §3.9: "`rolling_acuity_tier` applies the same band boundaries as the intake tier — 29, 59, and 84 — to the rolling score."

        Design: Difficulty/dual_variant_calc/acuity_intake_static_vs_rolling_outcome_blend
        """
        program, participant, volunteer = self._setup_and_run_closeout(api, coordinator_headers)
        after = validate_success(api.get_participant(participant["id"], coordinator_headers))
        assert after["effective_acuity_tier"] == "HIGH", (
            "more severe of MODERATE intake and HIGH rolling — identical rows, "
            "55 under the intake variant vs 68.5 under the rolling variant"
        )
