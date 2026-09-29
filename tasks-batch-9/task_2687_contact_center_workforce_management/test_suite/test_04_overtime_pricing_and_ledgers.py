"""Overtime pricing tiers, and the ledger restoration a revocation owes."""

from test_helpers.assertions import (
    assert_agent_hours,
    assert_cycle_ledgers,
    assert_instant_equals,
    assert_ratio,
    assert_shift_hours,
)
from test_helpers.constants import ACTION_STATUS_REVOKED
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    generate_grid,
    lock_requirements,
    make_agent,
    make_forecast_group,
    make_labor_agreement,
    make_ot_offer,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_template,
    publish_shift,
    read_action,
    read_agent,
    read_cycle,
    read_shift,
    respond_to_action,
    revoke_action,
    set_clock,
)

SERVICE_DATES = ("2026-09-07", "2026-09-08", "2026-09-09")


def _overtime_week(api, days=3):
    """A locked week with one agent, one published shift per day and one offer per shift."""
    set_clock(api, CANONICAL_CLOCK)
    agreement = make_labor_agreement(api)
    cycle = make_planning_cycle(api, name="W37-OT")
    group = make_forecast_group(api, cycle["id"])
    generate_grid(api, group["id"], HORIZON_START)
    agent = make_agent(api, agreement["id"], hourly_rate_cents=2400)
    template = make_shift_template(
        api,
        cycle["id"],
        code="T-WK-AM",
        days_of_week=list(range(days)),
        slots_total=days,
    )
    shifts = [
        make_schedule_shift(
            api, cycle["id"], agent["id"], template["id"], service_date
        )
        for service_date in SERVICE_DATES[:days]
    ]
    lock_requirements(api, cycle["id"])
    shifts = [publish_shift(api, shift["id"]) for shift in shifts]
    offers = [
        make_ot_offer(
            api, cycle["id"], agent["id"], shift["id"], group["id"], hours=4.0
        )
        for shift in shifts
    ]
    return {
        "agreement": agreement,
        "cycle": cycle,
        "group": group,
        "agent": agent,
        "template": template,
        "shifts": shifts,
        "offers": offers,
    }


class TestOvertimeTierEvaluationOrder:
    """Each acceptance is priced against the spend as it stood before it."""

    def test_the_first_two_acceptances_price_in_the_first_tier(self, api):
        """Pre-acceptance spends of 0 and 14400 both sit below 20000, so both price at 1.50.

        "If the cycle's `ot_spend_committed_cents` before the acceptance is
        strictly below 20,000 cents — two hundred currency units — the tier
        multiplier is 1.50, the first tier."

        Design: Difficulty/combinatorial_formula/overtime_tier_pre_state_evaluation_order
        """
        world = _overtime_week(api)

        first = respond_to_action(api, world["offers"][0]["id"], world["agent"]["id"])
        second = respond_to_action(api, world["offers"][1]["id"], world["agent"]["id"])

        assert_ratio(first["ot_multiplier_applied"], 1.50, "ot_multiplier_applied")
        assert first["cost_cents"] == 14400
        assert_ratio(second["ot_multiplier_applied"], 1.50, "ot_multiplier_applied")
        assert second["cost_cents"] == 14400

    def test_the_third_acceptance_crosses_into_the_second_tier(self, api):
        """With 28800 already committed the third identical offer prices at 1.75.

        "Otherwise, if it is strictly below 60,000 cents — six hundred currency
        units — the tier multiplier is 1.75, the second tier."

        Design: Difficulty/combinatorial_formula/overtime_tier_pre_state_evaluation_order
        """
        world = _overtime_week(api)
        respond_to_action(api, world["offers"][0]["id"], world["agent"]["id"])
        respond_to_action(api, world["offers"][1]["id"], world["agent"]["id"])

        third = respond_to_action(api, world["offers"][2]["id"], world["agent"]["id"])

        assert_ratio(third["ot_multiplier_applied"], 1.75, "ot_multiplier_applied")
        assert third["cost_cents"] == 16800

    def test_earlier_acceptances_are_never_repriced(self, api):
        """The first two actions keep their frozen 1.50 price after the tier moves.

        "Both `ot_multiplier_applied` and `cost_cents` are frozen on the action at
        acceptance and are never recomputed afterwards."

        Design: Difficulty/combinatorial_formula/overtime_tier_pre_state_evaluation_order
        """
        world = _overtime_week(api)
        respond_to_action(api, world["offers"][0]["id"], world["agent"]["id"])
        respond_to_action(api, world["offers"][1]["id"], world["agent"]["id"])

        respond_to_action(api, world["offers"][2]["id"], world["agent"]["id"])

        for offer in world["offers"][:2]:
            stored = read_action(api, offer["id"])
            assert_ratio(stored["ot_multiplier_applied"], 1.50, "ot_multiplier_applied")
            assert stored["cost_cents"] == 14400

    def test_the_three_acceptances_total_45600_cents_across_the_ledgers(self, api):
        """Two first-tier prices plus one second-tier price accumulate to 45600 and 12 hours.

        "the cycle's `ot_spend_committed_cents` (the integer sum of `cost_cents`
        over the same set)"

        Design: Difficulty/combinatorial_formula/overtime_tier_pre_state_evaluation_order
        """
        world = _overtime_week(api)
        for offer in world["offers"]:
            respond_to_action(api, offer["id"], world["agent"]["id"])

        cycle = read_cycle(api, world["cycle"]["id"])

        assert_cycle_ledgers(
            cycle, ot_spend_committed_cents=45600, ot_hours_committed=12.00
        )

    def test_each_acceptance_extends_its_own_shift_and_the_agent_total(self, api):
        """The Monday shift ends four hours later and the agent's committed hours reach 34.50.

        "An accepted overtime offer then extends the shift's `end_at` by `hours`
        and recomputes the shift's `scheduled_seconds`, `ot_hours` and
        `paid_hours`, the agent's `scheduled_hours_committed`, the cycle's
        `ot_hours_committed` (the two-decimal sum of `hours` over the cycle's
        accepted overtime actions), the cycle's `ot_spend_committed_cents` (the
        integer sum of `cost_cents` over the same set) and the cycle's
        `total_scheduled_hours`."

        Design: Difficulty/combinatorial_formula/overtime_tier_pre_state_evaluation_order
        """
        world = _overtime_week(api)
        for offer in world["offers"]:
            respond_to_action(api, offer["id"], world["agent"]["id"])

        monday = read_shift(api, world["shifts"][0]["id"])

        assert_instant_equals(monday["end_at"], "2026-09-07T20:00:00Z", "end_at")
        assert_shift_hours(monday, ot_hours=4.00)
        assert_agent_hours(read_agent(api, world["agent"]["id"]), 34.50)


