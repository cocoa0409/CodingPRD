"""Shooting days and scenes (stripboard)."""
from flask import Blueprint, request

from db import db, now_iso, new_id
from errors import err
from middleware import authenticate, authorize
from helpers import (get_json_body, require_string, require_enum, require_int,
                     optional_enum, parse_pagination, paginate)
from response import success_object, success_array
from services.serialize import public
from services.recompute import touch, recompute_committed_cost

bp = Blueprint("schedule", __name__)

UNITS = {"MAIN", "SECOND", "SPLINTER"}
INT_EXT = {"INT", "EXT"}
DAY_NIGHT = {"DAY", "NIGHT"}
ALL_ROLES = {"LineProducer", "FirstAD", "PayrollCoordinator", "PostSupervisor", "UnionRep"}


def recompute_page_eighths(day):
    total = sum(s["page_eighths"] for s in db.scenes.values()
                if s["shooting_day_id"] == day["id"])
    if day["estimated_page_eighths"] != total:
        day["estimated_page_eighths"] = total
        touch(day)


# --- ShootingDay ------------------------------------------------------------
@bp.route("/shooting-days", methods=["POST"])
def create_shooting_day():
    role = authenticate()
    authorize(role, {"FirstAD"})
    body = get_json_body()
    production_id = require_string(body, "production_id")
    if production_id not in db.productions:
        raise err("ERR_NOT_FOUND", "Production not found.")
    shoot_date = require_string(body, "shoot_date")
    day_number = require_int(body, "day_number", minimum=1)
    unit = optional_enum(body, "unit", UNITS, "MAIN")
    with db.lock:
        # day_number unique among non-CANCELLED days of the production
        for d in db.shooting_days.values():
            if (d["production_id"] == production_id and d["status"] != "CANCELLED"
                    and d["day_number"] == day_number):
                raise err("ERR_DUPLICATE_DAY_NUMBER", "Duplicate day_number for production.")
        ts = now_iso()
        day = {
            "id": new_id(),
            "production_id": production_id,
            "shoot_date": shoot_date,
            "day_number": day_number,
            "unit": unit,
            "status": "PLANNED",
            "estimated_page_eighths": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.shooting_days[day["id"]] = day
        return success_object(public(day), status=201)


@bp.route("/shooting-days/<did>", methods=["GET"])
def get_shooting_day(did):
    role = authenticate()
    authorize(role, ALL_ROLES)
    day = db.shooting_days.get(did)
    if not day:
        raise err("ERR_NOT_FOUND", "Shooting day not found.")
    return success_object(public(day))


@bp.route("/shooting-days", methods=["GET"])
def list_shooting_days():
    role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    production_id = request.args.get("production_id")
    status = request.args.get("status")
    items = list(db.shooting_days.values())
    if production_id is not None:
        items = [d for d in items if d["production_id"] == production_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_array([public(d) for d in page], limit, offset, total)


@bp.route("/shooting-days/<did>/start", methods=["POST"])
def start_day(did):
    role = authenticate()
    authorize(role, {"FirstAD"})
    with db.lock:
        day = db.shooting_days.get(did)
        if not day:
            raise err("ERR_NOT_FOUND", "Shooting day not found.")
        if day["status"] != "CALLED":
            raise err("ERR_INVALID_STATE", "Day must be CALLED to start.")
        day["status"] = "IN_PROGRESS"
        touch(day)
        return success_object(public(day))


@bp.route("/shooting-days/<did>/wrap", methods=["POST"])
def wrap_day(did):
    role = authenticate()
    authorize(role, {"FirstAD"})
    with db.lock:
        day = db.shooting_days.get(did)
        if not day:
            raise err("ERR_NOT_FOUND", "Shooting day not found.")
        if day["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "Day must be IN_PROGRESS to wrap.")
        for a in db.assignments.values():
            if a["shooting_day_id"] == did and a["attendance_status"] in ("SCHEDULED", "CHECKED_IN"):
                raise err("ERR_OPEN_ASSIGNMENTS_BLOCK_WRAP",
                          "Day still has open assignments.")
        day["status"] = "WRAPPED"
        touch(day)
        return success_object(public(day))


@bp.route("/shooting-days/<did>/cancel", methods=["POST"])
def cancel_day(did):
    role = authenticate()
    authorize(role, {"FirstAD"})
    with db.lock:
        day = db.shooting_days.get(did)
        if not day:
            raise err("ERR_NOT_FOUND", "Shooting day not found.")
        if day["status"] not in ("PLANNED", "CALLED"):
            raise err("ERR_INVALID_STATE", "Only a PLANNED or CALLED day can be cancelled.")
        was_called = day["status"] == "CALLED"
        day["status"] = "CANCELLED"
        # cascade: SCHEDULED assignments -> NO_SHOW / VOID
        voided_any = False
        for a in db.assignments.values():
            if a["shooting_day_id"] == did and a["attendance_status"] == "SCHEDULED":
                a["attendance_status"] = "NO_SHOW"
                a["payment_status"] = "VOID"
                touch(a)
                voided_any = True
        # cascade: unschedule scenes
        for s in db.scenes.values():
            if s["shooting_day_id"] == did:
                s["shooting_day_id"] = None
                touch(s)
        # cascade: cancel the published call sheet (only when day was CALLED)
        if was_called:
            for cs in db.call_sheets.values():
                if cs["shooting_day_id"] == did and cs["status"] == "PUBLISHED":
                    cs["status"] = "CANCELLED"
                    touch(cs)
        touch(day)
        # VOIDing assignments removes their estimate from committed_cost; the
        # production's committed_cost_cents is a computed field that must reflect
        # the new payment_status set (PRD 3.5 + 2.4).
        if voided_any:
            prod = db.productions.get(day["production_id"])
            if prod:
                recompute_committed_cost(prod)
        # Unscheduling scenes changes the day's estimated_page_eighths, a computed
        # field that must be recomputed (PRD 3.3 + 2.4).
        recompute_page_eighths(day)
        return success_object(public(day))


# --- Scene ------------------------------------------------------------------
@bp.route("/scenes", methods=["POST"])
def create_scene():
    role = authenticate()
    authorize(role, {"FirstAD"})
    body = get_json_body()
    production_id = require_string(body, "production_id")
    if production_id not in db.productions:
        raise err("ERR_NOT_FOUND", "Production not found.")
    scene_number = require_string(body, "scene_number")
    page_eighths = require_int(body, "page_eighths", minimum=1)
    int_ext = require_enum(body, "int_ext", INT_EXT)
    day_night = require_enum(body, "day_night", DAY_NIGHT)
    with db.lock:
        ts = now_iso()
        scene = {
            "id": new_id(),
            "production_id": production_id,
            "shooting_day_id": None,
            "scene_number": scene_number,
            "page_eighths": page_eighths,
            "int_ext": int_ext,
            "day_night": day_night,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.scenes[scene["id"]] = scene
        return success_object(public(scene), status=201)


@bp.route("/scenes/<sid>", methods=["GET"])
def get_scene(sid):
    role = authenticate()
    authorize(role, {"LineProducer", "FirstAD", "PostSupervisor", "UnionRep"})
    scene = db.scenes.get(sid)
    if not scene:
        raise err("ERR_NOT_FOUND", "Scene not found.")
    return success_object(public(scene))


@bp.route("/scenes", methods=["GET"])
def list_scenes():
    role = authenticate()
    authorize(role, {"LineProducer", "FirstAD", "PostSupervisor", "UnionRep"})
    limit, offset = parse_pagination()
    production_id = request.args.get("production_id")
    shooting_day_id = request.args.get("shooting_day_id")
    items = list(db.scenes.values())
    if production_id is not None:
        items = [s for s in items if s["production_id"] == production_id]
    if shooting_day_id is not None:
        items = [s for s in items if s["shooting_day_id"] == shooting_day_id]
    page, total = paginate(items, limit, offset)
    return success_array([public(s) for s in page], limit, offset, total)


@bp.route("/scenes/<sid>/schedule", methods=["POST"])
def schedule_scene(sid):
    role = authenticate()
    authorize(role, {"FirstAD"})
    scene = db.scenes.get(sid)
    if not scene:
        raise err("ERR_NOT_FOUND", "Scene not found.")
    body = get_json_body()
    shooting_day_id = require_string(body, "shooting_day_id")
    day = db.shooting_days.get(shooting_day_id)
    if not day:
        raise err("ERR_NOT_FOUND", "Shooting day not found.")
    with db.lock:
        # same production AND day must be PLANNED, else ERR_SCENE_SCHEDULE_LOCKED
        if day["production_id"] != scene["production_id"] or day["status"] != "PLANNED":
            raise err("ERR_SCENE_SCHEDULE_LOCKED",
                      "Scene can only be scheduled onto a PLANNED day of the same production.")
        scene["shooting_day_id"] = shooting_day_id
        touch(scene)
        recompute_page_eighths(day)
        return success_object(public(scene))
