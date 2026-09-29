"""The reel allocation plan, the release compensation and the cut settlement
(PRD Sections 3.6 and 3.7).
"""
import math
from decimal import Decimal

import clock
import db
import calculations as calc
from errors import ApiError
from services import lookup, pricing


def _avail(reel, sim_alloc):
    return calc.dec(reel["current_length_ft"]) - sim_alloc[reel["id"]]


def plan_allocation(order, policy):
    """Produce the allocation plan without persisting anything.

    Lines are processed in ascending line_number; a line whose residual demand is
    zero or below is skipped entirely, which is what makes a re-run after restock
    top up only the shortfall and leave existing reservations alone.
    """
    lines = lookup.order_lines_of(order["id"])
    reels = sorted(db.reels.values(), key=db.sort_key)
    sim_alloc = {r["id"]: calc.dec(r["allocated_length_ft"]) for r in reels}

    plans = []
    lot_pins = {}

    for line in lines:
        residual = calc.dec(line["required_length_ft"]) - calc.dec(line["allocated_length_ft"])
        if residual <= 0:
            continue
        product = db.products[line["product_id"]]
        candidates = [
            r for r in reels
            if r["product_id"] == line["product_id"]
            and r["branch_id"] == order["branch_id"]
            and r["status"] in ("IN_STOCK", "ALLOCATED_PARTIAL")
            and _avail(r, sim_alloc) > 0
        ]

        if line["parallel_set_size"] > 1:
            _plan_parallel_set(line, candidates, sim_alloc, policy, plans, lot_pins)
        elif line["put_up"] == "MASTER_REEL":
            _plan_master_reels(line, product, candidates, sim_alloc, residual, plans)
        else:
            _plan_waterfall(line, candidates, sim_alloc, residual, policy, plans)

    return plans, lot_pins


def _plan_parallel_set(line, candidates, sim_alloc, policy, plans, lot_pins):
    """Same-lot, whole-conductor rule -- all-or-nothing, never partially filled."""
    billable = calc.dec(line["billable_length_ft"])
    chosen_lot = None
    usable = []
    for lot in sorted({r["lot_code"] for r in candidates}):
        lot_usable = [
            r for r in candidates
            if r["lot_code"] == lot and _avail(r, sim_alloc) >= billable
        ]
        if len(lot_usable) >= line["parallel_set_size"]:
            chosen_lot = lot
            usable = lot_usable
            break
    if chosen_lot is None:
        raise ApiError("ERR_PARALLEL_SET_INCOMPLETE")

    ranked = calc.rank_candidates(
        usable, billable, policy, lambda r: _avail(r, sim_alloc), db.sort_key
    )
    for reel in ranked[:line["parallel_set_size"]]:
        plans.append({"line": line, "reel": reel, "length_ft": calc.as_number(billable)})
        sim_alloc[reel["id"]] += billable
    lot_pins[line["id"]] = chosen_lot


def _plan_master_reels(line, product, candidates, sim_alloc, residual, plans):
    """Whole-reel pick: only untouched full master reels, in ascending created_at."""
    master_len = calc.dec(product["master_reel_length_ft"])
    usable = [
        r for r in candidates
        if r["reel_type"] == "MASTER"
        and sim_alloc[r["id"]] == 0
        and calc.dec(r["current_length_ft"]) == calc.dec(r["nominal_length_ft"])
        and calc.dec(r["nominal_length_ft"]) == master_len
    ]
    picks = sorted(usable, key=db.sort_key)
    wanted = int(math.ceil(residual / master_len)) if master_len > 0 else 0
    for reel in picks[:max(wanted, 0)]:
        length = calc.dec(reel["current_length_ft"])
        plans.append({"line": line, "reel": reel, "length_ft": calc.as_number(length)})
        sim_alloc[reel["id"]] += length


def _plan_waterfall(line, candidates, sim_alloc, residual, policy, plans):
    """Single-conductor cut line: splitting across reels is permitted."""
    remaining = residual
    pool = list(candidates)
    while remaining > 0 and pool:
        ranked = calc.rank_candidates(
            pool, remaining, policy, lambda r: _avail(r, sim_alloc), db.sort_key
        )
        reel = ranked[0]
        take = min(remaining, _avail(reel, sim_alloc))
        if take <= 0:
            break
        plans.append({"line": line, "reel": reel, "length_ft": calc.as_number(take)})
        sim_alloc[reel["id"]] += take
        remaining -= take
        pool.remove(reel)


