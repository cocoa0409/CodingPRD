"""The labour-cost rate ladder: planned versus actual basis, and the overtime knee."""

from test_helpers import (
    TEST_USERS,
    confirm_assignment,
    confirm_program,
    create_staff_member,
    deliver,
    lock_design,
    mark_ready,
    propose_assignment,
    setup_locked_program_with_segment,
    setup_program_with_contracted_element,
    staff_check_in,
    start_execution,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]

LONG_SHIFT = ("2026-09-11T08:00:00Z", "2026-09-11T18:00:00Z")


def _coordinator_on_a_ten_hour_shift():
    """Contracted element plus one CONFIRMED ten-hour coordinator shift on it."""
    ctx = setup_program_with_contracted_element(
        element_overrides={"title": "Waterfront Welcome Reception"}
    )
    staff = create_staff_member(full_name="Dana Okafor", pay_rate_cents_per_hour=4_500)
    assignment = propose_assignment(
        staff["id"],
        ctx["program"]["id"],
        target_type="ELEMENT",
        element_id=ctx["element"]["id"],
        role_type="COORDINATOR",
        starts_at=LONG_SHIFT[0],
        ends_at=LONG_SHIFT[1],
    )
    lock_design(ctx["program"]["id"])
    ctx["staff"] = staff
    ctx["assignment"] = confirm_assignment(assignment["id"])
    return ctx


class TestPlannedVersusActualLaborCost:
    def test_planned_variant_prices_the_whole_scheduled_window(self, api):
        """PRD §3.6: "The **planned** variant, run at confirmation, uses the scheduled
        window: the whole minutes from the assignment's `starts_at` to its `ends_at`,
        independent of any check-in."

        Design: Difficulty/dual_variant_calc/staff_labor_cost_planned_vs_actual_divergence
        """
        ctx = _coordinator_on_a_ten_hour_shift()

        assert ctx["assignment"]["status"] == "CONFIRMED"
        assert ctx["assignment"]["planned_labor_cost_cents"] == 49_500
        assert ctx["assignment"]["actual_labor_cost_cents"] == 0
        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))
        assert staff["confirmed_minutes_total"] == 600

    def test_actual_variant_prices_only_the_worked_window(self, api):
        """PRD §3.6: "The **actual** variant, run when an assignment reaches `COMPLETED`,
        uses the worked window: the whole minutes from `check_in_at` to `completed_at`;
        for an assignment that reached `NO_SHOW` without ever checking in, the minute
        basis is zero."

        Design: Difficulty/dual_variant_calc/staff_labor_cost_planned_vs_actual_divergence
        """
        ctx = _coordinator_on_a_ten_hour_shift()
        confirm_program(ctx["program"]["id"])
        start_execution(ctx["program"]["id"])
        mark_ready(ctx["element"]["id"])
        staff_check_in(
            ctx["assignment"]["id"], ctx["staff"]["id"], clock="2026-09-11T12:00:00Z"
        )
        deliver(ctx["element"]["id"], 40, clock="2026-09-11T13:30:00Z")

        assignment = validate_success(
            api.get_staff_assignment(ctx["assignment"]["id"], PD)
        )
        assert assignment["status"] == "COMPLETED"
        assert assignment["check_in_at"].startswith("2026-09-11T12:00:00")
        assert assignment["completed_at"].startswith("2026-09-11T13:30:00")
        assert assignment["actual_labor_cost_cents"] == 18_000

    def test_the_two_variants_diverge_on_one_and_the_same_shift(self, api):
        """PRD §3.6: "One consequence is worth flagging to whoever writes the tests: a
        coordinator who checks in late and whose element finishes early bills fewer worked
        minutes than planned, yet the 240-minute call-out floor can make the actual figure
        identical to the planned figure for short shifts."

        Design: Difficulty/dual_variant_calc/staff_labor_cost_planned_vs_actual_divergence
        """
        ctx = _coordinator_on_a_ten_hour_shift()
        confirm_program(ctx["program"]["id"])
        start_execution(ctx["program"]["id"])
        mark_ready(ctx["element"]["id"])
        staff_check_in(
            ctx["assignment"]["id"], ctx["staff"]["id"], clock="2026-09-11T12:00:00Z"
        )
        deliver(ctx["element"]["id"], 40, clock="2026-09-11T13:30:00Z")

        assignment = validate_success(
            api.get_staff_assignment(ctx["assignment"]["id"], PD)
        )
        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))
        program = validate_success(api.get_program(ctx["program"]["id"], PD))

        assert assignment["planned_labor_cost_cents"] == 49_500
        assert assignment["actual_labor_cost_cents"] == 18_000
        # Completion neither returns nor re-reserves the member's confirmed minutes.
        assert staff["confirmed_minutes_total"] == 600
        assert program["staffing_gap_count"] == 0
        assert program["execution_status"] == "COMPLETED"


