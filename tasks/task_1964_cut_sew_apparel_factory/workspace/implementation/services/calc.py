"""Calculation rules (SCAFFOLD table 3 / PRD §3).

Every formula here follows the pinned algorithm, precision, and rounding of
the scaffold: Decimal arithmetic throughout, ROUND_HALF_UP at the declared
scale, exact ceilings where required. No floats for money.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from db import store
from services.core import pack_operations, pack_requirements, touch

# --- Constants (SCAFFOLD calculations[].constants) ---
END_LOSS_PCT = Decimal("0.02")
SPLICE_YARDS = Decimal("0.5")
HOURLY_GUARANTEE_CENTS = 1500
BONUS_TIER_LOW = Decimal("90")
BONUS_TIER_HIGH = Decimal("100")
DOMESTIC_COST_THRESHOLD = Decimal("0.7")
CHANGEOVER_BUFFER_MINUTES = 15


def round_dec(value, places):
    """Round half-up to the given number of decimal places."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def ceil_int(value):
    """Exact ceiling of a Decimal to an integer."""
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


# =============================================================================
# size_grading (PRD §3.1) — computed read, never persisted
# =============================================================================
def size_grading(style, pack):
    sizes = style["size_run"]
    i_base = sizes.index(style["base_size"])
    increments = {g["point"]: g["per_step_increment_in"] for g in pack["grade_rules"]}
    cells = []
    for m in pack["base_measurements"]:
        point = m["point"]
        base = m["base_value_in"]
        inc = increments.get(point, Decimal(0))
        for size in sizes:
            steps = sizes.index(size) - i_base
            raw = base + Decimal(steps) * inc
            graded = round_dec(raw * 8, 0) / Decimal(8)  # nearest 1/8", half-up on the eighth-count
            cells.append({
                "point": point,
                "size": size,
                "value": graded,
            })
    return {"size_run": list(sizes), "cells": cells}


# =============================================================================
# marker_allocation_and_utilization (PRD §3.5) — at marker approve
# =============================================================================
def marker_allocation(marker_length_yards):
    length = Decimal(marker_length_yards)
    allocated = round_dec(length * (1 + END_LOSS_PCT), 2) + SPLICE_YARDS
    gross = round_dec(Decimal(100) * length / allocated, 1)
    net = round_dec(Decimal(100) * length / (allocated - SPLICE_YARDS), 1)
    return allocated, gross, net


# =============================================================================
# trim_grossing (PRD §3.4) — plan + receive sweep; per-line ceiling THEN sum
# =============================================================================
def trim_grossing_lines(order, pack):
    """Per-line {requirement, item, required_units, available_units, shortage_units}."""
    lines = []
    for req in pack_requirements(pack["id"]):
        item = store.trim_items[req["trim_item_id"]]
        exact = (Decimal(order["total_order_qty"])
                 * Decimal(req["units_per_garment"])
                 * (Decimal(1) + req["wastage_pct"]))
        required = ceil_int(exact)  # ceiling applied PER LINE first
        available = item["qty_available"]
        lines.append({
            "requirement": req,
            "item": item,
            "required_units": required,
            "available_units": available,
            "shortage_units": max(0, required - available),
        })
    return lines


def shortage_report(lines):
    return [
        {
            "trim_item_id": l["item"]["id"],
            "required_units": l["required_units"],
            "available_units": l["available_units"],
            "shortage_units": l["shortage_units"],
        }
        for l in lines if l["shortage_units"] > 0
    ]


def apply_reservations(order, lines):
    """Reserve each line in full; each touched TrimItem is a mutation."""
    for l in lines:
        item = l["item"]
        item["qty_reserved"] += l["required_units"]
        item["qty_available"] = item["qty_on_hand"] - item["qty_reserved"]
        touch(item)
    order["_reserved"] = [[l["item"]["id"], l["required_units"]] for l in lines]


def release_reservations(order):
    """Compensate all trim reservations this order holds (order finish)."""
    for item_id, units in order.get("_reserved", []):
        item = store.trim_items.get(item_id)
        if item is None:
            continue
        item["qty_reserved"] -= units
        item["qty_available"] = item["qty_on_hand"] - item["qty_reserved"]
        touch(item)
    order["_reserved"] = []


