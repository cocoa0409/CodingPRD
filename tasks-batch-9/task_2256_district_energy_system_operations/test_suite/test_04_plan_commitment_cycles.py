"""Commitment, withdrawal and re-approval, and the stored-energy ledger they move."""

from test_helpers import (
    CTRL_1,
    assert_loop_state,
    assert_plan_metrics,
    campus_dispatch_stack,
    commit_plan,
    decommit_plan,
    optimize_plan,
    plan_orders,
    read_asset,
    read_loop,
    read_plan,
    review_plan,
    submit_plan,
)


class TestCommitDecommitReapprove:
    """An approved plan can be committed, withdrawn and earned back again."""

    def test_committing_an_approved_plan_moves_it_to_committed(self):
        """Commitment is the point at which stored thermal energy leaves the tanks.

        PRD: "**Commitment** moves an approved plan to `COMMITTED` and is the point
        at which stored thermal energy actually leaves the tanks."

        Design: Difficulty/non_linear_state_machine/dispatch_plan_commit_decommit_reoptimise_cycle
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")

        committed = commit_plan(stack["plan"]["id"])

        assert_plan_metrics(committed, plan_state="COMMITTED")

    def test_decommitting_returns_the_plan_to_drafting_and_clears_the_reviewer(self):
        """Withdrawal is the exact compensating move for a commitment.

        PRD: "The plan returns from `COMMITTED` to `DRAFT`, its
        `reviewed_by_user_id` is cleared to null, and for every storage order the
        referenced asset's `state_of_charge_kwh` is increased by that order's
        `discharged_kwh` with the asset's `version` incremented by 1".

        Design: Difficulty/non_linear_state_machine/dispatch_plan_commit_decommit_reoptimise_cycle
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")
        commit_plan(stack["plan"]["id"])

        withdrawn = decommit_plan(stack["plan"]["id"], "forecast revision expected")

        assert_plan_metrics(withdrawn, plan_state="DRAFT", reviewed_by_user_id=None)

    def test_a_withdrawn_plan_can_be_re_optimised_submitted_and_approved_again(self):
        """The whole draft-to-approved arc runs a second time on the same plan.

        PRD: "**Optimising** the plan is a self-loop from `DRAFT` back to `DRAFT`
        that may be run as often as the operator likes; each run deletes every
        dispatch order the plan currently owns and rebuilds the set from scratch."

        Design: Difficulty/non_linear_state_machine/dispatch_plan_commit_decommit_reoptimise_cycle
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")
        plan_id = stack["plan"]["id"]
        first_approved_version = stack["plan"]["version"]
        commit_plan(plan_id)
        decommit_plan(plan_id, "forecast revision expected")

        optimize_plan(plan_id)
        submit_plan(plan_id, "second pass")
        reapproved = review_plan(plan_id, "APPROVE", "re-approved after decommit")

        assert_plan_metrics(
            reapproved, plan_state="APPROVED", reviewed_by_user_id=CTRL_1
        )
        assert reapproved["version"] == first_approved_version + 5, (
            f"expected version {first_approved_version + 5}, got {reapproved['version']}"
        )

    def test_the_second_approval_reproduces_every_metric_of_the_first(self):
        """Re-optimisation over unchanged inputs lands on identical determinants.

        PRD: "Second, **duties are segregated**: the operator who authors a
        dispatch plan may not approve it, the technician who raises a work order
        may not sign it off, and a customer may act only on its own account."

        Design: Difficulty/non_linear_state_machine/dispatch_plan_commit_decommit_reoptimise_cycle
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")
        plan_id = stack["plan"]["id"]
        commit_plan(plan_id)
        decommit_plan(plan_id, "forecast revision expected")
        optimize_plan(plan_id)
        submit_plan(plan_id, "second pass")
        review_plan(plan_id, "APPROVE", "re-approved after decommit")

        final = read_plan(plan_id)

        assert_plan_metrics(
            final,
            plan_state="APPROVED",
            allocated_capacity_kw=2527.20,
            total_dispatch_cost=1584.36,
            reserve_margin_pct=46.41,
            fuel_diversity_hhi=0.5489,
        )
        assert len(plan_orders(plan_id)) == 3
        assert read_asset(stack["storage"]["id"])["state_of_charge_kwh"] == 4000.0
        assert_loop_state(read_loop(stack["loop"]["id"]), posture="NORMAL")


