"""
Treatment yield and purity arithmetic, the contract fulfillment ledger, the storm
allocation waterfall and the shortfall penalty ledger.

Every expected figure below is re-derived from the PRD formulas of §3.5, §3.8 and
§3.9 under the decimal round-half-up discipline of §2.7: tonnage and money at two
decimal places, `purity_pct_nacl` at three.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f, fixtures as fx
from test_helpers.assertions import (
    assert_amount,
    assert_lot_tonnage,
    assert_money,
    assert_purity,
    assert_tons,
)
from test_helpers.constants import (
    ALLOCATION_RESERVED,
    CHEMICAL_FEEDSTOCK,
    COARSE,
    COVERED,
    DECISION_PASS,
    DEPOT_SURGE,
    FINE,
    FOOD_GRADE,
    HIGHWAY_DEICING,
    JURISDICTION_MUNICIPAL,
    LOT_AVAILABLE,
    MEDIUM,
    METHOD_SEVERITY_WEIGHTED,
    ORDER_ALLOCATED,
    ORDER_DELIVERED,
    ORDER_SHORTED,
    ORIGIN_WATERFALL,
    PENALTY_ACCRUED,
    PENALTY_NONE,
    QC_PASSED,
    RUN_HOISTED,
)
from test_helpers.test_users import CONTRACT_ADMIN, LAB_LEAD, LAB_TECH, LOGISTICS

# A 24,000 t/day shaft: effective capacity 24,000.00 and hourly capacity 1,000.
MINE = {"name": "Retsof Salt Mine", "state_code": "NY", "rated_hoist_tons_per_day": 24000}

# 100,000 gross tons at 50 % extraction, grade 96.00, insolubles 2.00 and no pillar
# recovery: base 50,000, grade factor 1.00, no insolubles penalty, under the 72 %
# cap, so `recoverable_tons` is 50,000.00.
PANEL_96 = {
    "panel_code": "P-1",
    "gross_tons_in_place": 100000,
    "extraction_ratio_pct": 50,
    "grade_pct_nacl": 96.00,
    "insolubles_pct": 2.00,
}

WINDOW = {
    "hoist_window_start": "2026-08-02T00:00:00Z",
    "hoist_window_end": "2026-08-03T00:00:00Z",
}

FORECAST = {
    "season_code": "2026-27",
    "region_code": "NY-CENTRAL",
    "normal_season_tons": 20000,
    "severity_index": 60,
    "prior_season_1_actual_tons": 21000,
    "prior_season_2_actual_tons": 19000,
    "prior_season_3_actual_tons": 18000,
    "method": METHOD_SEVERITY_WEIGHTED,
    "preseason_lock_date": "2026-10-15T00:00:00Z",
}


def test_three_screen_cuts_on_one_run_yield_three_distinct_tonnages(api):
    """
    Three batches of 1,000 dry tons off the same hoisted run, cut COARSE, MEDIUM and
    FINE, must land on three different tonnages and three different purities because
    each screen cut carries its own yield factor and its own purity upgrade.
    "Each screen cut carries a yield factor — 0.94 for `COARSE`, 0.90 for `MEDIUM`,
    0.82 for `FINE` — and a rework loss factor of 0.97 raised to the power of the
    current `rework_count`, which is exactly 1 while `rework_count` is 0."

    Design: Corner/calculations/three_screen_specs_on_one_run_yield_three_distinct_tonnages
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=PANEL_96,
        hoisted_tons=3000,
        planned_tons=3000,
        **WINDOW,
    )
    run_id = world["run"]["id"]
    depot = fx.create_depot(
        api,
        name="Syracuse Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=500,
        outbound_freight_rate_per_ton=12.500,
    )

    coarse = validate_success(
        api.create_batch(
            f.batch_payload(
                run_id,
                depot["id"],
                product_line=HIGHWAY_DEICING,
                screen_spec=COARSE,
                anticaking_ppm=20.00,
                corrosion_inhibitor_pct=0.50,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )
    medium = validate_success(
        api.create_batch(
            f.batch_payload(
                run_id,
                depot["id"],
                product_line=CHEMICAL_FEEDSTOCK,
                screen_spec=MEDIUM,
                anticaking_ppm=10.00,
                corrosion_inhibitor_pct=0.00,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )
    fine = validate_success(
        api.create_batch(
            f.batch_payload(
                run_id,
                depot["id"],
                product_line=FOOD_GRADE,
                screen_spec=FINE,
                anticaking_ppm=8.00,
                corrosion_inhibitor_pct=0.00,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )

    # 1000 * 0.94 / 0.90 / 0.82, dry feed and no rework loss.
    assert_tons(coarse["yield_tons"], 940.00, "yield_tons")
    assert_tons(medium["yield_tons"], 900.00, "yield_tons")
    assert_tons(fine["yield_tons"], 820.00, "yield_tons")
    # 96.00 panel grade plus the cut's upgrade of 0.5 / 1.2 / 2.5 points.
    assert_purity(coarse["purity_pct_nacl"], 96.500)
    assert_purity(medium["purity_pct_nacl"], 97.200)
    assert_purity(fine["purity_pct_nacl"], 98.500)

    run = fx.refresh_run(api, run_id)
    assert run["open_batch_count"] == 3, (
        f"three pending batches, got open_batch_count {run['open_batch_count']}"
    )
    assert run["status"] == RUN_HOISTED, (
        f"a run with pending batches stays HOISTED, got {run['status']}"
    )
    # No quality-control pass yet, so no tonnage exists at the depot.
    depot_after = fx.refresh_depot(api, depot["id"])
    assert_tons(depot_after["covered_stored_tons"], 0.00, "covered_stored_tons")


def test_purity_upgrade_is_clamped_by_the_ceiling(api):
    """
    A 99.60 % NaCl panel screened FINE would compute 102.100 purity, which the 99.9
    ceiling clamps to 99.900, while the independent FINE yield factor of 0.82 still
    applies in full and the minted lot inherits the clamped assay.
    "The batch's `purity_pct_nacl` is the `grade_pct_nacl` of the panel behind the
    feeding run plus that upgrade, capped at a ceiling of 99.9, rounded half up to
    three decimal places."

    Design: Corner/calculations/purity_upgrade_is_clamped_by_the_ceiling_constant
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs={
            "panel_code": "P-HG",
            "gross_tons_in_place": 100000,
            "extraction_ratio_pct": 50,
            "grade_pct_nacl": 99.60,
            "insolubles_pct": 0.50,
        },
        hoisted_tons=500,
        planned_tons=500,
        **WINDOW,
    )
    depot = fx.create_depot(
        api,
        name="Syracuse Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=500,
        outbound_freight_rate_per_ton=12.500,
    )

    batch = validate_success(
        api.create_batch(
            f.batch_payload(
                world["run"]["id"],
                depot["id"],
                product_line=FOOD_GRADE,
                screen_spec=FINE,
                anticaking_ppm=8.00,
                corrosion_inhibitor_pct=0.00,
                input_tons=500,
                moisture_pct=0.00,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )
    assert_purity(batch["purity_pct_nacl"], 99.900)
    assert_tons(batch["yield_tons"], 410.00, "yield_tons")
    # Grade tier 1.00 and no insolubles penalty at 0.50 %: 100000 * 0.50 = 50000.00.
    assert_tons(
        fx.refresh_panel(api, world["panel"]["id"])["recoverable_tons"],
        50000.00,
        "recoverable_tons",
    )

    # 99.900 clears the FOOD_GRADE minimum of 99.6, so the pass mints a lot.
    passed = validate_success(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD), 200
    )
    assert passed["qc_state"] == QC_PASSED, f"expected PASSED, got {passed['qc_state']}"

    lot = fx.lot_of_batch(api, batch["id"])
    assert_purity(lot["purity_pct_nacl"], 99.900)
    assert_lot_tonnage(lot, on_hand=410.00, reserved=0.00, available=410.00)


def test_yield_rounds_half_up_once_at_two_decimals(api):
    """
    Two batches whose exact yields fall on a half-cent and on a repeating third
    decimal: 1,003 tons at 2.50 % moisture computes 919.2495 and must be published as
    919.25, and 1,000 tons at 3.33 % moisture computes 908.698 and must be published
    as 908.70 — one half-up rounding applied at the end of the whole product.
    "The batch's `yield_tons` is `input_tons` multiplied by the screen's yield factor,
    multiplied by one minus `moisture_pct` divided by 100, multiplied by the rework
    loss factor, rounded half up to two decimal places."
    "All tonnage and monetary arithmetic is performed in decimal, never in binary
    floating point."

    Design: Corner/calculations/yield_rounds_half_up_once_at_two_decimals
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=PANEL_96,
        hoisted_tons=3000,
        planned_tons=3000,
        **WINDOW,
    )
    run_id = world["run"]["id"]
    depot = fx.create_depot(
        api,
        name="Syracuse Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=500,
        outbound_freight_rate_per_ton=12.500,
    )

    half_cent = validate_success(
        api.create_batch(
            f.batch_payload(
                run_id,
                depot["id"],
                product_line=HIGHWAY_DEICING,
                screen_spec=COARSE,
                anticaking_ppm=20.00,
                corrosion_inhibitor_pct=0.50,
                input_tons=1003,
                moisture_pct=2.50,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )
    repeating = validate_success(
        api.create_batch(
            f.batch_payload(
                run_id,
                depot["id"],
                product_line=HIGHWAY_DEICING,
                screen_spec=COARSE,
                anticaking_ppm=20.00,
                corrosion_inhibitor_pct=0.50,
                input_tons=1000,
                moisture_pct=3.33,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )

    # 1003 * 0.94 * 0.975 = 919.2495 exactly, which rounds half up to 919.25.
    assert_tons(half_cent["yield_tons"], 919.25, "yield_tons")
    # 1000 * 0.94 * 0.9667 = 908.698, which rounds half up to 908.70.
    assert_tons(repeating["yield_tons"], 908.70, "yield_tons")
    # Purity is a separate computation and is untouched by moisture.
    assert_purity(half_cent["purity_pct_nacl"], 96.500)
    assert_purity(repeating["purity_pct_nacl"], 96.500)
    assert half_cent["rework_count"] == 0, (
        f"a new batch opens at rework_count 0, got {half_cent['rework_count']}"
    )


def test_ledger_counts_delivered_only_while_the_take_band_counts_every_live_order(api):
    """
    One contract with a delivered 300-ton order and a still-allocated 200-ton order:
    the fulfillment side of the ledger sees only the delivered 300 tons, while the
    take-band side has already spent all 500 tons.
    "`fulfilled_tons` is the sum of `allocated_tons` across the contract's delivery
    orders whose `status` is `DELIVERED` — only delivered orders count, so allocating
    tonnage moves nothing here."
    "The tonnage a contract has already spoken for is the sum of `requested_tons`
    across its delivery orders whose `status` is `REQUESTED`, `ALLOCATED`, `SHORTED`
    or `DELIVERED` — every order that has not been withdrawn, whether or not it was
    ever filled."

    Design: Corner/calculations/ledger_counts_delivered_only_while_take_band_counts_every_live_order
    """
    world = fx.lot_at_depot(
        api,
        mine_kwargs=MINE,
        panel_kwargs=PANEL_96,
        depot_kwargs={
            "name": "Syracuse Depot",
            "state_code": "NY",
            "covered_capacity_tons": 5000,
            "open_pad_capacity_tons": 5000,
            "loadout_rate_tons_per_hour": 500,
            "outbound_freight_rate_per_ton": 12.500,
        },
        run_kwargs={"planned_tons": 3000, **WINDOW},
        hoisted_tons=3000,
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=20.00,
        corrosion_inhibitor_pct=0.50,
        input_tons=1000,
        moisture_pct=0.00,
        storage_kind=COVERED,
    )
    depot_id = world["depot"]["id"]
    # 1000 * 0.94 on the ground, which covers the 500-ton activation floor.
    assert_tons(world["lot"]["tons_on_hand"], 940.00, "tons_on_hand")

    contract = fx.active_contract(
        api,
        forecast_kwargs=FORECAST,
        contract_kwargs={
            "customer_name": "City of Syracuse DPW",
            "jurisdiction_level": JURISDICTION_MUNICIPAL,
            "state_code": "NY",
            "product_line": HIGHWAY_DEICING,
            "committed_tons": 1000,
            "guaranteed_price_per_ton": 80.00,
            "min_take_pct": 50,
            "max_take_pct": 110,
            "failure_to_supply_penalty_per_ton": 30.00,
            "price_guarantee_cap_pct": 10,
        },
    )["contract"]

    delivered = fx.create_order(
        api,
        contract["id"],
        depot_id,
        requested_tons=300,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )
    fx.allocate(api, delivered["id"])
    delivered = validate_success(api.deliver_order(delivered["id"], LOGISTICS), 200)
    assert delivered["status"] == ORDER_DELIVERED, (
        f"expected DELIVERED, got {delivered['status']}"
    )
    assert_tons(delivered["allocated_tons"], 300.00, "allocated_tons")

    still_open = fx.create_order(
        api,
        contract["id"],
        depot_id,
        requested_tons=200,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )
    still_open = validate_success(api.allocate_order(still_open["id"], LOGISTICS), 200)
    assert still_open["status"] == ORDER_ALLOCATED, (
        f"expected ALLOCATED, got {still_open['status']}"
    )

    ledger = validate_success(api.get_contract_ledger(contract["id"], CONTRACT_ADMIN), 200)
    assert_tons(ledger["committed_tons"], 1000.00, "committed_tons")
    # Only the delivered order counts here.
    assert_tons(ledger["fulfilled_tons"], 300.00, "fulfilled_tons")
    assert_tons(ledger["open_committed_tons"], 700.00, "open_committed_tons")
    assert_amount(ledger["take_pct"], 30.00, 2, "take_pct")
    # Both live orders count here: 300 + 200.
    assert_tons(ledger["take_band_consumed_tons"], 500.00, "take_band_consumed_tons")
    # 1000 * 110 / 100.
    assert_tons(ledger["take_band_limit_tons"], 1100.00, "take_band_limit_tons")
    assert_money(ledger["penalty_accrued_usd"], 0.00, "penalty_accrued_usd")
    assert ledger["accrued_penalty_order_count"] == 0, (
        f"no shorts occurred, got accrued_penalty_order_count "
        f"{ledger['accrued_penalty_order_count']}"
    )
    # Coverage is read live off the lots, so the delivered tonnage is gone and the
    # 200 tons still reserved are excluded: 940 - 300 - 200.
    assert_tons(ledger["preseason_coverage_tons"], 440.00, "preseason_coverage_tons")
    assert_tons(
        ledger["preseason_coverage_required_tons"], 500.00, "preseason_coverage_required_tons"
    )

    lot = fx.refresh_lot(api, world["lot"]["id"])
    assert_lot_tonnage(lot, on_hand=640.00, reserved=200.00, available=440.00)
    assert lot["lot_state"] == LOT_AVAILABLE, (
        f"the lot still holds saleable tonnage, got {lot['lot_state']}"
    )

    posture = fx.storage_posture(api, depot_id)
    assert_tons(posture["covered_stored_tons"], 640.00, "covered_stored_tons")
    assert_amount(posture["covered_utilization_pct"], 12.80, 2, "covered_utilization_pct")
    assert_tons(posture["reserved_tons"], 200.00, "reserved_tons")


def test_waterfall_fills_the_local_lot_first_then_overflows_to_the_cheaper_depot(api):
    """
    Three lots of highway deicing salt sit in New York: a small 282-ton pile at the
    depot the order names, a 940-ton pile at a cheap-to-ship depot and a 940-ton pile
    at a dearer one. A 1,000-ton order must drain the local pile first even though it
    is the smallest, then take the balance from the cheaper of the two remote depots
    and never touch the dearer one.
    "Lots held at the order's own `depot_id` sort ahead of lots held anywhere else —
    the local shed is drawn down first."
    "Then by the holding depot's `outbound_freight_rate_per_ton`, ascending — the
    cheapest depot to ship out of comes next."

    Design: Corner/calculations/waterfall_fills_the_same_depot_lot_first_then_overflows_to_the_cheaper_one
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=PANEL_96,
        hoisted_tons=3000,
        planned_tons=3000,
        **WINDOW,
    )
    run_id = world["run"]["id"]

    local = fx.create_depot(
        api,
        name="Syracuse Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=500,
        outbound_freight_rate_per_ton=12.500,
    )
    cheap = fx.create_depot(
        api,
        name="Rochester Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=500,
        outbound_freight_rate_per_ton=6.000,
    )
    dear = fx.create_depot(
        api,
        name="Buffalo Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=500,
        outbound_freight_rate_per_ton=9.000,
    )

    batch_kwargs = {
        "product_line": HIGHWAY_DEICING,
        "screen_spec": COARSE,
        "anticaking_ppm": 20.00,
        "corrosion_inhibitor_pct": 0.50,
        "moisture_pct": 0.00,
        "storage_kind": COVERED,
    }
    # 300 * 0.94 = 282.00 at the local depot, 1000 * 0.94 = 940.00 at each remote one.
    local_lot = fx.mint_lot(api, run_id, local["id"], input_tons=300, **batch_kwargs)["lot"]
    cheap_lot = fx.mint_lot(api, run_id, cheap["id"], input_tons=1000, **batch_kwargs)["lot"]
    dear_lot = fx.mint_lot(api, run_id, dear["id"], input_tons=1000, **batch_kwargs)["lot"]
    assert_tons(local_lot["tons_available"], 282.00, "tons_available")

    contract = fx.active_contract(
        api,
        forecast_kwargs=FORECAST,
        contract_kwargs={
            "customer_name": "Onondaga County Highways",
            "jurisdiction_level": JURISDICTION_MUNICIPAL,
            "state_code": "NY",
            "product_line": HIGHWAY_DEICING,
            "committed_tons": 1000,
            "guaranteed_price_per_ton": 80.00,
            "min_take_pct": 80,
            "max_take_pct": 110,
            "failure_to_supply_penalty_per_ton": 30.00,
            "price_guarantee_cap_pct": 10,
        },
    )["contract"]

    order = fx.create_order(
        api,
        contract["id"],
        local["id"],
        requested_tons=1000,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )

    allocated = validate_success(api.allocate_order(order["id"], LOGISTICS), 200)

    assert allocated["status"] == ORDER_ALLOCATED, (
        f"the pool covers the order in full, expected ALLOCATED, got {allocated['status']}"
    )
    assert_tons(allocated["allocated_tons"], 1000.00, "allocated_tons")
    assert_tons(allocated["shorted_tons"], 0.00, "shorted_tons")
    assert allocated["penalty_state"] == PENALTY_NONE, (
        f"a fully filled order accrues nothing, got {allocated['penalty_state']}"
    )
    assert_money(allocated["shortfall_penalty_usd"], 0.00, "shortfall_penalty_usd")

    rows = fx.allocations_of_order(api, order["id"])
    assert len(rows) == 2, f"expected two waterfall rows, got {len(rows)}"
    by_rank = {row["rank_position"]: row for row in rows}
    assert sorted(by_rank) == [1, 2], (
        f"rank_position counts up from 1, got {sorted(by_rank)}"
    )
    first, second = by_rank[1], by_rank[2]
    assert first["stockpile_lot_id"] == local_lot["id"], (
        "rank 1 must be the lot at the order's own depot"
    )
    assert_tons(first["tons"], 282.00, "tons")
    assert second["stockpile_lot_id"] == cheap_lot["id"], (
        "rank 2 must be the cheaper of the two remote depots"
    )
    # 1000 outstanding less the 282 the local shed could give.
    assert_tons(second["tons"], 718.00, "tons")
    for row in rows:
        assert row["origin"] == ORIGIN_WATERFALL, (
            f"a waterfall row carries origin WATERFALL, got {row['origin']}"
        )
        assert row["state"] == ALLOCATION_RESERVED, (
            f"a fresh allocation row is RESERVED, got {row['state']}"
        )

    # Reserving moves nothing out of the pile: on-hand stands still everywhere.
    assert_lot_tonnage(
        fx.refresh_lot(api, local_lot["id"]), on_hand=282.00, reserved=282.00, available=0.00
    )
    assert_lot_tonnage(
        fx.refresh_lot(api, cheap_lot["id"]), on_hand=940.00, reserved=718.00, available=222.00
    )
    # The dearer depot was ranked third and never reached.
    assert_lot_tonnage(
        fx.refresh_lot(api, dear_lot["id"]), on_hand=940.00, reserved=0.00, available=940.00
    )
    drained = fx.refresh_lot(api, local_lot["id"])
    assert drained["lot_state"] == LOT_AVAILABLE, (
        f"a fully reserved lot is not depleted, got {drained['lot_state']}"
    )


def test_shortfall_haircut_saturates_at_forty_points_while_the_penalty_hits_its_cap(api):
    """
    A 2,600-ton routine order finds only 94 tons in an admissible depot, because the
    1,880-ton pile sits at a depot the depot manager has put into SURGE and a routine
    order may not draw on a surge depot. The 2,506-ton short prices out at 75,180 by
    tonnage but is capped at 15 percent of the order's value, and the reliability
    haircut it implies — 125.30 points — saturates at 40.
    "Hop one, on the order: `shorted_tons` becomes `requested_tons` minus
    `allocated_tons`, and `shortfall_penalty_usd` is computed as the smaller of two
    quantities — the shortfall tonnage multiplied by the contract's
    `failure_to_supply_penalty_per_ton` multiplied by a storm multiplier of 2.00 for a
    `STORM_EMERGENCY` order or 1.00 for a `ROUTINE` one, and a cap of 15 percent of
    the order's own value, that value being `requested_tons` multiplied by
    `guaranteed_price_per_ton` rounded half up to two decimal places — with the chosen
    quantity rounded half up to two decimal places."
    "Sum the `shorted_tons` across the contract's delivery orders whose
    `penalty_state` is `ACCRUED`; take that cumulative shortfall multiplied by 100,
    divided by `committed_tons`, rounded half up to two decimal places, and cap the
    resulting haircut at 40 points."

    Design: Corner/calculations/shortfall_haircut_saturates_at_forty_points_while_penalty_hits_the_per_event_cap
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=PANEL_96,
        hoisted_tons=2500,
        planned_tons=2500,
        **WINDOW,
    )
    run_id = world["run"]["id"]

    surging = fx.create_depot(
        api,
        name="Watertown Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=600,
        outbound_freight_rate_per_ton=6.000,
    )
    open_depot = fx.create_depot(
        api,
        name="Syracuse Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=500,
        outbound_freight_rate_per_ton=12.500,
    )
    batch_kwargs = {
        "product_line": HIGHWAY_DEICING,
        "screen_spec": COARSE,
        "anticaking_ppm": 20.00,
        "corrosion_inhibitor_pct": 0.50,
        "moisture_pct": 0.00,
        "storage_kind": COVERED,
    }
    # 2000 * 0.94 = 1880.00 behind the surge gate, 100 * 0.94 = 94.00 in the open.
    big_lot = fx.mint_lot(api, run_id, surging["id"], input_tons=2000, **batch_kwargs)["lot"]
    small_lot = fx.mint_lot(api, run_id, open_depot["id"], input_tons=100, **batch_kwargs)["lot"]
    surged = fx.set_posture(
        api, surging["id"], DEPOT_SURGE, reason="Regional storm posture declared"
    )
    assert surged["depot_state"] == DEPOT_SURGE, (
        f"expected SURGE, got {surged['depot_state']}"
    )

    contract = fx.active_contract(
        api,
        forecast_kwargs=FORECAST,
        contract_kwargs={
            "customer_name": "Jefferson County DPW",
            "jurisdiction_level": JURISDICTION_MUNICIPAL,
            "state_code": "NY",
            "product_line": HIGHWAY_DEICING,
            "committed_tons": 2000,
            "guaranteed_price_per_ton": 80.00,
            "min_take_pct": 80,
            "max_take_pct": 130,
            "failure_to_supply_penalty_per_ton": 30.00,
            "price_guarantee_cap_pct": 10,
        },
    )["contract"]
    # Activation cleared its coverage gate because a SURGE depot still counts toward
    # pre-season coverage: 1880.00 + 94.00 against a 1,600-ton requirement.
    # The awarded value is 2000 * 80.00.
    assert_money(contract["contract_value_usd"], 160000.00, "contract_value_usd")

    order = fx.create_order(
        api,
        contract["id"],
        open_depot["id"],
        requested_tons=2600,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )

    shorted = validate_success(api.allocate_order(order["id"], LOGISTICS), 200)

    assert shorted["status"] == ORDER_SHORTED, (
        f"only 94 of 2600 tons were admissible, expected SHORTED, got {shorted['status']}"
    )
    assert_tons(shorted["allocated_tons"], 94.00, "allocated_tons")
    assert_tons(shorted["shorted_tons"], 2506.00, "shorted_tons")
    # By tonnage 2506 * 30.00 * 1.00 = 75180.00; the cap is 0.15 * 2600 * 80.00.
    assert_money(shorted["shortfall_penalty_usd"], 31200.00, "shortfall_penalty_usd")
    assert shorted["penalty_state"] == PENALTY_ACCRUED, (
        f"a short accrues its penalty, got {shorted['penalty_state']}"
    )

    ledger = validate_success(api.get_contract_ledger(contract["id"], CONTRACT_ADMIN), 200)
    assert_money(ledger["penalty_accrued_usd"], 31200.00, "penalty_accrued_usd")
    assert ledger["accrued_penalty_order_count"] == 1, (
        f"one accrued order, got {ledger['accrued_penalty_order_count']}"
    )
    # 2506 * 100 / 2000 = 125.30 points of haircut, capped at 40: 100 - 40.
    assert ledger["supply_reliability_score"] == 60, (
        f"expected a score of 60 after the 40-point cap, got "
        f"{ledger['supply_reliability_score']}"
    )
    # 31200.00 is far past 5 percent of 160000.00.
    assert ledger["breach_watch"] is True, (
        f"expected breach_watch true, got {ledger['breach_watch']}"
    )
    assert_tons(ledger["fulfilled_tons"], 0.00, "fulfilled_tons")
    # Coverage is a live read: the surge pile still counts, the reserved 94 tons do not.
    assert_tons(ledger["preseason_coverage_tons"], 1880.00, "preseason_coverage_tons")
    assert_tons(
        ledger["preseason_coverage_required_tons"], 1600.00, "preseason_coverage_required_tons"
    )

    rows = fx.allocations_of_order(api, order["id"])
    assert len(rows) == 1, f"only the open depot was admissible, got {len(rows)} rows"
    assert rows[0]["stockpile_lot_id"] == small_lot["id"], (
        "the single reservation must come from the OPEN depot's lot"
    )
    assert_lot_tonnage(
        fx.refresh_lot(api, big_lot["id"]), on_hand=1880.00, reserved=0.00, available=1880.00
    )
