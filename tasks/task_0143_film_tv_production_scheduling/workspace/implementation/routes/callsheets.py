"""Call sheets — cyclic publish/revise loop, calling the day."""
from flask import Blueprint, request

from db import db, now_iso, new_id
from errors import err
from middleware import authenticate, authorize
from helpers import (get_json_body, require_string, optional_string,
                     parse_pagination, paginate)
from response import success_object, success_array
from services.serialize import public
from services.recompute import touch

bp = Blueprint("callsheets", __name__)

ALL_ROLES = {"LineProducer", "FirstAD", "PayrollCoordinator", "PostSupervisor", "UnionRep"}


@bp.route("/call-sheets", methods=["POST"])
def create_call_sheet():
    role = authenticate()
    authorize(role, {"FirstAD"})
    body = get_json_body()
    shooting_day_id = require_string(body, "shooting_day_id")
    if shooting_day_id not in db.shooting_days:
        raise err("ERR_NOT_FOUND", "Shooting day not found.")
    general_call_time = require_string(body, "general_call_time")
    with db.lock:
        ts = now_iso()
        cs = {
            "id": new_id(),
            "shooting_day_id": shooting_day_id,
            "status": "DRAFT",
            "revision_number": 0,
            "general_call_time": general_call_time,
            "published_at": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.call_sheets[cs["id"]] = cs
        return success_object(public(cs), status=201)


@bp.route("/call-sheets/<csid>", methods=["GET"])
def get_call_sheet(csid):
    role = authenticate()
    authorize(role, ALL_ROLES)
    cs = db.call_sheets.get(csid)
    if not cs:
        raise err("ERR_NOT_FOUND", "Call sheet not found.")
    return success_object(public(cs))


@bp.route("/call-sheets", methods=["GET"])
def list_call_sheets():
    role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    shooting_day_id = request.args.get("shooting_day_id")
    status = request.args.get("status")
    items = list(db.call_sheets.values())
    if shooting_day_id is not None:
        items = [c for c in items if c["shooting_day_id"] == shooting_day_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_array([public(c) for c in page], limit, offset, total)


@bp.route("/call-sheets/<csid>/publish", methods=["POST"])
def publish_call_sheet(csid):
    role = authenticate()
    authorize(role, {"FirstAD"})
    with db.lock:
        cs = db.call_sheets.get(csid)
        if not cs:
            raise err("ERR_NOT_FOUND", "Call sheet not found.")
        day = db.shooting_days.get(cs["shooting_day_id"])
        if cs["status"] == "DRAFT":
            # first publish: calls the day. Day must be PLANNED, day has >=1
            # assignment, grandparent production ACTIVE.
            if day["status"] != "PLANNED":
                raise err("ERR_INVALID_STATE", "Parent day must be PLANNED to publish.")
            prod = db.productions.get(day["production_id"])
            if not prod or prod["status"] != "ACTIVE":
                raise err("ERR_PRODUCTION_NOT_ACTIVE", "Parent production must be ACTIVE.")
            has_assignment = any(a["shooting_day_id"] == day["id"]
                                 for a in db.assignments.values())
            if not has_assignment:
                raise err("ERR_INVALID_STATE", "Day must have at least one assignment.")
            cs["status"] = "PUBLISHED"
            cs["published_at"] = now_iso()
            touch(cs)
            day["status"] = "CALLED"
            touch(day)
        elif cs["status"] == "REVISED":
            # re-publish: neither calls the day nor requires PLANNED.
            cs["status"] = "PUBLISHED"
            cs["published_at"] = now_iso()
            touch(cs)
        else:
            raise err("ERR_INVALID_STATE", "Call sheet is not in a publishable state.")
        return success_object(public(cs))


@bp.route("/call-sheets/<csid>/revise", methods=["POST"])
def revise_call_sheet(csid):
    role = authenticate()
    authorize(role, {"FirstAD"})
    body = get_json_body()
    new_call = optional_string(body, "general_call_time", None)
    with db.lock:
        cs = db.call_sheets.get(csid)
        if not cs:
            raise err("ERR_NOT_FOUND", "Call sheet not found.")
        if cs["status"] != "PUBLISHED":
            raise err("ERR_INVALID_STATE", "Call sheet must be PUBLISHED to revise.")
        day = db.shooting_days.get(cs["shooting_day_id"])
        if not day or day["status"] not in ("CALLED", "IN_PROGRESS"):
            raise err("ERR_INVALID_STATE",
                      "Parent day must be CALLED or IN_PROGRESS to revise.")
        cs["status"] = "REVISED"
        cs["revision_number"] += 1
        if new_call is not None:
            cs["general_call_time"] = new_call
        touch(cs)
        return success_object(public(cs))


@bp.route("/call-sheets/<csid>/finalize", methods=["POST"])
def finalize_call_sheet(csid):
    role = authenticate()
    authorize(role, {"FirstAD"})
    with db.lock:
        cs = db.call_sheets.get(csid)
        if not cs:
            raise err("ERR_NOT_FOUND", "Call sheet not found.")
        if cs["status"] != "PUBLISHED":
            raise err("ERR_INVALID_STATE", "Call sheet must be PUBLISHED to finalize.")
        day = db.shooting_days.get(cs["shooting_day_id"])
        if not day or day["status"] != "WRAPPED":
            raise err("ERR_INVALID_STATE", "Parent day must be WRAPPED to finalize.")
        cs["status"] = "FINALIZED"
        touch(cs)
        return success_object(public(cs))
