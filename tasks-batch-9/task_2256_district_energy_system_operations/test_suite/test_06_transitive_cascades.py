"""Cascades that travel two and three entities deep from a single write."""

from test_helpers import (
    FIELD_TECHNICIAN,
    FIELD_TECHNICIAN_ALT,
    NETWORK_ENGINEER,
    TECH_2,
    api_client,
    assert_loop_state,
    assert_plan_metrics,
    assert_segment_condition,
    backfill_work_order,
    begin_excavation,
    begin_repair,
    campus_dispatch_stack,
    complete_work_order,
    create_work_order,
    decide_permit,
    get_success_data,
    industrial_leak_stack,
    plan_orders,
    read_asset,
    read_loop,
    read_plan,
    read_work_order,
    set_clock,
    set_fuel_contract_status,
    submit_permit,
)


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


class TestFuelSuspensionCascade:
    """Suspending a supply contract reaches the asset, the plan and the loop."""

    def test_suspension_derates_only_the_assets_on_that_contract(self):
        """The cogeneration unit derates; the store and the other boilers do not.

        PRD: "`ACTIVE → SUSPENDED` sets the contract's `status` to `SUSPENDED`;
        cascades **every** production asset whose `fuel_contract_id` names this
        contract and whose `availability_state` is `AVAILABLE` to `DERATED`".

        Design: Difficulty/transitive_cascade/fuel_suspension_derates_asset_reverts_plan_constrains_loop
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")

        suspended = set_fuel_contract_status(
            stack["gas_contract"]["id"], "SUSPENDED", reason="supplier force majeure"
        )

        assert suspended["status"] == "SUSPENDED"
        assert read_asset(stack["chp"]["id"])["availability_state"] == "DERATED"
        assert read_asset(stack["storage"]["id"])["availability_state"] == "AVAILABLE"
        assert read_asset(stack["biomass_boiler"]["id"])["availability_state"] == "AVAILABLE"
        assert read_asset(stack["oil_boiler"]["id"])["availability_state"] == "AVAILABLE"

    def test_suspension_reverts_the_approved_plan_and_clears_its_reviewer(self):
        """An approval earned on withdrawn fuel is not allowed to stand.

        PRD: "When suspending a fuel supply contract cascades at least one asset
        referenced by this plan's dispatch orders to `DERATED` or `OUTAGE`, the
        plan is reverted from `APPROVED` to `DRAFT`, its `reviewed_by_user_id` is
        cleared to null, its `version` is incremented by 1, and the loop's
        `posture` is cascaded from `NORMAL` to `CONSTRAINED`."

        Design: Difficulty/transitive_cascade/fuel_suspension_derates_asset_reverts_plan_constrains_loop
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")

        set_fuel_contract_status(
            stack["gas_contract"]["id"], "SUSPENDED", reason="supplier force majeure"
        )

        assert_plan_metrics(
            read_plan(stack["plan"]["id"]), plan_state="DRAFT", reviewed_by_user_id=None
        )

    def test_suspension_carries_the_loop_into_a_constrained_posture(self):
        """The third hop of the cascade lands on the loop's master interlock.

        PRD: "`NORMAL → CONSTRAINED` fires when suspending a fuel supply contract
        reverted at least one `APPROVED` dispatch plan on this loop back to
        `DRAFT`."

        Design: Difficulty/transitive_cascade/fuel_suspension_derates_asset_reverts_plan_constrains_loop
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")

        set_fuel_contract_status(
            stack["gas_contract"]["id"], "SUSPENDED", reason="supplier force majeure"
        )

        assert_loop_state(
            read_loop(stack["loop"]["id"]),
            posture="CONSTRAINED",
            committed_reserved_kw=3000.0,
            open_isolation_count=0,
        )

    def test_the_reverted_plan_keeps_the_dispatch_orders_it_already_owned(self):
        """Reversion is a state change, not a re-optimisation.

        PRD: "This is the intended serialisation point between the supply side and
        the control room: an approval earned on a fuel supply that has since been
        withdrawn is not allowed to stand."

        Design: Difficulty/transitive_cascade/fuel_suspension_derates_asset_reverts_plan_constrains_loop
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")

        set_fuel_contract_status(
            stack["gas_contract"]["id"], "SUSPENDED", reason="supplier force majeure"
        )

        assert len(plan_orders(stack["plan"]["id"])) == 3


