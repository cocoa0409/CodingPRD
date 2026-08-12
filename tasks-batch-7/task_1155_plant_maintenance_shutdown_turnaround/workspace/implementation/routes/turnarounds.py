"""Turnaround lifecycle endpoints (PRD 3.1, 3.8, 3.9)."""
from flask import Blueprint

import db
from clock import logical_now
from errors import bad_request, conflict, invalid_state
from helpers import (actor, as_dt, as_int, as_str, body, get_or_404,
                     req_field, require_roles)
from response import ok
from serialize import turnaround_out
from services import computed, ranking
from util import fmt_iso

bp = Blueprint("turnarounds", __name__)

TM = ("TurnaroundManager",)
COST_SUMMARY_ROLES = ("TurnaroundManager", "Planner", "CostController")
OPEN_PUNCH_STATUSES = ("OPEN", "READY", "REOPENED")
PRE_TERMINAL_STATUSES = ("SCOPE_FROZEN", "MOBILIZATION", "EXECUTION", "STARTUP")


def _new_entity(fields):
    now = db.now_iso()
    fields.setdefault("version", 1)
    fields["created_at"] = now
    fields["updated_at"] = now
    return fields


@bp.post("/turnarounds")
def create_turnaround():
    _uid, role = actor()
    require_roles(role, TM)
    b = body()
    name = as_str(req_field(b, "name"), "name")
    plant_unit = as_str(req_field(b, "plant_unit"), "plant_unit")
    planned_start = as_dt(req_field(b, "planned_start"), "planned_start")
    planned_end = as_dt(req_field(b, "planned_end"), "planned_end")
    budget = as_int(req_field(b, "authorized_budget_cents"),
                    "authorized_budget_cents", minimum=1)
    contingency = as_int(req_field(b, "contingency_budget_cents"),
                         "contingency_budget_cents", minimum=0)
    if planned_end <= planned_start:
        bad_request("planned_end must be strictly after planned_start")
    t = db.create(db.turnarounds, _new_entity({
        "id": db.mint_id(),
        "name": name,
        "plant_unit": plant_unit,
        "planned_start": fmt_iso(planned_start),
        "planned_end": fmt_iso(planned_end),
        "authorized_budget_cents": budget,
        "contingency_budget_cents": contingency,
        "status": "PLANNING",
        "schedule_run_index": 0,
        "scope_frozen_at": None,
        "handed_over_at": None,
    }))
    return ok(turnaround_out(t), status=201)


@bp.get("/turnarounds/<tid>")
def get_turnaround(tid):
    actor()
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    return ok(turnaround_out(t))


@bp.post("/turnarounds/<tid>/freeze-scope")
def freeze_scope(tid):
    _uid, role = actor()
    require_roles(role, TM)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    cutoff = as_int(req_field(b, "scope_cutoff_count"), "scope_cutoff_count",
                    minimum=0)
    if t["status"] != "PLANNING":
        invalid_state("Scope can only be frozen while the turnaround is PLANNING")
    proposed = [w for w in computed.work_items_of(tid) if w["status"] == "PROPOSED"]
    if not proposed:
        invalid_state("At least one PROPOSED work item is required to freeze scope")
    # work_rank_score + critical_path_float over the PROPOSED input set.
    ranked = ranking.compute_rankings(tid, proposed)
    ranking.compute_critical_path(tid, proposed)
    for pos, w in enumerate(ranked, start=1):
        w["status"] = "FROZEN" if pos <= cutoff else "DEFERRED"
        db.touch(w)
    t["status"] = "SCOPE_FROZEN"
    t["scope_frozen_at"] = db.now_iso()
    db.touch(t)
    return ok(turnaround_out(t))


@bp.post("/turnarounds/<tid>/advance")
def advance(tid):
    _uid, role = actor()
    require_roles(role, TM)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    status = t["status"]
    if status == "SCOPE_FROZEN":
        t["status"] = "MOBILIZATION"
    elif status == "MOBILIZATION":
        mobilized = any(c["turnaround_id"] == tid
                        and c["mobilization_status"] == "MOBILIZED"
                        for c in db.contractors.values())
        if not mobilized:
            conflict("ERR_NO_MOBILIZED_CONTRACTOR",
                     "Advancing to EXECUTION requires at least one MOBILIZED contractor")
        t["status"] = "EXECUTION"
    elif status == "EXECUTION":
        # Gate order: (1) work items, (2) permits, (3) isolations.
        for w in computed.work_items_of(tid):
            if w["status"] not in ("DEFERRED", "CANCELLED") and w["status"] != "VERIFIED":
                conflict("ERR_WORK_ITEMS_OPEN",
                         "Every scope work item must be VERIFIED before STARTUP")
        wi_ids = {w["id"] for w in computed.work_items_of(tid)}
        for p in db.permits.values():
            if p["work_item_id"] in wi_ids and p["status"] in (
                    "REQUESTED", "ISSUED", "ACTIVE", "SUSPENDED"):
                conflict("ERR_PERMITS_STILL_ACTIVE",
                         "No permit may remain open when advancing to STARTUP")
        for iso in db.isolations.values():
            if iso["turnaround_id"] == tid and iso["status"] in (
                    "PLANNED", "ISOLATED", "VERIFIED"):
                conflict("ERR_ISOLATIONS_ENGAGED",
                         "No isolation may remain engaged when advancing to STARTUP")
        t["status"] = "STARTUP"
    else:
        invalid_state("Turnaround in %s cannot be advanced" % status)
    db.touch(t)
    return ok(turnaround_out(t))


