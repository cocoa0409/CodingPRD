"""Monitoring cadence: scheduling rules, completion chaining, clock sweeps."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_checkin,
    create_checkin_payload,
    get_case,
    list_case_audit_events,
    list_case_checkins,
    make_threat_assessor_headers,
    reschedule_checkin,
    schedule_checkin,
    set_clock,
    setup_case_plan_active,
    validate_error,
    validate_paginated,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")
TL1 = TEST_USERS["team_lead_headers"]


class TestCadenceModeDivergence:
    def _setup_two_cases(self, api):
        """Two MODERATE cases, cadence 7, activated at the default clock so
        each holds one auto check-in due 2026-08-08; A runs FROM_COMPLETION,
        B runs FIXED_ANCHOR. Clock then advances to 2026-08-03 (before either
        due date, so no miss sweep fires)."""
        case_a, _ra_a, _plan_a, chk_a = setup_case_plan_active(
            cadence_mode="FROM_COMPLETION", cadence_days=7)
        case_b, _ra_b, _plan_b, chk_b = setup_case_plan_active(
            cadence_mode="FIXED_ANCHOR", cadence_days=7)
        set_clock("2026-08-03T00:00:00Z")
        complete_checkin(chk_a["id"])
        complete_checkin(chk_b["id"])
        return case_a, case_b

    def test_from_completion_next_due_is_completion_date_plus_cadence(self, api):
        """PRD: "Under `FROM_COMPLETION`, the next `due_date` is the
        completion calendar date plus the cadence in days, so a late
        completion pushes the schedule out by the full cadence from the actual
        completion date."

        Design: Difficulty/dual_variant_calc/monitoring_cadence_mode_divergence
        """
        case_a, _case_b = self._setup_two_cases(api)
        scheduled, meta = list_case_checkins(case_a["id"], status="SCHEDULED")
        assert meta["total_count"] == 1
        assert scheduled[0]["due_date"] == "2026-08-10", (
            "completion on 2026-08-03 plus the 7-day cadence"
        )
        assert scheduled[0]["auto_created"] is True

    def test_fixed_anchor_next_due_stays_on_activation_grid(self, api):
        """PRD: "Under `FIXED_ANCHOR`, due dates stay on the grid anchored at
        the plan's activation date: the next due date is the earliest grid
        date — the activation date plus a whole number of cadence intervals —
        that falls strictly after the completion date, so a late completion
        does not shift the grid."

        Design: Difficulty/dual_variant_calc/monitoring_cadence_mode_divergence
        """
        case_a, case_b = self._setup_two_cases(api)
        scheduled_b, meta_b = list_case_checkins(case_b["id"], status="SCHEDULED")
        assert meta_b["total_count"] == 1
        assert scheduled_b[0]["due_date"] == "2026-08-08", (
            "earliest 2026-08-01 + k*7 grid date strictly after 2026-08-03"
        )
        scheduled_a, _meta_a = list_case_checkins(case_a["id"], status="SCHEDULED")
        assert scheduled_a[0]["due_date"] != scheduled_b[0]["due_date"], (
            "identical completion inputs diverge across the two cadence modes"
        )


class TestManualSchedulingRules:
    def test_checkin_same_day_conflict_and_next_day_allowed(self, api):
        """PRD: "A `due_date` earlier than the current logical date is
        rejected with `ERR_INVALID_DUE_DATE`, and because at most one check-in
        in `SCHEDULED` or `MISSED` status may exist per case per calendar day,
        a clashing date draws `ERR_CHECKIN_DAY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/checkin_discrete_calendar_day_uniqueness
        """
        case, _ra, _plan, first = setup_case_plan_active(cadence_days=14)
        assert first["due_date"] == "2026-08-15"

        conflict = api.create_checkin(
            create_checkin_payload(case["id"], "2026-08-15"), TA1)
        validate_error(conflict, ApiErrorId.ERR_CHECKIN_DAY_CONFLICT)

    def test_checkin_next_calendar_day_is_allowed(self, api):
        """PRD: "A `due_date` earlier than the current logical date is
        rejected with `ERR_INVALID_DUE_DATE`, and because at most one check-in
        in `SCHEDULED` or `MISSED` status may exist per case per calendar day,
        a clashing date draws `ERR_CHECKIN_DAY_CONFLICT`."
        PRD: "A `ThreatAssessor` creates one against a `PLAN_ACTIVE` case
        (`ERR_CASE_NOT_PLAN_ACTIVE` otherwise) by supplying `case_id` and a
        `due_date` calendar date."

        Design: Difficulty/resource_temporal_overlap/checkin_discrete_calendar_day_uniqueness
        """
        case, _ra, _plan, _first = setup_case_plan_active(cadence_days=14)
        created = validate_success(
            api.create_checkin(create_checkin_payload(case["id"], "2026-08-16"),
                               TA1),
            201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["due_date"] == "2026-08-16"
        assert created["auto_created"] is False

    def test_manual_checkin_with_past_due_date_rejected(self, api):
        """PRD: "A `due_date` earlier than the current logical date is
        rejected with `ERR_INVALID_DUE_DATE`, and because at most one check-in
        in `SCHEDULED` or `MISSED` status may exist per case per calendar day,
        a clashing date draws `ERR_CHECKIN_DAY_CONFLICT`."

        Design: Corner/endpoints/manual_checkin_with_past_due_date_rejected
        """
        case, _ra, _plan, _first = setup_case_plan_active(cadence_days=7)

        past = api.create_checkin(
            create_checkin_payload(case["id"], "2026-07-31"), TA1)
        validate_error(past, ApiErrorId.ERR_INVALID_DUE_DATE)

        today = validate_success(
            api.create_checkin(create_checkin_payload(case["id"], "2026-08-01"),
                               TA1),
            201,
        )
        assert today["status"] == "SCHEDULED"
        assert today["due_date"] == "2026-08-01", (
            "a due date equal to the current logical date is not earlier "
            "than it and is allowed"
        )


class TestMissedCheckInCascade:
    def test_first_miss_increments_counter_without_escalation(self, api):
        """PRD: "Check-ins that lapse are caught by the clock advance of
        §2.5: when the current calendar date moves past a `SCHEDULED`
        check-in's `due_date`, the check-in becomes `MISSED`, the case's
        `consecutive_missed_count` increases by one, and `CHECKIN_MISSED` is
        written; the moment that count reaches two, the case's
        `escalation_flag` is set and `ESCALATION_RAISED` is written."
        PRD: "Rescheduling returns the check-in to `SCHEDULED` with its
        `due_date` updated and writes `CHECKIN_RESCHEDULED`, but it
        deliberately does not reset `consecutive_missed_count` — the miss
        history is preserved."

        Design: Difficulty/transitive_cascade/missed_checkin_counter_escalation_cascade
        """
        case, _ra, _plan, chk = setup_case_plan_active()
        assert chk["due_date"] == "2026-08-15"

        set_clock("2026-08-16T00:00:00Z")
        missed, missed_meta = list_case_checkins(case["id"], status="MISSED")
        assert missed_meta["total_count"] == 1
        assert missed[0]["id"] == chk["id"]

        case_after = get_case(case["id"])
        assert case_after["consecutive_missed_count"] == 1
        assert case_after["escalation_flag"] is False, (
            "escalation fires only when the count reaches two"
        )

        rescheduled = reschedule_checkin(chk["id"], "2026-08-16")
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["due_date"] == "2026-08-16"
        assert get_case(case["id"])["consecutive_missed_count"] == 1, (
            "rescheduling deliberately preserves the miss history"
        )

    def test_second_consecutive_miss_raises_escalation(self, api):
        """PRD: "Check-ins that lapse are caught by the clock advance of
        §2.5: when the current calendar date moves past a `SCHEDULED`
        check-in's `due_date`, the check-in becomes `MISSED`, the case's
        `consecutive_missed_count` increases by one, and `CHECKIN_MISSED` is
        written; the moment that count reaches two, the case's
        `escalation_flag` is set and `ESCALATION_RAISED` is written."

        Design: Difficulty/transitive_cascade/missed_checkin_counter_escalation_cascade
        """
        case, _ra, _plan, chk = setup_case_plan_active()
        set_clock("2026-08-16T00:00:00Z")
        reschedule_checkin(chk["id"], "2026-08-16")

        set_clock("2026-08-17T00:00:00Z")
        case_after = get_case(case["id"])
        assert case_after["consecutive_missed_count"] == 2
        assert case_after["escalation_flag"] is True

        events, ev_meta = list_case_audit_events(case["id"], TL1,
                                                 action="ESCALATION_RAISED")
        assert ev_meta["total_count"] == 1
        assert events[0]["action"] == "ESCALATION_RAISED"


class TestCheckInStateGuards:
    def test_complete_missed_checkin_returns_not_scheduled(self, api):
        """PRD: "Completing a check-in requires it to be `SCHEDULED`
        (`ERR_CHECKIN_NOT_SCHEDULED`) and takes an `outcome` of `ON_TRACK` or
        `CONCERNS_ESCALATED` — anything else is `ERR_INVALID_REQUEST` — plus
        free-text `notes`."

        Design: Corner/state_machines/complete_missed_checkin_returns_not_scheduled
        """
        case, _ra, _plan, chk = setup_case_plan_active(cadence_days=7)
        set_clock("2026-08-09T00:00:00Z")

        resp = api.complete_checkin(
            chk["id"], {"outcome": "ON_TRACK", "notes": "late"}, TA1)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_NOT_SCHEDULED)

    def test_reschedule_scheduled_checkin_returns_not_missed(self, api):
        """PRD: "A missed check-in is not dead weight: a `ThreatAssessor` may
        reschedule one that is `MISSED` (`ERR_CHECKIN_NOT_MISSED` otherwise)
        by supplying a `new_due_date` no earlier than the current logical date
        (`ERR_INVALID_DUE_DATE`) that does not collide with another
        `SCHEDULED` or `MISSED` check-in for the case on that day
        (`ERR_CHECKIN_DAY_CONFLICT`)."

        Design: Corner/state_machines/reschedule_scheduled_checkin_returns_not_missed
        """
        case, _ra, _plan, chk = setup_case_plan_active(cadence_days=7)
        assert chk["status"] == "SCHEDULED"

        resp = api.reschedule_checkin(chk["id"], {"new_due_date": "2026-08-20"},
                                      TA1)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_NOT_MISSED)
