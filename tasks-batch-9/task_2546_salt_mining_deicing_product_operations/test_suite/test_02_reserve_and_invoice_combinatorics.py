"""
Formulas whose terms interact rather than merely accumulate.

A panel's recoverable reserve multiplies a stepped grade tier by a capped
insolubles penalty, adds a bonus that exists only while the parent mine is
compliant, and only then clips the whole thing against a geological ceiling. An
invoice, at the other end of the chain, pins the order in which its lines are
rounded, which is worth whole cents on a multi-line order.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_lot_tonnage, assert_money, assert_tons
from test_helpers.constants import (
    COARSE,
    COVERED,
    HIGHWAY_DEICING,
    JURISDICTION_MUNICIPAL,
    METHOD_SEVERITY_WEIGHTED,
    MODE_TRUCK,
    ORDER_ALLOCATED,
    ORDER_DELIVERED,
    PANEL_PLANNED,
    ROUTINE,
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

# Geometry shared by both reserve panels: 1,000,000 t in place at 60 % extraction,
# assayed at exactly the top grade tier with 5.0 % insolubles.
PANEL_GEOMETRY = dict(
    gross_tons_in_place=1000000,
    extraction_ratio_pct=60,
    grade_pct_nacl=95.0,
    insolubles_pct=5.0,
)


def test_recoverable_reserve_combines_tier_penalty_and_pillar_bonus_under_the_cap(api):
    """
    A panel allowed secondary recovery under a compliant mine earns the additive
    bonus on top of the tier-and-penalty product, and the 72 percent ceiling is not
    reached, so the combined figure survives the cap unchanged.

    PRD §3.2: "Choose a single grade factor from the assayed `grade_pct_nacl`: 1.00
    when the grade is at least 95.0; 0.96 when the grade is at least 90.0 but below
    95.0; 0.88 when the grade is below 90.0."

    PRD §3.2: "Take `insolubles_pct` minus 3.0, floor that difference at zero,
    multiply it by 0.012, and cap the result at 0.20."

    PRD §3.2: "Multiply the base tonnage by the grade factor, then by one minus the
    insolubles penalty, then add the pillar bonus."

    PRD §3.2: "Take the smaller of that combined figure and 72 percent of
    `gross_tons_in_place`, and round the winner half up to two decimal places."

    Design: Difficulty/combinatorial_formula/panel_recoverable_tons_tier_times_penalty_plus_conditional_bonus_under_cap
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)

    panel = get_success_data(
        api.create_panel(
            f.panel_payload(
                mine["id"],
                panel_code="P-BONUS",
                pillar_recovery_allowed=True,
                **PANEL_GEOMETRY,
            ),
            MINE_PLANNER,
        ),
        201,
    )

    # Base 600000.00 x tier 1.00 x (1 - 0.024) = 585600.00, plus the 32000.00 bonus
    # on the 400000.00 t left behind, all under the 720000.00 hard cap.
    assert_tons(panel["recoverable_tons"], 617600.00, "recoverable_tons")
    assert panel["status"] == PANEL_PLANNED
    assert_tons(panel["mined_tons"], 0.00, "mined_tons")
    assert panel["pillar_recovery_allowed"] is True


def test_pillar_bonus_is_the_only_difference_between_two_identical_panels(api):
    """
    Two panels with identical geometry under the same compliant mine differ by
    exactly the additive pillar term, which is the whole of the 32000.00 t gap.

    PRD §3.2: "In every other case — the flag is false, or the mine is `CITED`, or
    the mine is under a `WITHDRAWAL_ORDER` — the bonus is zero."

    PRD §3.2: "Because the cap is applied **after** the bonus is added, the cap also
    clips the pillar bonus; a panel already near its geological ceiling gains
    nothing from being allowed secondary recovery."

    Design: Difficulty/combinatorial_formula/panel_recoverable_tons_tier_times_penalty_plus_conditional_bonus_under_cap
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)

    with_bonus = get_success_data(
        api.create_panel(
            f.panel_payload(
                mine["id"],
                panel_code="P-BONUS",
                pillar_recovery_allowed=True,
                **PANEL_GEOMETRY,
            ),
            MINE_PLANNER,
        ),
        201,
    )
    without_bonus = get_success_data(
        api.create_panel(
            f.panel_payload(
                mine["id"],
                panel_code="P-NOBONUS",
                pillar_recovery_allowed=False,
                **PANEL_GEOMETRY,
            ),
            MINE_PLANNER,
        ),
        201,
    )

    assert_tons(with_bonus["recoverable_tons"], 617600.00, "recoverable_tons")
    assert_tons(without_bonus["recoverable_tons"], 585600.00, "recoverable_tons")
    assert_tons(
        round(
            float(with_bonus["recoverable_tons"])
            - float(without_bonus["recoverable_tons"]),
            2,
        ),
        32000.00,
        "pillar bonus term",
    )


def _two_line_order_world(api):
    """
    Leave exactly 100.10 t at Depot A and 5427.10 t at Depot B, so a 200.2 t routine
    order is filled by two allocation rows of exactly 100.10 t drawn from two depots.
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
        screen_spec=COARSE,
        anticaking_ppm=30,
        input_tons=6000,
        moisture_pct=2.0,
    )
    depot_b = fx.create_depot(api, name="Depot B", outbound_freight_rate_per_ton=4.00)

    shipment = fx.create_shipment(
        api,
        world["lot"]["id"],
        world["depot"]["id"],
        depot_b["id"],
        5427.10,
        mode=MODE_TRUCK,
        load_window_start="2026-08-12T08:00:00Z",
        load_window_end="2026-08-12T10:00:00Z",
        destination_storage_kind=COVERED,
    )
    get_success_data(api.load_shipment(shipment["id"], LOGISTICS))
    shipment = get_success_data(api.receive_shipment(shipment["id"], LOGISTICS))

    origin_lot = fx.refresh_lot(api, world["lot"]["id"])
    assert_lot_tonnage(origin_lot, 100.10, 0.00, 100.10)

    world.update(fx.active_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS))
    order = fx.create_order(
        api,
        world["contract"]["id"],
        world["depot"]["id"],
        requested_tons=200.2,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=70.00,
        storm_priority=ROUTINE,
    )
    world.update(
        {
            "depot_b": depot_b,
            "origin_lot": origin_lot,
            "received_lot_id": shipment["received_lot_id"],
            "order": get_success_data(api.allocate_order(order["id"], LOGISTICS)),
        }
    )
    return world


