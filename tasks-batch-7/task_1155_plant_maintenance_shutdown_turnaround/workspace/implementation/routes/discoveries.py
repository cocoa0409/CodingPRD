"""Discovery work & change authorization (PRD 3.6).

Segregation of duties: the decider's X-User-ID must differ from the recorded
reported_by_user_id. Authorization creates the FROZEN addendum work item and
draws down contingency; rejection can be appealed (appeal_count < 2).
"""
from flask import Blueprint, request

import db
from errors import conflict, cross_scope, invalid_state, sod
from helpers import (actor, as_enum, as_int, as_num, as_str, body, get_or_404,
                     opt_field, paged, pagination_params, req_field,
                     require_roles, sorted_by_created)
from response import ok
from serialize import discovery_out, work_item_out
from services import computed

bp = Blueprint("discoveries", __name__)

TM = ("TurnaroundManager",)
REPORT_ROLES = ("ContractorSupervisor", "TurnaroundManager")
APPEAL_ROLES = ("ContractorSupervisor", "TurnaroundManager")
DECIDE_OUTCOMES = ("AUTHORIZED", "REJECTED")


@bp.post("/turnarounds/<tid>/discoveries")
def create_discovery(tid):
    uid, role = actor()
    require_roles(role, REPORT_ROLES)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    description = as_str(req_field(b, "description"), "description")
    quoted_cost = as_int(req_field(b, "quoted_cost_cents"),
                         "quoted_cost_cents", minimum=1)
    quoted_hours = as_num(req_field(b, "quoted_hours"), "quoted_hours", gt=0)
    origin_id = opt_field(b, "origin_work_item_id", None)
    if origin_id is not None:
        if not isinstance(origin_id, str):
            from errors import bad_request
            bad_request("origin_work_item_id must be a string")
        origin = db.work_items.get(origin_id)
        if origin is None or origin["turnaround_id"] != tid:
            cross_scope("origin_work_item_id must resolve within the same "
                        "turnaround")
    if t["status"] != "EXECUTION":
        invalid_state("Discovery work can only be reported while the turnaround "
                      "is EXECUTION")
    now = db.now_iso()
    d = db.create(db.discoveries, {
        "id": db.mint_id(),
        "turnaround_id": tid,
        "origin_work_item_id": origin_id,
        "description": description,
        "quoted_cost_cents": quoted_cost,
        "quoted_hours": quoted_hours,
        "authorized_cost_cents": None,
        "status": "REPORTED",
        "reported_by_user_id": uid,
        "authorized_by_user_id": None,
        "appeal_count": 0,
        "triage_note": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    return ok(discovery_out(d), status=201)


@bp.get("/turnarounds/<tid>/discoveries")
def list_discoveries(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = computed.discoveries_of(tid)
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([discovery_out(d) for d in page], pagination=meta)


@bp.get("/discoveries/<did>")
def get_discovery(did):
    actor()
    d = get_or_404(db.discoveries, did, "DiscoveryWork")
    return ok(discovery_out(d))


@bp.get("/discoveries/<did>/work-items")
def list_discovery_work_items(did):
    actor()
    get_or_404(db.discoveries, did, "DiscoveryWork")
    items = [w for w in db.work_items.values() if w["discovery_id"] == did]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([work_item_out(w) for w in page], pagination=meta)


@bp.post("/discoveries/<did>/triage")
def triage_discovery(did):
    _uid, role = actor()
    require_roles(role, TM)
    d = get_or_404(db.discoveries, did, "DiscoveryWork")
    b = body()
    note = opt_field(b, "triage_note", None)
    if note is not None and not isinstance(note, str):
        from errors import bad_request
        bad_request("triage_note must be a string")
    if d["status"] != "REPORTED":
        invalid_state("Only a REPORTED discovery can be triaged")
    if note is not None:
        d["triage_note"] = note
    d["status"] = "TRIAGED"
    db.touch(d)
    return ok(discovery_out(d))


@bp.post("/discoveries/<did>/decide")
def decide_discovery(did):
    uid, role = actor()
    require_roles(role, TM)
    d = get_or_404(db.discoveries, did, "DiscoveryWork")
    b = body()
    outcome = as_enum(req_field(b, "outcome"), "outcome", DECIDE_OUTCOMES)
    authorized_cost = None
    if outcome == "AUTHORIZED":
        authorized_cost = as_int(req_field(b, "authorized_cost_cents"),
                                 "authorized_cost_cents", minimum=1)
    if d["status"] != "TRIAGED":
        invalid_state("Only a TRIAGED discovery can be decided")
    if uid == d["reported_by_user_id"]:
        sod("The discovery decider must differ from the reporter")
    t = db.turnarounds.get(d["turnaround_id"])
    if outcome == "AUTHORIZED":
        if t is None or authorized_cost > computed.contingency_remaining_cents(t):
            conflict("ERR_CONTINGENCY_EXCEEDED",
                     "authorized_cost_cents exceeds the remaining contingency")
        # Cascade link 1: addendum work item, FROZEN, back-referencing the
        # discovery; committed cost recompute follows on the fly.
        now = db.now_iso()
        origin = db.work_items.get(d["origin_work_item_id"]) \
            if d["origin_work_item_id"] else None
        db.create(db.work_items, {
            "id": db.mint_id(),
            "turnaround_id": d["turnaround_id"],
            "discovery_id": did,
            "planned_shift_id": None,
            "title": "Discovery addendum: %s" % d["description"],
            "system_area": origin["system_area"] if origin else "",
            "work_type": "DISCOVERY_ADDENDUM",
            "risk_class": "C",
            "estimated_hours": d["quoted_hours"],
            "estimated_cost_cents": authorized_cost,
            "requires_permit": False,
            "rank_score": None,
            "rank_position": None,
            "is_critical_path": False,
            "actual_hours": None,
            "status": "FROZEN",
            "version": 1,
            "created_at": now,
            "updated_at": now,
        })
        d["authorized_cost_cents"] = authorized_cost
        d["authorized_by_user_id"] = uid
        d["status"] = "AUTHORIZED"
        db.touch(d)
        if t is not None:
            db.touch(t)  # cascade link 2: forecast/posture recompute
    else:
        d["status"] = "REJECTED"
        db.touch(d)
    return ok(discovery_out(d))


@bp.post("/discoveries/<did>/appeal")
def appeal_discovery(did):
    _uid, role = actor()
    require_roles(role, APPEAL_ROLES)
    d = get_or_404(db.discoveries, did, "DiscoveryWork")
    if d["status"] != "REJECTED":
        invalid_state("Only a REJECTED discovery can be appealed")
    if d["appeal_count"] >= 2:
        conflict("ERR_APPEAL_LIMIT", "At most two appeals are allowed")
    d["appeal_count"] += 1
    d["status"] = "TRIAGED"
    db.touch(d)
    return ok(discovery_out(d))
