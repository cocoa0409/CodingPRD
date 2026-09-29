"""
Two-variant computations that the system stores side by side.

The pre-season stockpile target is computed by two independent methods on every
forecast write, and failure-to-supply money is computed twice over the same
delivery history — once per short event on the order, once in aggregate on the
contract at season close.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_common_fields, assert_money, assert_tons
from test_helpers.constants import (
    COARSE,
    CONTRACT_FORFEITED,
    DEPOT_SURGE,
    HIGHWAY_DEICING,
    JURISDICTION_MUNICIPAL,
    MEDIUM,
    METHOD_SEVERITY_WEIGHTED,
    METHOD_TRAILING_BASELINE,
    ORDER_DELIVERED,
    ORDER_SHORTED,
    PENALTY_ACCRUED,
    ROUTINE,
)
from test_helpers.test_users import CONTRACT_ADMIN

CLOCK = "2026-08-10T00:00:00Z"

# One market outlook: a normal winter of 200,000 t, a severity index of 60, and
# three prior actuals that run hotter than the mixture model on the recent end.
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


def test_forecast_stores_both_stockpile_target_variants_and_their_signed_spread(api):
    """
    Both variants are computed and stored from one row, and the selected method
    decides only which one binds.

    PRD §3.8: "Each weight is applied to a consumption scenario expressed as a
    multiple of `normal_season_tons` — 0.75 of normal in a mild winter, 1.00 in a
    normal winter, and 1.40 in a severe one — the three products are summed, that
    sum is multiplied by a safety-stock factor of 1.05, and the result is rounded
    half up to two decimal places."

    PRD §3.8: "That average is then multiplied by a severity uplift chosen by band
    — 1.00 when the `severity_index` is 40 or below, 1.10 when it falls anywhere
    from 41 through 70 inclusive, and 1.25 when it is 71 or above — multiplied by
    the same safety-stock factor of 1.05, and rounded half up to two decimal
    places."

    PRD §3.8: "The `variant_spread_tons` is the severity-weighted target minus the
    trailing-baseline target, rounded half up to two decimal places".

    Design: Difficulty/dual_variant_calc/preseason_target_severity_weighted_versus_trailing_baseline_switch
    """
    fx.set_clock(api, CLOCK, CONTRACT_ADMIN)

    forecast = get_success_data(
        api.create_forecast(f.forecast_payload(**FORECAST_KWARGS), CONTRACT_ADMIN), 201
    )

    # Mixture: severe 0.60, mild 0.16, normal 0.24 over 0.75/1.00/1.40 of normal,
    # then the 1.05 safety-stock factor.
    assert_tons(
        forecast["target_tons_severity_weighted"],
        252000.00,
        "target_tons_severity_weighted",
    )
    # History: (240000*3 + 180000*2 + 150000*1)/6 = 205000, uplift 1.10, then 1.05.
    assert_tons(
        forecast["target_tons_trailing_baseline"],
        236775.00,
        "target_tons_trailing_baseline",
    )
    assert_tons(forecast["variant_spread_tons"], 15225.00, "variant_spread_tons")
    assert_tons(forecast["binding_target_tons"], 252000.00, "binding_target_tons")
    assert forecast["method"] == METHOD_SEVERITY_WEIGHTED
    assert_common_fields(forecast, expected_version=1)


def test_switching_the_binding_method_moves_only_binding_target_tons(api):
    """
    A method switch re-points `binding_target_tons` at the other stored variant and
    leaves every computed figure exactly where it was.

    PRD §3.8: "Changing only the `method` on an existing forecast therefore leaves
    both `target_tons_severity_weighted` and `target_tons_trailing_baseline` and
    the `variant_spread_tons` exactly as they were and moves only the
    `binding_target_tons`."

    Design: Difficulty/dual_variant_calc/preseason_target_severity_weighted_versus_trailing_baseline_switch
    """
    fx.set_clock(api, CLOCK, CONTRACT_ADMIN)
    before = get_success_data(
        api.create_forecast(f.forecast_payload(**FORECAST_KWARGS), CONTRACT_ADMIN), 201
    )
    assert_tons(before["binding_target_tons"], 252000.00, "binding_target_tons")

    after = get_success_data(
        api.patch_forecast(
            before["id"],
            f.forecast_patch_payload(method=METHOD_TRAILING_BASELINE),
            CONTRACT_ADMIN,
        )
    )

    assert after["method"] == METHOD_TRAILING_BASELINE
    assert_tons(after["binding_target_tons"], 236775.00, "binding_target_tons")
    assert_tons(
        after["target_tons_severity_weighted"],
        252000.00,
        "target_tons_severity_weighted",
    )
    assert_tons(
        after["target_tons_trailing_baseline"],
        236775.00,
        "target_tons_trailing_baseline",
    )
    assert_tons(after["variant_spread_tons"], 15225.00, "variant_spread_tons")
    assert_common_fields(after, expected_version=2)


def _shorted_delivery_world(api):
    """
    Build the identical delivery history both money variants are read from: a
    900.00 t lot at an OPEN depot, a 5527.20 t lot at a SURGE depot invisible to a
    ROUTINE waterfall, and a 1300 t routine order run through the waterfall.
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)
    panel = fx.create_panel(api, mine["id"], panel_code="P-1", pillar_recovery_allowed=True)
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

    # 1000 t of MEDIUM feed at zero moisture yields exactly 900.00 t at Depot A.
    near = fx.mint_lot(
        api,
        run["id"],
        depot_a["id"],
        screen_spec=MEDIUM,
        anticaking_ppm=30,
        input_tons=1000,
        moisture_pct=0.0,
    )
    # 6000 t of COARSE feed at 2 % moisture yields 5527.20 t at Depot B.
    far = fx.mint_lot(
        api,
        run["id"],
        depot_b["id"],
        screen_spec=COARSE,
        anticaking_ppm=30,
        input_tons=6000,
        moisture_pct=2.0,
    )
    fx.set_posture(api, depot_b["id"], DEPOT_SURGE, reason="storm staging")

    world = fx.active_contract(
        api, forecast_kwargs=FORECAST_KWARGS, contract_kwargs=CONTRACT_KWARGS
    )
    order = fx.create_order(
        api,
        world["contract"]["id"],
        depot_a["id"],
        requested_tons=1300,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=70.00,
        storm_priority=ROUTINE,
    )
    world.update(
        {
            "depot_a": depot_a,
            "depot_b": depot_b,
            "near_lot": near["lot"],
            "far_lot": far["lot"],
            "order": get_success_data(api.allocate_order(order["id"], fx.LOGISTICS)),
        }
    )
    return world


