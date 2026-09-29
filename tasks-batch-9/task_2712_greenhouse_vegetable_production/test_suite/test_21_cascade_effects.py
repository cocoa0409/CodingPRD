"""Multi-hop cascades: a drainage reading that locks irrigation and then flags the
crop, and a crop-cycle abort that cancels labor and repays the compartment budget.

Each hop in these chains is a real mutation of a real row, and the later hops are
caused by the earlier hops rather than by the original request.
"""

import pytest

from test_helpers import (
    create_drainage_reading,
    create_fertigation_batch,
    create_hive_placement,
    create_labor_task,
    create_worker,
    read_batch,
    read_crop_cycle,
    read_labor_task,
    read_worker,
    read_zone,
    setup_transplanted_cycle,
    transition_crop_cycle,
    transition_fertigation_batch,
)

BREACHING_DRAIN_EC_MS = 6.2


def _zone_with_two_drain_alarms():
    """A TRANSPLANTED cycle, three DELIVERED batches and two batches already alarmed.

    Every batch is mixed and delivered before any reading is filed, so no posture gate
    can interfere with the setup. Two readings at an out-of-reuse-range conductivity
    leave the compartment's drain_alarm_count at 2.
    """
    state = setup_transplanted_cycle()
    zone_id = state["zone"]["id"]
    cycle_id = state["cycle"]["id"]

    batches = []
    for _ in range(3):
        batch = create_fertigation_batch(zone_id, cycle_id)
        batches.append(
            transition_fertigation_batch(
                batch["id"], "DELIVERED", delivered_volume_liters=12000
            )
        )

    create_drainage_reading(
        batches[0]["id"],
        drain_volume_liters=3600.0,
        drain_ec_ms=BREACHING_DRAIN_EC_MS,
        reading_at="2026-08-06T12:00:00Z",
    )
    create_drainage_reading(
        batches[1]["id"],
        drain_volume_liters=3600.0,
        drain_ec_ms=BREACHING_DRAIN_EC_MS,
        reading_at="2026-08-06T13:00:00Z",
    )
    state["batches"] = batches
    return state


def _file_third_breaching_reading(state):
    return create_drainage_reading(
        state["batches"][2]["id"],
        drain_volume_liters=3600.0,
        drain_ec_ms=BREACHING_DRAIN_EC_MS,
        reading_at="2026-08-06T14:00:00Z",
    )


