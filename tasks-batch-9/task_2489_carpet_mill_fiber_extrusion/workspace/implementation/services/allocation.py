"""The deterministic roll-good selector and the allocation waterfall (PRD 3.9)."""

from decimal import Decimal

import calc
from calc import dec, rhu
from db import insert, ordered, store, touch
from errors import ApiError
from services import compliance, ledgers

BAND_ORDINAL = {"A": 0, "B": 1, "C": 2, "SOLUTION": 3, "OUT": 4}
LOT_ALLOCATABLE_STATUSES = ("APPROVED", "EXHAUSTED")


def _run_ids_of_style(style_id):
    return set(r["id"] for r in ledgers.runs_of_style(style_id))


def candidates_for(order):
    """The pre-shade candidate set of PRD 3.9, in default (created_at) order."""
    run_ids = _run_ids_of_style(order["style_id"])
    out = []
    for roll in ordered(list(store.roll_goods.values())):
        if roll["production_run_id"] not in run_ids:
            continue
        if roll["qa_status"] != "PASSED":
            continue
        if roll["inventory_status"] != "AVAILABLE":
            continue
        if dec(roll["available_yards"]) <= 0:
            continue
        if roll["shade_band"] == "OUT":
            continue
        lot_id = roll.get("dye_lot_id")
        if lot_id:
            lot = store.dye_lots.get(lot_id)
            if not lot or lot["status"] not in LOT_ALLOCATABLE_STATUSES:
                continue
        out.append(roll)
    return out


def choose_band(candidates):
    """Band with the greatest total available_yards; ties broken by band ordinal."""
    totals = {}
    for roll in candidates:
        band = roll["shade_band"]
        totals[band] = totals.get(band, Decimal(0)) + dec(roll["available_yards"])
    if not totals:
        return None
    best = None
    for band, total in totals.items():
        key = (-total, BAND_ORDINAL.get(band, 99))
        if best is None or key < best[0]:
            best = (key, band)
    return best[1]


def choose_lot(candidates):
    """Lot with the greatest uncommitted_yards; ties broken by earlier created_at."""
    lots = []
    seen = set()
    for roll in candidates:
        lot_id = roll.get("dye_lot_id")
        if not lot_id or lot_id in seen:
            continue
        lot = store.dye_lots.get(lot_id)
        if not lot:
            continue
        seen.add(lot_id)
        lots.append(lot)
    if not lots:
        return None
    best = None
    for lot in lots:
        key = (-dec(lot["uncommitted_yards"]), lot["created_at"], lot["_seq"])
        if best is None or key < best[0]:
            best = (key, lot)
    return best[1]


def rank(candidates):
    """is_remnant DESC, available_yards ASC, created_at ASC."""
    return sorted(
        candidates,
        key=lambda r: (
            0 if r["is_remnant"] else 1,
            dec(r["available_yards"]),
            r["created_at"],
            r["_seq"],
        ),
    )


def _remaining_for(order):
    remaining = dec(order["requested_yards"]) - dec(order["allocated_yards"])
    if remaining < 0:
        return Decimal("0.0")
    return remaining


def auto_allocate(order):
    """Rungs 26, 28 and 29 followed by the waterfall of PRD 3.9."""
    pool = candidates_for(order)

    chosen_lot = None
    if pool:
        # Rung 26 — dye-lot availability for allocation.
        if order["shade_tolerance"] == "SINGLE_LOT":
            chosen_lot = choose_lot(pool)
            if chosen_lot is not None and chosen_lot["status"] == "EXHAUSTED":
                raise ApiError(
                    "ERR_DYE_LOT_EXHAUSTED",
                    "Dye lot %s is exhausted and cannot close a SINGLE_LOT order"
                    % chosen_lot["lot_code"],
                )

    # Rung 28 — non-empty candidate set.
    if not pool:
        raise ApiError(
            "ERR_NO_ELIGIBLE_ROLL_GOODS",
            "No roll good of the ordered style is eligible for allocation",
        )

    if order["shade_tolerance"] == "BAND_MATCH":
        band = choose_band(pool)
        pool = [r for r in pool if r["shade_band"] == band]
    elif order["shade_tolerance"] == "SINGLE_LOT":
        lot_id = chosen_lot["id"] if chosen_lot is not None else None
        pool = [r for r in pool if r.get("dye_lot_id") == lot_id]

    if not pool:
        raise ApiError(
            "ERR_NO_ELIGIBLE_ROLL_GOODS",
            "No roll good of the ordered style is eligible for allocation",
        )

    remaining = _remaining_for(order)
    plan = []
    for roll in rank(pool):
        if remaining <= 0:
            break
        take = rhu(min(remaining, dec(roll["available_yards"])), 1)
        if take <= 0:
            continue
        plan.append((roll, take))
        remaining = remaining - take

    # Rung 29 — a CUSTOM order is never partially allocated.
    if remaining > 0 and order["order_type"] == "CUSTOM":
        raise ApiError(
            "ERR_INSUFFICIENT_YARDAGE",
            "Candidate yardage does not fully cover the requested yards",
        )

    lines = []
    for roll, take in plan:
        lines.append(create_line(order, roll, take))

    settle(order, lines)

    if remaining <= 0:
        order["status"] = "ALLOCATED"
    else:
        order["status"] = "BACKORDERED"
    touch(order)

    style = store.styles.get(order["style_id"])
    if style:
        ledgers.recompute_style_posture(style)
    return order


def create_line(order, roll, yards):
    """Create one RESERVED allocation line against ``roll``."""
    style = store.styles.get(order["style_id"])
    price = style["list_price_cents_per_yard"] if style else 0
    band = roll["shade_band"]
    from_remnant = bool(roll["is_remnant"])
    line = insert(
        store.cut_allocations,
        {
            "cut_order_id": order["id"],
            "roll_good_id": roll["id"],
            "yards": float(rhu(yards, 1)),
            "shade_band": band,
            "from_remnant": from_remnant,
            "line_cents": calc.line_cents(float(rhu(yards, 1)), price, band, from_remnant),
            "status": "RESERVED",
        },
    )
    return line


def settle(order, lines):
    """Reconcile rolls, order charges and dye lots after new lines appear."""
    seen = set()
    for line in lines:
        roll_id = line["roll_good_id"]
        if roll_id in seen:
            continue
        seen.add(roll_id)
        roll = store.roll_goods.get(roll_id)
        if roll:
            ledgers.recompute_roll(roll)
    ledgers.recompute_order_financials(order)
    ledgers.recompute_dye_lots_for_lines(ledgers.lines_of_order(order["id"]))