class TestStorageLedgerConservation:
    """Two commit-and-withdraw cycles leave the tank exactly where it started."""

    def test_commitment_draws_the_scheduled_energy_out_of_the_store(self):
        """The store's charge falls by the order's discharged energy on commit.

        PRD: "On success the plan becomes `COMMITTED`, and for every storage order
        the referenced asset's `state_of_charge_kwh` is decreased by that order's
        `discharged_kwh` with the asset's `version` incremented by 1."

        Design: Difficulty/compensating_invariant/storage_energy_kwh_ledger_returns_to_zero_drift_over_two_commit_cycles
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")
        storage_id = stack["storage"]["id"]
        opening_version = read_asset(storage_id)["version"]

        commit_plan(stack["plan"]["id"])

        after_commit = read_asset(storage_id)
        assert after_commit["state_of_charge_kwh"] == 0.0
        assert after_commit["version"] == opening_version + 1

    def test_two_full_cycles_restore_the_ledger_with_no_drift(self):
        """Commit, withdraw, re-approve, commit and withdraw again all cancel out.

        PRD: "so the storage energy ledger returns to its pre-commitment total
        exactly, with no drift."

        Design: Difficulty/compensating_invariant/storage_energy_kwh_ledger_returns_to_zero_drift_over_two_commit_cycles
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")
        plan_id = stack["plan"]["id"]
        storage_id = stack["storage"]["id"]
        opening = read_asset(storage_id)

        commit_plan(plan_id)
        after_commit_one = read_asset(storage_id)["state_of_charge_kwh"]
        decommit_plan(plan_id, "cycle one withdrawn")
        after_decommit_one = read_asset(storage_id)["state_of_charge_kwh"]
        submit_plan(plan_id, "cycle two")
        review_plan(plan_id, "APPROVE", "cleared again")
        commit_plan(plan_id)
        after_commit_two = read_asset(storage_id)["state_of_charge_kwh"]
        decommit_plan(plan_id, "cycle two withdrawn")
        closing = read_asset(storage_id)

        assert opening["state_of_charge_kwh"] == 4000.0
        assert after_commit_one == 0.0
        assert after_decommit_one == 4000.0
        assert after_commit_two == 0.0
        assert closing["state_of_charge_kwh"] == opening["state_of_charge_kwh"]
        assert closing["version"] == opening["version"] + 4

    def test_non_storage_orders_never_move_a_state_of_charge(self):
        """Only the thermal store carries a discharged figure, so only it is drawn down.

        PRD: "`discharged_kwh` is `allocated_kw` multiplied by the four-hour
        discharge window, rounded half-up to two decimal places, for a
        `THERMAL_STORAGE` asset, and is exactly 0.0 for every other asset."

        Design: Difficulty/compensating_invariant/storage_energy_kwh_ledger_returns_to_zero_drift_over_two_commit_cycles
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")
        plan_id = stack["plan"]["id"]
        orders = {order["asset_id"]: order for order in plan_orders(plan_id)}

        commit_plan(plan_id)

        assert orders[stack["chp"]["id"]]["discharged_kwh"] == 0.00
        assert orders[stack["biomass_boiler"]["id"]]["discharged_kwh"] == 0.00
        assert read_asset(stack["chp"]["id"])["state_of_charge_kwh"] == 0.0
        assert read_asset(stack["biomass_boiler"]["id"])["state_of_charge_kwh"] == 0.0

    def test_the_plan_ends_the_second_cycle_back_in_drafting(self):
        """After the last withdrawal the plan is a draft again, ready to re-optimise.

        PRD: "**Decommitment** is the exact compensating move, available to a
        `SystemController` on a `COMMITTED` plan with an optional `reason`."

        Design: Difficulty/compensating_invariant/storage_energy_kwh_ledger_returns_to_zero_drift_over_two_commit_cycles
        """
        stack = campus_dispatch_stack(plan_state="APPROVED")
        plan_id = stack["plan"]["id"]

        commit_plan(plan_id)
        decommit_plan(plan_id, "cycle one withdrawn")
        submit_plan(plan_id, "cycle two")
        review_plan(plan_id, "APPROVE", "cleared again")
        commit_plan(plan_id)
        final = decommit_plan(plan_id, "cycle two withdrawn")

        assert_plan_metrics(final, plan_state="DRAFT", reviewed_by_user_id=None)