@bp.post("/turnarounds/<tid>/cancel")
def cancel(tid):
    _uid, role = actor()
    require_roles(role, TM)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    if t["status"] not in ("PLANNING", "SCOPE_FROZEN"):
        invalid_state("Only a PLANNING or SCOPE_FROZEN turnaround can be cancelled")
    for w in computed.work_items_of(tid):
        if w["status"] in ("PROPOSED", "FROZEN"):
            w["status"] = "CANCELLED"
            db.touch(w)
    t["status"] = "CANCELLED"
    db.touch(t)
    return ok(turnaround_out(t))


@bp.post("/turnarounds/<tid>/handover")
def handover(tid):
    _uid, role = actor()
    require_roles(role, TM)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    ack = b.get("operations_acknowledged")
    if ack is not True:
        bad_request("operations_acknowledged must be present and true")
    if t["status"] != "STARTUP":
        invalid_state("Handover is only possible from STARTUP")
    open_cat_a = sum(1 for p in db.punch_items.values()
                     if p["turnaround_id"] == tid and p["category"] == "A"
                     and p["status"] in OPEN_PUNCH_STATUSES)
    if open_cat_a != 0:
        conflict("ERR_OPEN_PUNCH_ITEMS",
                 "Category-A punch items must be verified before handover")
    t["status"] = "HANDED_OVER"
    t["handed_over_at"] = db.now_iso()
    db.touch(t)
    return ok(turnaround_out(t))


@bp.get("/turnarounds/<tid>/cost-summary")
def cost_summary(tid):
    _uid, role = actor()
    require_roles(role, COST_SUMMARY_ROLES)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    committed, provisional, posture = computed.forecast(t)
    return ok({
        "committed_cost_cents": committed,
        "reported_cost_cents": computed.reported_cost_cents(tid),
        "forecast_committed_cents": committed,
        "forecast_provisional_cents": provisional,
        "contingency_remaining_cents": computed.contingency_remaining_cents(t),
        "cost_posture": posture,
    })


@bp.post("/turnarounds/<tid>/run-ops")
def run_ops(tid):
    _uid, role = actor()
    require_roles(role, TM)
    t = get_or_404(db.turnarounds, tid, "Turnaround")
    now = logical_now()
    wi_ids = {w["id"] for w in computed.work_items_of(tid)}
    # Expire permits whose validity window has been reached; an expired
    # ACTIVE permit cascades a hold onto an IN_PROGRESS covered item.
    for p in sorted(db.permits.values(), key=lambda p: p["_seq"]):
        if p["work_item_id"] not in wi_ids:
            continue
        if p["status"] in ("ISSUED", "ACTIVE", "SUSPENDED") and p["_valid_until"] <= now:
            was_active = p["status"] == "ACTIVE"
            p["status"] = "EXPIRED"
            db.touch(p)
            if was_active:
                wi = db.work_items.get(p["work_item_id"])
                if wi is not None and wi["status"] == "IN_PROGRESS":
                    wi["status"] = "ON_HOLD"
                    db.touch(wi)
    # Auto-release stale staging reservations.
    area_ids = {a["id"] for a in db.laydown_areas.values()
                if a["turnaround_id"] == tid}
    for r in sorted(db.reservations.values(), key=lambda r: r["_seq"]):
        if r["laydown_area_id"] not in area_ids:
            continue
        if r["status"] in ("RESERVED", "STAGED") and r["_window_until"] <= now:
            r["status"] = "RELEASED"
            db.touch(r)
            area = db.laydown_areas.get(r["laydown_area_id"])
            if area is not None:
                db.touch(area)
    t["schedule_run_index"] += 1
    db.touch(t)
    return ok(turnaround_out(t))
