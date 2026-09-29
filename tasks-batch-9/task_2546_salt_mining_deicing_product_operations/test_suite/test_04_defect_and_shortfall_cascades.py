"""
Single writes whose consequences reach entities the caller never named.

Filing one ground-control inspection moves a panel, then the shaft above it, then
the run booked on that shaft, then the shaft's open tonnage. Allocating one short
delivery order writes money on the order, re-derives the contract's ledger from it,
and only through that re-derivation flips a boolean the caller cannot post.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_immutable_inspection_fields,
    assert_lot_tonnage,
    assert_money,
    assert_penalty_ledger_invariant,
    assert_rate_per_hour,
    assert_tons,
)
from test_helpers.constants import (
    COARSE,
    COMPLIANT,
    DEPOT_SURGE,
    FINDING_DEFECT,
    HELD_REASON_GROUND_CONTROL,
    HIGHWAY_DEICING,
    HOIST_AVAILABLE,
    HOIST_DERATED,
    JURISDICTION_MUNICIPAL,
    MEDIUM,
    METHOD_SEVERITY_WEIGHTED,
    ORIGIN_WATERFALL,
    PANEL_PRODUCING,
    PANEL_SUSPENDED,
    PENALTY_ACCRUED,
    ROUTINE,
    RUN_HELD,
    RUN_SCHEDULED,
    ALLOCATION_RESERVED,
    ORDER_SHORTED,
)

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


def _mine_with_two_panels_and_a_booked_run(api):
    """
    A 24000 t/day shaft carrying two producing panels and one 6000 t run booked over
    six hours on the first of them — exactly the mine's 1000.0000 t/h capacity.
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)
    first = fx.create_panel(
        api, mine["id"], panel_code="P-1", pillar_recovery_allowed=True
    )
    fx.develop(api, first["id"])
    fx.start_production(api, first["id"])
    second = fx.create_panel(
        api, mine["id"], panel_code="P-2", pillar_recovery_allowed=True
    )
    fx.develop(api, second["id"])
    fx.start_production(api, second["id"])

    before = fx.refresh_mine(api, mine["id"])
    assert before["hoist_state"] == HOIST_AVAILABLE
    assert_tons(
        before["effective_hoist_tons_per_day"], 24000.00, "effective_hoist_tons_per_day"
    )

    run = fx.create_run(
        api,
        mine["id"],
        first["id"],
        planned_tons=6000,
        hoist_window_start="2026-08-11T00:00:00Z",
        hoist_window_end="2026-08-11T06:00:00Z",
    )
    return {"mine": before, "panel": first, "other_panel": second, "run": run}


def test_one_defect_inspection_moves_the_panel_the_shaft_and_the_run(api):
    """
    Three of the four hops, on three entity types, from a single POST the caller
    aimed only at a panel: the panel suspends, the shaft derates to 13200.00 t/day
    because a second panel is still producing, and the run booked on that shaft is
    held for ground control.

    PRD §3.3: "If the panel was `PRODUCING`, it moves `PRODUCING → SUSPENDED`,
    `suspended_by_user_id` is set to the filing engineer's `X-User-ID`, this record's
    `caused_suspension` becomes true, and the mine's `producing_panel_count` drops by
    1."

    PRD §3.3: "If the mine still has at least one `PRODUCING` panel after the
    suspension, `hoist_state` moves `HOIST_AVAILABLE → HOIST_DERATED` and the shaft
    factor becomes 0.55."

    PRD §3.3: "Because the shaft dimension changed, every production run on the
    suspended panel whose `status` is `SCHEDULED` moves to `HELD` with `held_reason`
    set to `GROUND_CONTROL`."

    Design: Difficulty/transitive_cascade/defect_inspection_cascades_panel_mine_run_and_open_tonnage
    """
    world = _mine_with_two_panels_and_a_booked_run(api)
    run = world["run"]
    assert run["status"] == RUN_SCHEDULED
    # Accepted at exactly the mine's hourly capacity: 6000 t over six hours.
    assert_rate_per_hour(run["planned_tons_per_hour"], 1000.0000)

    inspection = fx.file_inspection(
        api,
        world["panel"]["id"],
        FINDING_DEFECT,
        roof_span_ft=44.0,
        convergence_rate_in_per_day=0.51,
    )

    panel = fx.refresh_panel(api, world["panel"]["id"])
    assert panel["status"] == PANEL_SUSPENDED
    assert panel["open_defect"] is True
    assert panel["ground_control_defect_count"] == 1
    assert panel["suspended_by_user_id"] is not None

    mine = fx.refresh_mine(api, world["mine"]["id"])
    assert mine["hoist_state"] == HOIST_DERATED
    assert_tons(
        mine["effective_hoist_tons_per_day"], 13200.00, "effective_hoist_tons_per_day"
    )

    held = fx.refresh_run(api, run["id"])
    assert held["status"] == RUN_HELD
    assert held["held_reason"] == HELD_REASON_GROUND_CONTROL

    assert inspection["caused_suspension"] is True
    assert_immutable_inspection_fields(inspection)