def test_per_event_shortfall_penalty_takes_the_uncapped_storm_free_product(api):
    """
    The per-event variant prices the short alone: 400.00 t at 22.00/t with the
    routine multiplier of 1.00, which is well under the 15 percent order-value cap
    of 13367.25, and it forgives no tolerance band whatsoever.

    PRD §3.9: "Hop one, on the order: `shorted_tons` becomes `requested_tons` minus
    `allocated_tons`, and `shortfall_penalty_usd` is computed as the smaller of two
    quantities — the shortfall tonnage multiplied by the contract's
    `failure_to_supply_penalty_per_ton` multiplied by a storm multiplier of 2.00
    for a `STORM_EMERGENCY` order or 1.00 for a `ROUTINE` one, and a cap of 15
    percent of the order's own value, that value being `requested_tons` multiplied
    by `guaranteed_price_per_ton` rounded half up to two decimal places — with the
    chosen quantity rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/shortfall_penalty_per_event_versus_season_aggregate_reconciliation
    """
    world = _shorted_delivery_world(api)
    order = world["order"]

    assert order["status"] == ORDER_SHORTED
    assert_tons(order["allocated_tons"], 900.00, "allocated_tons")
    assert_tons(order["shorted_tons"], 400.00, "shorted_tons")
    assert order["penalty_state"] == PENALTY_ACCRUED
    assert_money(order["shortfall_penalty_usd"], 8800.00, "shortfall_penalty_usd")

    contract = fx.refresh_contract(api, world["contract"]["id"])
    assert_money(contract["penalty_accrued_usd"], 8800.00, "penalty_accrued_usd")


def test_season_close_prices_the_same_history_in_aggregate_and_reconciles_the_delta(api):
    """
    The aggregate variant forgives the min-take tolerance band and drops both the
    storm multiplier and the per-order cap, so the same 900.00 t of fulfilment
    costs 68200.00 at season close against 8800.00 already booked event by event.

    PRD §3.8: "A tolerance band is then forgiven: `committed_tons` multiplied by the
    quantity 100 minus `min_take_pct`, divided by 100 — so a contract with a
    `min_take_pct` of 90 forgives the first 10 percent of its commitment outright."

    PRD §3.8: "The billable shortfall is the season shortfall minus that tolerance,
    floored at 0, and the `season_penalty_usd` is the billable shortfall multiplied
    by `failure_to_supply_penalty_per_ton`, rounded half up to two decimal places."

    PRD §3.8: "The `penalty_reconciliation_delta_usd` is then the
    `season_penalty_usd` minus the `penalty_accrued_usd` already booked event by
    event, rounded half up to two decimal places, and it is **signed** — negative
    whenever per-event accruals overshot the season view, which happens routinely
    because the per-event path forgives nothing."

    PRD §3.8: "Add a flat 25-point haircut when the contract's `status` is
    `FORFEITED`, and nothing otherwise."

    Design: Difficulty/dual_variant_calc/shortfall_penalty_per_event_versus_season_aggregate_reconciliation
    """
    world = _shorted_delivery_world(api)
    order = get_success_data(api.deliver_order(world["order"]["id"], fx.LOGISTICS))
    assert order["status"] == ORDER_DELIVERED
    assert order["penalty_state"] == PENALTY_ACCRUED

    closed = get_success_data(
        api.close_season(
            world["contract"]["id"], CONTRACT_ADMIN, f.note_payload("season closeout")
        )
    )

    # take_pct 18.00 is strictly below min_take_pct 80.
    assert closed["status"] == CONTRACT_FORFEITED
    assert_tons(closed["fulfilled_tons"], 900.00, "fulfilled_tons")
    # (5000 - 900) less the 1000 t tolerance band = 3100.00 billable t at 22.00/t.
    assert_money(closed["season_penalty_usd"], 68200.00, "season_penalty_usd")
    assert_money(closed["penalty_accrued_usd"], 8800.00, "penalty_accrued_usd")
    assert_money(
        closed["penalty_reconciliation_delta_usd"],
        59400.00,
        "penalty_reconciliation_delta_usd",
    )
    # 100 less an 8.00-point shortfall haircut less the 25-point forfeit haircut.
    assert_money(
        closed["supply_reliability_score"], 67.00, "supply_reliability_score"
    )
