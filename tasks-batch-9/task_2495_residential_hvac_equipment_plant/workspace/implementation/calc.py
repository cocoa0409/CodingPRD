"""The plant's twelve calculations (PRD 2.6, 3.5, 3.7, 3.8, 3.9)."""

from decimal import Decimal
from fractions import Fraction

import db
import derive
from prec import dec, q, q0_int, q_frac

HELIUM_BASE_LIMIT = Decimal("3.000")
DECAY_ALLOWANCE_PER_15MIN = Decimal("2.00")
A2L_TIGHTENING_FACTOR = Decimal("0.500")
MIN_PRESSURE_DECAY_HOLD_MINUTES = 15

RATING_AMBIENT_C = Decimal("35.0")
AMBIENT_COEFFICIENT_PER_C = Decimal("0.0040")

CAPACITY_TOLERANCE = {
    "STANDARD": {"A1": Decimal("0.9500"), "A2L": Decimal("0.9400")},
    "HIGH": {"A1": Decimal("0.9700"), "A2L": Decimal("0.9600")},
    "PREMIUM": {"A1": Decimal("0.9800"), "A2L": Decimal("0.9800")},
}
EFFICIENCY_TOLERANCE = {
    "STANDARD": {"A1": Decimal("0.9300"), "A2L": Decimal("0.9200")},
    "HIGH": {"A1": Decimal("0.9500"), "A2L": Decimal("0.9400")},
    "PREMIUM": {"A1": Decimal("0.9600"), "A2L": Decimal("0.9600")},
}
EFFICIENCY_TOLERANCE_FLOOR = Decimal("0.90")

CARRYING_RATE_CENTS_PER_PALLET_WEEK = 1165
DAYS_PER_WEEK = 7

DERATE_TABLE = {
    "COMPRESSOR": {"LOW": 25, "MID": 50, "HIGH": 100},
    "CONTROL_BOARD": {"LOW": 25, "MID": 25, "HIGH": 50},
}


# ------------------------------------------------------------- leak testing
def class_factor(flammability_class):
    return A2L_TIGHTENING_FACTOR if flammability_class == "A2L" else Decimal("1.000")


def leak_test_verdict(method, flammability_class, measured_leak_rate, decay_kpa,
                      hold_minutes):
    factor = class_factor(flammability_class)
    if method == "HELIUM_MASS_SPEC":
        applied = q(HELIUM_BASE_LIMIT * factor, 3)
        verdict = "PASS" if dec(measured_leak_rate) <= applied else "FAIL"
    else:
        exact = (
            Fraction(DECAY_ALLOWANCE_PER_15MIN)
            * Fraction(int(hold_minutes), 15)
            * Fraction(factor)
        )
        applied = q_frac(exact, 2)
        verdict = "PASS" if dec(decay_kpa) <= applied else "FAIL"
    return applied, verdict


# -------------------------------------------------------------- run testing
def run_test_verdict(platform, flammability_class, measured_capacity_btuh,
                     measured_power_w, measured_ambient_c):
    ambient_delta = dec(measured_ambient_c) - RATING_AMBIENT_C
    corrected = q0_int(
        dec(measured_capacity_btuh) * (Decimal(1) + AMBIENT_COEFFICIENT_PER_C * ambient_delta)
    )
    capacity_ratio = q_frac(
        Fraction(corrected, int(platform["rated_capacity_btuh"])), 4
    )
    measured_eer = Fraction(corrected, int(measured_power_w))
    efficiency_ratio = q_frac(measured_eer / Fraction(dec(platform["rated_eer"])), 4)

    tier = platform["efficiency_tier"]
    capacity_tolerance = CAPACITY_TOLERANCE[tier][flammability_class]
    efficiency_tolerance = EFFICIENCY_TOLERANCE[tier][flammability_class]
    if efficiency_tolerance < EFFICIENCY_TOLERANCE_FLOOR:
        efficiency_tolerance = EFFICIENCY_TOLERANCE_FLOOR

    verdict = (
        "PASS"
        if capacity_ratio >= capacity_tolerance and efficiency_ratio >= efficiency_tolerance
        else "FAIL"
    )
    return {
        "corrected_capacity_btuh": corrected,
        "capacity_ratio": capacity_ratio,
        "efficiency_ratio": efficiency_ratio,
        "applied_capacity_tolerance": capacity_tolerance,
        "applied_efficiency_tolerance": efficiency_tolerance,
        "verdict": verdict,
    }


# --------------------------------------------------- test cell availability
def conflicting_run_test(cell, window_start, window_end):
    buffer_minutes = cell["cooldown_minutes"]
    from datetime import timedelta

    buffer_delta = timedelta(minutes=buffer_minutes)
    conflicts = []
    for existing in db.db.rows("run_tests"):
        if existing["test_cell_id"] != cell["id"]:
            continue
        other_start = existing["_window_start"]
        other_end = existing["_window_end"]
        if window_start < other_end + buffer_delta and other_start < window_end + buffer_delta:
            conflicts.append(existing)
    if not conflicts:
        return None
    return sorted(conflicts, key=lambda r: r["_seq"])[0]


