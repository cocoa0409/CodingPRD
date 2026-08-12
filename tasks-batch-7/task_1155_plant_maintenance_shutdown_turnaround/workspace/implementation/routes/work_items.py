"""Work item endpoints: propose/list/get, estimate (OCC), dependencies,
schedule, start/hold/complete/verify, plus scoped permit/discovery/punch
listings (PRD 3.1, 3.5)."""
from flask import Blueprint

import db
from errors import conflict, cross_scope, invalid_state, stale
from helpers import (actor, as_bool, as_enum, as_int, as_num, as_str, body,
                     get_or_404, opt_field, paged, pagination_params,
                     req_field, require_roles, sorted_by_created)
from response import ok
from serialize import (dependency_out, discovery_out, punch_item_out,
                       work_item_out, permit_out)
from services import computed, ranking

bp = Blueprint("work_items", __name__)

PLANNER = ("Planner",)
SUPERVISOR = ("ContractorSupervisor",)
OPS = ("OperationsRep",)

WORK_TYPES = ("CORRECTIVE", "PREVENTIVE", "INSPECTION", "DISCOVERY_ADDENDUM")
RISK_CLASSES = ("A", "B", "C")
VERIFY_OUTCOMES = ("VERIFIED", "REOPENED")


def _new_work_item(fields):
    now = db.now_iso()
    fields.setdefault("version", 1)
    fields["created_at"] = now
    fields["updated_at"] = now
    return db.create(db.work_items, fields)


@bp.post("/turnarounds/<tid>/work-items")
def create_work_item(tid):
    _uid, role = actor()
    require_roles(role, PLANNER)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    title = as_str(req_field(b, "title"), "title")
    system_area = as_str(req_field(b, "system_area"), "system_area")
    work_type = as_enum(req_field(b, "work_type"), "work_type", WORK_TYPES)
    risk_class = as_enum(req_field(b, "risk_class"), "risk_class", RISK_CLASSES)
    est_hours = as_num(req_field(b, "estimated_hours"), "estimated_hours", gt=0)
    est_cost = as_int(req_field(b, "estimated_cost_cents"),
                      "estimated_cost_cents", minimum=0)
    requires_permit = opt_field(b, "requires_permit", False)
    as_bool(requires_permit, "requires_permit")
    if t["status"] != "PLANNING":
        invalid_state("Work items can only be proposed while the turnaround is PLANNING")
    w = _new_work_item({
        "id": db.mint_id(),
        "turnaround_id": tid,
        "discovery_id": None,
        "planned_shift_id": None,
        "title": title,
        "system_area": system_area,
        "work_type": work_type,
        "risk_class": risk_class,
        "estimated_hours": est_hours,
        "estimated_cost_cents": est_cost,
        "requires_permit": requires_permit,
        "rank_score": None,
        "rank_position": None,
        "is_critical_path": False,
        "actual_hours": None,
        "status": "PROPOSED",
    })
    return ok(work_item_out(w), status=201)


