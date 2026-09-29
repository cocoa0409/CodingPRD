"""Compensating actions that must restore a ledger exactly.

Aborting a deployment gives back the labor minutes, waiving an incident gives
back the remake cost, and abandoning a merged car gives back the merge position.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.test_users import ADMIN_HEADERS


ABORT_REASON = "Team member pulled to the front counter mid-deployment"
WAIVER_REASON = (
    "Guest confirmed the item was correct; the complaint was logged against the wrong car"
)
ABANDON_REASON = "Guest drove off from the window without collecting the order"


# ------------------------------------------------------------- the labor ledger
def _store_with_an_active_deployment_on_a_small_budget(api: DriveThruApiClient):
    """A 120-minute budget with a 30-minute deployment live on position."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-V",
        labor_minutes_budget=120,
        staff_name="Ada Quan",
        name="Chamblee Labor Ledger",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    deployment = fx.plan_deployment(api, ctx, fx.at(11, 0, 0), fx.at(11, 30, 0))
    fx.activate_deployment(api, ctx, deployment["id"])
    fx.set_clock(api, fx.at(11, 12, 0))
    return ctx, deployment["id"]


class TestLaborMinutesConservedOnAbort:
    """Abort restores the ledger to exactly its pre-activation value."""

    def test_abort_gives_back_the_full_planned_minutes(self, api):
        """PRD §3.2: "From `ACTIVE`, an `Operator` abort — requiring the store not to
        be frozen — stores the supplied `abort_reason`, leaves
        `labor_minutes_charged` at 0, returns the member to `AVAILABLE` with
        `deployed_minutes_today` untouched, and drops the full `planned_minutes`
        back out of `labor_minutes_committed`, restoring `labor_minutes_available`
        to exactly the value it had before activation."

        Design: Difficulty/compensating_invariant/labor_minutes_conserved_on_activate_then_abort
        """
        ctx, deployment_id = _store_with_an_active_deployment_on_a_small_budget(api)

        before = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(before, committed=30, available=90)
        a.assert_rollup(before, deployed_oot_count=1)

        aborted = validate_success(
            api.abort_deployment(
                deployment_id, {"abort_reason": ABORT_REASON}, ctx.operator_headers
            )
        )
        assert aborted["deployment_state"] == "ABORTED", aborted
        assert aborted["abort_reason"] == ABORT_REASON, aborted
        a.assert_deployment_charge(
            aborted, labor_minutes_charged=0, released_at_is_null=True
        )

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=0, available=120)

    def test_the_budget_invariant_holds_after_the_abort(self, api):
        """PRD §3.2: "Across all four states the invariant that must hold after every
        request is that `labor_minutes_budget` equals `labor_minutes_committed`
        plus `labor_minutes_available`; deployments in `PLANNED` and `ABORTED`
        contribute zero to the committed side."

        Design: Difficulty/compensating_invariant/labor_minutes_conserved_on_activate_then_abort
        """
        ctx, deployment_id = _store_with_an_active_deployment_on_a_small_budget(api)

        validate_success(
            api.abort_deployment(
                deployment_id, {"abort_reason": ABORT_REASON}, ctx.operator_headers
            )
        )

        store = fx.get_restaurant(api, ctx.restaurant_id)
        assert store["labor_minutes_budget"] == 120, store
        assert (
            store["labor_minutes_budget"]
            == store["labor_minutes_committed"] + store["labor_minutes_available"]
        ), store

        staff = validate_success(api.get_staff_member(ctx.staff_id, ADMIN_HEADERS))
        assert staff["staff_state"] == "AVAILABLE", staff
        assert staff["deployed_minutes_today"] == 0, staff

    def test_the_store_posture_returns_to_open_with_nobody_on_position(self, api):
        """PRD §2.4: "`deployed_oot_count` is the number of the store's deployments
        whose `deployment_state` is `ACTIVE` and whose `position` is either
        `OOT_LANE_A` or `OOT_LANE_B`."

        Design: Difficulty/compensating_invariant/labor_minutes_conserved_on_activate_then_abort
        """
        ctx, deployment_id = _store_with_an_active_deployment_on_a_small_budget(api)

        validate_success(
            api.abort_deployment(
                deployment_id, {"abort_reason": ABORT_REASON}, ctx.operator_headers
            )
        )

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            deployed_oot_count=0,
            required_oot_count=0,
            service_posture="OPEN",
        )


