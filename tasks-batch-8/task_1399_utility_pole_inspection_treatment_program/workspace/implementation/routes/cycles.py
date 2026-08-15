from datetime import datetime

from flask import Blueprint

import db
from calc import (add_years, add_days, sample_size_for, priority_score,
                  production_billing, FIELD_SEASON_DAYS)
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok
from serializers import ser_cycle, TASK_TERMINAL
from validators import (body, req_field, opt_field, as_int, as_num, as_enum,
                        as_str, as_str_list)

bp = Blueprint("cycles", __name__)

VARIANT_POLICIES = ["CONSERVATIVE", "STATISTICAL"]


def _blank_task_fields():
    return dict(shell_thickness_in=None, sound_wood_pct=None,
                decay_pocket_depth_in=None, moisture_pct=None,
                hazard_flag=False, photos=[], submitted_by_user_id=None,
                qa_reviewed_by_user_id=None, rs_conservative_pct=None,
                rs_statistical_pct=None, effective_rs_pct=None,
                classification=None)


@bp.post("/pole-program/inspection-cycles")
@locked
def create_cycle():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    year = as_int(req_field(d, "year"), "year", 2000, 2100)
    cycle_length_years = as_int(req_field(d, "cycle_length_years"),
                                "cycle_length_years", 1)
    sample_pct = as_num(req_field(d, "sample_pct"), "sample_pct", 0, 100)
    mandatory_zone_tags = opt_field(d, "mandatory_zone_tags", [])
    as_str_list(mandatory_zone_tags, "mandatory_zone_tags")
    strength_variant_policy = as_enum(req_field(d, "strength_variant_policy"),
                                      "strength_variant_policy",
                                      VARIANT_POLICIES)
    rec = db.new_record()
    rec.update(year=year, cycle_length_years=cycle_length_years,
               sample_pct=sample_pct, mandatory_zone_tags=mandatory_zone_tags,
               strength_variant_policy=strength_variant_policy, status="DRAFT",
               opened_at=None, reconciled_at=None, sample_pool_size=0)
    db.cycles[rec["id"]] = rec
    return ok(ser_cycle(rec), 201)


@bp.get("/pole-program/inspection-cycles/<cid>")
def get_cycle(cid):
    authenticate()
    rec = db.cycles.get(cid)
    if rec is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle id does not resolve")
    return ok(ser_cycle(rec), 200)


