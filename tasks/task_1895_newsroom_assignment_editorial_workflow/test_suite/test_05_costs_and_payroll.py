"""Assignment costing: provisional and final variants, the weekly overtime
threshold, chronological allocation, and payroll rounding order."""
from test_helpers import (
    TEST_USERS,
    create_greenlit_story,
    get_success_data,
    propose_and_accept,
    propose_assignment,
    set_clock,
    setup_newsroom,
)

ND = TEST_USERS["news_director_headers"]


def _payroll(api, staff_id, week_start="2026-08-03"):
    return get_success_data(api.get_staff_payroll(
        staff_id, ND, params={"week_start": week_start}))


class TestProvisionalCost:
    def test_provisional_cost_known_inputs(self, api):
        """PRD §3.3: "A clean proposal lands in `PROPOSED` status with its
        `provisional_cost_cents` computed immediately: the planned minutes
        multiplied by the staff member's per-minute rate (`hourly_rate_cents`
        divided by 60), rounded half-up to a whole cent, ignoring overtime and
        actuals entirely."
        PRD §3.3: "`final_cost_cents` stays null until the assignment
        completes, and only `COMPLETED` assignments ever enter payroll —
        proposed, accepted, declined, cancelled, and bumped work is excluded
        from the weekly snapshot described in §3.1."

        Design: Corner/calculations/provisional_cost_known_inputs
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx)
        asg = propose_assignment(
            ctx, story_id, ctx["reporter"]["id"],
            start_at="2026-08-01T08:00:00Z", end_at="2026-08-01T09:30:00Z",
            planned_effort_minutes=90)
        # 90 minutes x 6000c/h = 90 x 100c/min = 9000c.
        assert asg["provisional_cost_cents"] == 9000
        assert asg["final_cost_cents"] is None, \
            "FINAL cost exists only after completion"


class TestFinalCostOvertime:
    def test_final_cost_overtime_split(self, api):
        """PRD §3.3: "Each assignment's actual minutes split into a regular
        portion — the smaller of its own actual minutes and the room remaining
        below the weekly regular threshold of 2,400 minutes (forty hours),
        never below zero — and an overtime portion of whatever actual minutes
        remain."
        PRD §3.3: "The assignment's `final_cost_cents` is the sum of its
        regular minutes plus its overtime minutes multiplied by 1.5, all
        multiplied by the per-minute rate, rounded half-up to a whole cent."

        Design: Corner/calculations/final_cost_overtime_split
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(
            ctx, deadline_at="2026-08-05T00:00:00Z")
        asg = propose_and_accept(
            ctx, story_id, "reporter",
            start_at="2026-08-03T08:00:00Z", end_at="2026-08-03T09:00:00Z")
        set_clock("2026-08-03T09:00:00Z")
        done = get_success_data(api.complete_assignment(
            asg["id"], {"actual_effort_minutes": 2500},
            ctx["reporter_headers"]))
        # 2400 regular + 100 overtime: (2400 + 100 x 1.5) x 100c = 255000c.
        assert done["final_cost_cents"] == 255000

        payroll = _payroll(api, ctx["reporter"]["id"])
        assert payroll["total_cents"] == 255000
        assert payroll["regular_minutes"] == 2400
        assert payroll["overtime_minutes"] == 100