class TestDrainageCascade:
    """One drainage reading walks alarm counter, irrigation posture and crop flag."""

    def test_two_alarmed_batches_take_the_irrigation_posture_only_to_watch(self, api):
        """PRD §3.5: "Its second hop re-derives `irrigation_posture`, taking the compartment to `WATCH` when `drain_alarm_count` reaches 2 and to `LOCKED` when it reaches 3."

        Design: Difficulty/transitive_cascade/drainage_reading_cascade_locks_irrigation_then_flags_nutrient_stress
        """
        state = _zone_with_two_drain_alarms()
        zone = read_zone(state["zone"]["id"])

        assert zone["drain_alarm_count"] == 2, (
            f"two alarmed batches raise drain_alarm_count to 2, got {zone['drain_alarm_count']}"
        )
        assert zone["irrigation_posture"] == "WATCH", (
            f"a drain_alarm_count of 2 reads WATCH, got {zone['irrigation_posture']}"
        )

    def test_third_alarm_locks_irrigation_and_flags_nutrient_stress_on_the_cycle(
        self, api
    ):
        """PRD §3.5: "Its third hop, caused by the `LOCKED` posture rather than by the reading, sets `nutrient_stress_flag` to true on every crop cycle in that compartment whose status is `TRANSPLANTED`, `PRODUCTION`, or `TERMINATION_SCHEDULED`."

        Design: Difficulty/transitive_cascade/drainage_reading_cascade_locks_irrigation_then_flags_nutrient_stress
        """
        state = _zone_with_two_drain_alarms()
        cycle_id = state["cycle"]["id"]

        before = read_crop_cycle(cycle_id)
        assert before["nutrient_stress_flag"] is False, (
            "a WATCH posture must not flag the crop, got "
            f"nutrient_stress_flag={before['nutrient_stress_flag']}"
        )

        _file_third_breaching_reading(state)

        zone = read_zone(state["zone"]["id"])
        assert zone["drain_alarm_count"] == 3, (
            f"the third alarmed batch raises drain_alarm_count to 3, got {zone['drain_alarm_count']}"
        )
        assert zone["irrigation_posture"] == "LOCKED", (
            f"a drain_alarm_count of 3 reads LOCKED, got {zone['irrigation_posture']}"
        )

        after = read_crop_cycle(cycle_id)
        assert after["nutrient_stress_flag"] is True, (
            "the LOCKED posture must flag the TRANSPLANTED cycle, got "
            f"nutrient_stress_flag={after['nutrient_stress_flag']}"
        )

    def test_the_first_hop_latches_the_batch_alarm_and_counts_it_exactly_once(self, api):
        """PRD §3.5: "If any of the three holds and the batch's `drain_alarm` was still false, `drain_alarm` latches to true and the compartment's `drain_alarm_count` increments by exactly one."

        Design: Difficulty/transitive_cascade/drainage_reading_cascade_locks_irrigation_then_flags_nutrient_stress
        """
        state = setup_transplanted_cycle()
        zone_id = state["zone"]["id"]
        batch = create_fertigation_batch(zone_id, state["cycle"]["id"])
        batch = transition_fertigation_batch(
            batch["id"], "DELIVERED", delivered_volume_liters=12000
        )

        assert batch["drain_alarm"] is False, (
            f"a delivered batch starts unalarmed, got drain_alarm={batch['drain_alarm']}"
        )
        assert read_zone(zone_id)["drain_alarm_count"] == 0

        create_drainage_reading(
            batch["id"],
            drain_volume_liters=3600.0,
            drain_ec_ms=BREACHING_DRAIN_EC_MS,
            reading_at="2026-08-06T12:00:00Z",
        )
        after_first = read_batch(batch["id"])
        assert after_first["drain_alarm"] is True, (
            "a conductivity breach latches the batch alarm, got "
            f"drain_alarm={after_first['drain_alarm']}"
        )
        assert read_zone(zone_id)["drain_alarm_count"] == 1, (
            "the latch raises the compartment counter by exactly one, got "
            f"{read_zone(zone_id)['drain_alarm_count']}"
        )

        create_drainage_reading(
            batch["id"],
            drain_volume_liters=100.0,
            drain_ec_ms=BREACHING_DRAIN_EC_MS,
            reading_at="2026-08-06T15:00:00Z",
        )
        assert read_batch(batch["id"])["drain_alarm"] is True
        assert read_zone(zone_id)["drain_alarm_count"] == 1, (
            "an already-alarmed batch never raises the counter a second time, got "
            f"{read_zone(zone_id)['drain_alarm_count']}"
        )

    def test_an_accepted_reading_posts_its_own_bookkeeping_before_any_hop(self, api):
        """PRD §3.5: "An accepted reading increments `drain_reading_count` by one, adds `drain_volume_liters` to `cumulative_drain_volume_liters`, records `drain_ec_ms` as `last_drain_ec_ms`, and recomputes `drain_fraction_pct` as one hundred multiplied by `cumulative_drain_volume_liters`, divided by `delivered_volume_liters`, rounded half up to two decimal places."

        Design: Difficulty/transitive_cascade/drainage_reading_cascade_locks_irrigation_then_flags_nutrient_stress
        """
        state = setup_transplanted_cycle()
        batch = create_fertigation_batch(state["zone"]["id"], state["cycle"]["id"])
        batch = transition_fertigation_batch(
            batch["id"], "DELIVERED", delivered_volume_liters=12000
        )

        reading = create_drainage_reading(
            batch["id"],
            drain_volume_liters=3600.0,
            drain_ec_ms=BREACHING_DRAIN_EC_MS,
            reading_at="2026-08-06T12:00:00Z",
        )
        for row in (reading, read_batch(batch["id"])):
            assert row["drain_reading_count"] == 1, (
                f"one accepted reading counts one, got {row['drain_reading_count']}"
            )
            assert row["cumulative_drain_volume_liters"] == pytest.approx(
                3600.00, abs=0.01
            ), (
                "cumulative_drain_volume_liters accumulates the reading, got "
                f"{row['cumulative_drain_volume_liters']}"
            )
            assert row["last_drain_ec_ms"] == pytest.approx(
                BREACHING_DRAIN_EC_MS, abs=0.01
            ), f"last_drain_ec_ms records the reading, got {row['last_drain_ec_ms']}"
            assert row["drain_fraction_pct"] == pytest.approx(30.00, abs=0.01), (
                "3600 of 12000 delivered litres is a 30.00 percent drain fraction, got "
                f"{row['drain_fraction_pct']}"
            )


def _cycle_with_scheduled_task_and_hives():
    """A TRANSPLANTED cycle carrying one SCHEDULED harvest task and four placed hives."""
    state = setup_transplanted_cycle()
    worker = create_worker()
    task = create_labor_task(
        state["zone"]["id"], state["cycle"]["id"], worker["id"]
    )
    state["worker"] = worker
    state["task"] = task
    create_hive_placement(state["cycle"]["id"], 4, "2026-08-06T09:00:00Z")
    return state


