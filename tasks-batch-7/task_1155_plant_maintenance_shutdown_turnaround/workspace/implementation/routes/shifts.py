"""Shift planning, crew assignment gates, lock (PRD 3.3)."""
from flask import Blueprint, request

import db
from errors import bad_request, conflict, cross_scope, forbidden, invalid_state
from helpers import (actor, as_date, as_dt, as_enum, as_int, as_num, as_str,
                     body, get_or_404, paged, pagination_params, req_field,
                     require_roles, sorted_by_created)
from response import ok
from serialize import assignment_out, shift_out, work_item_out
from services import computed
from util import fmt_iso

bp = Blueprint("shifts", __name__)

PLANNER = ("Planner",)
ASSIGN_ROLES = ("Planner", "ContractorSupervisor")
SHIFT_TYPES = ("DAY", "NIGHT")
KEPT = ("ASSIGNED", "COMPLETED")


@bp.post("/turnarounds/<tid>/shifts")
def create_shift(tid):
    _uid, role = actor()
    require_roles(role, PLANNER)
    get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    shift_date = as_date(req_field(b, "shift_date"), "shift_date")
    shift_type = as_enum(req_field(b, "shift_type"), "shift_type", SHIFT_TYPES)
    starts_at = as_dt(req_field(b, "starts_at"), "starts_at")
    ends_at = as_dt(req_field(b, "ends_at"), "ends_at")
    headcount = as_int(req_field(b, "planned_headcount"), "planned_headcount",
                       minimum=1)
    if ends_at <= starts_at:
        bad_request("ends_at must be strictly after starts_at")
    now = db.now_iso()
    s = db.create(db.shifts, {
        "id": db.mint_id(),
        "turnaround_id": tid,
        "shift_date": shift_date.isoformat(),
        "shift_type": shift_type,
        "starts_at": fmt_iso(starts_at),
        "ends_at": fmt_iso(ends_at),
        "planned_headcount": headcount,
        "status": "PLANNED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "_starts_at": starts_at,
        "_ends_at": ends_at,
    })
    return ok(shift_out(s), status=201)


@bp.get("/turnarounds/<tid>/shifts")
def list_shifts(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = [s for s in db.shifts.values() if s["turnaround_id"] == tid]
    shift_type = request.args.get("shift_type")
    if shift_type is not None:
        items = [s for s in items if s["shift_type"] == shift_type]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([shift_out(s) for s in page], pagination=meta)


@bp.get("/shifts/<sid>")
def get_shift(sid):
    actor()
    s = get_or_404(db.shifts, sid, "Shift")
    return ok(shift_out(s))


@bp.get("/shifts/<sid>/work-items")
def list_shift_work_items(sid):
    actor()
    get_or_404(db.shifts, sid, "Shift")
    items = [w for w in db.work_items.values() if w["planned_shift_id"] == sid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([work_item_out(w) for w in page], pagination=meta)


@bp.post("/shifts/<sid>/lock")
def lock_shift(sid):
    _uid, role = actor()
    require_roles(role, PLANNER)
    s = get_or_404(db.shifts, sid, "Shift")
    if s["status"] != "PLANNED":
        invalid_state("Only a PLANNED shift can be locked")
    assigned = any(a["shift_id"] == sid and a["status"] == "ASSIGNED"
                   for a in db.assignments.values())
    if not assigned:
        conflict("ERR_EMPTY_SHIFT",
                 "Locking a shift requires at least one ASSIGNED assignment")
    s["status"] = "LOCKED"
    db.touch(s)
    return ok(shift_out(s))


@bp.post("/shifts/<sid>/assignments")
def create_assignment(sid):
    uid, role = actor()
    require_roles(role, ASSIGN_ROLES)
    s = get_or_404(db.shifts, sid, "Shift")
    b = body()
    worker_id = as_str(req_field(b, "worker_id"), "worker_id")
    planned_hours = as_num(req_field(b, "planned_hours"), "planned_hours", gt=0)
    worker = db.workers.get(worker_id)
    # Ownership (priority 2): a supervisor may only touch their own workers.
    if role == "ContractorSupervisor" and worker is not None \
            and worker["contractor_id"] != uid:
        forbidden("A ContractorSupervisor can only assign their own contractor's "
                  "workers")
    # Cross-scope (priority 6): the worker must resolve within the shift's
    # turnaround.
    if worker is None:
        cross_scope("worker_id does not resolve")
    contractor = db.contractors.get(worker["contractor_id"])
    if contractor is None or contractor["turnaround_id"] != s["turnaround_id"]:
        cross_scope("worker_id must belong to the shift's turnaround")
    # Safety gates (priority 9): badge, then fatigue projection.
    if worker["badge_status"] != "BADGED":
        conflict("ERR_BADGE_NOT_CLEARED", "The worker's badge is not BADGED")
    projected = computed.projected_fatigue_score(worker_id, s)
    if projected >= computed.FATIGUE_SCORE_LIMIT:
        conflict("ERR_FATIGUE_LIMIT",
                 "Projected fatigue penalty score would reach the limit")
    # Temporal rules (priority 10): half-open overlap, then minimum rest gap.
    kept = []
    for a in db.assignments.values():
        if a["worker_id"] != worker_id or a["status"] not in KEPT:
            continue
        other = db.shifts.get(a["shift_id"])
        if other is not None:
            kept.append((other, a))
    for other, _a in kept:
        if s["_starts_at"] < other["_ends_at"] and other["_starts_at"] < s["_ends_at"]:
            conflict("ERR_SHIFT_OVERLAP",
                     "The worker already holds an assignment on an overlapping shift")
    rows = sorted(kept + [(s, None)],
                  key=lambda r: (r[0]["_starts_at"],
                                 r[1]["_seq"] if r[1] is not None else float("inf")))
    prev = None
    for shift_row, _a in rows:
        if prev is not None:
            gap = (shift_row["_starts_at"] - prev["_ends_at"]).total_seconds() / 3600.0
            if gap < computed.MIN_REST_HOURS:
                conflict("ERR_REST_PERIOD_VIOLATION",
                         "Consecutive assignments must respect the minimum rest gap")
        prev = shift_row
    # Structural constraints (priority 11): headcount room, then PLANNED shift.
    non_cancelled = sum(1 for a in db.assignments.values()
                        if a["shift_id"] == sid and a["status"] != "CANCELLED")
    if non_cancelled >= s["planned_headcount"]:
        conflict("ERR_SHIFT_HEADCOUNT_FULL", "The shift has no headcount room")
    if s["status"] != "PLANNED":
        conflict("ERR_SHIFT_LOCKED",
                 "Assignments are only accepted while the shift is PLANNED")
    now = db.now_iso()
    a = db.create(db.assignments, {
        "id": db.mint_id(),
        "shift_id": sid,
        "worker_id": worker_id,
        "planned_hours": planned_hours,
        "actual_hours": None,
        "status": "ASSIGNED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    return ok(assignment_out(a), status=201)


@bp.get("/shifts/<sid>/assignments")
def list_shift_assignments(sid):
    actor()
    get_or_404(db.shifts, sid, "Shift")
    items = [a for a in db.assignments.values() if a["shift_id"] == sid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([assignment_out(a) for a in page], pagination=meta)
