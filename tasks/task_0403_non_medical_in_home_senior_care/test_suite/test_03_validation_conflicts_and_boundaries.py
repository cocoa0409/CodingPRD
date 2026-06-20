"""Validation precedence, boundary precision, and cross-entity gate tests
(queue A: Difficulty).

Covers which error wins when two checks both fail, EVV rounding and weekly-hours
boundaries, and the match->caregiver / visit->care-plan cross-entity gates.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, setup_schedulable_scenario,
    create_completed_visit, create_in_progress_visit,
    create_agency, create_active_caregiver, create_active_client,
    create_published_plan, create_active_match, create_caregiver,
    create_client, schedule_visit, clock_in_visit,
    make_caregiver_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]


class TestStateVsNoActiveMatchPrecedence:
    """rule_id: priority_pair_validation_conflict / clockin_state_vs_no_active_match."""

    def _setup_completed_visit_with_ended_match(self, api):
        s = setup_schedulable_scenario()
        cg, cl, plan, match = s["caregiver"], s["client"], s["plan"], s["match"]
        v = create_completed_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        validate_success(api.transition_match(match["id"], {"action": "END"}, SCHEDULER))
        return cg, v

    def test_clockin_on_completed_visit_without_match_returns_state_error(self, api):
        """PRD §2.6: "Fifth is the state check: the target resource must be in a state from
        which the requested transition is legal, otherwise a state error is returned ...
        Only after these five tiers pass does the system evaluate the business-referential,
        temporal, fiscal, and concurrency rules attached to the specific operation."
        PRD §3.6: "Four preconditions guard clock-in: the visit must be in SCHEDULED or
        EN_ROUTE (otherwise ERR_INVALID_STATE)".

        Design: Difficulty/priority_pair_validation_conflict/clockin_state_vs_no_active_match
        """
        cg, v = self._setup_completed_visit_with_ended_match(api)
        resp = api.clock_in(v["id"], {"event_at": "2026-06-01T12:00:00Z"},
                            make_caregiver_headers(cg["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_error_precedes_no_active_match(self, api):
        """PRD §2.6: "the state check ... otherwise a state error is returned (the generic
        ERR_INVALID_STATE ... all at HTTP 409). Only after these five tiers pass does the
        system evaluate the business-referential, temporal, fiscal, and concurrency rules
        attached to the specific operation."

        Design: Difficulty/priority_pair_validation_conflict/clockin_state_vs_no_active_match
        """
        cg, v = self._setup_completed_visit_with_ended_match(api)
        resp = api.clock_in(v["id"], {"event_at": "2026-06-01T12:00:00Z"},
                            make_caregiver_headers(cg["id"]))
        body = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert body["error_id"] != ApiErrorId.ERR_NO_ACTIVE_MATCH.value


class TestDoubleBookedVsWeeklyHoursPrecedence:
    """rule_id: priority_pair_validation_conflict / visit_double_booked_vs_weekly_hours."""

    def _setup_caregiver_with_one_visit(self, api):
        set_clock("2026-06-01T07:00:00Z")
        agency = create_agency()
        cg = create_active_caregiver(agency["id"], max_weekly_hours=10)
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        schedule_visit(cg["id"], cl["id"], plan["id"],
                       "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z")
        return cg, cl, plan

    def test_overlapping_and_over_cap_visit_returns_double_booked(self, api):
        """PRD §2.6: "Within that final tier, the per-operation orderings stated in §3
        apply."
        PRD §3.5: "Scheduling enforces three business constraints ... First, a caregiver
        may not be double-booked ... a true overlap is rejected with
        ERR_CAREGIVER_DOUBLE_BOOKED. ... Third, scheduling must not push the caregiver's
        total scheduled billable hours within the visit's ISO week above that caregiver's
        max_weekly_hours; exceeding the cap is rejected with ERR_WEEKLY_HOURS_EXCEEDED."

        Design: Difficulty/priority_pair_validation_conflict/visit_double_booked_vs_weekly_hours
        """
        cg, cl, plan = self._setup_caregiver_with_one_visit(api)
        # 10:00-18:00 overlaps 09:00-17:00 AND total would be 16h > 10.
        resp = api.create_visit({
            "caregiver_id": cg["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-01T10:00:00Z",
            "scheduled_end": "2026-06-01T18:00:00Z",
        }, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CAREGIVER_DOUBLE_BOOKED.value)

    def test_double_booked_reported_over_weekly_hours(self, api):
        """PRD §3.5: "First, a caregiver may not be double-booked ... a true overlap is
        rejected with ERR_CAREGIVER_DOUBLE_BOOKED."

        Design: Difficulty/priority_pair_validation_conflict/visit_double_booked_vs_weekly_hours
        """
        cg, cl, plan = self._setup_caregiver_with_one_visit(api)
        resp = api.create_visit({
            "caregiver_id": cg["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-01T10:00:00Z",
            "scheduled_end": "2026-06-01T18:00:00Z",
        }, SCHEDULER)
        body = validate_error(resp, ApiErrorId.ERR_CAREGIVER_DOUBLE_BOOKED.value)
        assert body["error_id"] != ApiErrorId.ERR_WEEKLY_HOURS_EXCEEDED.value


class TestEvvRoundingBoundary:
    """rule_id: boundary_precision_check / evv_rounding_half_increment_boundary."""

    def _setup_two_in_progress(self, api):
        s = setup_schedulable_scenario(caregiver_overrides={"max_weekly_hours": 50})
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v7 = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z", "2026-06-01T09:00:00Z")
        v8 = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z", "2026-06-01T11:00:00Z")
        return cg, v7, v8

    def test_seven_minute_window_rounds_down_to_zero(self, api):
        """PRD §3.6: "It then rounds that raw figure to the nearest multiple of the
        agency's evv_rounding_minutes using round-half-up — that is, it divides the raw
        minutes by the rounding increment, rounds that quotient to the nearest whole
        number with halves going up, and multiplies back by the increment."

        Design: Difficulty/boundary_precision_check/evv_rounding_half_increment_boundary
        """
        cg, v7, _v8 = self._setup_two_in_progress(api)
        done = validate_success(api.clock_out(
            v7["id"], {"event_at": "2026-06-01T09:07:00Z"},
            make_caregiver_headers(cg["id"])))
        # 7 min / 15 = 0.467 -> rounds to 0 increments -> 0 billable minutes.
        assert done["billable_minutes"] == 0, \
            f"7-min window should round to 0 billable minutes, got {done['billable_minutes']}"
        assert done["visit_charge"] == pytest.approx(0.00, abs=0.01)

    def test_eight_minute_window_rounds_up_to_one_increment(self, api):
        """PRD §3.6: "it divides the raw minutes by the rounding increment, rounds that
        quotient to the nearest whole number with halves going up, and multiplies back by
        the increment. ... For an HOURLY visit, the charge is the billable_minutes divided
        by 60 and multiplied by the agency's base_hourly_rate, rounded half-up to 2 decimal
        places".

        Design: Difficulty/boundary_precision_check/evv_rounding_half_increment_boundary
        """
        cg, _v7, v8 = self._setup_two_in_progress(api)
        done = validate_success(api.clock_out(
            v8["id"], {"event_at": "2026-06-01T11:08:00Z"},
            make_caregiver_headers(cg["id"])))
        # 8 min / 15 = 0.533 -> rounds to 1 increment -> 15 billable minutes.
        assert done["billable_minutes"] == 15, \
            f"8-min window should round up to 15 billable minutes, got {done['billable_minutes']}"
        # 15/60 * 30 = 7.50.
        assert done["visit_charge"] == pytest.approx(7.50, abs=0.01), \
            f"15-min HOURLY charge should be 7.50, got {done['visit_charge']}"


class TestWeeklyHoursCapBoundary:
    """rule_id: boundary_precision_check / weekly_hours_at_exact_cap_vs_over."""

    def _setup_cap_10_with_8h(self, api):
        set_clock("2026-06-01T07:00:00Z")
        agency = create_agency(travel_buffer_minutes=0)
        cg = create_active_caregiver(agency["id"], max_weekly_hours=10)
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        schedule_visit(cg["id"], cl["id"], plan["id"],
                       "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z")
        return cg, cl, plan

    def test_visit_reaching_exact_cap_is_accepted(self, api):
        """PRD §3.5: "scheduling must not push the caregiver's total scheduled billable
        hours within the visit's ISO week above that caregiver's max_weekly_hours;
        exceeding the cap is rejected with ERR_WEEKLY_HOURS_EXCEEDED."

        Design: Difficulty/boundary_precision_check/weekly_hours_at_exact_cap_vs_over
        """
        cg, cl, plan = self._setup_cap_10_with_8h(api)
        # Second 2h visit brings week to exactly 10h -> 10 is not ABOVE 10 -> accepted.
        v2 = validate_success(api.create_visit({
            "caregiver_id": cg["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-02T09:00:00Z",
            "scheduled_end": "2026-06-02T11:00:00Z",
        }, SCHEDULER), expected_status=201)
        assert v2["status"] == "SCHEDULED", \
            f"visit reaching exactly the cap should be accepted, got {v2['status']}"

    def test_visit_exceeding_cap_is_rejected(self, api):
        """PRD §3.5: "exceeding the cap is rejected with ERR_WEEKLY_HOURS_EXCEEDED."

        Design: Difficulty/boundary_precision_check/weekly_hours_at_exact_cap_vs_over
        """
        cg, cl, plan = self._setup_cap_10_with_8h(api)
        validate_success(api.create_visit({
            "caregiver_id": cg["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-02T09:00:00Z",
            "scheduled_end": "2026-06-02T11:00:00Z",
        }, SCHEDULER), expected_status=201)
        # Third 1h visit reaches 11h > 10 -> rejected.
        resp = api.create_visit({
            "caregiver_id": cg["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-03T09:00:00Z",
            "scheduled_end": "2026-06-03T10:00:00Z",
        }, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_WEEKLY_HOURS_EXCEEDED.value)


class TestMatchActivateRequiresCaregiverActive:
    """rule_id: cross_entity_state_dependency / match_activate_requires_caregiver_active."""

    def test_activate_match_with_applicant_caregiver_rejected(self, api):
        """PRD §3.4: "its preconditions are evaluated in the following order. First, the
        referenced caregiver's employment_status must be ACTIVE, otherwise
        ERR_CAREGIVER_NOT_ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/match_activate_requires_caregiver_active
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        validate_success(api.transition_caregiver(
            cg["id"], {"action": "CLEAR_BACKGROUND", "target_tier": "TIER_2"}, ADMIN))
        cl = create_active_client(agency["id"])
        match = validate_success(api.create_match({
            "caregiver_id": cg["id"], "client_id": cl["id"], "is_primary": True
        }, SCHEDULER), expected_status=201)
        resp = api.transition_match(match["id"], {"action": "ACTIVATE"}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CAREGIVER_NOT_ACTIVE.value)

    def test_match_remains_proposed_after_rejected_activation(self, api):
        """PRD §3.4: "When all four hold, match_status becomes ACTIVE."
        PRD §3.4: "First, the referenced caregiver's employment_status must be ACTIVE,
        otherwise ERR_CAREGIVER_NOT_ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/match_activate_requires_caregiver_active
        """
        agency = create_agency()
        cg = create_caregiver(agency["id"])
        validate_success(api.transition_caregiver(
            cg["id"], {"action": "CLEAR_BACKGROUND", "target_tier": "TIER_2"}, ADMIN))
        cl = create_active_client(agency["id"])
        match = validate_success(api.create_match({
            "caregiver_id": cg["id"], "client_id": cl["id"], "is_primary": True
        }, SCHEDULER), expected_status=201)
        api.transition_match(match["id"], {"action": "ACTIVATE"}, SCHEDULER)
        fresh = validate_success(api.get_match(match["id"], SCHEDULER))
        assert fresh["match_status"] == "PROPOSED", \
            f"match should remain PROPOSED, got {fresh['match_status']}"


