"""The hold, the lameness chain (CASCADE-A) and the expiry chain (CASCADE-D)."""

from core.constants import LAMENESS_HOLD_SEVERITY_THRESHOLD, TERMINAL_APPOINTMENT_STATUSES
from core.store import db, order_key

from .reservations import release_reservations
from .rollups import recompute_appointment_rollups, recompute_estimate
from .routecalc import (
    appointments_of_stop,
    recompute_route_totals,
    recompute_stop_minutes,
    revert_planned_route_if_emptied,
)
from .scheduling import refresh_next_due


def cases_of(horse):
    rows = [c for c in db.lameness_cases.values() if c["horse_id"] == horse["id"]]
    rows.sort(key=order_key)
    return rows


def appointments_of(horse):
    rows = [a for a in db.appointments.values() if a["horse_id"] == horse["id"]]
    rows.sort(key=order_key)
    return rows


def hold_is_warranted(horse):
    """One qualifying case still open keeps the horse on hold."""
    for case in cases_of(horse):
        if case["hold_applied"] and case["status"] in ("OPEN", "PRESCRIBED"):
            return True
    return False


def qualifies_for_hold(severity):
    return severity >= LAMENESS_HOLD_SEVERITY_THRESHOLD


def run_lameness_chain(horse):
    """Hops 3-6 plus the parallel branch 3b/4b of CASCADE-A."""
    touched_stops = []
    for appointment in appointments_of(horse):
        if appointment["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        stop = db.get("route_stops", appointment.get("route_stop_id"))
        appointment["status"] = "BLOCKED"
        appointment["route_stop_id"] = None
        db.touch(appointment)
        # hop 4/5: only RESERVED rows are released; COMMITTED and RELEASED are untouched.
        release_reservations(appointment)
        if stop is not None and stop not in touched_stops:
            touched_stops.append(stop)

    routes = []
    for stop in touched_stops:
        if recompute_stop_minutes(stop):
            db.touch(stop)
        # hop 3b: only a stop left with NO attached appointment at all is voided.
        if stop["status"] == "PENDING" and not appointments_of_stop(stop):
            stop["status"] = "VOIDED"
            db.touch(stop)
        route = db.get("routes", stop["route_id"])
        if route is not None and route not in routes:
            routes.append(route)
    for route in routes:
        before = recompute_route_totals(route)
        db.touch(route)
        revert_planned_route_if_emptied(route, before)


def clear_hold(horse):
    """Every BLOCKED appointment of the horse returns to UNROUTED, unattached."""
    for appointment in appointments_of(horse):
        if appointment["status"] == "BLOCKED":
            appointment["status"] = "UNROUTED"
            db.touch(appointment)


def recompute_hold(horse, run_chain=False):
    """Re-derive hold_status.  Returns True when the horse row changed."""
    wanted = "HOLD" if hold_is_warranted(horse) else "CLEAR"
    if wanted == horse["hold_status"]:
        return False
    horse["hold_status"] = wanted
    if wanted == "HOLD":
        if run_chain:
            run_lameness_chain(horse)
    else:
        clear_hold(horse)
    return True


def expire_prescription(prescription):
    """CASCADE-D hops 2-5 for one prescription the clock has pushed past."""
    prescription["status"] = "EXPIRED"
    db.touch(prescription)
    horse = db.get("horses", prescription["horse_id"])
    if horse is None:
        return
    horse_changed = False
    if horse.get("active_prescription_id") == prescription["id"]:
        horse["active_prescription_id"] = None
        horse_changed = True
    # hop 3: next_due_on reverts to the routine derivation.
    if refresh_next_due(horse):
        horse_changed = True
    if horse_changed:
        db.touch(horse)

    # hop 4: every PLANNED CORRECTIVE line on a non-terminal appointment goes REMOVED.
    affected = []
    for appointment in appointments_of(horse):
        if appointment["status"] in TERMINAL_APPOINTMENT_STATUSES:
            continue
        lines = [
            line
            for line in db.service_lines.values()
            if line["appointment_id"] == appointment["id"]
            and line["status"] == "PLANNED"
            and line["service_type"] == "CORRECTIVE"
        ]
        if not lines:
            continue
        for line in sorted(lines, key=order_key):
            line["status"] = "REMOVED"
            db.touch(line)
        affected.append(appointment)

    # hop 5: roll-ups, stop minutes and route totals are recomputed.
    routes = []
    for appointment in affected:
        recompute_appointment_rollups(appointment, horse)
        recompute_estimate(appointment, horse)
        db.touch(appointment)
        stop = db.get("route_stops", appointment.get("route_stop_id"))
        if stop is not None:
            if recompute_stop_minutes(stop):
                db.touch(stop)
            route = db.get("routes", stop["route_id"])
            if route is not None and route not in routes:
                routes.append(route)
    for route in routes:
        before = recompute_route_totals(route)
        db.touch(route)
        revert_planned_route_if_emptied(route, before)
