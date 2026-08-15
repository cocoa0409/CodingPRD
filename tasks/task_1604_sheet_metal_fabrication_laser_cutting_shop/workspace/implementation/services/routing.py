"""Routing generation, machine selection, due-date chain, and step advancement."""
import math
from datetime import timedelta
from decimal import Decimal

import db
from db import store, new_id, touch, new_common, iso_logical
from errors import ApiError
from services.audit import audit
from services.capacity import booked_minutes, can_absorb, select_machine
from services.pricing import dec, part_area_cm2, select_vendor

STATION_ORDER = ["LASER", "BRAKE", "WELD", "OUTSIDE_VENDOR", "POWDER"]
IN_HOUSE = {"LASER", "BRAKE", "WELD", "POWDER"}
SLA_DAYS = {"STANDARD": 5, "EXPEDITE": 3, "RUSH": 1}

BRAKE_MIN_PER_BEND_UNIT = 3
WELD_MIN_PER_INCH = 4
POWDER_BASE_MIN = 30
POWDER_AREA_DIVISOR = 500
LASER_LOAD_MIN_PER_SHEET = 5


def required_stations(lines):
    needed = {"LASER"}
    for ln in lines:
        if ln.get("bend_count", 0) > 0:
            needed.add("BRAKE")
        if ln.get("weld_inches", 0) > 0:
            needed.add("WELD")
        if ln.get("finish") in ("PLATING", "ANODIZING"):
            needed.add("OUTSIDE_VENDOR")
        if ln.get("finish") == "POWDER":
            needed.add("POWDER")
    return [s for s in STATION_ORDER if s in needed]


def planned_minutes_for(station, lines, sheets_used):
    if station == "LASER":
        total_secs = sum(ln["billed_cut_seconds"] * ln["qty"] for ln in lines)
        return int(math.ceil(total_secs / 60)) + sheets_used * LASER_LOAD_MIN_PER_SHEET
    if station == "BRAKE":
        return sum(ln["bend_units"] for ln in lines) * BRAKE_MIN_PER_BEND_UNIT
    if station == "WELD":
        total_inches = sum(dec(ln["weld_inches"]) * ln["qty"] for ln in lines)
        return int(math.ceil(total_inches * WELD_MIN_PER_INCH))
    if station == "POWDER":
        total_area = sum(part_area_cm2(ln) * ln["qty"] for ln in lines)
        return POWDER_BASE_MIN + int(math.ceil(total_area / Decimal(POWDER_AREA_DIVISOR)))
    return 0  # OUTSIDE_VENDOR: capacity-free


def assign_machines(stations, lines, sheets_used, exclude_order_id=None):
    """Trial machine selection per in-house station in routing order.
    Returns ({station: machine_id}, error). No mutation."""
    planned = {s: planned_minutes_for(s, lines, sheets_used) for s in stations}
    assigned = {}
    # sequential reservation: simulate booked load accumulating on chosen machines
    simulated = {}
    for station in stations:
        if station not in IN_HOUSE:
            continue
        candidates = [m for m in store.machines.values()
                      if m["station"] == station and m["status"] == "ACTIVE"]

        def load(m):
            return booked_minutes(m["id"], exclude_order_id) + simulated.get(m["id"], 0)

        candidates.sort(key=lambda m: (load(m), m["created_at"], m["_seq"]))
        chosen = None
        for m in candidates:
            if can_absorb(m, load(m), planned[station]):
                chosen = m
                break
        if chosen is None:
            return None, ApiError("ERR_NO_MACHINE_CAPACITY", 409,
                                  "No ACTIVE machine of station %s can absorb the step" % station)
        assigned[station] = chosen["id"]
        simulated[chosen["id"]] = simulated.get(chosen["id"], 0) + planned[station]
    return assigned, None


def generate_routing(order, lines, sheets_used, accept_dt):
    """Create the RoutingStep chain with machine selection and the SLA due chain."""
    stations = required_stations(lines)
    mapping, err = assign_machines(stations, lines, sheets_used)
    if err is not None:
        raise err
    vendor = None
    if "OUTSIDE_VENDOR" in stations:
        processes = {ln["finish"] for ln in lines if ln["finish"] in ("PLATING", "ANODIZING")}
        vendor = select_vendor(processes)
    chain_due = accept_dt + timedelta(days=SLA_DAYS[order["expedite_tier"]])
    steps = []
    for seq, station in enumerate(stations, start=1):
        st = {
            "id": new_id(),
            "order_id": order["id"],
            "station": station,
            "seq": seq,
            "machine_id": mapping.get(station),
            "vendor_id": vendor["id"] if (station == "OUTSIDE_VENDOR" and vendor) else None,
            "planned_minutes": planned_minutes_for(station, lines, sheets_used),
            "completing_operator_id": None,
            "status": "PENDING",
            "_due_dt": chain_due,
            "due_date": iso_logical(chain_due),
        }
        new_common(st)
        store.routing_steps[st["id"]] = st
        steps.append(st)
    return steps


def recompute_order_due(order):
    steps = [st for st in store.routing_steps.values() if st["order_id"] == order["id"]]
    if not steps:
        return
    latest = max(st["_due_dt"] for st in steps if st.get("_due_dt") is not None)
    order["due_date"] = iso_logical(latest)


def advance_after_step(order, step):
    """Serial chain advancement after a step completes or is skipped."""
    steps = sorted([st for st in store.routing_steps.values() if st["order_id"] == order["id"]],
                   key=lambda s: s["seq"])
    nxt = next((st for st in steps if st["status"] == "PENDING"), None)
    if nxt is None:
        order["status"] = "INSPECTION"
        touch(order)
        audit("FabricationOrder", order["id"], "ORDER_READY_FOR_INSPECTION",
              "system", "system", {"after": {"status": "INSPECTION"}})
    elif nxt["station"] == "OUTSIDE_VENDOR":
        nxt["status"] = "IN_PROGRESS"
        vendor = store.outside_vendors.get(nxt["vendor_id"])
        lead = vendor["lead_time_days"] if vendor else 0
        if order["expedite_tier"] == "RUSH":
            lead = int(math.ceil(lead / 2))
        due = db.LOGICAL_CLOCK + timedelta(days=lead)
        nxt["_due_dt"] = due
        nxt["due_date"] = iso_logical(due)
        touch(nxt)
        order["status"] = "AWAITING_OUTSIDE"
        touch(order)
        audit("FabricationOrder", order["id"], "ORDER_SENT_OUTSIDE",
              "system", "system", {"after": {"status": "AWAITING_OUTSIDE"}})
    else:
        nxt["status"] = "IN_PROGRESS"
        touch(nxt)
        if nxt["station"] == "POWDER":
            order["status"] = "FINISHING"
            touch(order)
    recompute_order_due(order)