class TestRepairSignOffCascade:
    """Signing off a leak repair rewrites the survey inputs and the loop posture."""

    def _isolated_leak_repair(self):
        stack = industrial_leak_stack()
        order = create_work_order(
            stack["suspect_segment"]["id"],
            stack["loop"]["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T16:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="LEAK_REPAIR",
            requires_isolation=True,
        )
        submit_permit(order["id"], FIELD_TECHNICIAN)
        decide_permit(order["id"], "GRANTED", decision_note="leak repair permitted")
        set_clock("2026-09-01T09:00:00Z")
        begin_excavation(order["id"], FIELD_TECHNICIAN)
        begin_repair(order["id"], FIELD_TECHNICIAN)
        backfill_work_order(order["id"], FIELD_TECHNICIAN)
        stack["order"] = order
        return stack

    def test_the_open_excavation_isolates_the_loop_and_clears_the_suspect_count(self):
        """Breaking ground takes the segment out of the suspect population.

        PRD: "`SUSPECT → UNDER_REPAIR` additionally decrements the loop's
        `suspect_segment_count` by 1 and increments the loop's `version` by 1,
        because the segment has left the suspect population."

        Design: Difficulty/transitive_cascade/work_order_completion_rebands_segment_and_restores_loop_posture
        """
        stack = self._isolated_leak_repair()

        assert_loop_state(
            read_loop(stack["loop"]["id"]),
            posture="ISOLATED",
            open_isolation_count=1,
            suspect_segment_count=0,
        )
        assert_segment_condition(
            _read_segment(stack["suspect_segment"]["id"]), condition="UNDER_REPAIR"
        )

    def test_sign_off_resets_the_makeup_water_and_records_the_confirmed_leak(self):
        """A leak repair zeroes the makeup ratio and adds one to the leak history.

        PRD: "The segment's `makeup_water_ratio` is reset to 0.0 — the repair
        stopped the leak — and when the `work_type` was `LEAK_REPAIR` the segment's
        `historical_leak_count` is incremented by 1, recording the confirmed leak
        on its permanent history."

        Design: Difficulty/transitive_cascade/work_order_completion_rebands_segment_and_restores_loop_posture
        """
        stack = self._isolated_leak_repair()

        complete_work_order(
            stack["order"]["id"],
            completion_note="joint replaced, insulation patched",
            completer_headers=FIELD_TECHNICIAN_ALT,
        )

        assert_segment_condition(
            _read_segment(stack["suspect_segment"]["id"]),
            makeup_water_ratio=0.0,
            historical_leak_count=3,
        )

    def test_the_recomputed_score_rebands_the_segment_down_to_monitored(self):
        """Clearing the makeup water outweighs the extra leak, but only just.

        PRD: "Only then is the leak-risk score recomputed from those revised
        inputs, and the segment is re-banded out of `UNDER_REPAIR` into whichever
        band the new score implies, with the segment's `version` incremented by 1."

        Design: Difficulty/transitive_cascade/work_order_completion_rebands_segment_and_restores_loop_posture
        """
        stack = self._isolated_leak_repair()

        complete_work_order(
            stack["order"]["id"],
            completion_note="joint replaced, insulation patched",
            completer_headers=FIELD_TECHNICIAN_ALT,
        )

        assert_segment_condition(
            _read_segment(stack["suspect_segment"]["id"]),
            condition="MONITORED",
            leak_risk_score=56.08,
        )

    def test_sign_off_restores_the_loop_to_a_normal_posture(self):
        """With the ground closed and no suspect segments the loop is normal again.

        PRD: "Finally, when `requires_isolation` was true the loop's
        `open_isolation_count` is decremented by 1, and the loop's `posture` is
        cascaded out of `ISOLATED` to `NORMAL` when the recomputed
        `suspect_segment_count` is 0 and to `CONSTRAINED` when it is greater than
        0, with the loop's `version` incremented by 1."

        Design: Difficulty/transitive_cascade/work_order_completion_rebands_segment_and_restores_loop_posture
        """
        stack = self._isolated_leak_repair()

        completed = complete_work_order(
            stack["order"]["id"],
            completion_note="joint replaced, insulation patched",
            completer_headers=FIELD_TECHNICIAN_ALT,
        )

        assert completed["work_state"] == "COMPLETED"
        assert completed["completed_by_user_id"] == TECH_2
        assert read_work_order(stack["order"]["id"])["work_state"] == "COMPLETED"
        assert_loop_state(
            read_loop(stack["loop"]["id"]),
            posture="NORMAL",
            open_isolation_count=0,
            suspect_segment_count=0,
        )
