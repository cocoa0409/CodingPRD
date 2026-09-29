"""Two calendars with two different interval semantics on the same plan."""

from test_helpers import (
    FC,
    HR,
    ApiErrorId,
    BonusPlanScenario,
    accrual_period_payload,
    leave_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _leave_calendar_scenario() -> BonusPlanScenario:
    """One participant already carrying an unpaid leave over 2026-02-01..2026-03-31."""
    scenario = BonusPlanScenario()
    scenario.add_unit("UNIT-T", name="Unit T")
    scenario.create_plan(
        plan_name="FY26 Leave Interval Plan", discretionary_budget_pct=10.00
    )
    scenario.add_target("L3", target_bonus_pct=10.00)
    scenario.add_pool("UNIT-T")
    scenario.add_participant(
        "lea",
        "UNIT-T",
        employee_code="E301",
        full_name="Lea Ves",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2025-01-01",
    )
    scenario.add_leave("lea", "2026-02-01", "2026-03-31", note="first unpaid leave")
    return scenario


class TestHalfOpenLeaveIntervals:
    def test_a_leave_starting_the_day_after_another_ends_is_adjacent_and_allowed(
        self, api
    ):
        """PRD §3.2: "A new leave interval, running from `effective_date` through the day
        after `leave_end_date` exclusively, must not overlap any existing non-superseded
        leave interval of the same participant; because the interval is half-open, a leave
        that starts exactly on the day after another's `leave_end_date` is adjacent, not
        overlapping, and is allowed, while a genuine overlap is
        `ERR_LEAVE_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/adjacent_leave_allowed_but_overlapping_leave_rejected_half_open
        """
        scenario = _leave_calendar_scenario()

        adjacent = validate_success(
            api.create_eligibility_event(
                leave_event_payload(
                    scenario.participant_id("lea"),
                    "2026-04-01",
                    "2026-04-30",
                    False,
                    note="adjacent leave, starts the day after the first ends",
                ),
                HR,
            ),
            expected_status=201,
        )

        assert adjacent["effective_date"] == "2026-04-01"
        assert adjacent["leave_end_date"] == "2026-04-30"
        assert adjacent["superseded"] is False
        assert scenario.events[0]["leave_end_date"] == "2026-03-31"

    def test_a_leave_sharing_a_single_day_with_another_is_refused(self, api):
        """PRD §2.10: "**Temporal integrity**, in this order: an event's `effective_date`
        inside the plan period (`ERR_EVENT_DATE_OUTSIDE_PLAN_PERIOD`), an event not
        preceding the hire date and a leave not ending before it starts
        (`ERR_EVENT_DATE_BEFORE_HIRE`), leave intervals not overlapping
        (`ERR_LEAVE_INTERVAL_OVERLAP`), no event after a live termination
        (`ERR_PARTICIPANT_ALREADY_TERMINATED`), accrual periods not overlapping
        (`ERR_ACCRUAL_PERIOD_OVERLAP`), accrual periods tiling contiguously and earlier
        periods being resolved before a later one posts (`ERR_ACCRUAL_PERIOD_GAP`),
        accrual reversal being last-in-first-out (`ERR_ACCRUAL_REVERSAL_OUT_OF_ORDER`),
        and the payment date having been reached (`ERR_PAYMENT_DATE_NOT_REACHED`)."

        Design: Difficulty/resource_temporal_overlap/adjacent_leave_allowed_but_overlapping_leave_rejected_half_open
        """
        scenario = _leave_calendar_scenario()
        scenario.add_leave(
            "lea",
            "2026-04-01",
            "2026-04-30",
            note="adjacent leave, starts the day after the first ends",
        )

        response = api.create_eligibility_event(
            leave_event_payload(
                scenario.participant_id("lea"),
                "2026-04-30",
                "2026-05-10",
                False,
                note="overlaps the adjacent leave by exactly one day",
            ),
            HR,
        )
        validate_error(
            response, ApiErrorId.ERR_LEAVE_INTERVAL_OVERLAP.value, expected_status=409
        )

        rows, meta = validate_paginated(
            api.list_eligibility_events(
                HR,
                params={
                    "participant_id": scenario.participant_id("lea"),
                    "event_type": "LEAVE",
                },
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


def _accrual_calendar_scenario() -> BonusPlanScenario:
    """A plan whose first half-year accrual period is created and already posted."""
    scenario = BonusPlanScenario()
    scenario.add_unit("UNIT-S", name="Unit S")
    scenario.create_plan(
        plan_name="FY26 Accrual Tiling Plan", discretionary_budget_pct=10.00
    )
    scenario.add_target("L3", target_bonus_pct=10.00)
    scenario.add_pool("UNIT-S")
    scenario.add_participant(
        "cal",
        "UNIT-S",
        employee_code="E302",
        full_name="Cal Endar",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2025-01-01",
    )
    period = scenario.open_accrual_period("2026-01-01", "2026-06-30", 60.00)
    scenario.post_accrual_period(period["id"], posting_note="H1 provisional accrual")
    return scenario


class TestClosedInclusiveAccrualTiling:
    def test_a_one_day_hole_after_the_posted_period_is_refused_as_a_gap(self, api):
        """PRD §3.8: "A new period must not overlap any existing non-`REVERSED` period of
        the plan (`ERR_ACCRUAL_PERIOD_OVERLAP`), and its `period_start` must equal the
        plan's `plan_period_start` if it is the plan's first period and otherwise the day
        after the latest existing `period_end` — unlike leave intervals, accrual periods
        may not be adjacent-with-a-gap, and a one-day hole is refused with
        `ERR_ACCRUAL_PERIOD_GAP`."

        Design: Difficulty/resource_temporal_overlap/accrual_periods_must_tile_closed_inclusive_with_no_gap_and_no_overlap
        """
        scenario = _accrual_calendar_scenario()

        response = api.create_accrual_period(
            accrual_period_payload(scenario.plan_id, "2026-07-02", "2026-12-31", 60.00),
            FC,
        )
        validate_error(
            response, ApiErrorId.ERR_ACCRUAL_PERIOD_GAP.value, expected_status=422
        )

    def test_reusing_the_last_inclusive_day_is_refused_as_an_overlap(self, api):
        """PRD §3.8: "Accrual periods are closed-inclusive intervals: an **accrual
        period** carries `plan_id`, `period_start` (its first day) and `period_end` (its
        last day, inclusive), plus `forecast_company_achievement_pct`, the forecast
        company achievement between 0 and 200 with two decimals that stands in for the
        audited figure."

        Design: Difficulty/resource_temporal_overlap/accrual_periods_must_tile_closed_inclusive_with_no_gap_and_no_overlap
        """
        scenario = _accrual_calendar_scenario()

        response = api.create_accrual_period(
            accrual_period_payload(scenario.plan_id, "2026-06-30", "2026-12-31", 60.00),
            FC,
        )
        validate_error(
            response, ApiErrorId.ERR_ACCRUAL_PERIOD_OVERLAP.value, expected_status=409
        )

    def test_only_the_very_next_day_tiles_the_calendar_and_is_accepted(self, api):
        """PRD §3.8: "The periods must tile the plan year exactly."

        Design: Difficulty/resource_temporal_overlap/accrual_periods_must_tile_closed_inclusive_with_no_gap_and_no_overlap
        """
        scenario = _accrual_calendar_scenario()

        second = validate_success(
            api.create_accrual_period(
                accrual_period_payload(
                    scenario.plan_id, "2026-07-01", "2026-12-31", 60.00
                ),
                FC,
            ),
            expected_status=201,
        )
        assert second["status"] == "OPEN"
        assert second["period_start"] == "2026-07-01"
        assert second["period_end"] == "2026-12-31"

        first = validate_success(
            api.get_accrual_period(scenario.accrual_periods[0]["id"], FC)
        )
        assert first["status"] == "POSTED"
        assert first["period_end"] == "2026-06-30"

        rows, meta = validate_paginated(
            api.list_accrual_periods(FC, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