def test_waterfall_cuts_two_equal_lines_local_shed_first(api):
    """
    The order's own depot is drawn down before the remote one, so the 200.2 t
    request becomes two 100.10 t rows whose rank positions record the walk.

    PRD §3.9: "Lots held at the order's own `depot_id` sort ahead of lots held
    anywhere else — the local shed is drawn down first."

    PRD §3.9: "For each, the tonnage taken is the smaller of the tonnage still
    outstanding on the order and that lot's `tons_available`, and an allocation row
    is written with `tons` equal to that amount, `origin` set to `WATERFALL`, `state`
    set to `RESERVED`, and `rank_position` set to its position in the walk counting
    up from 1."

    Design: Difficulty/combinatorial_formula/delivery_invoice_per_line_rounding_before_summation_two_lots
    """
    world = _two_line_order_world(api)

    assert world["order"]["status"] == ORDER_ALLOCATED
    assert_tons(world["order"]["allocated_tons"], 200.20, "allocated_tons")

    rows = fx.allocations_of_order(api, world["order"]["id"])
    assert len(rows) == 2, f"expected two allocation rows, got {len(rows)}"
    assert_tons(rows[0]["tons"], 100.10, "tons")
    assert_tons(rows[1]["tons"], 100.10, "tons")
    assert rows[0]["rank_position"] == 1
    assert rows[1]["rank_position"] == 2
    assert rows[0]["stockpile_lot_id"] == world["origin_lot"]["id"]
    assert rows[1]["stockpile_lot_id"] == world["received_lot_id"]


def test_invoice_rounds_each_line_to_cents_before_summing_them(api):
    """
    Each 100.1 t line prices at 6861.855 and rounds up to 6861.86, so the product
    subtotal is 13723.72 — the forbidden sum-then-round order would report 13723.71
    and an invoice total one cent light.

    PRD §2.7: "Summing raw products and rounding once at the end is wrong and
    differs by whole cents on multi-line orders."

    PRD §3.9: "The order's `product_subtotal_usd` is the sum of the already-rounded
    product lines and its `freight_subtotal_usd` is the sum of the already-rounded
    freight lines."

    PRD §3.9: "The order's `storm_surcharge_usd` is 6 percent of the sum of those
    two subtotals, rounded half up to two decimal places, when the order's
    `storm_priority` is `STORM_EMERGENCY`, and is exactly 0.00 when it is `ROUTINE`."

    PRD §3.9: "The order's `invoice_total_usd` is then the `product_subtotal_usd`
    plus the `freight_subtotal_usd` plus the `storm_surcharge_usd` minus the
    `guarantee_credit_usd`, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/delivery_invoice_per_line_rounding_before_summation_two_lots
    """
    world = _two_line_order_world(api)

    delivered = get_success_data(api.deliver_order(world["order"]["id"], LOGISTICS))

    assert delivered["status"] == ORDER_DELIVERED
    assert_money(delivered["product_subtotal_usd"], 13723.72, "product_subtotal_usd")
    # 100.10 t at each source depot's own rate of 4.000/t, rounded per line.
    assert_money(delivered["freight_subtotal_usd"], 800.80, "freight_subtotal_usd")
    assert_money(delivered["storm_surcharge_usd"], 0.00, "storm_surcharge_usd")
    # A market of 70.00 sits below the unrounded 75.405 guarantee ceiling.
    assert_money(delivered["guarantee_credit_usd"], 0.00, "guarantee_credit_usd")
    assert_money(delivered["invoice_total_usd"], 14524.52, "invoice_total_usd")

    contract = fx.refresh_contract(api, world["contract"]["id"])
    assert_tons(contract["fulfilled_tons"], 200.20, "fulfilled_tons")