def test_the_defect_cascade_empties_the_open_tonnage_and_spares_the_sibling(api):
    """
    The fourth hop is arithmetic on the mine rather than a state change: the held
    run's 6000 t leaves `scheduled_hoist_tons_open`, while the surviving panel and the
    mine's compliance dimension are untouched by any of it.

    PRD §3.3: "Because those runs left `SCHEDULED`, the mine's
    `scheduled_hoist_tons_open` is recomputed downward by exactly the sum of the held
    runs' `planned_tons`; when every run was held, it reaches 0."

    PRD §3.3: "The capacity re-fit rule of §3.1 then continues over the mine's *other*
    panels, holding further `SCHEDULED` runs until the aggregate concurrent hourly
    rate fits the mine's new hourly capacity; those runs are marked `CAPACITY`, not
    `GROUND_CONTROL`."

    PRD §3.3: "Each record also carries `caused_suspension`, a computed boolean that
    is true only when filing this particular record was what moved its panel out of
    production."

    Design: Difficulty/transitive_cascade/defect_inspection_cascades_panel_mine_run_and_open_tonnage
    """
    world = _mine_with_two_panels_and_a_booked_run(api)
    booked = fx.refresh_mine(api, world["mine"]["id"])
    assert_tons(
        booked["scheduled_hoist_tons_open"], 6000.00, "scheduled_hoist_tons_open"
    )
    assert booked["producing_panel_count"] == 2

    fx.file_inspection(
        api,
        world["panel"]["id"],
        FINDING_DEFECT,
        roof_span_ft=44.0,
        convergence_rate_in_per_day=0.51,
    )

    mine = fx.refresh_mine(api, world["mine"]["id"])
    assert_tons(mine["scheduled_hoist_tons_open"], 0.00, "scheduled_hoist_tons_open")
    # P-2 survives, which is why the shaft derated instead of going down.
    assert mine["producing_panel_count"] == 1
    assert mine["compliance_state"] == COMPLIANT

    view = fx.hoist_capacity(api, mine["id"])
    assert_tons(view["scheduled_hoist_tons_open"], 0.00, "scheduled_hoist_tons_open")
    assert view["scheduled_run_count"] == 0

    assert fx.refresh_panel(api, world["other_panel"]["id"])["status"] == PANEL_PRODUCING


