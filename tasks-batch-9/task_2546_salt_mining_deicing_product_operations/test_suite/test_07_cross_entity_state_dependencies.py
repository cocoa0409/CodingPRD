"""
Writes whose legality — or whose stored numbers — live on another entity's row.

Two byte-identical delivery orders differ only in their storm flag, and that flag is
read against a depot's posture rather than anything on the order. A citation on a
mine changes no child state at all, yet rewrites a number stored on its live panels
while leaving a depleted sibling's copy of the same number frozen.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NO_ELIGIBLE_STOCKPILE
from test_helpers.assertions import assert_lot_tonnage, assert_tons
from test_helpers.constants import (
    ACTION_CITE,
    CITED,
    COARSE,
    COMPLIANT,
    CONTRACT_ACTIVE,
    DEPOT_OPEN,
    DEPOT_SURGE,
    HIGHWAY_DEICING,
    HOIST_AVAILABLE,
    JURISDICTION_MUNICIPAL,
    METHOD_SEVERITY_WEIGHTED,
    ORDER_ALLOCATED,
    ORDER_REQUESTED,
    PANEL_DEPLETED,
    PANEL_PRODUCING,
    PENALTY_NONE,
    ROUTINE,
    STORM_EMERGENCY,
)
from test_helpers.test_users import LOGISTICS, MINE_PLANNER

CLOCK = "2026-08-10T00:00:00Z"

FORECAST_KWARGS = dict(
    season_code="2026-27",
    region_code="NORTHEAST",
    normal_season_tons=200000,
    severity_index=60,
    prior_season_1_actual_tons=240000,
    prior_season_2_actual_tons=180000,
    prior_season_3_actual_tons=150000,
    method=METHOD_SEVERITY_WEIGHTED,
    preseason_lock_date="2026-10-15T00:00:00Z",
)

CONTRACT_KWARGS = dict(
    customer_name="City of Buffalo",
    jurisdiction_level=JURISDICTION_MUNICIPAL,
    state_code="NY",
    product_line=HIGHWAY_DEICING,
    committed_tons=5000,
    guaranteed_price_per_ton=68.55,
    min_take_pct=80,
    max_take_pct=110,
    failure_to_supply_penalty_per_ton=22.00,
    price_guarantee_cap_pct=10,
)

ORDER_KWARGS = dict(
    requested_tons=1000,
    required_by="2026-12-01T00:00:00Z",
    market_index_price_per_ton=70.00,
)


def _surge_depot_with_two_identical_orders(api):
    """
    One 5527.20 t lot at the only stocked depot, that depot posted `SURGE`, and two
    1000 t orders against it that differ in nothing but `storm_priority`.
    """
    fx.set_clock(api, CLOCK)
    world = fx.lot_at_depot(
        api,
        mine_kwargs=dict(name="Retsof", rated_hoist_tons_per_day=24000),
        panel_kwargs=dict(panel_code="P-1", pillar_recovery_allowed=True),
        depot_kwargs=dict(name="Depot A", outbound_freight_rate_per_ton=4.00),
        run_kwargs=dict(
            planned_tons=6000,
            hoist_window_start="2026-08-11T00:00:00Z",
            hoist_window_end="2026-08-11T06:00:00Z",
        ),
        hoisted_tons=6000,
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=30,
        input_tons=6000,
        moisture_pct=2.0,
    )
    assert_tons(world["lot"]["tons_available"], 5527.20, "tons_available")
    fx.set_posture(api, world["depot"]["id"], DEPOT_SURGE, reason="storm staging")

    world.update(fx.active_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS))
    assert world["contract"]["status"] == CONTRACT_ACTIVE

    world["routine_order"] = fx.create_order(
        api,
        world["contract"]["id"],
        world["depot"]["id"],
        storm_priority=ROUTINE,
        **ORDER_KWARGS,
    )
    world["storm_order"] = fx.create_order(
        api,
        world["contract"]["id"],
        world["depot"]["id"],
        storm_priority=STORM_EMERGENCY,
        **ORDER_KWARGS,
    )
    return world


def test_a_surge_depot_empties_the_routine_pool_but_serves_the_storm_order(api):
    """
    The routine order's waterfall finds no candidate at all and is refused outright —
    which is not a short and books no penalty — while the identical storm order draws
    its full 1000.00 t from the very same lot. A `SURGE` depot still counted toward the
    activation coverage that let the contract go live in the first place.

    PRD §3.8: "The contract's pre-season coverage is the sum of `tons_available` across
    every stockpile lot whose `lot_state` is `AVAILABLE`, whose `product_line` matches
    the contract's `product_line`, and which sits at a depot whose `state_code` matches
    the contract's `state_code` and whose `depot_state` is `OPEN` or `SURGE`."

    PRD §3.6: "`SURGE` narrows rather than widens the depot's normal role: a depot in
    `SURGE` is a candidate for the allocation waterfall of `STORM_EMERGENCY` orders
    only, and drops out of the candidate pool for `ROUTINE` orders."

    PRD §3.9: "**Nothing allocated.** When no candidate lot exists at all, the request
    is refused with `ERR_NO_ELIGIBLE_STOCKPILE`. No allocation rows are written, no lot
    tonnage moves, and the order stays at `REQUESTED` — a failed waterfall leaves no
    trace and may be retried once salt arrives."

    Design: Difficulty/cross_entity_state_dependency/routine_order_blocked_while_identical_storm_order_draws_from_surge_depot
    """
    world = _surge_depot_with_two_identical_orders(api)

    ledger = fx.contract_ledger(api, world["contract"]["id"])
    assert_tons(ledger["preseason_coverage_tons"], 5527.20, "preseason_coverage_tons")
    assert_tons(
        ledger["preseason_coverage_required_tons"],
        4000.00,
        "preseason_coverage_required_tons",
    )

    refused = api.allocate_order(world["routine_order"]["id"], LOGISTICS)
    validate_error(refused, ERR_NO_ELIGIBLE_STOCKPILE, 409)

    untouched = fx.refresh_order(api, world["routine_order"]["id"])
    assert untouched["status"] == ORDER_REQUESTED
    assert_tons(untouched["allocated_tons"], 0.00, "allocated_tons")
    assert_tons(untouched["shorted_tons"], 0.00, "shorted_tons")
    assert untouched["penalty_state"] == PENALTY_NONE
    assert fx.allocations_of_order(api, world["routine_order"]["id"]) == []
    assert_lot_tonnage(fx.refresh_lot(api, world["lot"]["id"]), 5527.20, 0.00, 5527.20)

    storm = get_success_data(api.allocate_order(world["storm_order"]["id"], LOGISTICS))
    assert storm["status"] == ORDER_ALLOCATED
    assert_tons(storm["allocated_tons"], 1000.00, "allocated_tons")


def test_posting_the_depot_back_to_open_lets_the_unchanged_routine_order_through(api):
    """
    Nothing about the refused order is edited or re-created; a posture call on a
    different entity is the whole difference between refusal and a full fill, and both
    reservations then sit on the one lot at once.

    PRD §3.6: "A `DepotManager` or a `LogisticsPlanner` sets it explicitly by naming
    the target `depot_state` and optionally a `reason`; the value named must differ from
    the value currently held, and the manual call stamps `storm_state_set_by_user_id`
    with the caller's `X-User-ID`."

    PRD §3.9: "**Fully allocated.** When the walk covers the whole `requested_tons`, the
    order moves `REQUESTED → ALLOCATED`, its `allocated_tons` is set to the
    `requested_tons`, its `shorted_tons` stays 0, and its `penalty_state` stays `NONE`."

    PRD §3.9: "Each write reserves against the lot per the invariant of §3.6 —
    `tons_reserved` up, `tons_available` down, `tons_on_hand` unchanged — and increments
    the lot's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/routine_order_blocked_while_identical_storm_order_draws_from_surge_depot
    """
    world = _surge_depot_with_two_identical_orders(api)
    validate_error(
        api.allocate_order(world["routine_order"]["id"], LOGISTICS),
        ERR_NO_ELIGIBLE_STOCKPILE,
        409,
    )
    get_success_data(api.allocate_order(world["storm_order"]["id"], LOGISTICS))

    reopened = fx.set_posture(
        api, world["depot"]["id"], DEPOT_OPEN, reason="storm passed"
    )
    assert reopened["depot_state"] == DEPOT_OPEN

    routine = get_success_data(
        api.allocate_order(world["routine_order"]["id"], LOGISTICS)
    )
    assert routine["status"] == ORDER_ALLOCATED
    assert_tons(routine["allocated_tons"], 1000.00, "allocated_tons")
    assert_tons(routine["shorted_tons"], 0.00, "shorted_tons")
    assert routine["penalty_state"] == PENALTY_NONE

    assert_lot_tonnage(
        fx.refresh_lot(api, world["lot"]["id"]), 5527.20, 2000.00, 3527.20
    )


def _mine_with_a_live_and_a_depleted_panel(api):
    """
    Two identically assayed panels under one compliant mine: one still `PRODUCING`, one
    already mined out, both reporting 617600.00 t while the mine is compliant.
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)

    live = fx.create_panel(
        api, mine["id"], panel_code="P-LIVE", pillar_recovery_allowed=True
    )
    fx.develop(api, live["id"])
    fx.start_production(api, live["id"])

    done = fx.create_panel(
        api, mine["id"], panel_code="P-DONE", pillar_recovery_allowed=True
    )
    fx.develop(api, done["id"])
    fx.start_production(api, done["id"])
    done = get_success_data(api.deplete_panel(done["id"], MINE_PLANNER))

    assert_tons(live["recoverable_tons"], 617600.00, "recoverable_tons")
    assert_tons(done["recoverable_tons"], 617600.00, "recoverable_tons")
    assert done["status"] == PANEL_DEPLETED

    return {
        "mine": fx.refresh_mine(api, mine["id"]),
        "live": live,
        "done": done,
    }