@bp.post("/pole-program/inspection-cycles/<cid>/open")
@locked
def open_cycle(cid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    cyc = db.cycles.get(cid)
    if cyc is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle id does not resolve")
    if cyc["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "open requires cycle.status == DRAFT")
    n = db.clock_now()
    # Eligible pool: IN_SERVICE|MONITOR, recency/zone condition, no live task.
    pool = []
    for p in db.poles.values():
        if p["status"] not in ("IN_SERVICE", "MONITOR"):
            continue
        lid = p["last_inspection_date"]
        eligible = (lid is None
                    or add_years(lid, cyc["cycle_length_years"]) <= n
                    or p["gis_tag"] in cyc["mandatory_zone_tags"])
        if not eligible:
            continue
        live = any(t["pole_id"] == p["id"]
                   and t["status"] in ("OPEN", "SUBMITTED", "REJECTED")
                   for t in db.tasks.values())
        if live:
            continue
        pool.append(p)
    # Ranking: never-inspected first, then last_inspection_date ASC, then created_at ASC.
    pool.sort(key=lambda p: (
        0 if p["last_inspection_date"] is None else 1,
        p["last_inspection_date"] or datetime.min.replace(tzinfo=db.UTC),
        p["created_at"], p["_seq"]))
    size = sample_size_for(len(pool), cyc["sample_pct"])
    for p in pool[:size]:
        t = db.new_record()
        t.update(cycle_id=cid, pole_id=p["id"], due_window_start=n,
                 due_window_end=add_days(n, FIELD_SEASON_DAYS), status="OPEN",
                 rework_count=0)
        t.update(_blank_task_fields())
        db.tasks[t["id"]] = t
    cyc["status"] = "OPEN"
    cyc["opened_at"] = n
    cyc["sample_pool_size"] = len(pool)
    db.touch(cyc)
    return ok(ser_cycle(cyc), 200)


@bp.post("/pole-program/inspection-cycles/<cid>/reconcile")
@locked
def reconcile_cycle(cid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    budget_id = as_str(req_field(d, "budget_id"), "budget_id")
    cyc = db.cycles.get(cid)
    if cyc is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle id does not resolve")
    budget = db.budgets.get(budget_id)
    if budget is None:
        raise ApiError("ERR_BUDGET_NOT_FOUND", 404, "budget_id does not resolve")
    if cyc["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "reconcile requires cycle.status == OPEN")
    cycle_tasks = [t for t in db.tasks.values() if t["cycle_id"] == cid]
    tasks_terminal = sum(1 for t in cycle_tasks if t["status"] in TASK_TERMINAL)
    if tasks_terminal != len(cycle_tasks):
        raise ApiError("ERR_CYCLE_TASKS_OPEN", 409,
                       "Reconcile attempted while tasks_terminal < tasks_total")
    n = db.clock_now()

    # Step 1: auto-requeue every DEFERRED replacement order (program-wide).
    for o in db.replacements.values():
        if o["status"] == "DEFERRED":
            o["status"] = "QUEUED"
            pole = db.poles[o["pole_id"]]
            o["priority_score"] = priority_score(pole, o["deferral_count"])
            db.touch(o)

    # Step 2: escalate overdue NOTIFIED violations.
    for a in db.audits.values():
        if (a["violation_status"] == "NOTIFIED"
                and a["cure_deadline"] is not None and a["cure_deadline"] < n):
            a["violation_status"] = "ESCALATED"
            db.touch(a)

    # Step 3: funding waterfall over the program-wide QUEUED backlog.
    remaining = (budget["total_cents"] - budget["committed_cents"]
                 - budget["spent_cents"])
    candidates = sorted(
        (o for o in db.replacements.values() if o["status"] == "QUEUED"),
        key=lambda o: (-o["priority_score"], o["created_at"], o["_seq"]))
    funded_count = 0
    for o in candidates:
        cost = o["escalated_cost_cents"]
        if cost <= remaining:  # inclusive boundary funds
            o["status"] = "FUNDED"
            o["budget_id"] = budget["id"]
            o["funded_at"] = n
            budget["committed_cents"] += cost
            remaining -= cost
            funded_count += 1
            db.touch(o)
    db.touch(budget)

    # Step 4: per-crew production billing for in-scope VERIFIED orders.
    season_end = add_days(cyc["opened_at"], FIELD_SEASON_DAYS)
    crew_billings = []
    crews_sorted = sorted(db.crews.values(),
                          key=lambda c: (c["created_at"], c["_seq"]))
    for crew in crews_sorted:
        orders = [o for o in db.treatments.values()
                  if o["status"] == "VERIFIED" and o["crew_id"] == crew["id"]
                  and o["applied_at"] is not None
                  and cyc["opened_at"] <= o["applied_at"] < n]
        if not orders:
            continue  # crew skipped, billing unchanged
        orders.sort(key=lambda o: (o["created_at"], o["_seq"]))
        billing = production_billing(crew, orders, db.poles, season_end)
        crew["current_cycle_billing_cents"] = billing
        db.touch(crew)
        crew_billings.append({"crew_id": crew["id"], "billing_cents": billing})

    # Step 5: immutable backlog snapshot.
    still_queued = [o for o in db.replacements.values()
                    if o["status"] == "QUEUED"]
    snap = db.new_record(with_version=False)
    snap.update(
        cycle_id=cid, budget_id=budget["id"],
        snapshot_seq=sum(1 for s in db.snapshots.values()
                         if s["cycle_id"] == cid) + 1,
        queued_count=len(still_queued),
        queued_escalated_cost_cents=sum(o["escalated_cost_cents"]
                                        for o in still_queued),
        funded_count=funded_count,
        budget_available_cents=(budget["total_cents"]
                                - budget["committed_cents"]
                                - budget["spent_cents"]),
        budget_committed_cents=budget["committed_cents"],
        crew_billings=crew_billings,
    )
    db.snapshots[snap["id"]] = snap

    cyc["status"] = "RECONCILED"
    cyc["reconciled_at"] = n
    db.touch(cyc)
    return ok(ser_cycle(cyc), 200)
