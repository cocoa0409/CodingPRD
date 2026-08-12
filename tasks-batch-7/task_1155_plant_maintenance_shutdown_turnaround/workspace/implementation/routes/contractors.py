"""Contractor and mobilization endpoints (PRD 3.2)."""
from flask import Blueprint, request

import db
from errors import conflict, forbidden, invalid_state
from helpers import (actor, as_int, as_str, body, get_or_404, paged,
                     pagination_params, req_field, require_roles,
                     sorted_by_created)
from response import ok
from serialize import contractor_out, daily_report_out, worker_out

bp = Blueprint("contractors", __name__)

TM = ("TurnaroundManager",)
SUPERVISOR = ("ContractorSupervisor",)


@bp.post("/turnarounds/<tid>/contractors")
def create_contractor(tid):
    _uid, role = actor()
    require_roles(role, TM)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    name = as_str(req_field(b, "name"), "name")
    craft = as_str(req_field(b, "craft"), "craft")
    cap = as_int(req_field(b, "headcount_cap"), "headcount_cap", minimum=1)
    if t["status"] not in ("SCOPE_FROZEN", "MOBILIZATION", "EXECUTION", "STARTUP"):
        invalid_state("Contractors can only be invited once the scope is frozen "
                      "(pre-terminal phases)")
    now = db.now_iso()
    c = db.create(db.contractors, {
        "id": db.mint_id(),
        "turnaround_id": tid,
        "name": name,
        "craft": craft,
        "headcount_cap": cap,
        "mobilization_status": "INVITED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    return ok(contractor_out(c), status=201)


@bp.get("/turnarounds/<tid>/contractors")
def list_contractors(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = [c for c in db.contractors.values() if c["turnaround_id"] == tid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([contractor_out(c) for c in page], pagination=meta)


@bp.get("/contractors/<cid>")
def get_contractor(cid):
    actor()
    c = get_or_404(db.contractors, cid, "Contractor")
    return ok(contractor_out(c))


@bp.post("/contractors/<cid>/mobilize")
def mobilize(cid):
    uid, role = actor()
    require_roles(role, SUPERVISOR)
    # Entity-backed ownership (priority 2): the acting supervisor's
    # X-User-ID must equal the target contractor's id.
    if uid != cid:
        forbidden("A ContractorSupervisor can only mobilize their own contractor")
    c = get_or_404(db.contractors, cid, "Contractor")
    t = db.turnarounds.get(c["turnaround_id"])
    status = c["mobilization_status"]
    if status == "INVITED":
        if t is None or t["status"] not in ("MOBILIZATION", "EXECUTION"):
            invalid_state("Mobilization requires the turnaround to be "
                          "MOBILIZATION or EXECUTION")
        c["mobilization_status"] = "MOBILIZING"
    elif status == "MOBILIZING":
        from services import computed
        if computed.badged_headcount(cid) < 1:
            conflict("ERR_NO_BADGED_WORKERS",
                     "Becoming MOBILIZED requires at least one badged worker")
        c["mobilization_status"] = "MOBILIZED"
    elif status == "MOBILIZED":
        if t is None or t["status"] != "STARTUP":
            invalid_state("Demobilization requires the turnaround to be STARTUP")
        c["mobilization_status"] = "DEMOBILIZED"
        # Cascade: debadge every worker holding a live badge; each debadging
        # cancels that worker's ASSIGNED shift assignments.
        for w in sorted(db.workers.values(), key=lambda w: w["_seq"]):
            if w["contractor_id"] == cid and w["badge_status"] in ("BADGED", "SUSPENDED"):
                w["badge_status"] = "DEBADGED"
                db.touch(w)
                for a in sorted(db.assignments.values(), key=lambda a: a["_seq"]):
                    if a["worker_id"] == w["id"] and a["status"] == "ASSIGNED":
                        a["status"] = "CANCELLED"
                        db.touch(a)
    else:
        invalid_state("A DEMOBILIZED contractor cannot be mobilized further")
    db.touch(c)
    return ok(contractor_out(c))


@bp.post("/contractors/<cid>/workers")
def register_worker(cid):
    uid, role = actor()
    require_roles(role, SUPERVISOR)
    if uid != cid:
        forbidden("A ContractorSupervisor can only register workers under "
                  "their own contractor")
    get_or_404(db.contractors, cid, "Contractor")
    b = body()
    full_name = as_str(req_field(b, "full_name"), "full_name")
    trade = as_str(req_field(b, "trade"), "trade")
    now = db.now_iso()
    w = db.create(db.workers, {
        "id": db.mint_id(),
        "contractor_id": cid,
        "full_name": full_name,
        "trade": trade,
        "badge_status": "REGISTERED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    return ok(worker_out(w), status=201)


@bp.get("/contractors/<cid>/workers")
def list_workers(cid):
    actor()
    get_or_404(db.contractors, cid, "Contractor")
    items = [w for w in db.workers.values() if w["contractor_id"] == cid]
    badge = request.args.get("badge_status")
    if badge is not None:
        items = [w for w in items if w["badge_status"] == badge]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([worker_out(w) for w in page], pagination=meta)


@bp.get("/contractors/<cid>/daily-reports")
def list_contractor_reports(cid):
    actor()
    get_or_404(db.contractors, cid, "Contractor")
    items = [r for r in db.daily_reports.values() if r["contractor_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([daily_report_out(r) for r in page], pagination=meta)
