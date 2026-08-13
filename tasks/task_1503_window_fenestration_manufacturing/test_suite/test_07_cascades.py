"""Transitive cascades: breakage depth-3 chain and order cancel depth-2 chain
(PRD §3.4, §3.5, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    advance_unit_to_gas_filled,
    assign_order,
    confirm_order,
    create_draft_order,
    create_open_wave,
    find_remake_of,
    get_success_data,
    list_line_units,
    lock_and_release,
    setup_mn_catalog,
    setup_order_in_production,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PL = TEST_USERS["production_lead_headers"]


def _two_orders_on_full_wave(api):
    """Order A qty4 + order B qty6 on one wave with capacity_units 10."""
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    line_a = add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=4)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])
    line_b = add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=6)
    confirm_order(order_b["id"])

    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=2000)
    assign_order(wave["id"], order_a["id"])
    assign_order(wave["id"], order_b["id"])
    wave = lock_and_release(wave["id"])
    return cat, order_a, line_a, order_b, line_b, wave


def test_breakage_cascade_depth3_unlocks_wave(api):
    """PRD §3.5: "Both failure paths run the same three-hop cascade. The unit
    becomes `BROKEN`, and a replacement unit is created immediately at `QUEUED`
    with its `remake_of_id` pointing at the broken unit — the auto-remake
    guarantee that keeps the line whole. The parent line then drops from
    `IN_PRODUCTION` to `GLASS_HOLD` (hop one), and the wave's allocation is
    recomputed without the held line (hop two). If that release leaves a
    `LOCKED` or `RELEASED` wave below half its unit capacity, rounded up, the
    wave reopens to `OPEN` by itself (hop three)."

    Design: Difficulty/transitive_cascade/breakage_cascade_depth3_unlocks_wave
    """
    _cat, order_a, line_a, order_b, line_b, wave = _two_orders_on_full_wave(api)
    unit_b = list_line_units(line_b["id"])[0]
    advance_unit_to_gas_filled(unit_b["id"])

    broken = validate_success(api.report_ig_breakage(
        unit_b["id"], {"break_cause": "SEAL_FAILURE"}, PL
    ), 200)
    assert broken["status"] == "BROKEN"

    # hop 1: the broken unit's line drops to GLASS_HOLD
    line_b_after = validate_success(api.get_order_line(line_b["id"], PL), 200)
    assert line_b_after["status"] == "GLASS_HOLD"

    # hop 2 + hop 3: allocation 10 -> 4 (< ceil(10/2) = 5) reopens the wave
    wave_after = get_success_data(api.get_wave(wave["id"], PL))
    assert wave_after["allocated_units"] == 4
    assert wave_after["status"] == "OPEN"

    remake = find_remake_of(unit_b["id"])
    assert remake["status"] == "QUEUED"
    assert remake["remake_of_id"] == unit_b["id"]

    # conditional cascade touches only the broken line
    line_a_after = validate_success(api.get_order_line(line_a["id"], PL), 200)
    assert line_a_after["status"] == "IN_PRODUCTION"


def test_breakage_releases_held_line_glass_allocation(api):
    """PRD §3.4: "The allocation counters count only lines whose status is
    `RELEASED`, `IN_PRODUCTION`, or `COMPLETED`; lines sitting on `GLASS_HOLD`
    and cancelled lines are excluded."
    PRD §3.4: "`allocated_units` is the sum of `quantity` over the counted
    lines; `allocated_glass_sqft` is the sum of each counted line's
    `glazing_sqft` times its `quantity`, rounded half-up to two decimal places
    after the summation."

    Design: Difficulty/transitive_cascade/breakage_cascade_depth3_unlocks_wave
    """
    _cat, order_a, line_a, order_b, line_b, wave = _two_orders_on_full_wave(api)
    unit_b = list_line_units(line_b["id"])[0]
    advance_unit_to_gas_filled(unit_b["id"])
    validate_success(api.report_ig_breakage(
        unit_b["id"], {"break_cause": "SEAL_FAILURE"}, PL
    ), 200)

    wave_after = get_success_data(api.get_wave(wave["id"], PL))
    # only order A's 4 units at 16.67 sqft each remain counted
    assert wave_after["allocated_glass_sqft"] == pytest.approx(66.68, abs=0.001)
    assert wave_after["allocated_units"] == 4


def test_order_cancel_cascade_depth2(api):
    """PRD §3.8: "From `IN_PROGRESS` — the `PlantManager`-only path — each line
    in `IN_PRODUCTION` or `GLASS_HOLD` moves to `CANCELLED`, and the cascade
    reaches one level deeper: every non-terminal insulating glass unit of those
    lines (any unit still `QUEUED`, `GLASS_CUT`, `SEALED`, or `GAS_FILLED`) is
    `SCRAPPED`."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    env = setup_order_in_production(quantity=2)
    cancelled = validate_success(api.cancel_order(env["order"]["id"], PM), 200)
    assert cancelled["production_status"] == "CANCELLED"
    assert cancelled["wave_id"] is None

    line = validate_success(api.get_order_line(env["line"]["id"], PM), 200)
    assert line["status"] == "CANCELLED"

    units = list_line_units(env["line"]["id"])
    assert len(units) == 2
    assert all(u["status"] == "SCRAPPED" for u in units)


def test_order_cancel_releases_allocation_and_reopens_wave(api):
    """PRD §3.8: "From `RELEASED`, the lines move to `CANCELLED`, the order's
    `wave_id` is cleared, and the wave's allocation is recomputed without the
    cancelled lines — a release that may reopen the wave per the auto-unlock
    rule of §3.4."
    PRD §3.4: "A wave reopens on its own when it drains: whenever a downward
    recompute — a line entering `GLASS_HOLD`, or a cancellation — leaves
    `allocated_units` strictly below half of `capacity_units` rounded up, a wave
    in `LOCKED` or `RELEASED` automatically returns to `OPEN` and accepts new
    assignments again."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    env = setup_order_in_production(quantity=2)
    validate_success(api.cancel_order(env["order"]["id"], PM), 200)

    wave = get_success_data(api.get_wave(env["wave"]["id"], PL))
    assert wave["allocated_units"] == 0
    assert wave["allocated_glass_sqft"] == pytest.approx(0.0, abs=0.001)
    assert wave["status"] == "OPEN", "0 < ceil(10/2) = 5 auto-unlocks RELEASED -> OPEN"