def _shorted_two_thousand_ton_order(api):
    """
    A 2000 t routine order at a depot holding only 900.00 t, with the other 5527.20 t
    parked at a SURGE depot the routine waterfall may not touch.
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)
    panel = fx.create_panel(
        api, mine["id"], panel_code="P-1", pillar_recovery_allowed=True
    )
    fx.develop(api, panel["id"])
    fx.start_production(api, panel["id"])
    run = fx.create_run(
        api,
        mine["id"],
        panel["id"],
        planned_tons=7000,
        hoist_window_start="2026-08-11T00:00:00Z",
        hoist_window_end="2026-08-11T08:00:00Z",
    )
    fx.hoist(api, run["id"], 7000)

    depot_a = fx.create_depot(api, name="Depot A", outbound_freight_rate_per_ton=4.00)
    depot_b = fx.create_depot(api, name="Depot B", outbound_freight_rate_per_ton=4.00)
    near = fx.mint_lot(
        api,
        run["id"],
        depot_a["id"],
        screen_spec=MEDIUM,
        anticaking_ppm=30,
        input_tons=1000,
        moisture_pct=0.0,
    )
    fx.mint_lot(
        api,
        run["id"],
        depot_b["id"],
        screen_spec=COARSE,
        anticaking_ppm=30,
        input_tons=6000,
        moisture_pct=2.0,
    )
    fx.set_posture(api, depot_b["id"], DEPOT_SURGE, reason="storm staging")

    world = fx.active_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS)
    assert_money(world["contract"]["contract_value_usd"], 342750.00, "contract_value_usd")
    assert world["contract"]["breach_watch"] is False

    order = fx.create_order(
        api,
        world["contract"]["id"],
        depot_a["id"],
        requested_tons=2000,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=70.00,
        storm_priority=ROUTINE,
    )
    world.update(
        {
            "depot_a": depot_a,
            "depot_b": depot_b,
            "near_lot": near["lot"],
            "order": order,
        }
    )
    return world


def test_a_short_allocate_writes_the_capped_penalty_on_the_order(api):
    """
    Hop one lands where the caller pointed: the order shorts by 1100.00 t, and the
    money it books is the 15 percent cap of 20565.00 rather than the raw 24200.00 the
    tonnage alone would owe.

    PRD §3.9: "Hop one, on the order: `shorted_tons` becomes `requested_tons` minus
    `allocated_tons`, and `shortfall_penalty_usd` is computed as the smaller of two
    quantities — the shortfall tonnage multiplied by the contract's
    `failure_to_supply_penalty_per_ton` multiplied by a storm multiplier of 2.00 for a
    `STORM_EMERGENCY` order or 1.00 for a `ROUTINE` one, and a cap of 15 percent of
    the order's own value, that value being `requested_tons` multiplied by
    `guaranteed_price_per_ton` rounded half up to two decimal places — with the chosen
    quantity rounded half up to two decimal places."

    PRD §3.9: "The order's `penalty_state` becomes `ACCRUED`."

    PRD §3.6: "`SURGE` narrows rather than widens the depot's normal role: a depot in
    `SURGE` is a candidate for the allocation waterfall of `STORM_EMERGENCY` orders
    only, and drops out of the candidate pool for `ROUTINE` orders."

    Design: Difficulty/transitive_cascade/shortfall_cascades_order_penalty_into_contract_ledger_and_breach_watch
    """
    world = _shorted_two_thousand_ton_order(api)

    order = get_success_data(api.allocate_order(world["order"]["id"], fx.LOGISTICS))

    assert order["status"] == ORDER_SHORTED
    assert_tons(order["allocated_tons"], 900.00, "allocated_tons")
    assert_tons(order["shorted_tons"], 1100.00, "shorted_tons")
    assert order["penalty_state"] == PENALTY_ACCRUED
    assert_money(order["shortfall_penalty_usd"], 20565.00, "shortfall_penalty_usd")

    # The one lot the routine waterfall could see is fully reserved, not consumed.
    drawn = fx.refresh_lot(api, world["near_lot"]["id"])
    assert_lot_tonnage(drawn, 900.00, 900.00, 0.00)

    rows = fx.allocations_of_order(api, order["id"])
    assert len(rows) == 1, f"expected one allocation row, got {len(rows)}"
    assert rows[0]["state"] == ALLOCATION_RESERVED
    assert rows[0]["origin"] == ORIGIN_WATERFALL
    assert rows[0]["rank_position"] == 1
    assert rows[0]["stockpile_lot_id"] == world["near_lot"]["id"]


def test_the_orders_penalty_re_derives_the_ledger_and_flips_breach_watch(api):
    """
    Hops two and three land on an entity the allocate call never named: the contract's
    accrual and scorecard are re-derived from the order's penalty, and only that
    re-derived accrual crossing 17137.50 flips `breach_watch` — while fulfilment stays
    at zero, because a shorted order has delivered nothing.

    PRD §3.9: "Hop two, on the contract: `penalty_accrued_usd` and
    `supply_reliability_score` are both recomputed from the full ledger as described
    in §3.8, and the contract's `version` increments by 1."

    PRD §3.9: "Hop three, still on the contract: `breach_watch` flips to true the
    moment the recomputed `penalty_accrued_usd` reaches or exceeds 5 percent of
    `contract_value_usd`."

    PRD §3.8: "Sum the `shorted_tons` across the contract's delivery orders whose
    `penalty_state` is `ACCRUED`; take that cumulative shortfall multiplied by 100,
    divided by `committed_tons`, rounded half up to two decimal places, and cap the
    resulting haircut at 40 points."

    PRD §3.8: "`fulfilled_tons` is the sum of `allocated_tons` across the contract's
    delivery orders whose `status` is `DELIVERED` — only delivered orders count, so
    allocating tonnage moves nothing here."

    Design: Difficulty/transitive_cascade/shortfall_cascades_order_penalty_into_contract_ledger_and_breach_watch
    """
    world = _shorted_two_thousand_ton_order(api)
    before = fx.refresh_contract(api, world["contract"]["id"])
    assert_money(before["penalty_accrued_usd"], 0.00, "penalty_accrued_usd")

    order = get_success_data(api.allocate_order(world["order"]["id"], fx.LOGISTICS))

    contract = fx.refresh_contract(api, world["contract"]["id"])
    assert_money(contract["penalty_accrued_usd"], 20565.00, "penalty_accrued_usd")
    # 1100.00 t short on 5000 t committed is a 22.00-point haircut.
    assert_money(contract["supply_reliability_score"], 78.00, "supply_reliability_score")
    # 20565.00 clears 5 percent of the 342750.00 contract value.
    assert contract["breach_watch"] is True
    assert_tons(contract["fulfilled_tons"], 0.00, "fulfilled_tons")
    assert contract["version"] == before["version"] + 1
    assert_penalty_ledger_invariant(contract, [order])

    ledger = fx.contract_ledger(api, contract["id"])
    assert_money(ledger["penalty_accrued_usd"], 20565.00, "penalty_accrued_usd")
    assert ledger["accrued_penalty_order_count"] == 1
    assert ledger["breach_watch"] is True
