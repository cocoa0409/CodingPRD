"""Abandonment gives the nurse's concurrency slot back exactly."""

import pytest

from test_helpers.assertions import assert_nurse_load


@pytest.fixture
def single_slot_nurse_holding_one_call(world):
    """A nurse capped at one live call, currently holding it."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        max_concurrent_calls=1,
    )
    call_one = world.call_through_assignment(reason_text="chest discomfort")
    return call_one


class TestAbandonRestoresThePreAssignmentLoad:
    def test_the_assignment_consumed_the_only_slot(
        self, world, single_slot_nurse_holding_one_call
    ):
        """PRD §3.4: "the winning nurse's `active_call_load` increases by one, and
        the call's `version` increases by one."

        Design: Difficulty/compensating_invariant/abandon_returns_the_nurses_active_call_load_to_its_pre_assignment_value
        """
        call_one = single_slot_nurse_holding_one_call

        assert call_one["status"] == "ASSIGNED"
        assert call_one["assigned_nurse_id"] == world.nurse_id("nurse_a")
        assert_nurse_load(
            world.nurse("nurse_a"), active=1, high_risk=0, eligibility="ON_ROTATION"
        )

    def test_abandoning_decreases_the_load_by_exactly_the_amount_assignment_added(
        self, world, single_slot_nurse_holding_one_call
    ):
        """PRD §3.3: "if the call had an assigned nurse, that nurse's
        `active_call_load` is decreased by one, exactly compensating the increase the
        assignment made".

        Design: Difficulty/compensating_invariant/abandon_returns_the_nurses_active_call_load_to_its_pre_assignment_value
        """
        call_one = single_slot_nurse_holding_one_call

        abandoned = world.abandon_call(call_one["id"])

        assert abandoned["status"] == "ABANDONED"
        assert_nurse_load(
            world.nurse("nurse_a"), active=0, high_risk=0, eligibility="ON_ROTATION"
        )

    def test_the_freed_slot_lets_a_second_call_reach_the_same_nurse(
        self, world, single_slot_nurse_holding_one_call
    ):
        """PRD §3.4: "the nurse's `active_call_load` is strictly less than their
        `max_concurrent_calls`."

        Design: Difficulty/compensating_invariant/abandon_returns_the_nurses_active_call_load_to_its_pre_assignment_value
        """
        call_one = single_slot_nurse_holding_one_call
        world.abandon_call(call_one["id"])

        call_two = world.call_through_assignment(reason_text="sore throat")

        assert call_two["status"] == "ASSIGNED"
        assert call_two["assigned_nurse_id"] == world.nurse_id("nurse_a")
        assert call_two["deferred_assignment_count"] == 0, (
            "the pool was not empty, so nothing was deferred"
        )
        assert world.nurse("nurse_a")["active_call_load"] == 1

    def test_the_abandoned_call_still_names_the_nurse_it_released(
        self, world, single_slot_nurse_holding_one_call
    ):
        """PRD §3.3: "An abandoned call is final; nothing reopens it."

        Design: Difficulty/compensating_invariant/abandon_returns_the_nurses_active_call_load_to_its_pre_assignment_value
        """
        call_one = single_slot_nurse_holding_one_call
        world.abandon_call(call_one["id"])
        world.call_through_assignment(reason_text="sore throat")

        after = world.call(call_one["id"])
        assert after["status"] == "ABANDONED"
        assert after["assigned_nurse_id"] == world.nurse_id("nurse_a"), (
            "releasing the slot does not erase the assignment history"
        )
        assert after["abandon_reason"] == (
            "Caller disconnected before triage could begin."
        )