def trim_hold_sweep():
    """Receive sweep (PRD §3.4): held orders re-evaluated in created_at ASC;
    all-or-nothing per order; reservations applied before the next order."""
    held = sorted(
        [o for o in store.production_orders.values()
         if o["trim_hold_status"] == "TRIM_HOLD"],
        key=lambda o: (o["created_at"], o["_seq"]),
    )
    for order in held:
        pack = store.tech_packs.get(order["tech_pack_id"])
        if pack is None:
            continue
        lines = trim_grossing_lines(order, pack)
        if all(l["shortage_units"] == 0 for l in lines):
            apply_reservations(order, lines)
            order["trim_hold_status"] = "MATERIALS_OK"
            order["trim_shortages"] = []
            touch(order)


# =============================================================================
# piece_rate_earnings (PRD §3.6/§3.7) — straight variant at log time
# =============================================================================
def straight_piece(qty, operation):
    piece_earnings = qty * operation["piece_rate_cents"]
    earned_minutes = round_dec(
        Decimal(qty) * Decimal(operation["sam_seconds"]) / Decimal(60), 2)
    return piece_earnings, earned_minutes


# =============================================================================
# operator_efficiency (PRD §3.7)
# =============================================================================
def operator_efficiency(operator_id):
    earned = Decimal(0)
    for e in store.piece_work_entries.values():
        if e["operator_id"] == operator_id and e["status"] in ("VERIFIED", "PAID"):
            earned += e["earned_minutes"]
    attended = sum(
        a["end_minute"] - a["start_minute"]
        for a in store.line_assignments.values()
        if a["operator_id"] == operator_id
    )
    if attended == 0:
        eff = Decimal(0)
    else:
        eff = round_dec(Decimal(100) * earned / Decimal(attended), 1)
    return eff, earned, attended


# =============================================================================
# payroll_run_totals (PRD §3.7) — pinned evaluation order (1)..(5)
# =============================================================================
def _allocate_pro_rata(pool, entries):
    """Pro-rata `pool` (int cents) across entries by piece_earnings_cents.

    Shares rounded half-up to integer cents; remainder cents go to the entry
    with the earliest created_at. A zero total weight (all-zero piece earnings)
    sends the whole pool to the earliest entry.
    """
    shares = {e["id"]: 0 for e in entries}
    if pool == 0 or not entries:
        return shares
    total_weight = sum(e["piece_earnings_cents"] for e in entries)
    if total_weight == 0:
        earliest = min(entries, key=lambda e: (e["created_at"], e["_seq"]))
        shares[earliest["id"]] = pool
        return shares
    for e in entries:
        shares[e["id"]] = int(round_dec(
            Decimal(pool) * Decimal(e["piece_earnings_cents"]) / Decimal(total_weight), 0))
    remainder = pool - sum(shares.values())
    if remainder:
        earliest = min(entries, key=lambda e: (e["created_at"], e["_seq"]))
        shares[earliest["id"]] += remainder
    return shares