class TestOvertimeThresholdInteraction:
    GREETER = {
        "role_type": "GREETER",
        "pay_rate_cents_per_hour": 3_600,
        "min_rest_minutes": 600,
        "max_daily_minutes": 720,
    }

    def _two_greeters_either_side_of_the_threshold(self):
        ctx = setup_locked_program_with_segment(
            program_overrides={
                "client_name": "Northwind Insurance",
                "group_name": "Agent Summit",
                "guaranteed_count": 80,
                "markup_pct": 0.20,
            }
        )
        staff_a = create_staff_member(full_name="Ana Ruiz", **self.GREETER)
        staff_b = create_staff_member(full_name="Bo Lindqvist", **self.GREETER)
        proposals = {}
        for key, staff, ends_at in (
            ("a", staff_a, "2026-09-11T17:00:00Z"),
            ("b", staff_b, "2026-09-11T17:01:00Z"),
        ):
            proposals[key] = propose_assignment(
                staff["id"],
                ctx["program"]["id"],
                target_type="SEGMENT",
                segment_id=ctx["segment"]["id"],
                role_type="GREETER",
                starts_at="2026-09-11T09:00:00Z",
                ends_at=ends_at,
            )
        ctx.update(
            {
                "staff_a": staff_a,
                "staff_b": staff_b,
                "proposal_a": proposals["a"],
                "proposal_b": proposals["b"],
            }
        )
        return ctx

    def test_a_shift_of_exactly_the_threshold_carries_no_overtime_leg(self, api):
        """PRD §3.6: "The regular leg is the smaller of the billable minutes and the
        eight-hour overtime threshold of 480 minutes; the overtime leg is whatever
        billable minutes exceed 480, and zero when none do."

        Design: Difficulty/combinatorial_formula/labor_cost_three_input_interaction_at_ot_threshold
        """
        ctx = self._two_greeters_either_side_of_the_threshold()

        confirmed = validate_success(
            api.confirm_staff_assignment(ctx["proposal_a"]["id"], PD)
        )

        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["planned_labor_cost_cents"] == 28_800
        staff = validate_success(api.get_staff_member(ctx["staff_a"]["id"], PD))
        assert staff["confirmed_minutes_total"] == 480

    def test_the_first_minute_past_the_threshold_costs_the_overtime_multiplier(self, api):
        """PRD §3.6: "The overtime leg's cents figure is the overtime minutes divided by
        60, multiplied by `pay_rate_cents_per_hour`, multiplied again by the overtime
        multiplier of 1.5, and rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/labor_cost_three_input_interaction_at_ot_threshold
        """
        ctx = self._two_greeters_either_side_of_the_threshold()

        confirmed_a = validate_success(
            api.confirm_staff_assignment(ctx["proposal_a"]["id"], PD)
        )
        confirmed_b = validate_success(
            api.confirm_staff_assignment(ctx["proposal_b"]["id"], PD)
        )

        assert confirmed_a["planned_labor_cost_cents"] == 28_800
        assert confirmed_b["planned_labor_cost_cents"] == 28_890
        assert (
            confirmed_b["planned_labor_cost_cents"]
            - confirmed_a["planned_labor_cost_cents"]
            == 90
        )

    def test_neither_shift_reaches_the_daily_ceiling(self, api):
        """PRD §3.6: "Add up the scheduled minutes of the member's assignments in
        `CONFIRMED`, `CHECKED_IN` or `COMPLETED` whose `starts_at` falls on the same UTC
        calendar day as the candidate's `starts_at`, add the candidate's own minutes, and
        require the result to be at most the member's `max_daily_minutes`."

        Design: Difficulty/combinatorial_formula/labor_cost_three_input_interaction_at_ot_threshold
        """
        ctx = self._two_greeters_either_side_of_the_threshold()

        response_a = api.confirm_staff_assignment(ctx["proposal_a"]["id"], PD)
        response_b = api.confirm_staff_assignment(ctx["proposal_b"]["id"], PD)

        assert response_a.status_code == 200
        assert response_b.status_code == 200
        staff_a = validate_success(api.get_staff_member(ctx["staff_a"]["id"], PD))
        staff_b = validate_success(api.get_staff_member(ctx["staff_b"]["id"], PD))
        assert staff_a["confirmed_minutes_total"] == 480
        assert staff_b["confirmed_minutes_total"] == 481
        assert staff_a["max_daily_minutes"] == 720
        assert staff_b["max_daily_minutes"] == 720