def test_a_citation_on_the_mine_rewrites_the_live_panels_stored_reserve(api):
    """
    The citation is a write on the mine, but the number it moves is stored on the child:
    the live panel loses the 32000.00 t pillar term because that term is granted only
    while the parent is compliant, and the shaft's own dimension never moves.

    PRD §3.2: "**Pillar bonus.** When `pillar_recovery_allowed` is true **and** the
    parent mine's `compliance_state` is `COMPLIANT` at the moment of evaluation, the
    bonus is 8 percent of the tonnage left behind by first-pass development, that is 8
    percent of `gross_tons_in_place` minus the base tonnage."

    PRD §3.2: "In every other case — the flag is false, or the mine is `CITED`, or the
    mine is under a `WITHDRAWAL_ORDER` — the bonus is zero."

    PRD §3.1: "Moving to `CITED` therefore strips the pillar-recovery bonus from those
    panels; moving to `WITHDRAWAL_ORDER` strips it too; and `CLEAR` restores it wherever
    the panel's `pillar_recovery_allowed` is true."

    PRD §3.1: "Every compliance action stamps `last_compliance_action_at` from the
    logical clock, recomputes `effective_hoist_tons_per_day`, and increments the mine's
    `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/mine_citation_re_derives_child_panel_reserve_but_spares_depleted_panels
    """
    world = _mine_with_a_live_and_a_depleted_panel(api)
    before = world["mine"]
    assert before["compliance_state"] == COMPLIANT

    cited = fx.compliance_action(
        api,
        before["id"],
        ACTION_CITE,
        note="MSHA citation, ground control plan deficiency",
    )

    assert cited["compliance_state"] == CITED
    # 24000 x hoist factor 1.00 x compliance factor 0.80.
    assert_tons(
        cited["effective_hoist_tons_per_day"], 19200.00, "effective_hoist_tons_per_day"
    )
    # The two dimensions are independent: the shaft was never touched.
    assert cited["hoist_state"] == HOIST_AVAILABLE
    assert cited["version"] == before["version"] + 1

    live = fx.refresh_panel(api, world["live"]["id"])
    assert_tons(live["recoverable_tons"], 585600.00, "recoverable_tons")
    assert live["status"] == PANEL_PRODUCING