class TestPayrollSnapshot:
    def test_payroll_empty_week_zero(self, api):
        """PRD §3.1: "The response reports `week_start`, the
        `assignment_count` of completed assignments in that week, the
        `regular_minutes` and `overtime_minutes` allocated chronologically
        across them, and the `total_cents` payable."
        PRD §3.3: "`final_cost_cents` stays null until the assignment
        completes, and only `COMPLETED` assignments ever enter payroll —
        proposed, accepted, declined, cancelled, and bumped work is excluded
        from the weekly snapshot described in §3.1."

        Design: Corner/calculations/payroll_empty_week_zero
        """
        ctx = setup_newsroom()
        payroll = _payroll(api, ctx["reporter"]["id"])
        assert payroll["total_cents"] == 0
        assert payroll["assignment_count"] == 0
        assert payroll["regular_minutes"] == 0
        assert payroll["overtime_minutes"] == 0

    def test_payroll_chronological_split_order(self, api):
        """PRD §3.3: "The final cost accounts for weekly overtime: consider
        every `COMPLETED` assignment of that staff member whose `completed_at`
        falls inside the same payroll week, process them in chronological
        order by `completed_at` with ties broken by `created_at` ascending,
        and keep a running total of actual minutes already allocated."
        PRD §2.10: "Weekly cost allocation processes a staff member's
        completed assignments in chronological order — by `completed_at`
        ascending, ties broken by `created_at` ascending — and weekly overtime
        applies to actual effort beyond the first 2,400 minutes (forty hours)
        allocated in that order."

        Design: Corner/calculations/payroll_chronological_split_order
        """
        ctx = setup_newsroom()
        s1 = create_greenlit_story(ctx, title="CO one",
                                   deadline_at="2026-08-05T00:00:00Z")[1]
        s2 = create_greenlit_story(ctx, title="CO two",
                                   deadline_at="2026-08-05T00:00:00Z")[1]
        a1 = propose_and_accept(ctx, s1, "reporter",
                                start_at="2026-08-03T08:00:00Z",
                                end_at="2026-08-03T09:00:00Z",
                                planned_effort_minutes=600)
        a2 = propose_and_accept(ctx, s2, "reporter",
                                start_at="2026-08-03T10:00:00Z",
                                end_at="2026-08-03T11:00:00Z",
                                planned_effort_minutes=2000)
        set_clock("2026-08-03T10:00:00Z")
        d1 = get_success_data(api.complete_assignment(
            a1["id"], {"actual_effort_minutes": 600}, ctx["reporter_headers"]))
        assert d1["final_cost_cents"] == 60000, "600 regular minutes x 100c"

        set_clock("2026-08-03T11:00:00Z")
        d2 = get_success_data(api.complete_assignment(
            a2["id"], {"actual_effort_minutes": 2000},
            ctx["reporter_headers"]))
        # Running total 600: reg = min(2000, 2400-600) = 1800, ot = 200.
        assert d2["final_cost_cents"] == 210000, \
            "overtime lands on the later completion: (1800 + 200 x 1.5) x 100c"

        payroll = _payroll(api, ctx["reporter"]["id"])
        assert payroll["total_cents"] == 270000
        assert payroll["regular_minutes"] == 2400
        assert payroll["overtime_minutes"] == 200


class TestPayrollRoundingOrder:
    def _two_45_minute_completions(self, api, ctx):
        """Two 45-minute completions at 6050c/h in the same payroll week.
        Returns (first_final, second_final)."""
        s1 = create_greenlit_story(ctx, title="Story one",
                                   deadline_at="2026-08-04T00:00:00Z")[1]
        s2 = create_greenlit_story(ctx, title="Story two",
                                   deadline_at="2026-08-04T00:00:00Z")[1]
        a1 = propose_and_accept(ctx, s1, "reporter",
                                start_at="2026-08-03T08:00:00Z",
                                end_at="2026-08-03T09:30:00Z")
        a2 = propose_and_accept(ctx, s2, "reporter",
                                start_at="2026-08-03T10:00:00Z",
                                end_at="2026-08-03T11:30:00Z")
        set_clock("2026-08-03T10:00:00Z")
        d1 = get_success_data(api.complete_assignment(
            a1["id"], {"actual_effort_minutes": 45}, ctx["reporter_headers"]))
        set_clock("2026-08-03T10:30:00Z")
        d2 = get_success_data(api.complete_assignment(
            a2["id"], {"actual_effort_minutes": 45}, ctx["reporter_headers"]))
        return d1["final_cost_cents"], d2["final_cost_cents"]

    def test_per_assignment_rounding_half_up(self, api):
        """PRD §3.3: "The assignment's `final_cost_cents` is the sum of its
        regular minutes plus its overtime minutes multiplied by 1.5, all
        multiplied by the per-minute rate, rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/payroll_per_assignment_rounding
        """
        ctx = setup_newsroom(reporter_rate=6050, reporter_max=3)
        f1, f2 = self._two_45_minute_completions(api, ctx)
        # round_half_up(45 x 6050/60, 0) = round_half_up(4537.5) = 4538.
        assert f1 == 4538
        assert f2 == 4538, "running total 90 minutes is far below 2400"

    def test_payroll_sums_per_assignment_rounded_figures(self, api):
        """PRD §2.10: "When a weekly payroll figure is reported, each
        assignment's cost is rounded to whole cents first and the rounded
        figures are then summed; minutes are never summed first and rounded
        once."

        Design: Difficulty/combinatorial_formula/payroll_per_assignment_rounding
        """
        ctx = setup_newsroom(reporter_rate=6050, reporter_max=3)
        f1, f2 = self._two_45_minute_completions(api, ctx)
        payroll = _payroll(api, ctx["reporter"]["id"])
        assert f1 == 4538 and f2 == 4538
        # 4538 + 4538 = 9076; the forbidden sum-then-round order would give
        # round_half_up(9075.0) = 9075.
        assert payroll["total_cents"] == 9076
        assert payroll["regular_minutes"] == 90
        assert payroll["overtime_minutes"] == 0
        assert payroll["assignment_count"] == 2