def payroll_calculate(run):
    """Sweep + stamp entries, set totals, move run to CALCULATED.

    Caller has already done auth/existence/schema/OCC/state checks; the caller
    stamps calculated_by_user_id before invoking.
    """
    # (1) sweep set: VERIFIED, unstamped, work_date within inclusive period
    sweep = sorted(
        [e for e in store.piece_work_entries.values()
         if e["status"] == "VERIFIED"
         and e["payroll_run_id"] is None
         and run["period_start"] <= e["work_date"] <= run["period_end"]],
        key=lambda e: (e["created_at"], e["_seq"]),
    )

    # (2) guaranteed-minimum variant per (operator, work_date)
    day_groups = {}
    for e in sweep:
        day_groups.setdefault((e["operator_id"], e["work_date"]), []).append(e)
    topup_by_day = {}
    for (op_id, wdate), entries in day_groups.items():
        day_piece = sum(e["piece_earnings_cents"] for e in entries)
        day_minutes = sum(
            a["end_minute"] - a["start_minute"]
            for a in store.line_assignments.values()
            if a["operator_id"] == op_id and a["shift_date"] == wdate
        )
        day_guarantee = int(round_dec(
            Decimal(day_minutes) * Decimal(HOURLY_GUARANTEE_CENTS) / Decimal(60), 0))
        topup_by_day[(op_id, wdate)] = max(day_piece, day_guarantee) - day_piece

    # (3) pre-pay efficiency snapshot per operator (VERIFIED + PAID entries,
    #     deliberately including this run's just-swept VERIFIED entries)
    op_groups = {}
    for e in sweep:
        op_groups.setdefault(e["operator_id"], []).append(e)
    eff_by_op = {op_id: operator_efficiency(op_id)[0] for op_id in op_groups}

    # (4) bonus per operator: straight piece total in this run x tier rate
    bonus_by_op = {}
    for op_id, entries in op_groups.items():
        piece_total = sum(e["piece_earnings_cents"] for e in entries)
        eff = eff_by_op[op_id]
        if eff >= BONUS_TIER_HIGH:
            rate = Decimal("0.10")
        elif eff >= BONUS_TIER_LOW:
            rate = Decimal("0.05")
        else:
            rate = Decimal(0)
        bonus_by_op[op_id] = int(round_dec(Decimal(piece_total) * rate, 0))

    # (5) stamp each entry: piece + pro-rata topup share (per day) + pro-rata
    #     bonus share (per run)
    topup_share = {}
    for key, entries in day_groups.items():
        topup_share.update(_allocate_pro_rata(topup_by_day[key], entries))
    bonus_share = {}
    for op_id, entries in op_groups.items():
        bonus_share.update(_allocate_pro_rata(bonus_by_op[op_id], entries))
    for e in sweep:
        e["payable_cents"] = (e["piece_earnings_cents"]
                              + topup_share[e["id"]]
                              + bonus_share[e["id"]])
        e["payroll_run_id"] = run["id"]
        touch(e)

    run["entry_count"] = len(sweep)
    run["total_piece_cents"] = sum(e["piece_earnings_cents"] for e in sweep)
    run["total_topup_cents"] = sum(topup_by_day.values())
    run["total_bonus_cents"] = sum(bonus_by_op.values())
    run["total_payable_cents"] = (run["total_piece_cents"]
                                  + run["total_topup_cents"]
                                  + run["total_bonus_cents"])
    run["status"] = "CALCULATED"
    touch(run)
    return sweep


# =============================================================================
# aql_sample_plan (PRD §3.8) — integer table lookup
# =============================================================================
LOT_TIERS = [
    (2, 8, "A"), (9, 15, "B"), (16, 25, "C"), (26, 50, "D"), (51, 90, "E"),
    (91, 150, "F"), (151, 280, "G"), (281, 500, "H"), (501, 1200, "J"),
]
LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "J"]
SAMPLE_SIZES = {"A": 2, "B": 3, "C": 5, "D": 8, "E": 13, "F": 20, "G": 32,
                "H": 50, "J": 80}
ACCEPT_REJECT = {
    "AQL_2_5": {"A": (0, 1), "B": (0, 1), "C": (0, 1), "D": (0, 1),
                "E": (1, 2), "F": (1, 2), "G": (2, 3), "H": (3, 4),
                "J": (5, 6)},
    "AQL_4_0": {"A": (0, 1), "B": (0, 1), "C": (0, 1), "D": (1, 2),
                "E": (1, 2), "F": (2, 3), "G": (3, 4), "H": (5, 6),
                "J": (7, 8)},
}


def aql_sample_plan(lot_size, inspection_level, aql_level):
    letter = None
    for lo, hi, l in LOT_TIERS:  # inclusive both ends
        if lo <= lot_size <= hi:
            letter = l
            break
    if letter is None:
        # Outside the published table: tiny lots take A, oversized lots cap at J.
        letter = "A" if lot_size < 2 else "J"
    if inspection_level == "TIGHTENED":
        letter = LETTERS[min(LETTERS.index(letter) + 1, len(LETTERS) - 1)]
    sample_size = SAMPLE_SIZES[letter]
    accept_max, reject_min = ACCEPT_REJECT[aql_level][letter]
    return letter, sample_size, accept_max, reject_min


