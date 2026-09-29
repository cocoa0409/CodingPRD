"""
Forward moves and their exact inverses, on two different conserved quantities.

Tonnage is conserved on the pile: a hand-written reservation promises salt without
moving it, and releasing that promise puts the three lot figures back where they
stood, to the hundredth of a ton. Money is conserved on the contract ledger: a
waived penalty is re-derived out of the ledger to the cent while the order keeps the
charge it was assessed and every ton it had reserved.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PENALTY_NOT_ACCRUED
from test_helpers.assertions import (
    assert_lot_tonnage,
    assert_money,
    assert_penalty_ledger_invariant,
    assert_tons,
)
from test_helpers.constants import (
    ALLOCATION_RELEASED,
    ALLOCATION_RESERVED,
    COARSE,
    DEPOT_SURGE,
    HIGHWAY_DEICING,
    JURISDICTION_MUNICIPAL,
    LOT_AVAILABLE,
    MEDIUM,
    METHOD_SEVERITY_WEIGHTED,
    ORDER_REQUESTED,
    ORDER_SHORTED,
    ORIGIN_MANUAL,
    PENALTY_ACCRUED,
    PENALTY_WAIVED,
    ROUTINE,
)
from test_helpers.test_users import COMPLIANCE, LOGISTICS

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


def _order_over_a_full_lot(api):
    """
    A 5527.20 t lot at an open depot, an active contract it covers, and one 2000 t
    routine order — none of it allocated, so the pile is untouched.
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
    assert_lot_tonnage(world["lot"], 5527.20, 0.00, 5527.20)

    world.update(fx.active_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS))
    world["order"] = fx.create_order(
        api,
        world["contract"]["id"],
        world["depot"]["id"],
        requested_tons=2000,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=70.00,
        storm_priority=ROUTINE,
    )
    return world


def test_a_manual_reservation_promises_tonnage_without_moving_the_pile(api):
    """
    1200 t of a 5527.20 t lot changes column but not total: reserved rises, available
    falls by the identical figure, and on-hand does not budge, with the invariant
    4327.20 == 5527.20 - 1200.00 exact at two decimals. The order it serves counts the
    tonnage without leaving `REQUESTED`.

    PRD §3.6: "Three tonnage figures live on each lot, and their relationship is a
    **conserved-quantity invariant** that must hold exactly, with zero drift at two
    decimal places, after every request that touches the lot: `tons_available` equals
    `tons_on_hand` minus the sum of `tons` across the lot's allocations whose `state` is
    `RESERVED`."

    PRD §3.6: "**Reserving** tonnage raises `tons_reserved` and lowers `tons_available`
    by the reserved amount, and leaves `tons_on_hand` untouched. The salt has not moved;
    it has been promised."

    PRD §3.9: "A manual row is written with `origin` set to `MANUAL`, `rank_position` at
    its default of 1, and `state` at `RESERVED`, and it reserves against the lot exactly
    as a waterfall row does."

    PRD §3.9: "A manual row updates the order's `allocated_tons` to the new sum of its
    reserved and consumed rows, and increments the order's, the lot's and the contract's
    `version` by 1."

    Design: Difficulty/compensating_invariant/manual_reservation_then_release_restores_lot_tonnage_with_zero_drift
    """
    world = _order_over_a_full_lot(api)
    before = fx.refresh_lot(api, world["lot"]["id"])

    row = fx.reserve_manually(api, world["order"]["id"], before["id"], 1200)
    assert row["origin"] == ORIGIN_MANUAL
    assert row["rank_position"] == 1
    assert row["state"] == ALLOCATION_RESERVED
    assert row["version"] == 1
    assert_tons(row["tons"], 1200.00, "tons")

    mid = fx.refresh_lot(api, before["id"])
    assert_lot_tonnage(mid, 5527.20, 1200.00, 4327.20)
    assert mid["lot_state"] == LOT_AVAILABLE
    assert mid["version"] == before["version"] + 1

    order = fx.refresh_order(api, world["order"]["id"])
    assert_tons(order["allocated_tons"], 1200.00, "allocated_tons")
    # A hand-written partial reservation is not the waterfall: no promotion, no short.
    assert order["status"] == ORDER_REQUESTED
    assert_tons(order["shorted_tons"], 0.00, "shorted_tons")


