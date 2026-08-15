"""Treatment machines and the machine-down cascade (PRD 3.6, 3.8)."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_MACHINE_ALREADY_DOWN,
                    ERR_MACHINE_NOT_DOWN)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import machine_json, session_json, simulation_json
from timeutil import new_id
from validate import req_str, req_enum

bp = Blueprint("machines", __name__)

MACHINE_TYPES = {"CT_SIMULATOR", "LINAC"}
STATUSES = {"OPERATIONAL", "DOWN"}


@bp.post("/oncology/machines")
@require_roles("SystemAdmin")
def create_machine(user_id):
    body = get_body()
    name = req_str(body, "name")
    mtype = req_enum(body, "machine_type", MACHINE_TYPES)
    room = req_str(body, "room")
    m = new_entity()
    m.update({"id": new_id(), "name": name, "machine_type": mtype,
              "room": room, "status": "OPERATIONAL"})
    store.machines[m["id"]] = m
    return success(machine_json(m), 201)


@bp.get("/oncology/machines")
@require_roles(*ALL_ROLES)
def list_machines(user_id):
    items = sorted_all(store.machines.values())
    page, meta = paginate(items)
    return success([machine_json(m) for m in page], 200, pagination=meta)


@bp.get("/oncology/machines/<mid>")
@require_roles(*ALL_ROLES)
def get_machine(mid, user_id):
    m = store.machines.get(mid)
    if m is None:
        err(ERR_NOT_FOUND, "machine not found")
    return success(machine_json(m), 200)


@bp.put("/oncology/machines/<mid>/status")
@require_roles("SystemAdmin")
def set_machine_status(mid, user_id):
    m = store.machines.get(mid)
    if m is None:
        err(ERR_NOT_FOUND, "machine not found")
    body = get_body()
    status = req_enum(body, "status", STATUSES)
    if status == "DOWN":
        if m["status"] == "DOWN":
            err(ERR_MACHINE_ALREADY_DOWN, "Machine already DOWN")
        m["status"] = "DOWN"
        touch(m)
        # cascade: future SCHEDULED fractions on this machine are cancelled and
        # each affected course gains an OPEN MACHINE_DOWN interruption
        now = store.clock
        affected = [s for s in store.sessions.values()
                    if s["machine_id"] == mid and s["status"] == "SCHEDULED"
                    and s["_start"] >= now]
        affected.sort(key=lambda s: (s["_start"], s["_seq"]))
        by_course = {}
        for s in affected:
            s["status"] = "CANCELLED"
            s["cancellation_reason"] = "MACHINE_DOWN"
            touch(s)
            by_course.setdefault(s["course_id"], []).append(s)
        for course_id, sessions in by_course.items():
            course = store.courses.get(course_id)
            if course is None:
                continue
            earliest = sessions[0]["_start"].date().isoformat()
            intr = new_entity()
            intr.update({
                "id": new_id(), "course_id": course_id, "reason": "MACHINE_DOWN",
                "missed_count": len(sessions),
                "start_date": earliest, "end_date": earliest,
                "gap_days": 1,
                "applied_strategy": None, "status": "OPEN",
            })
            store.interruptions[intr["id"]] = intr
            course["open_interruption_count"] += 1
            touch(course)
    else:  # OPERATIONAL
        if m["status"] != "DOWN":
            err(ERR_MACHINE_NOT_DOWN, "Restore requires machine DOWN")
        m["status"] = "OPERATIONAL"
        touch(m)
    return success(machine_json(m), 200)


@bp.get("/oncology/machines/<mid>/fraction-sessions")
@require_roles(*ALL_ROLES)
def machine_sessions(mid, user_id):
    if mid not in store.machines:
        err(ERR_NOT_FOUND, "machine not found")
    items = sorted_all(s for s in store.sessions.values() if s["machine_id"] == mid)
    page, meta = paginate(items)
    return success([session_json(s) for s in page], 200, pagination=meta)


@bp.get("/oncology/machines/<mid>/simulation-appointments")
@require_roles(*ALL_ROLES)
def machine_simulations(mid, user_id):
    if mid not in store.machines:
        err(ERR_NOT_FOUND, "machine not found")
    items = sorted_all(a for a in store.simulations.values() if a["machine_id"] == mid)
    page, meta = paginate(items)
    return success([simulation_json(a) for a in page], 200, pagination=meta)
