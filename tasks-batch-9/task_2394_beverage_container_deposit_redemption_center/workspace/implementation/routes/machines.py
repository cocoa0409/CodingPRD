from datetime import timedelta

from flask import Blueprint

import clock
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, narrow, own
from routes.common import fk, lookup, require_operational
from services import projections as proj

bp = Blueprint("machines", __name__)

EVENTS = ("SESSION_OPEN", "SESSION_CLOSE", "JAM_REPORTED", "JAM_CLEARED", "BIN_FULL",
          "EMPTY_BIN", "TAKE_OUT_OF_SERVICE", "RETURN_TO_SERVICE", "RETIRE")

ORIGIN_STATES = {
    "SESSION_OPEN": ("IDLE",),
    "SESSION_CLOSE": ("COUNTING",),
    "JAM_REPORTED": ("COUNTING",),
    "JAM_CLEARED": ("JAMMED",),
    "BIN_FULL": ("IDLE",),
    "EMPTY_BIN": ("BIN_FULL",),
    "TAKE_OUT_OF_SERVICE": ("IDLE",),
    "RETURN_TO_SERVICE": ("OUT_OF_SERVICE",),
    "RETIRE": ("IDLE", "OUT_OF_SERVICE"),
}

COOLDOWN = timedelta(minutes=5)


@bp.get("/reverse-vending-machines/<rid>")
def get_machine(rid):
    authenticate("ProgramAdmin", "CenterOperator")
    rec = db.machines.get(rid)
    if rec is not None:
        own(center_id=rec.get("center_id"))
    rec = lookup("machine", rid)
    return response.obj(db.public(rec))


def _cooldown_active(machine):
    stamp = machine.get("last_session_closed_at")
    if not stamp:
        return False
    closed = clock.parse_stamp(stamp)
    if closed is None:
        return False
    now = clock.now().replace(microsecond=0)
    closed = closed.replace(microsecond=0)
    return closed <= now < closed + COOLDOWN