# ------------------------------------------------------- the remake cost ledger
def _closed_car_carrying_a_logged_defect(api: DriveThruApiClient):
    """A served car whose order was logged as wrong, cost accrued against the store."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-W",
        staff_name="Yusuf Adler",
        name="Brookhaven Accuracy Ledger",
    )
    fx.add_staff_member(
        api,
        ctx.restaurant_id,
        "Mira Cortez",
        oot_certified=False,
        window_certified=True,
    )
    loop = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=None,
        order_items_count=4,
    )
    incident = fx.log_incident(api, ctx, loop["id"], incident_type="WRONG_ITEM")
    fx.set_clock(api, fx.at(11, 4, 10))
    departed = fx.depart_loop(api, ctx, loop["id"])
    return ctx, departed, incident


class TestRemakeCostReversedOnWaive:
    """Waiving takes the penalty and the cost back out again."""

    def test_waiving_reverses_the_cost_without_erasing_the_record(self, api):
        """PRD §3.6: "Waiving is the true compensating action: the loop's
        `accuracy_state` becomes `WAIVED`, the incident's `penalty_seconds`
        **leave** `adjusted_total_seconds`, and the store's
        `remake_cost_accrued_cents` drops by exactly this incident's
        `remake_cost_cents`, restoring the ledger to the value it held before the
        incident was logged."

        Design: Difficulty/compensating_invariant/remake_cost_ledger_reversed_on_waive
        """
        ctx, departed, incident = _closed_car_carrying_a_logged_defect(api)

        a.assert_loop_segments(
            departed, total_seconds=250, adjusted_total_seconds=295
        )
        before = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            before,
            open_remake_count=1,
            remake_cost_accrued_cents=750,
            required_oot_count=2,
        )

        waived = fx.waive_incident(api, incident["id"], WAIVER_REASON)
        assert waived["incident_state"] == "WAIVED", waived
        assert waived["settlement_state"] == "REVERSED", waived
        assert waived["waiver_reason"] == WAIVER_REASON, waived
        # The figures stay on the record; only their effect is reversed.
        assert waived["penalty_seconds"] == 45, waived
        assert waived["remake_cost_cents"] == 750, waived

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(store, remake_cost_accrued_cents=0, open_remake_count=0)

    def test_the_waived_penalty_leaves_the_adjusted_total(self, api):
        """PRD §3.3: "The **accuracy penalty** is the sum of `penalty_seconds` over
        this loop's accuracy incidents whose `incident_state` is `LOGGED`,
        `REMADE` or `CLOSED` — incidents in `WAIVED` are excluded, which is
        precisely why waiving is a genuine reversal."

        Design: Difficulty/compensating_invariant/remake_cost_ledger_reversed_on_waive
        """
        ctx, departed, incident = _closed_car_carrying_a_logged_defect(api)

        fx.waive_incident(api, incident["id"], WAIVER_REASON)

        loop = validate_success(api.get_timer_loop(departed["id"], ADMIN_HEADERS))
        a.assert_loop_states(loop, timing_state="CLOSED", accuracy_state="WAIVED")
        a.assert_loop_segments(
            loop, total_seconds=250, adjusted_total_seconds=250
        )
        assert loop["adjusted_total_seconds"] == loop["total_seconds"], loop

    def test_the_staffing_requirement_drops_back_by_the_accuracy_bump(self, api):
        """PRD §3.6: "`open_remake_count` drops and `service_posture` is
        recomputed."

        Design: Difficulty/compensating_invariant/remake_cost_ledger_reversed_on_waive
        """
        ctx, _departed, incident = _closed_car_carrying_a_logged_defect(api)

        fx.waive_incident(api, incident["id"], WAIVER_REASON)

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=1,
            volume_tier="TIER_2",
            open_remake_count=0,
            required_oot_count=1,
            deployed_oot_count=0,
            service_posture="SURGE",
        )


# ------------------------------------------------------- the merge capacity ledger
def _merged_car_at_the_window_holding_a_committed_slot(api: DriveThruApiClient):
    """A two-position merge lane with one position committed to a car at the window."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-X",
        lane_config="DUAL_PARALLEL",
        merge_slots_capacity=2,
        staff_name="Zoe Hartline",
        name="Lilburn Dual Parallel",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    loop = fx.open_loop(api, ctx, lane="LANE_A")
    fx.set_clock(api, fx.at(11, 0, 20))
    fx.greet_loop(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 1, 0))
    fx.complete_order(api, ctx, loop["id"], order_items_count=3)
    slot = fx.award_merge_slot(api, ctx)
    fx.commit_slot(api, ctx, slot["id"])
    fx.set_clock(api, fx.at(11, 2, 0))
    fx.arrive_at_window(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 4, 10))
    return ctx, loop["id"], slot