class TestOvertimeRevocationRestoresTheLedgers:
    """Revoking an accepted offer must give back exactly what it took."""

    def test_revocation_subtracts_the_frozen_cost_not_a_fresh_price(self, api):
        """The cycle drops from 28800 to 14400 and from eight hours to four.

        "Revoking an accepted overtime offer shortens the shift's `end_at` back by
        `hours`, subtracts **exactly** the frozen `cost_cents` from the cycle's
        `ot_spend_committed_cents` and `hours` from the cycle's
        `ot_hours_committed`, and recomputes the shift's `scheduled_seconds`,
        `ot_hours` and `paid_hours`, the agent's `scheduled_hours_committed` and
        the cycle's `total_scheduled_hours`."

        Design: Difficulty/compensating_invariant/ot_revoke_restores_cycle_ot_spend
        """
        world = _overtime_week(api, days=2)
        respond_to_action(api, world["offers"][0]["id"], world["agent"]["id"])
        respond_to_action(api, world["offers"][1]["id"], world["agent"]["id"])
        before = read_cycle(api, world["cycle"]["id"])
        assert_cycle_ledgers(
            before, ot_spend_committed_cents=28800, ot_hours_committed=8.00
        )

        revoke_action(api, world["offers"][0]["id"])

        after = read_cycle(api, world["cycle"]["id"])
        assert_cycle_ledgers(
            after, ot_spend_committed_cents=14400, ot_hours_committed=4.00
        )

    def test_the_revoked_action_keeps_its_cost_as_the_historical_record(self, api):
        """The revoked action is REVOKED yet still reports the 14400 cents it once carried.

        "Both `ot_multiplier_applied` and `cost_cents` are frozen on the action at
        acceptance and are never recomputed afterwards."

        Design: Difficulty/compensating_invariant/ot_revoke_restores_cycle_ot_spend
        """
        world = _overtime_week(api, days=2)
        respond_to_action(api, world["offers"][0]["id"], world["agent"]["id"])
        respond_to_action(api, world["offers"][1]["id"], world["agent"]["id"])

        revoked = revoke_action(api, world["offers"][0]["id"])

        assert revoked["status"] == ACTION_STATUS_REVOKED
        assert read_action(api, world["offers"][0]["id"])["cost_cents"] == 14400

    def test_revocation_rolls_back_only_its_own_shift(self, api):
        """Monday returns to a 16:00 finish while Tuesday keeps its four overtime hours.

        "Revoking an accepted overtime offer shortens the shift's `end_at` back by
        `hours`, subtracts **exactly** the frozen `cost_cents` from the cycle's
        `ot_spend_committed_cents` and `hours` from the cycle's
        `ot_hours_committed`, and recomputes the shift's `scheduled_seconds`,
        `ot_hours` and `paid_hours`, the agent's `scheduled_hours_committed` and
        the cycle's `total_scheduled_hours`."

        Design: Difficulty/compensating_invariant/ot_revoke_restores_cycle_ot_spend
        """
        world = _overtime_week(api, days=2)
        respond_to_action(api, world["offers"][0]["id"], world["agent"]["id"])
        respond_to_action(api, world["offers"][1]["id"], world["agent"]["id"])

        revoke_action(api, world["offers"][0]["id"])

        monday = read_shift(api, world["shifts"][0]["id"])
        tuesday = read_shift(api, world["shifts"][1]["id"])
        assert_instant_equals(monday["end_at"], "2026-09-07T16:00:00Z", "end_at")
        assert_shift_hours(monday, ot_hours=0.00)
        assert_instant_equals(tuesday["end_at"], "2026-09-08T20:00:00Z", "end_at")
        assert_shift_hours(tuesday, ot_hours=4.00)

    def test_revocation_restores_the_agent_and_cycle_hour_totals(self, api):
        """The agent falls back to 19 committed hours and the cycle total follows it.

        "The agent's `scheduled_hours_committed` — the sum of `paid_hours` over
        that agent's shifts whose `publication_status` is `PUBLISHED`, at two
        decimal places — and the cycle's `total_scheduled_hours` are both
        recomputed."

        Design: Difficulty/compensating_invariant/ot_revoke_restores_cycle_ot_spend
        """
        world = _overtime_week(api, days=2)
        respond_to_action(api, world["offers"][0]["id"], world["agent"]["id"])
        respond_to_action(api, world["offers"][1]["id"], world["agent"]["id"])

        revoke_action(api, world["offers"][0]["id"])

        assert_agent_hours(read_agent(api, world["agent"]["id"]), 19.00)
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]), total_scheduled_hours=19.00
        )
