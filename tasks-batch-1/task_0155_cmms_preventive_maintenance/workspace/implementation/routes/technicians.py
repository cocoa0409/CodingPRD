"""Technician routes (PRD §3.1, §4)."""
from flask import Blueprint

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import require_str, require_enum, require_number, parse_pagination, paginate
from response import object_response, array_response

bp = Blueprint("technicians", __name__)

SKILL_LEVELS = {"JUNIOR", "SENIOR", "MASTER"}


@bp.post("/technicians")
def create_technician():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager"])
    body = get_json_body()
    name = require_str(body, "name")
    skill = require_enum(body, "skill_level", SKILL_LEVELS)
    capacity = require_number(body, "weekly_capacity_hours", gt=0)
    with db.LOCK:
        rec = db.new_record()
        rec.update({
            "name": name,
            "skill_level": skill,
            "weekly_capacity_hours": capacity,
            "backlog_hours": 0,
        })
        db.technicians[rec["id"]] = rec
        return object_response(serialize.technician(rec), 201)


@bp.get("/technicians/<tid>")
def get_technician(tid):
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician"])
    with db.LOCK:
        rec = db.technicians.get(tid)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.technician(rec), 200)


@bp.get("/technicians")
def list_technicians():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician"])
    limit, offset = parse_pagination()
    with db.LOCK:
        items = sorted(db.technicians.values(), key=lambda r: r["_seq"])
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.technician(r) for r in page], limit, offset, total)
