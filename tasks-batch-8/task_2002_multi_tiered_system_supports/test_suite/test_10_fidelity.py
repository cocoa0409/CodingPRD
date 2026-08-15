"""Delivery fidelity: per-week truncation, then average truncation (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    get_plan,
    record_session,
    setup_active_plan,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestFidelityRoundingOrder:
    def test_fidelity_rounds_per_week_then_averages(self, api):
        """PRD §3.6: "For each week, a weekly fidelity figure is computed as the
        count of that week's sessions whose `outcome` is `DELIVERED`, multiplied
        by one hundred, divided by the number of sessions scheduled that week,
        and truncated down to a whole percent."
        PRD §3.6: "The plan's `fidelity_pct` is then the sum of those weekly
        figures divided by the number of weeks that had at least one scheduled
        session, again truncated down to a whole percent."
        PRD §3.6: "This per-week-then-average order loses fractions differently
        than a single division of total delivered sessions by total scheduled
        sessions, and the latter computation must not be substituted."

        Week of 2026-08-10: 4 DELIVERED of 5 -> 80. Week of 2026-08-17: 3
        DELIVERED of 3 -> 100. Plan fidelity is floor((80 + 100) / 2) = 90; the
        substituted single division would give floor(7 * 100 / 8) = 87.

        Design: Difficulty/combinatorial_formula/fidelity_pct_per_week_then_average
        """
        ctx = setup_active_plan(api, tier="TIER_2", session_minutes=30,
                                sessions_per_week=3)
        for date, outcome in [
            ("2026-08-10", "DELIVERED"), ("2026-08-11", "DELIVERED"),
            ("2026-08-12", "DELIVERED"), ("2026-08-13", "DELIVERED"),
            ("2026-08-14", "STUDENT_ABSENT"),
            ("2026-08-17", "DELIVERED"), ("2026-08-18", "DELIVERED"),
            ("2026-08-19", "DELIVERED"),
        ]:
            record_session(api, ctx, date, minutes=30, outcome=outcome)

        plan = get_plan(api, ctx["district"]["id"], ctx["school"]["id"],
                        ctx["student"]["id"], ctx["plan"]["id"])
        assert plan["fidelity_pct"] == 90, (
            "per-week floor (80, 100) then average floor -> 90, not 87")

    def test_fidelity_truncates_within_a_single_week(self, api):
        """PRD §3.6: "For each week, a weekly fidelity figure is computed as the
        count of that week's sessions whose `outcome` is `DELIVERED`, multiplied
        by one hundred, divided by the number of sessions scheduled that week,
        and truncated down to a whole percent."

        One week with 2 DELIVERED of 3 truncates to 66, not 67.

        Design: Difficulty/combinatorial_formula/fidelity_pct_per_week_then_average
        """
        ctx = setup_active_plan(api, tier="TIER_2", session_minutes=30,
                                sessions_per_week=3)
        for date, outcome in [
            ("2026-08-10", "DELIVERED"), ("2026-08-11", "DELIVERED"),
            ("2026-08-12", "STUDENT_ABSENT"),
        ]:
            record_session(api, ctx, date, minutes=30, outcome=outcome)

        plan = get_plan(api, ctx["district"]["id"], ctx["school"]["id"],
                        ctx["student"]["id"], ctx["plan"]["id"])
        assert plan["fidelity_pct"] == 66, "floor(2 * 100 / 3) = 66"