def test_releasing_the_row_restores_the_pile_exactly_and_keeps_the_audit_line(api):
    """
    The inverse is exact rather than approximate: available returns to 5527.20 and
    reserved to 0.00, the lot never touches `DEPLETED`, and its `version` moved once per
    tonnage movement and no more. The released row survives as history and stops
    counting toward the reserved sum.

    PRD §3.6: "**Releasing** a reservation lowers `tons_reserved` and raises
    `tons_available` by the same amount, again leaving `tons_on_hand` untouched. A
    reservation followed by its release restores both `tons_available` and
    `tons_on_hand` to exactly their pre-reservation values."

    PRD §3.6: "Allocations that are `RELEASED` or `CONSUMED` contribute nothing to that
    sum, and `tons_reserved` is precisely that sum."

    PRD §3.9: "Releasing returns the tonnage to the lot per the compensation rule of
    §3.6 — `tons_reserved` down, `tons_available` up, `tons_on_hand` unchanged —
    recomputes the order's `allocated_tons`, and increments the allocation's, the lot's
    and the order's `version` by 1."

    PRD §3.9: "A `RELEASED` row is kept for audit; it is never deleted and never
    re-reserved."

    Design: Difficulty/compensating_invariant/manual_reservation_then_release_restores_lot_tonnage_with_zero_drift
    """
    world = _order_over_a_full_lot(api)
    lot_id = world["lot"]["id"]
    opening = fx.refresh_lot(api, lot_id)

    row = fx.reserve_manually(api, world["order"]["id"], lot_id, 1200)

    released = get_success_data(
        api.release_allocation(
            row["id"], LOGISTICS, f.release_payload("customer deferred the pull")
        )
    )
    assert released["state"] == ALLOCATION_RELEASED
    assert_tons(released["tons"], 1200.00, "tons")

    restored = fx.refresh_lot(api, lot_id)
    assert_lot_tonnage(restored, 5527.20, 0.00, 5527.20)
    assert restored["lot_state"] == LOT_AVAILABLE
    # One bump for the reservation, one for its release: no third write happened.
    assert restored["version"] == opening["version"] + 2

    order = fx.refresh_order(api, world["order"]["id"])
    assert_tons(order["allocated_tons"], 0.00, "allocated_tons")
    assert order["status"] == ORDER_REQUESTED

    reserved_rows = fx.list_rows(
        api.list_allocations(
            LOGISTICS,
            {"stockpile_lot_id": lot_id, "state": ALLOCATION_RESERVED, "limit": 100},
        )
    )
    assert reserved_rows == [], f"no reserved row may remain, found {len(reserved_rows)}"

    kept = fx.refresh_allocation(api, row["id"])
    assert kept["state"] == ALLOCATION_RELEASED
    assert kept["stockpile_lot_id"] == lot_id


def _shorted_order_with_an_accrued_penalty(api):
    """
    900.00 t within reach of a routine order for 2000 t, the other 5527.20 t parked at a
    depot posted `SURGE` where the routine waterfall may not look. Allocating therefore
    shorts by 1100.00 t and books 20565.00 on a 342750.00 contract.
    """
    fx.set_clock(api, CLOCK)
    world = fx.hoisted_run(
        api,
        mine_kwargs=dict(name="Retsof", rated_hoist_tons_per_day=24000),
        panel_kwargs=dict(panel_code="P-1", pillar_recovery_allowed=True),
        hoisted_tons=7000,
        planned_tons=7000,
        hoist_window_start="2026-08-11T00:00:00Z",
        hoist_window_end="2026-08-11T08:00:00Z",
    )
    near = fx.create_depot(api, name="Depot A", outbound_freight_rate_per_ton=4.00)
    far = fx.create_depot(api, name="Depot B", outbound_freight_rate_per_ton=4.00)

    minted = fx.mint_lot(
        api,
        world["run"]["id"],
        near["id"],
        product_line=HIGHWAY_DEICING,
        screen_spec=MEDIUM,
        anticaking_ppm=30,
        input_tons=1000,
        moisture_pct=0.0,
    )
    fx.mint_lot(
        api,
        world["run"]["id"],
        far["id"],
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=30,
        input_tons=6000,
        moisture_pct=2.0,
    )
    fx.set_posture(api, far["id"], DEPOT_SURGE, reason="storm staging")

    world.update(fx.active_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS))
    assert_money(
        world["contract"]["contract_value_usd"], 342750.00, "contract_value_usd"
    )

    world["near_lot"] = minted["lot"]
    world["order"] = fx.create_order(
        api,
        world["contract"]["id"],
        near["id"],
        requested_tons=2000,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=70.00,
        storm_priority=ROUTINE,
    )
    world["order"] = fx.allocate(api, world["order"]["id"])
    world["contract"] = fx.refresh_contract(api, world["contract"]["id"])
    return world


