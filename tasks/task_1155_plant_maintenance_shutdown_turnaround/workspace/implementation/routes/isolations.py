"""Isolation control endpoints (PRD 3.4).

Isolation windows are CLOSED intervals (both bounds inclusive); two SHARED
isolations may coexist on one equipment_tag, any EXCLUSIVE involvement in an
overlap conflicts.
"""
from flask import Blueprint, request

import db
from errors import bad_request, conflict, invalid_state
from helpers import (actor, as_dt, as_enum, as_str, body, get_or_404, paged,
                     pagination_params, req_field, require_roles,
                     sorted_by_created)
from response import ok
from serialize import isolation_out, permit_out
from util import fmt_iso

bp = Blueprint("isolations", __name__)

PC = ("PermitCoordinator",)
ISOLATION_MODES = ("EXCLUSIVE", "SHARED")
ISOLATION_STATUSES = ("PLANNED", "ISOLATED", "VERIFIED", "DEISOLATED")
LIVE_PERMIT_STATUSES = ("ISSUED", "ACTIVE", "SUSPENDED")


@bp.post("/turnarounds/<tid>/isolations")
def create_isolation(tid):
    _uid, role = actor()
    require_roles(role, PC)
    get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    tag = as_str(req_field(b, "equipment_tag"), "equipment_tag")
    mode = as_enum(req_field(b, "isolation_mode"), "isolation_mode",
                   ISOLATION_MODES)
    start = as_dt(req_field(b, "isolated_from"), "isolated_from")
    end = as_dt(req_field(b, "isolated_until"), "isolated_until")
    if end <= start:
        bad_request("isolated_until must be strictly after isolated_from")
    # Temporal (priority 10): closed-interval, mode-conditional conflict.
    for other in db.isolations.values():
        if other["turnaround_id"] != tid or other["equipment_tag"] != tag:
            continue
        if other["status"] == "DEISOLATED":
            continue
        overlap = start <= other["_isolated_until"] and \
            other["_isolated_from"] <= end
        if overlap and (mode == "EXCLUSIVE"
                        or other["isolation_mode"] == "EXCLUSIVE"):
            conflict("ERR_ISOLATION_CONFLICT",
                     "Conflicting isolation window on equipment %s" % tag)
    now = db.now_iso()
    i = db.create(db.isolations, {
        "id": db.mint_id(),
        "turnaround_id": tid,
        "equipment_tag": tag,
        "isolation_mode": mode,
        "isolated_from": fmt_iso(start),
        "isolated_until": fmt_iso(end),
        "status": "PLANNED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "_isolated_from": start,
        "_isolated_until": end,
    })
    return ok(isolation_out(i), status=201)


@bp.get("/turnarounds/<tid>/isolations")
def list_isolations(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = [i for i in db.isolations.values() if i["turnaround_id"] == tid]
    tag = request.args.get("equipment_tag")
    if tag is not None:
        items = [i for i in items if i["equipment_tag"] == tag]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([isolation_out(i) for i in page], pagination=meta)


@bp.get("/isolations/<iid>")
def get_isolation(iid):
    actor()
    i = get_or_404(db.isolations, iid, "Isolation")
    return ok(isolation_out(i))


@bp.post("/isolations/<iid>/transition")
def transition_isolation(iid):
    _uid, role = actor()
    require_roles(role, PC)
    i = get_or_404(db.isolations, iid, "Isolation")
    b = body()
    to = as_enum(req_field(b, "to"), "to", ISOLATION_STATUSES)
    current = i["status"]
    legal = (current, to) in (
        ("PLANNED", "ISOLATED"),
        ("ISOLATED", "VERIFIED"),
        ("ISOLATED", "DEISOLATED"),
        ("VERIFIED", "DEISOLATED"),
    )
    if not legal:
        invalid_state("Illegal isolation transition from %s to %s"
                      % (current, to))
    if to == "DEISOLATED":
        # Safety gate (priority 9): blocked while referenced by a live permit.
        for p in db.permits.values():
            if iid in p["required_isolation_ids"] and \
                    p["status"] in LIVE_PERMIT_STATUSES:
                conflict("ERR_ISOLATION_IN_USE",
                         "A live permit still references this isolation")
    i["status"] = to
    db.touch(i)
    return ok(isolation_out(i))


@bp.get("/isolations/<iid>/permits")
def list_isolation_permits(iid):
    actor()
    get_or_404(db.isolations, iid, "Isolation")
    items = [p for p in db.permits.values() if iid in p["required_isolation_ids"]]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([permit_out(p) for p in page], pagination=meta)
