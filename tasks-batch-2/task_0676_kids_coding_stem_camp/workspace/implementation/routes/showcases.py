"""Showcase routes & lifecycle (PRD §3.8)."""
from flask import Blueprint

import errors
from errors import err
from clock import clock
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import (
    get_body, require_int, parse_datetime, parse_iso, parse_pagination, invalid,
)
from services import lookup
from routes.common import arg, paginate

bp = Blueprint("showcases", __name__)


@bp.route("/showcases", methods=["POST"])
def create_showcase():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    center_id = body.get("center_id")
    lookup.require_center(center_id)
    program_id = body.get("program_id")
    lookup.require_program(program_id)
    min_belt_rank = require_int(body, "min_belt_rank", minimum=1)
    capacity = require_int(body, "capacity", minimum=1)
    starts_at = parse_datetime(body, "starts_at")
    entry_deadline_at = parse_datetime(body, "entry_deadline_at")
    if entry_deadline_at >= starts_at:
        raise invalid("entry_deadline_at must be strictly before starts_at.")
    rec = db.make({
        "center_id": center_id,
        "program_id": program_id,
        "min_belt_rank": min_belt_rank,
        "capacity": capacity,
        "starts_at": body["starts_at"],
        "entry_deadline_at": body["entry_deadline_at"],
        "status": "DRAFT",
        "accepted_entry_count": 0,
    })
    db.showcases[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/showcases/<rid>", methods=["GET"])
def get_showcase(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_showcase(rid)
    return success(out(rec))


@bp.route("/showcases", methods=["GET"])
def list_showcases():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    center_id = arg("center_id")
    program_id = arg("program_id")
    status = arg("status")
    items = [s for s in db.showcases.values()
             if (center_id is None or s["center_id"] == center_id)
             and (program_id is None or s["program_id"] == program_id)
             and (status is None or s["status"] == status)]
    return paginate(items, limit, offset)


@bp.route("/showcases/<rid>/open", methods=["POST"])
def open_showcase(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    s = lookup.require_showcase(rid)
    if s["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Showcase is not DRAFT.")
    deadline = parse_iso(s["entry_deadline_at"])
    starts = parse_iso(s["starts_at"])
    if not (deadline < starts):
        raise err(errors.ERR_INVALID_STATE, "entry_deadline_at must be before starts_at.")
    s["status"] = "OPEN"
    db.touch(s)
    return success(out(s))


@bp.route("/showcases/<rid>/close-entries", methods=["POST"])
def close_entries(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    s = lookup.require_showcase(rid)
    if s["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Showcase is not OPEN.")
    deadline = parse_iso(s["entry_deadline_at"])
    if not (clock.now() > deadline):
        raise err(errors.ERR_DEADLINE_NOT_REACHED, "Entry deadline has not passed.")
    # deadline sweep: SUBMITTED -> REJECTED
    for e in db.showcase_entries.values():
        if e["showcase_id"] == s["id"] and e["status"] == "SUBMITTED":
            e["status"] = "REJECTED"
            db.touch(e)
    s["status"] = "JUDGING"
    db.touch(s)
    return success(out(s))


@bp.route("/showcases/<rid>/post-results", methods=["POST"])
def post_results(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    s = lookup.require_showcase(rid)
    if s["status"] != "JUDGING":
        raise err(errors.ERR_INVALID_STATE, "Showcase is not JUDGING.")
    # every ACCEPTED entry must be SCORED
    for e in db.showcase_entries.values():
        if e["showcase_id"] == s["id"] and e["status"] == "ACCEPTED":
            raise err(errors.ERR_UNSCORED_ENTRIES_REMAIN, "Unscored accepted entries remain.")
    # rank SCORED entries: score DESC, created_at (seq) ASC
    scored = [e for e in db.showcase_entries.values()
              if e["showcase_id"] == s["id"] and e["status"] == "SCORED"]
    scored.sort(key=lambda e: (-(e["score"] if e["score"] is not None else 0), e["_seq"]))
    for i, e in enumerate(scored):
        e["rank"] = i + 1
        db.touch(e)
    s["status"] = "COMPLETED"
    db.touch(s)
    return success(out(s))


@bp.route("/showcases/<rid>/cancel", methods=["POST"])
def cancel_showcase(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    s = lookup.require_showcase(rid)
    if s["status"] not in ("DRAFT", "OPEN", "JUDGING"):
        raise err(errors.ERR_INVALID_STATE, "Showcase cannot be cancelled from its current state.")
    for e in db.showcase_entries.values():
        if e["showcase_id"] != s["id"]:
            continue
        if e["status"] in ("SUBMITTED", "ACCEPTED", "SCORED"):
            e["status"] = "WITHDRAWN"
            db.touch(e)
    s["accepted_entry_count"] = 0
    s["status"] = "CANCELLED"
    db.touch(s)
    return success(out(s))