@bp.post("/reverse-vending-machines/<rid>/machine-events")
def machine_event(rid):
    authenticate("CenterOperator", "ProgramAdmin")
    machine = db.machines.get(rid)
    if machine is not None:
        own(center_id=machine.get("center_id"))
    body = v.body()
    raw_event = body.get("event_type")
    if isinstance(raw_event, str):
        narrow(raw_event, program_admin_only=("RETIRE",))
    machine = lookup("machine", rid)
    visit = fk("visit", body, "visit_id")
    if visit is not None:
        own(center_id=visit.get("center_id"))
    event = v.req_enum(body, "event_type", EVENTS)
    v.opt_str(body, "note")

    center = db.centers.get(machine["center_id"])

    # Rung 11 -- only a session open demands an operational centre.
    if event == "SESSION_OPEN":
        require_operational(center)

    # Rung 16 -- machine state machine.
    if machine["status"] not in ORIGIN_STATES[event]:
        fail("ERR_INVALID_MACHINE_STATE",
             "Event %s is not available from %s." % (event, machine["status"]))
    if event == "BIN_FULL" and machine["bin_filled_count"] < machine["bin_capacity_containers"]:
        fail("ERR_INVALID_MACHINE_STATE", "The bin has not reached its capacity.")

    # Rung 27 -- cool-down window.
    if event == "SESSION_OPEN" and _cooldown_active(machine):
        fail("ERR_MACHINE_COOLDOWN_ACTIVE", "The machine cool-down window has not elapsed.")

    # Rung 34 -- machine / visit coherence.
    occupying_id = machine.get("_session_visit_id")
    if event == "SESSION_OPEN":
        if visit is None:
            v.bad("Field 'visit_id' is required for a SESSION_OPEN event.")
        if visit.get("machine_id") != machine["id"] or visit.get("center_id") != machine["center_id"]:
            fail("ERR_MACHINE_CENTER_MISMATCH",
                 "The named visit is not being served by this machine.")
        if visit["count_status"] not in ("OPEN", "COUNTING"):
            fail("ERR_INVALID_COUNT_STATE", "The named visit is not open for counting.")
    elif event in ("JAM_REPORTED", "JAM_CLEARED", "SESSION_CLOSE"):
        if visit is not None:
            if visit.get("center_id") != machine["center_id"]:
                fail("ERR_MACHINE_CENTER_MISMATCH",
                     "The named visit belongs to another centre.")
            if occupying_id is not None and visit["id"] != occupying_id:
                fail("ERR_MACHINE_CENTER_MISMATCH",
                     "The named visit is not the visit occupying this machine.")
            if occupying_id is None and visit.get("machine_id") != machine["id"]:
                fail("ERR_MACHINE_CENTER_MISMATCH",
                     "The named visit is not being served by this machine.")
        elif occupying_id is not None:
            visit = db.visits.get(occupying_id)
    elif visit is not None:
        if visit.get("center_id") != machine["center_id"]:
            fail("ERR_MACHINE_CENTER_MISMATCH", "The named visit belongs to another centre.")

    now = clock.now_iso()
    today = clock.today()
    recompute_machines = False
    check_fleet_down = False

    if event == "SESSION_OPEN":
        machine["status"] = "COUNTING"
        machine["session_started_at"] = now
        machine["open_session_count"] = 1
        machine["_session_visit_id"] = visit["id"]
    elif event == "SESSION_CLOSE":
        machine["status"] = "IDLE"
        machine["last_session_closed_at"] = now
        machine["session_started_at"] = None
        machine["open_session_count"] = 0
        machine["_session_visit_id"] = None
    elif event == "JAM_REPORTED":
        fourth = machine["jam_day"] == today and machine["jam_count_today"] >= 3
        machine["jam_hold_count"] += 1
        if machine["jam_day"] != today:
            machine["jam_day"] = today
            machine["jam_count_today"] = 1
        else:
            machine["jam_count_today"] += 1
        if fourth:
            machine["status"] = "OUT_OF_SERVICE"
            machine["session_started_at"] = None
            machine["open_session_count"] = 0
            machine["_session_visit_id"] = None
            recompute_machines = True
            check_fleet_down = True
        else:
            machine["status"] = "JAMMED"
        if visit is not None:
            if visit["count_status"] == "COUNTING":
                visit["count_status"] = "JAM_HOLD"
            visit["requires_manual_recount"] = True
            visit["jam_events_count"] += 1
            touch(visit)
    elif event == "JAM_CLEARED":
        machine["status"] = "IDLE"
        machine["last_session_closed_at"] = now
        machine["session_started_at"] = None
        machine["open_session_count"] = 0
        machine["_session_visit_id"] = None
        if visit is not None and visit["count_status"] == "JAM_HOLD":
            visit["count_status"] = "COUNTING"
            touch(visit)
    elif event == "BIN_FULL":
        machine["status"] = "BIN_FULL"
    elif event == "EMPTY_BIN":
        machine["status"] = "IDLE"
        machine["bin_filled_count"] = 0
    elif event == "TAKE_OUT_OF_SERVICE":
        machine["status"] = "OUT_OF_SERVICE"
        recompute_machines = True
        check_fleet_down = True
    elif event == "RETURN_TO_SERVICE":
        machine["status"] = "IDLE"
        machine["jam_count_today"] = 0
        machine["jam_day"] = None
        recompute_machines = True
    elif event == "RETIRE":
        machine["status"] = "RETIRED"
        machine["session_started_at"] = None
        machine["open_session_count"] = 0
        machine["_session_visit_id"] = None
        recompute_machines = True

    touch(machine)
    if recompute_machines and center is not None:
        proj.recompute_center_machine_counts(center)
        if check_fleet_down:
            proj.maybe_suspend_for_fleet_down(center)
    return response.obj(db.public(machine))