def test_a_depleted_sibling_keeps_the_reserve_the_citation_rewrote_next_door(api):
    """
    The re-run input set excludes terminal panels, so two children of one parent
    legitimately disagree about the same formula afterwards — and neither child's state
    moved at all.

    PRD §3.1: "On **every** compliance action, the recoverable reserve of every panel on
    the mine whose `status` is one of `PLANNED`, `DEVELOPED`, `PRODUCING` or `SUSPENDED`
    is recomputed from scratch, because one term of that reserve formula is only granted
    while the mine is compliant (§3.2)."

    PRD §3.1: "Panels already `DEPLETED` or `ABANDONED` are never touched — their reserve
    is frozen for good."

    PRD §3.2: "The panel's `recoverable_tons` is frozen at its current value and is never
    recomputed again, no matter how many compliance actions follow."

    Design: Difficulty/cross_entity_state_dependency/mine_citation_re_derives_child_panel_reserve_but_spares_depleted_panels
    """
    world = _mine_with_a_live_and_a_depleted_panel(api)

    fx.compliance_action(
        api,
        world["mine"]["id"],
        ACTION_CITE,
        note="MSHA citation, ground control plan deficiency",
    )

    done = fx.refresh_panel(api, world["done"]["id"])
    assert_tons(done["recoverable_tons"], 617600.00, "recoverable_tons")
    assert done["status"] == PANEL_DEPLETED

    live = fx.refresh_panel(api, world["live"]["id"])
    assert_tons(live["recoverable_tons"], 585600.00, "recoverable_tons")
    assert live["status"] == PANEL_PRODUCING

    mine = fx.refresh_mine(api, world["mine"]["id"])
    assert mine["producing_panel_count"] == 1
    assert mine["compliance_state"] == CITED