@bp.get("/turnarounds/<tid>/work-items")
def list_work_items(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = [w for w in computed.work_items_of(tid)]
    status = _opt_query("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    work_type = _opt_query("work_type")
    if work_type is not None:
        items = [w for w in items if w["work_type"] == work_type]
    icp = _opt_query("is_critical_path")
    if icp is not None:
        want = icp.lower() == "true"
        items = [w for w in items if bool(w["is_critical_path"]) == want]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([work_item_out(w) for w in page], pagination=meta)


def _opt_query(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None


@bp.get("/work-items/<wid>")
def get_work_item(wid):
    actor()
    w = get_or_404(db.work_items, wid, "WorkItem")
    return ok(work_item_out(w))


@bp.post("/work-items/<wid>/estimate")
def estimate_work_item(wid):
    _uid, role = actor()
    require_roles(role, PLANNER)
    w = get_or_404(db.work_items, wid, "WorkItem")
    b = body()
    # OCC (priority 4) precedes request-shape checks (priority 5).
    occ = b.get("expected_work_item_version")
    if isinstance(occ, int) and not isinstance(occ, bool):
        if occ != w["version"]:
            stale("expected_work_item_version does not match the work item version")
    as_int(req_field(b, "expected_work_item_version"),
           "expected_work_item_version")
    est_hours = as_num(req_field(b, "estimated_hours"), "estimated_hours", gt=0)
    est_cost = as_int(req_field(b, "estimated_cost_cents"),
                      "estimated_cost_cents", minimum=0)
    risk_class = as_enum(req_field(b, "risk_class"), "risk_class", RISK_CLASSES)
    t = db.turnarounds.get(w["turnaround_id"])
    if w["status"] != "PROPOSED" or t is None or t["status"] != "PLANNING":
        invalid_state("Re-estimation is only legal for a PROPOSED item while PLANNING")
    w["estimated_hours"] = est_hours
    w["estimated_cost_cents"] = est_cost
    w["risk_class"] = risk_class
    db.touch(w)
    return ok(work_item_out(w))


@bp.post("/work-items/<wid>/dependencies")
def create_dependency(wid):
    _uid, role = actor()
    require_roles(role, PLANNER)
    successor = get_or_404(db.work_items, wid, "WorkItem")
    b = body()
    pred_id = as_str(req_field(b, "predecessor_work_item_id"),
                     "predecessor_work_item_id")
    lag = opt_field(b, "lag_hours", 0)
    lag = as_int(lag, "lag_hours", minimum=0)
    predecessor = db.work_items.get(pred_id)
    if predecessor is None or predecessor["turnaround_id"] != successor["turnaround_id"]:
        cross_scope("predecessor_work_item_id must resolve within the same turnaround")
    t = db.turnarounds.get(successor["turnaround_id"])
    if t is None or t["status"] != "PLANNING":
        invalid_state("Dependency edits are only legal while the turnaround is PLANNING")
    if ranking.would_create_cycle(successor["turnaround_id"], pred_id, wid):
        conflict("ERR_DEPENDENCY_CYCLE",
                 "Dependency would create a cycle in the work-item DAG")
    now = db.now_iso()
    d = db.create(db.dependencies, {
        "id": db.mint_id(),
        "turnaround_id": successor["turnaround_id"],
        "predecessor_work_item_id": pred_id,
        "successor_work_item_id": wid,
        "lag_hours": lag,
        "created_at": now,
    })
    # Pre-freeze: planners see the network's shape (critical-path recompute).
    proposed = [w for w in computed.work_items_of(successor["turnaround_id"])
                if w["status"] == "PROPOSED"]
    ranking.compute_critical_path(successor["turnaround_id"], proposed)
    return ok(dependency_out(d), status=201)


@bp.get("/work-items/<wid>/dependencies")
def list_work_item_dependencies(wid):
    actor()
    w = get_or_404(db.work_items, wid, "WorkItem")
    edges = [d for d in db.dependencies.values()
             if d["predecessor_work_item_id"] == wid
             or d["successor_work_item_id"] == wid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(edges), limit, offset)
    return ok([dependency_out(d) for d in page], pagination=meta)


@bp.get("/turnarounds/<tid>/dependencies")
def list_turnaround_dependencies(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    edges = [d for d in db.dependencies.values() if d["turnaround_id"] == tid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(edges), limit, offset)
    return ok([dependency_out(d) for d in page], pagination=meta)


@bp.post("/work-items/<wid>/schedule")
def schedule_work_item(wid):
    _uid, role = actor()
    require_roles(role, PLANNER)
    w = get_or_404(db.work_items, wid, "WorkItem")
    b = body()
    shift_id = opt_field(b, "planned_shift_id", None)
    shift = None
    if shift_id is not None:
        if not isinstance(shift_id, str):
            from errors import bad_request
            bad_request("planned_shift_id must be a string")
        shift = db.shifts.get(shift_id)
        if shift is None or shift["turnaround_id"] != w["turnaround_id"]:
            cross_scope("planned_shift_id must resolve within the same turnaround")
    t = db.turnarounds.get(w["turnaround_id"])
    if w["status"] != "FROZEN":
        invalid_state("Only a FROZEN work item can be scheduled")
    if t is None or t["status"] not in ("MOBILIZATION", "EXECUTION"):
        invalid_state("Scheduling requires the turnaround to be MOBILIZATION or EXECUTION")
    w["planned_shift_id"] = shift_id
    w["status"] = "SCHEDULED"
    db.touch(w)
    return ok(work_item_out(w))


@bp.post("/work-items/<wid>/start")
def start_work_item(wid):
    _uid, role = actor()
    require_roles(role, SUPERVISOR)
    w = get_or_404(db.work_items, wid, "WorkItem")
    t = db.turnarounds.get(w["turnaround_id"])
    if t is None or t["status"] != "EXECUTION":
        invalid_state("Starting work requires the turnaround to be EXECUTION")
    if w["status"] not in ("SCHEDULED", "ON_HOLD", "REOPENED"):
        invalid_state("Only a SCHEDULED, ON_HOLD, or REOPENED work item can be started")
    if w["requires_permit"]:
        active = any(p["work_item_id"] == wid and p["status"] == "ACTIVE"
                     for p in db.permits.values())
        if not active:
            conflict("ERR_PERMIT_NOT_ACTIVE",
                     "A permit-requiring work item needs an ACTIVE permit to start")
    w["status"] = "IN_PROGRESS"
    db.touch(w)
    return ok(work_item_out(w))


@bp.post("/work-items/<wid>/hold")
def hold_work_item(wid):
    _uid, role = actor()
    require_roles(role, SUPERVISOR)
    w = get_or_404(db.work_items, wid, "WorkItem")
    if w["status"] != "IN_PROGRESS":
        invalid_state("Only an IN_PROGRESS work item can be placed on hold")
    # Sideways cascade: ACTIVE permits covering this item auto-suspend.
    for p in sorted(db.permits.values(), key=lambda p: p["_seq"]):
        if p["work_item_id"] == wid and p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            db.touch(p)
    w["status"] = "ON_HOLD"
    db.touch(w)
    return ok(work_item_out(w))


@bp.post("/work-items/<wid>/complete")
def complete_work_item(wid):
    _uid, role = actor()
    require_roles(role, SUPERVISOR)
    w = get_or_404(db.work_items, wid, "WorkItem")
    b = body()
    actual = as_num(req_field(b, "actual_hours"), "actual_hours", ge=0)
    if w["status"] != "IN_PROGRESS":
        invalid_state("Only an IN_PROGRESS work item can be completed")
    w["actual_hours"] = actual
    w["status"] = "COMPLETE"
    db.touch(w)
    return ok(work_item_out(w))


@bp.post("/work-items/<wid>/verify")
def verify_work_item(wid):
    _uid, role = actor()
    require_roles(role, OPS)
    w = get_or_404(db.work_items, wid, "WorkItem")
    b = body()
    outcome = as_enum(req_field(b, "outcome"), "outcome", VERIFY_OUTCOMES)
    if w["status"] != "COMPLETE":
        invalid_state("Only a COMPLETE work item can be verified")
    w["status"] = outcome  # VERIFIED (terminal) or REOPENED (rework loop)
    db.touch(w)
    return ok(work_item_out(w))


@bp.get("/work-items/<wid>/permits")
def list_work_item_permits(wid):
    actor()
    get_or_404(db.work_items, wid, "WorkItem")
    permits = [p for p in db.permits.values() if p["work_item_id"] == wid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(permits), limit, offset)
    return ok([permit_out(p) for p in page], pagination=meta)


@bp.get("/work-items/<wid>/discoveries")
def list_work_item_discoveries(wid):
    actor()
    get_or_404(db.work_items, wid, "WorkItem")
    discs = [d for d in db.discoveries.values() if d["origin_work_item_id"] == wid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(discs), limit, offset)
    return ok([discovery_out(d) for d in page], pagination=meta)


@bp.get("/work-items/<wid>/punch-items")
def list_work_item_punch_items(wid):
    actor()
    get_or_404(db.work_items, wid, "WorkItem")
    items = [p for p in db.punch_items.values() if p["work_item_id"] == wid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([punch_item_out(p) for p in page], pagination=meta)