def test_the_waiver_re_derives_the_contract_ledger_back_to_nothing(api):
    """
    Forgiveness is a re-derivation, not a subtraction: with no `ACCRUED` order left, the
    accrual falls to exactly 0.00, the breach flag that 20565.00 raised against a
    17137.50 threshold clears, and the 22.00-point shortfall haircut vanishes from the
    score.

    PRD §3.9: "The waiver moves the order's `penalty_state` to `WAIVED` and **keeps** its
    `shortfall_penalty_usd` at the computed figure, because the audit record of what was
    forgiven is the point of the operation."

    PRD §3.9: "What changes is the contract's ledger, and it changes by re-derivation
    rather than by subtraction: `penalty_accrued_usd` is recomputed as the sum over the
    orders that remain `ACCRUED`, and `breach_watch` and `supply_reliability_score` are
    recomputed from that same remaining set — so a waiver can flip `breach_watch` back to
    false and can lift the score."

    PRD §3.8: "Sum the `shorted_tons` across the contract's delivery orders whose
    `penalty_state` is `ACCRUED`; take that cumulative shortfall multiplied by 100,
    divided by `committed_tons`, rounded half up to two decimal places, and cap the
    resulting haircut at 40 points."

    PRD §1: "money and tonnage are conserved quantities"

    Design: Difficulty/compensating_invariant/penalty_accrual_then_waiver_restores_contract_ledger_without_refilling_tons
    """
    world = _shorted_order_with_an_accrued_penalty(api)
    order = world["order"]
    before = world["contract"]

    assert order["status"] == ORDER_SHORTED
    assert order["penalty_state"] == PENALTY_ACCRUED
    assert_money(order["shortfall_penalty_usd"], 20565.00, "shortfall_penalty_usd")
    assert_money(before["penalty_accrued_usd"], 20565.00, "penalty_accrued_usd")
    assert before["breach_watch"] is True
    assert_money(
        before["supply_reliability_score"], 78.00, "supply_reliability_score"
    )

    waived = get_success_data(
        api.waive_penalty(
            order["id"],
            f.waiver_payload(
                "force majeure: rail embargo during the December storm"
            ),
            COMPLIANCE,
        )
    )
    assert waived["penalty_state"] == PENALTY_WAIVED

    after = fx.refresh_contract(api, before["id"])
    assert_money(after["penalty_accrued_usd"], 0.00, "penalty_accrued_usd")
    assert after["breach_watch"] is False
    assert_money(after["supply_reliability_score"], 100.00, "supply_reliability_score")
    assert after["version"] == before["version"] + 1
    assert_penalty_ledger_invariant(after, [])

    ledger = fx.contract_ledger(api, before["id"])
    assert_money(ledger["penalty_accrued_usd"], 0.00, "penalty_accrued_usd")
    assert ledger["accrued_penalty_order_count"] == 0
    assert ledger["breach_watch"] is False


def test_the_waived_order_keeps_its_charge_its_tonnage_and_refuses_a_second_waiver(api):
    """
    The compensation is one-directional and one-shot: the order still shows the
    20565.00 it was charged and is still `SHORTED` with 1100.00 t missing and 900.00 t
    reserved, and asking for the same forgiveness twice is refused rather than applied
    twice.

    PRD §3.9: "The order's `status` is untouched: a waived order that was `SHORTED` stays
    `SHORTED`, and a waived order that was `DELIVERED` stays `DELIVERED`."

    PRD §3.9: "an order whose `penalty_state` is `NONE` or already `WAIVED` refuses the
    request with `ERR_PENALTY_NOT_ACCRUED`"

    PRD §2.6: "**Penalty accrual state** — `ERR_PENALTY_NOT_ACCRUED` (409) on
    `POST /salt/delivery-orders/{id}/waive-penalty` when the order's `penalty_state` is
    `NONE` or already `WAIVED`."

    PRD §3.6: "**Consuming** a reservation at delivery lowers `tons_reserved` and lowers
    `tons_on_hand` by the same amount, and leaves `tons_available` unchanged. Consumption
    moves the pile itself, so it is not compensable — there is no operation that
    un-delivers tonnage."

    Design: Difficulty/compensating_invariant/penalty_accrual_then_waiver_restores_contract_ledger_without_refilling_tons
    """
    world = _shorted_order_with_an_accrued_penalty(api)
    order_id = world["order"]["id"]

    waived = get_success_data(
        api.waive_penalty(
            order_id,
            f.waiver_payload("force majeure: rail embargo during the December storm"),
            COMPLIANCE,
        )
    )

    # The charge is history, not a balance: it stays on the order verbatim.
    assert_money(waived["shortfall_penalty_usd"], 20565.00, "shortfall_penalty_usd")
    assert waived["status"] == ORDER_SHORTED
    assert_tons(waived["shorted_tons"], 1100.00, "shorted_tons")
    assert_tons(waived["allocated_tons"], 900.00, "allocated_tons")

    rows = fx.allocations_of_order(api, order_id)
    assert len(rows) == 1, f"expected the single reserved row, got {len(rows)}"
    assert rows[0]["state"] == ALLOCATION_RESERVED
    assert_tons(rows[0]["tons"], 900.00, "tons")
    assert_lot_tonnage(fx.refresh_lot(api, world["near_lot"]["id"]), 900.00, 900.00, 0.00)

    again = api.waive_penalty(
        order_id, f.waiver_payload("second bite at the same storm"), COMPLIANCE
    )
    validate_error(again, ERR_PENALTY_NOT_ACCRUED, 409)

    unchanged = fx.refresh_order(api, order_id)
    assert unchanged["penalty_state"] == PENALTY_WAIVED
    assert_money(unchanged["shortfall_penalty_usd"], 20565.00, "shortfall_penalty_usd")
    assert_money(
        fx.refresh_contract(api, world["contract"]["id"])["penalty_accrued_usd"],
        0.00,
        "penalty_accrued_usd",
    )