class TestVisitClockinRequiresCarePlanPublished:
    """rule_id: cross_entity_state_dependency / visit_clockin_requires_care_plan_published."""

    def _setup_draft_plan_scheduled_visit(self, api):
        agency = create_agency()
        cg = create_active_caregiver(agency["id"])
        cl = create_active_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)  # DRAFT
        create_active_match(cg["id"], cl["id"], is_primary=True)
        v = schedule_visit(cg["id"], cl["id"], plan["id"],
                           "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        return cg, v

    def test_clockin_against_draft_plan_rejected(self, api):
        """PRD §3.6: "the referenced care plan's status must be PUBLISHED (otherwise
        ERR_CARE_PLAN_NOT_PUBLISHED)".

        Design: Difficulty/cross_entity_state_dependency/visit_clockin_requires_care_plan_published
        """
        cg, v = self._setup_draft_plan_scheduled_visit(api)
        resp = api.clock_in(v["id"], {"event_at": "2026-06-01T09:00:00Z"},
                            make_caregiver_headers(cg["id"]))
        validate_error(resp, ApiErrorId.ERR_CARE_PLAN_NOT_PUBLISHED.value)

    def test_visit_stays_scheduled_after_rejected_clockin(self, api):
        """PRD §3.3: "The publish gate matters because a visit may only be clocked in
        against a plan whose status is PUBLISHED."

        Design: Difficulty/cross_entity_state_dependency/visit_clockin_requires_care_plan_published
        """
        cg, v = self._setup_draft_plan_scheduled_visit(api)
        api.clock_in(v["id"], {"event_at": "2026-06-01T09:00:00Z"},
                     make_caregiver_headers(cg["id"]))
        fresh = validate_success(api.get_visit(v["id"], SCHEDULER))
        assert fresh["status"] == "SCHEDULED", \
            f"visit should stay SCHEDULED after rejected clock-in, got {fresh['status']}"
