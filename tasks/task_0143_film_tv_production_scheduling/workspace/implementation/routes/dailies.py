"""Dailies review pipeline — cyclic FLAGGED <-> IN_REVIEW loop."""
from flask import Blueprint, request

from db import db, now_iso, new_id
from errors import err
from middleware import authenticate, authorize
from helpers import (get_json_body, require_string, parse_pagination, paginate)
from response import success_object, success_array
from services.serialize import public
from services.recompute import touch

bp = Blueprint("dailies", __name__)

READ_ROLES = {"LineProducer", "FirstAD", "PostSupervisor", "UnionRep"}


@bp.route("/dailies", methods=["POST"])
def create_dailies():
    role = authenticate()
    authorize(role, {"PostSupervisor"})
    body = get_json_body()
    shooting_day_id = require_string(body, "shooting_day_id")
    if shooting_day_id not in db.shooting_days:
        raise err("ERR_NOT_FOUND", "Shooting day not found.")
    reel_label = require_string(body, "reel_label")
    with db.lock:
        ts = now_iso()
        d = {
            "id": new_id(),
            "shooting_day_id": shooting_day_id,
            "reel_label": reel_label,
            "status": "PENDING",
            "flagged_reason": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.dailies[d["id"]] = d
        return success_object(public(d), status=201)


@bp.route("/dailies/<did>", methods=["GET"])
def get_dailies(did):
    role = authenticate()
    authorize(role, READ_ROLES)
    d = db.dailies.get(did)
    if not d:
        raise err("ERR_NOT_FOUND", "Dailies not found.")
    return success_object(public(d))


@bp.route("/dailies", methods=["GET"])
def list_dailies():
    role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = parse_pagination()
    shooting_day_id = request.args.get("shooting_day_id")
    status = request.args.get("status")
    items = list(db.dailies.values())
    if shooting_day_id is not None:
        items = [d for d in items if d["shooting_day_id"] == shooting_day_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_array([public(d) for d in page], limit, offset, total)


@bp.route("/dailies/<did>/start-review", methods=["POST"])
def start_review(did):
    role = authenticate()
    authorize(role, {"PostSupervisor"})
    with db.lock:
        d = db.dailies.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dailies not found.")
        if d["status"] not in ("PENDING", "FLAGGED"):
            raise err("ERR_INVALID_STATE", "Dailies must be PENDING or FLAGGED to start review.")
        if d["status"] == "PENDING":
            # from PENDING only while parent day is WRAPPED or IN_PROGRESS.
            day = db.shooting_days.get(d["shooting_day_id"])
            if not day or day["status"] not in ("WRAPPED", "IN_PROGRESS"):
                raise err("ERR_INVALID_STATE",
                          "Parent day must be WRAPPED or IN_PROGRESS to begin review.")
        d["status"] = "IN_REVIEW"
        touch(d)
        return success_object(public(d))


@bp.route("/dailies/<did>/approve", methods=["POST"])
def approve_dailies(did):
    role = authenticate()
    authorize(role, {"PostSupervisor"})
    with db.lock:
        d = db.dailies.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dailies not found.")
        if d["status"] != "IN_REVIEW":
            raise err("ERR_INVALID_STATE", "Dailies must be IN_REVIEW to approve.")
        d["status"] = "APPROVED"
        touch(d)
        return success_object(public(d))


@bp.route("/dailies/<did>/flag", methods=["POST"])
def flag_dailies(did):
    role = authenticate()
    authorize(role, {"PostSupervisor"})
    d = db.dailies.get(did)
    if not d:
        raise err("ERR_NOT_FOUND", "Dailies not found.")
    body = get_json_body()
    with db.lock:
        if d["status"] != "IN_REVIEW":
            raise err("ERR_INVALID_STATE", "Dailies must be IN_REVIEW to flag.")
        # ERR_DAILIES_FLAG_REASON_REQUIRED (422): flagged_reason required
        reason = body.get("flagged_reason")
        if not isinstance(reason, str) or reason.strip() == "":
            raise err("ERR_DAILIES_FLAG_REASON_REQUIRED", "flagged_reason is required to flag.")
        d["status"] = "FLAGGED"
        d["flagged_reason"] = reason
        touch(d)
        return success_object(public(d))


@bp.route("/dailies/<did>/archive", methods=["POST"])
def archive_dailies(did):
    role = authenticate()
    authorize(role, {"PostSupervisor"})
    with db.lock:
        d = db.dailies.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dailies not found.")
        if d["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "Dailies must be APPROVED to archive.")
        d["status"] = "ARCHIVED"
        touch(d)
        return success_object(public(d))