class TestCropCycleAbortCascade:
    """Aborting a cycle cancels its labor, repays the compartment and frees the hives."""

    def test_the_first_hop_cancels_every_open_task_with_the_declared_reason(self, api):
        """PRD §3.3: "The first hop transitions every labor task on the cycle whose status is `SCHEDULED` or `IN_PROGRESS` to `CANCELLED` with `cancel_reason` set to the literal `CROP_CYCLE_ABORTED`."

        Design: Difficulty/transitive_cascade/crop_cycle_abort_cascade_cancels_task_then_repays_zone_budget
        """
        state = _cycle_with_scheduled_task_and_hives()
        assert state["task"]["status"] == "SCHEDULED"

        aborted = transition_crop_cycle(state["cycle"]["id"], "ABORTED")
        assert aborted["status"] == "ABORTED", (
            f"the cycle reaches ABORTED, got {aborted['status']}"
        )

        task = read_labor_task(state["task"]["id"])
        assert task["status"] == "CANCELLED", (
            f"the open task is cancelled by the abort, got {task['status']}"
        )
        assert task["cancel_reason"] == "CROP_CYCLE_ABORTED", (
            "the cancellation carries the literal reason, got "
            f"{task['cancel_reason']!r}"
        )

    def test_the_second_hop_repays_the_compartment_budget_and_the_worker_hours(self, api):
        """PRD §3.3: "The second hop is caused by those cancellations rather than by the abort itself: each cancelled task removes its own `planned_cost_usd` from the compartment's `labor_budget_committed_usd`, restores exactly the same amount to `labor_budget_remaining_usd`, and subtracts its `planned_hours` from the assigned worker's `committed_hours`."

        Design: Difficulty/transitive_cascade/crop_cycle_abort_cascade_cancels_task_then_repays_zone_budget
        """
        state = _cycle_with_scheduled_task_and_hives()
        zone_id = state["zone"]["id"]
        planned_cost = state["task"]["planned_cost_usd"]
        planned_hours = state["task"]["planned_hours"]

        committed_zone = read_zone(zone_id)
        assert committed_zone["labor_budget_committed_usd"] == pytest.approx(
            planned_cost, abs=0.01
        ), (
            "scheduling commits the planned cost, got "
            f"{committed_zone['labor_budget_committed_usd']}"
        )
        assert read_worker(state["worker"]["id"])["committed_hours"] == pytest.approx(
            planned_hours, abs=0.01
        )

        transition_crop_cycle(state["cycle"]["id"], "ABORTED")

        released_zone = read_zone(zone_id)
        assert released_zone["labor_budget_committed_usd"] == pytest.approx(
            0.00, abs=0.01
        ), (
            "the cancelled task's cost leaves the committed half, got "
            f"{released_zone['labor_budget_committed_usd']}"
        )
        assert released_zone["labor_budget_remaining_usd"] == pytest.approx(
            committed_zone["labor_budget_remaining_usd"] + planned_cost, abs=0.01
        ), (
            "exactly the same amount returns to the remaining half, got "
            f"{released_zone['labor_budget_remaining_usd']}"
        )
        assert read_worker(state["worker"]["id"])["committed_hours"] == pytest.approx(
            0.00, abs=0.01
        ), (
            "the task's planned hours leave the worker, got "
            f"{read_worker(state['worker']['id'])['committed_hours']}"
        )

    def test_the_abort_frees_the_hives_and_re_derives_the_compartment(self, api):
        """PRD §3.3: "The abort then sets the cycle's `hive_count_placed` to 0, decrementing the compartment's `hive_slots_used`, re-derives the compartment's occupancy `status`, and increments the compartment's `version` by one."

        Design: Difficulty/transitive_cascade/crop_cycle_abort_cascade_cancels_task_then_repays_zone_budget
        """
        state = _cycle_with_scheduled_task_and_hives()
        zone_id = state["zone"]["id"]

        before = read_zone(zone_id)
        assert before["hive_slots_used"] == 4, (
            f"four placed hives occupy four slots, got {before['hive_slots_used']}"
        )
        assert before["status"] == "PLANTED"

        aborted = transition_crop_cycle(state["cycle"]["id"], "ABORTED")
        assert aborted["hive_count_placed"] == 0, (
            f"the abort releases the cycle's hives, got {aborted['hive_count_placed']}"
        )

        after = read_zone(zone_id)
        assert after["hive_slots_used"] == 0, (
            f"the released hives free their slots, got {after['hive_slots_used']}"
        )
        assert after["status"] == "IDLE", (
            "a compartment whose only cycle has aborted re-derives to IDLE, got "
            f"{after['status']}"
        )
        assert after["version"] > before["version"], (
            "the compartment version advances on the abort, got "
            f"{after['version']} from {before['version']}"
        )