def apply_allocation(order, plans, lot_pins):
    """Persist the plan: RESERVED allocations, reel reservations, line status."""
    next_seq = {}
    for line in lookup.order_lines_of(order["id"]):
        existing = lookup.allocations_of_line(line["id"])
        next_seq[line["id"]] = max([a["sequence_no"] for a in existing], default=0) + 1

    for item in plans:
        line = item["line"]
        reel = item["reel"]
        rec = db.base_record()
        rec.update({
            "order_line_id": line["id"],
            "sales_order_id": order["id"],
            "reel_id": reel["id"],
            "remnant_reel_id": None,
            "sequence_no": next_seq[line["id"]],
            "length_ft": item["length_ft"],
            "status": "RESERVED",
            "commit_mode": None,
            "cut_window_start": None,
            "cut_window_end": None,
            "cut_charge_applied_cents": 0,
            "scrap_ft": 0,
        })
        next_seq[line["id"]] += 1
        db.allocations.add(rec)

        reel["allocated_length_ft"] = calc.as_number(
            calc.dec(reel["allocated_length_ft"]) + calc.dec(item["length_ft"])
        )
        if reel["status"] == "IN_STOCK" and calc.dec(reel["allocated_length_ft"]) > 0:
            reel["status"] = "ALLOCATED_PARTIAL"
        db.touch(reel)

    for line in lookup.order_lines_of(order["id"]):
        if line["id"] in lot_pins:
            line["lot_code"] = lot_pins[line["id"]]
        recompute_line(line)


def recompute_line(line):
    """allocated_length_ft is the sum of RESERVED, COMMITTED and CONSUMED footage."""
    total = Decimal(0)
    for alloc in lookup.allocations_of_line(line["id"]):
        if alloc["status"] in ("RESERVED", "COMMITTED", "CONSUMED"):
            total += calc.dec(alloc["length_ft"])
    line["allocated_length_ft"] = calc.as_number(total)
    line["allocation_status"] = calc.line_allocation_status(total, line["required_length_ft"])
    db.touch(line)


def release_allocations_of_order(order):
    """Every RESERVED allocation on the order goes back to the branch pool."""
    for alloc in lookup.allocations_of_order(order["id"]):
        if alloc["status"] != "RESERVED":
            continue
        release_allocation(alloc)


def release_allocation(alloc):
    alloc["status"] = "RELEASED"
    db.touch(alloc)
    reel = db.reels.get(alloc["reel_id"])
    if reel is None:
        return
    reel["allocated_length_ft"] = calc.as_number(
        calc.dec(reel["allocated_length_ft"]) - calc.dec(alloc["length_ft"])
    )
    if calc.dec(reel["allocated_length_ft"]) <= 0 and reel["status"] == "ALLOCATED_PARTIAL" \
            and calc.dec(reel["current_length_ft"]) > 0:
        reel["status"] = "IN_STOCK"
    db.touch(reel)


def settle_reel_after_cut(reel, alloc, product, branch):
    """The five-way remainder decision, evaluated in this exact order after the
    decrement; only the first matching branch fires."""
    current = calc.dec(reel["current_length_ft"])
    allocated = calc.dec(reel["allocated_length_ft"])
    min_cut = calc.dec(product["min_cut_length_ft"])

    if current == 0:
        reel["status"] = "DEPLETED"
    elif allocated > 0:
        reel["status"] = "ALLOCATED_PARTIAL"
    elif current < min_cut:
        remainder = current
        reel["scrap_ft"] = calc.as_number(calc.dec(reel["scrap_ft"]) + remainder)
        reel["current_length_ft"] = 0
        reel["allocated_length_ft"] = 0
        reel["status"] = "SCRAPPED"
        alloc["scrap_ft"] = calc.as_number(remainder)
        branch["scrap_ft_ytd"] = calc.as_number(calc.dec(branch["scrap_ft_ytd"]) + remainder)
        db.touch(branch)
    elif reel["reel_type"] == "MASTER":
        remainder = calc.as_number(current)
        remnant = db.base_record()
        remnant.update({
            "product_id": reel["product_id"],
            "branch_id": reel["branch_id"],
            "parent_reel_id": reel["id"],
            "reel_type": "REMNANT",
            "lot_code": reel["lot_code"],
            "nominal_length_ft": remainder,
            "current_length_ft": remainder,
            "allocated_length_ft": 0,
            "scrap_ft": 0,
            "status": "IN_STOCK",
            "delivered_sales_order_id": None,
            "delivered_at": None,
        })
        db.reels.add(remnant)
        alloc["remnant_reel_id"] = remnant["id"]
        reel["current_length_ft"] = 0
        reel["status"] = "DEPLETED"
    else:
        reel["status"] = "IN_STOCK"

    db.touch(reel)


def bubble_order_to_staged(order):
    """ALLOCATED -> STAGED once every allocation on the order is COMMITTED."""
    if order["fulfillment_status"] != "ALLOCATED":
        return False
    live = [a for a in lookup.allocations_of_order(order["id"])
            if a["status"] in ("RESERVED", "COMMITTED")]
    if not live:
        return False
    if any(a["status"] != "COMMITTED" for a in live):
        return False
    order["fulfillment_status"] = "STAGED"
    db.touch(order)
    return True
