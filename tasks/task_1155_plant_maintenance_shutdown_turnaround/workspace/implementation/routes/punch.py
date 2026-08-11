"""Punch list & handover support (PRD 3.9)."""
from flask import Blueprint, request

import db
from errors import cross_scope, invalid_state
from helpers import (actor, as_enum, as_str, body, get_or_404, paged,
                     pagination_params, req_field, require_roles,
                     sorted_by_created)
from response import ok
from serialize import punch_item_out

bp = Blueprint("punch", __name__)

RAISE_ROLES = ("OperationsRep", "ContractorSupervisor")
SUPERVISOR = ("ContractorSupervisor",)
OPS = ("OperationsRep",)
CATEGORIES = ("A", "B")
OUTCOMES = ("VERIFIED", "REOPENED")


@bp.post("/turnarounds/<tid>/punch-items")
def create_punch_item(tid):
    _uid, role = actor()
    require_roles(role, RAISE_ROLES)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    work_item_id = as_str(req_field(b, "work_item_id"), "work_item_id")
    category = as_enum(req_field(b, "category"), "category", CATEGORIES)
    description = as_str(req_field(b, "description"), "description")
    w = db.work_items.get(work_item_id)
    if w is None or w["turnaround_id"] != tid:
        cross_scope("work_item_id must resolve within the same turnaround")
    if t["status"] not in ("EXECUTION", "STARTUP"):
        invalid_state("Punch items can only be raised during EXECUTION or STARTUP")
    if w["status"] not in ("COMPLETE", "VERIFIED"):
        invalid_state("Punch items can only be raised on COMPLETE or VERIFIED "
                      "work items")
    now = db.now_iso()
    p = db.create(db.punch_items, {
        "id": db.mint_id(),
        "turnaround_id": tid,
        "work_item_id": work_item_id,
        "category": category,
        "description": description,
        "status": "OPEN",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    return ok(punch_item_out(p), status=201)


@bp.get("/turnarounds/<tid>/punch-items")
def list_punch_items(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = [p for p in db.punch_items.values() if p["turnaround_id"] == tid]
    category = request.args.get("category")
    if category is not None:
        items = [p for p in items if p["category"] == category]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([punch_item_out(p) for p in page], pagination=meta)


@bp.get("/punch-items/<pid>")
def get_punch_item(pid):
    actor()
    p = get_or_404(db.punch_items, pid, "PunchItem")
    return ok(punch_item_out(p))


@bp.post("/punch-items/<pid>/ready")
def ready_punch_item(pid):
    _uid, role = actor()
    require_roles(role, SUPERVISOR)
    p = get_or_404(db.punch_items, pid, "PunchItem")
    if p["status"] not in ("OPEN", "REOPENED"):
        invalid_state("Only an OPEN or REOPENED punch item can be marked ready")
    p["status"] = "READY"
    db.touch(p)
    return ok(punch_item_out(p))


@bp.post("/punch-items/<pid>/verify")
def verify_punch_item(pid):
    _uid, role = actor()
    require_roles(role, OPS)
    p = get_or_404(db.punch_items, pid, "PunchItem")
    b = body()
    outcome = as_enum(req_field(b, "outcome"), "outcome", OUTCOMES)
    if p["status"] != "READY":
        invalid_state("Only a READY punch item can be verified")
    p["status"] = outcome  # VERIFIED (terminal) or REOPENED
    db.touch(p)
    return ok(punch_item_out(p))