# =============================================================================
# line_balance (PRD §3.6) — computed read
# =============================================================================
def line_balance(line, pack):
    ops = pack_operations(pack["id"])
    total_sam = sum(o["sam_seconds"] for o in ops)
    stations = line["station_count"]
    takt = (total_sam + stations - 1) // stations  # exact ceiling
    # Greedy in-sequence packing against the takt allowance.
    loads = []
    current = None
    for o in ops:
        sam = o["sam_seconds"]
        if current is None:
            current = sam  # a single op longer than takt gets its own station
        elif current + sam <= takt:
            current += sam
        else:
            loads.append(current)
            current = sam
    if current is not None:
        loads.append(current)
    stations_used = len(loads)
    max_load = max(loads) if loads else 0
    if stations_used == 0 or max_load == 0:
        eff = Decimal(0)
    else:
        eff = round_dec(Decimal(100) * Decimal(total_sam)
                        / Decimal(stations_used * max_load), 1)
    return {
        "total_sam_seconds": total_sam,
        "takt_seconds": takt,
        "stations_used": stations_used,
        "max_station_load_seconds": max_load,
        "balance_efficiency_pct": eff,
    }


# =============================================================================
# domestic_content_determination (PRD §3.2) — on review APPROVE
# =============================================================================
def recompute_domestic_content(style):
    pack_id = style.get("active_tech_pack_id")
    pack = store.tech_packs.get(pack_id) if pack_id else None
    if pack is None:
        style["domestic_content_pct_cost"] = None
        style["domestic_component_ratio"] = None
        style["content_qualification"] = "UNDETERMINED"
        return
    reqs = pack_requirements(pack["id"])
    cost_total = Decimal(0)
    cost_domestic = Decimal(0)
    domestic_lines = 0
    for req in reqs:
        item = store.trim_items[req["trim_item_id"]]
        # exact decimal; deliberately NO per-line ceiling here (contrast §3.4)
        line_cost = (Decimal(req["units_per_garment"])
                     * Decimal(item["unit_cost_cents"])
                     * (Decimal(1) + req["wastage_pct"]))
        cost_total += line_cost
        if item["origin_country"] == "US":
            cost_domestic += line_cost
            domestic_lines += 1
    cost_total += (Decimal(pack["fabric_cost_cents_per_unit"])
                   + Decimal(pack["labor_cost_cents_per_unit"]))
    if style["declared_fabric_domestic"]:
        cost_domestic += Decimal(pack["fabric_cost_cents_per_unit"])
    cost_domestic += Decimal(pack["labor_cost_cents_per_unit"])  # labor domestic by scenario
    pct = Decimal(0) if cost_total == 0 else round_dec(cost_domestic / cost_total, 4)
    components_total = len(reqs) + 1  # each requirement line + the shell fabric
    components_domestic = domestic_lines + (1 if style["declared_fabric_domestic"] else 0)
    ratio = round_dec(Decimal(components_domestic) / Decimal(components_total), 4)
    style["domestic_content_pct_cost"] = pct
    style["domestic_component_ratio"] = ratio
    # Pinned precedence: strict unit basis first, then cost basis.
    if ratio == 1:
        style["content_qualification"] = "QUALIFIED_STRICT"
    elif pct >= DOMESTIC_COST_THRESHOLD:
        style["content_qualification"] = "QUALIFIED_COST_ONLY"
    else:
        style["content_qualification"] = "NOT_QUALIFIED"


# =============================================================================
# wip_by_sku (PRD §3.6) — computed read
# =============================================================================
def wip_by_sku(order):
    rows = []
    bundles = [b for b in store.bundles.values()
               if b["production_order_id"] == order["id"]]
    for line in order["size_quantities"]:
        size = line["size"]
        of_size = [b for b in bundles if b["size"] == size]
        rows.append({
            "size": size,
            "ordered_qty": line["qty"],
            "ticketed_qty": sum(b["qty"] for b in of_size
                                if b["status"] in ("TICKETED", "RELEASED")),
            "in_progress_qty": sum(b["qty"] for b in of_size
                                   if b["status"] in ("IN_PROGRESS", "REWORK_HOLD")),
            "completed_qty": sum(b["qty"] for b in of_size
                                 if b["status"] == "COMPLETED"),
        })
    return {"rows": rows}