class TestMergeCapacityConservedOnAbandon:
    """A drive-off forfeits the position and hands the capacity back."""

    def test_abandoning_forfeits_the_committed_slot_and_frees_capacity(self, api):
        """PRD §3.4: "And it becomes `FORFEITED` from `COMMITTED` when its awarded
        loop is abandoned. In every one of these cases the store's
        `merge_slots_free` is recomputed upward by one — capacity is conserved
        across award and abandonment exactly."

        Design: Difficulty/compensating_invariant/merge_slot_capacity_conserved_on_award_then_abandon
        """
        ctx, loop_id, slot = _merged_car_at_the_window_holding_a_committed_slot(api)

        assert slot["sequence_index"] == 1, slot
        held = fx.get_restaurant(api, ctx.restaurant_id)
        assert held["merge_slots_capacity"] == 2, held
        a.assert_merge_capacity(held, free=1)

        validate_success(
            api.abandon_timer_loop(
                loop_id, {"abandon_reason": ABANDON_REASON}, ctx.leader_headers
            )
        )

        forfeited = validate_success(api.get_merge_slot(slot["id"], ADMIN_HEADERS))
        assert forfeited["slot_state"] == "FORFEITED", forfeited
        assert forfeited["slot_state"] != "RELEASED", forfeited
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_merge_capacity(store, free=2)

    def test_an_abandoned_car_records_no_duration(self, api):
        """PRD §3.3: "`ABANDONED` is terminal, `total_seconds` stays null, and an
        abandoned car is emphatically **not** a served car — the rollup chain's
        trailing count does not move, so abandoning changes no tier and no
        posture."

        Design: Difficulty/compensating_invariant/merge_slot_capacity_conserved_on_award_then_abandon
        """
        ctx, loop_id, _slot = _merged_car_at_the_window_holding_a_committed_slot(api)

        abandoned = validate_success(
            api.abandon_timer_loop(
                loop_id, {"abandon_reason": ABANDON_REASON}, ctx.leader_headers
            )
        )
        a.assert_loop_states(
            abandoned, timing_state="ABANDONED", accuracy_state="PENDING"
        )
        assert abandoned["abandon_reason"] == ABANDON_REASON, abandoned
        a.assert_all_null(
            abandoned, ["total_seconds", "adjusted_total_seconds", "depart_at"]
        )

    def test_the_drive_off_moves_no_tier_and_no_posture(self, api):
        """PRD §2.4: "`cars_closed_trailing` is the number of the store's own timer
        loops whose `timing_state` is `CLOSED` and whose `depart_at` is strictly
        later than the instant ten minutes (600 seconds) before the current clock
        reading and no later than the current clock reading."

        Design: Difficulty/compensating_invariant/merge_slot_capacity_conserved_on_award_then_abandon
        """
        ctx, loop_id, _slot = _merged_car_at_the_window_holding_a_committed_slot(api)

        validate_success(
            api.abandon_timer_loop(
                loop_id, {"abandon_reason": ABANDON_REASON}, ctx.leader_headers
            )
        )

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=0,
            cars_per_hour_observed=0.0,
            cars_per_hour_effective=0.0,
            volume_tier="TIER_1",
            required_oot_count=0,
            service_posture="OPEN",
        )
