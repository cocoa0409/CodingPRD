"""The three capacity axes and the derived posture (PRD 2.9).

Adjudication of friction 4: order-status definition -- the STORED
`confirmed_units` on an OfferWindow is the same figure that
`window_units_remaining` consumes, i.e. the summed quantity of lines that are
neither RELEASED nor RECALL_VOID whose owning order is CONFIRMED,
IN_PRODUCTION, READY or FULFILLED.  The competing line-status definition
(ALLOCATED/FULFILLED/SHORTED/CREDITED plus PENDING lines of CONFIRMED orders)
diverges on PENDING lines of IN_PRODUCTION orders and on ALLOCATED lines of
FORFEITED orders; adopting it would make the declared window_unit_conservation
invariant of PRD 2.10 -- stated over the STORED field -- false in exactly those
situations, and would desynchronise the stored figure from the capacity ladder
that rungs 53-55 evaluate.  The order-status reading keeps both reachable.
"""

from fractions import Fraction
from math import ceil

import config
from db import DB, touch
from tsutil import lt, num2, round_half_up

CONFIRMED_ORDER_STATES = ("CONFIRMED", "IN_PRODUCTION", "READY", "FULFILLED")
DEAD_LINE_STATES = ("RELEASED", "RECALL_VOID")


def window_lines(window_id):
    """(line, order) pairs for every line attached to this window."""
    out = []
    for line in DB.values("order_lines"):
        order = DB.get("orders", line.get("order_id"))
        if order is None or order.get("offer_window_id") != window_id:
            continue
        out.append((line, order))
    return out


def _counted(window_id, now):
    """(confirmed_units, held_units, demand_by_menu_item) per PRD 2.9."""
    confirmed = 0
    held = 0
    demand = {}
    for line, order in window_lines(window_id):
        qty = line.get("quantity") or 0
        counted = False
        if (line.get("line_status") not in DEAD_LINE_STATES
                and order.get("order_status") in CONFIRMED_ORDER_STATES):
            confirmed += qty
            counted = True
        elif (line.get("line_status") == "PENDING"
              and order.get("order_status") == "PENDING_HOLD"
              and order.get("hold_expires_at") is not None
              and lt(now, order["hold_expires_at"])):
            held += qty
            counted = True
        if counted:
            key = line.get("menu_item_id")
            demand[key] = demand.get(key, 0) + qty
    return confirmed, held, demand


def reserved_units(window_id):
    total = 0
    for cyc in DB.coll("subscription_cycles").values():
        if cyc.get("offer_window_id") != window_id:
            continue
        if cyc.get("cycle_status") in ("RESERVED", "CONFIRMED"):
            total += cyc.get("reserved_units") or 0
    return total


def _oven_for(menu_item, slot_count):
    if menu_item is None:
        hours = config.OVEN_HOURS_PER_BATCH_SLOT
    elif menu_item.get("oven_profile") == "LONG_BAKE":
        hours = menu_item.get("oven_hours_per_batch")
        if hours is None:
            hours = config.OVEN_HOURS_PER_BATCH_SLOT
    else:
        # STANDARD ignores the item's own oven_hours_per_batch entirely
        hours = config.OVEN_HOURS_PER_BATCH_SLOT
    return round_half_up(Fraction(slot_count) * Fraction(str(hours)),
                         config.OVEN_HOURS_PRECISION_DECIMALS)


def slot_count_for(demand_units):
    if demand_units <= 0:
        return 0
    return int(ceil(Fraction(demand_units, config.BATCH_SLOT_UNITS)))


def figures(window, now, extra_item=None, extra_units=0):
    """All nine capacity figures plus the derived posture.

    `extra_item` / `extra_units` apply a prospective unit delta on one menu
    item, which is how rungs 53-55 test a line addition or a quantity patch.
    """
    wid = window["id"]
    confirmed, held, demand = _counted(wid, now)
    reserved = reserved_units(wid)
    if extra_item is not None and extra_units:
        held += extra_units
        demand[extra_item] = demand.get(extra_item, 0) + extra_units

    cap_units = window.get("capacity_units") or 0
    cap_slots = window.get("capacity_batch_slots") or 0
    cap_oven = window.get("capacity_oven_hours") or 0

    units_remaining = cap_units - confirmed - held - reserved

    slots_used = 0
    oven_used = round_half_up(0, config.OVEN_HOURS_PRECISION_DECIMALS)
    for item_id, units in demand.items():
        if units <= 0:
            continue
        slots = slot_count_for(units)
        slots_used += slots
        oven_used += _oven_for(DB.get("menu_items", item_id), slots)

    slots_remaining = cap_slots - slots_used
    oven_remaining = round_half_up(Fraction(str(cap_oven)), 2) - oven_used

    # ---- capacity_posture (PRD 2.9) ------------------------------------
    if units_remaining == 0 or slots_remaining == 0 or oven_remaining <= 0:
        posture = "EXHAUSTED"
    else:
        utils = []
        if cap_units > 0:
            utils.append(Fraction(confirmed + held + reserved, cap_units))
        elif confirmed + held + reserved > 0:
            utils.append(Fraction(1))
        if cap_slots > 0:
            utils.append(Fraction(slots_used, cap_slots))
        elif slots_used > 0:
            utils.append(Fraction(1))
        cap_oven_f = Fraction(str(cap_oven))
        if cap_oven_f > 0:
            utils.append(Fraction(oven_used) / cap_oven_f)
        elif oven_used > 0:
            utils.append(Fraction(1))
        threshold = Fraction(str(config.CAPACITY_CONSTRAINED_UTILIZATION_PCT))
        posture = ("CONSTRAINED" if utils and max(utils) >= threshold
                   else "OPEN_CAPACITY")

    return {
        "confirmed_units": confirmed,
        "held_units": held,
        "reserved_units": reserved,
        "units_remaining": units_remaining,
        "slots_used": slots_used,
        "batch_slots_remaining": slots_remaining,
        "oven_hours_used": num2(oven_used),
        "oven_hours_remaining": num2(oven_remaining),
        # exact 2-dp Decimals for rung 55, so the oven comparison never rides
        # on binary floating point
        "oven_hours_used_exact": oven_used,
        "oven_hours_remaining_exact": oven_remaining,
        "capacity_posture": posture,
        "demand_by_item": demand,
    }


def store(window, now):
    """Recompute and store the four window-held capacity figures.

    Returns True when `capacity_posture` moved, which is what PRD 2.9 makes a
    version-bumping event."""
    fig = figures(window, now)
    before = window.get("capacity_posture")
    window["confirmed_units"] = fig["confirmed_units"]
    window["held_units"] = fig["held_units"]
    window["reserved_units"] = fig["reserved_units"]
    window["capacity_posture"] = fig["capacity_posture"]
    return before != fig["capacity_posture"]


def sync(window, now, force_bump=False):
    """Recompute a window's capacity figures during a WRITE and bump its
    `version` at most once for the request.

    A window's version moves when the endpoint declares it (`force_bump`) or
    when `capacity_posture` moved (PRD 2.9: "Every posture change increments
    the window's version").  Exactly one bump per request per window, so an
    OCC client that read version N and adds a line lands on N+1 whether or not
    the posture happened to move in the same call."""
    if window is None:
        return False
    changed = store(window, now)
    if force_bump or changed:
        touch(window, now)
        return True
    return False