# ------------------------------------------------------------- allocation
def eligible_pools(component_type, part_number, supply_month):
    pools = [
        pool
        for pool in db.db.rows("supplies")
        if pool["component_type"] == component_type
        and pool["part_number"] == part_number
        and pool["supply_month"] == supply_month
        and pool["status"] in ("ACTIVE", "DERATED")
        and derive.available_units(pool) >= 1
    ]
    return sorted(pools, key=lambda p: (p["supply_month"], p["_seq"]))


def primary_compressor_supply(order, platform):
    pools = eligible_pools(
        "COMPRESSOR", platform["compressor_part_number"], order["requested_delivery_month"]
    )
    if not pools:
        return None
    return sorted(pools, key=lambda p: p["_seq"])[0]


def total_open_demand(order):
    total = 0
    for other in db.db.rows("orders"):
        if other["platform_id"] != order["platform_id"]:
            continue
        if other["requested_delivery_month"] != order["requested_delivery_month"]:
            continue
        if other["fulfillment_status"] != "PENDING":
            continue
        if other["allocation_status"] == "FULLY_ALLOCATED":
            continue
        total += other["requested_units"] - derive.allocated_units(other)
    return total


def allocation_plan(order, platform, policy_override=None):
    compressors = eligible_pools(
        "COMPRESSOR", platform["compressor_part_number"], order["requested_delivery_month"]
    )
    boards = eligible_pools(
        "CONTROL_BOARD",
        platform["control_board_part_number"],
        order["requested_delivery_month"],
    )
    compressor_pool = sum(derive.available_units(p) for p in compressors)
    board_pool = sum(derive.available_units(p) for p in boards)
    kit_capacity = min(compressor_pool, board_pool)
    remaining_need = order["requested_units"] - derive.allocated_units(order)
    if remaining_need < 0:
        remaining_need = 0
    open_demand = total_open_demand(order)

    primary = primary_compressor_supply(order, platform)
    policy = policy_override or (
        primary["allocation_policy"] if primary else "PRIORITY_WATERFALL"
    )

    if policy == "DEMAND_PRORATA":
        if open_demand > 0:
            fair_share = (kit_capacity * remaining_need) // open_demand
        else:
            fair_share = 0
        granted = min(remaining_need, fair_share)
    else:
        granted = min(remaining_need, kit_capacity)
    if granted < 0:
        granted = 0

    return {
        "policy": policy,
        "compressor_pool": compressor_pool,
        "board_pool": board_pool,
        "kit_capacity": kit_capacity,
        "remaining_need": remaining_need,
        "total_open_demand": open_demand,
        "granted_units": granted,
        "compressors": compressors,
        "boards": boards,
        "primary": primary,
    }


# ------------------------------------------------------------ carrying cost
def occupied_days(reservation, window_start, window_end):
    start = max(reservation["_start_date"], window_start)
    end = min(reservation["_end_date"], window_end)
    if end <= start:
        return 0
    return (end - start).days


def carrying_cost(warehouse, window_start, window_end, basis):
    rows = [
        r
        for r in derive.warehouse_reservations(warehouse, ("ACTIVE",))
        if occupied_days(r, window_start, window_end) > 0
    ]
    rows = sorted(rows, key=lambda r: r["_seq"])
    pooled = Fraction(0)
    per_reservation_cents = 0
    for reservation in rows:
        days = occupied_days(reservation, window_start, window_end)
        pallet_weeks = Fraction(reservation["pallet_units"] * days, DAYS_PER_WEEK)
        pooled += pallet_weeks
        per_reservation_cents += int(
            q_frac(pallet_weeks * CARRYING_RATE_CENTS_PER_PALLET_WEEK, 0)
        )
    pallet_week_total = q_frac(pooled, 4)
    if basis == "POOLED":
        cents = int(q_frac(pooled * CARRYING_RATE_CENTS_PER_PALLET_WEEK, 0))
    else:
        cents = per_reservation_cents
    return {
        "reservation_count": len(rows),
        "pallet_week_total": pallet_week_total,
        "carrying_cost_cents": cents,
    }


# ------------------------------------------------------------ supply derate
def derate_band(rate):
    rate = dec(rate)
    if rate >= Decimal("10.00"):
        return "HIGH"
    if rate >= Decimal("7.50"):
        return "MID"
    if rate >= Decimal("5.00"):
        return "LOW"
    return None


def derate_pct_for(component_type, rate):
    band = derate_band(rate)
    if band is None:
        return None
    return DERATE_TABLE[component_type][band]
