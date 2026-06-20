"""Stall / pasture routes (PRD §3.2)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from services.common import (
    new_common, require_str, require_int, parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list
from services.lookups import get_stall

bp = Blueprint("stalls", __name__)


@bp.route("/stalls", methods=["POST"])
def create_stall():
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    body = request.get_json(silent=True) or {}
    label = require_str(body, "label")
    kind = require_str(body, "kind")
    if kind not in ("STALL", "PASTURE"):
        raise err("ERR_INVALID_REQUEST", "kind must be STALL or PASTURE")
    capacity = require_int(body, "capacity")
    daily_rate = require_int(body, "daily_rate_cents")
    # capacity rule (PRD §2.7): STALL -> capacity == 1; PASTURE -> capacity >= 1
    if kind == "STALL" and capacity != 1:
        raise err("ERR_INVALID_REQUEST", "STALL capacity must be 1")
    if kind == "PASTURE" and capacity < 1:
        raise err("ERR_INVALID_REQUEST", "PASTURE capacity must be >= 1")
    # label unique across stalls (PRD §3.2)
    for s in db.stalls.values():
        if s["label"] == label:
            raise err("ERR_INVALID_REQUEST", "label must be unique across stalls")
    stall = new_common()
    stall.update({
        "label": label,
        "kind": kind,
        "capacity": capacity,
        "daily_rate_cents": daily_rate,
        "occupied_count": 0,
    })
    db.stalls[stall["id"]] = stall
    return success(view(stall), 201)


@bp.route("/stalls/<stall_id>", methods=["GET"])
def get_stall_route(stall_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    stall = get_stall(stall_id)
    return success(view(stall), 200)


@bp.route("/stalls/<stall_id>/boarding-agreements", methods=["GET"])
def list_stall_agreements(stall_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    get_stall(stall_id)
    limit, offset = parse_pagination(request.args)
    items = [a for a in db.agreements.values() if a["stall_id"] == stall_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.route("/stalls/<stall_id>/turnouts", methods=["GET"])
def list_stall_turnouts(stall_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    get_stall(stall_id)
    limit, offset = parse_pagination(request.args)
    items = [t for t in db.turnouts.values() if t["pasture_id"] == stall_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)
