"""ProductionRun + BatchAllocation + ChangeoverRecord endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import domain as D
from db import store, mint, touch
from errors import err
from middleware import authorize, ROLES
from response import ok, ok_list
from validate import body, need_str, need_num, need_int, need_dt, paginate

bp = Blueprint("runs", __name__)


# ---- ProductionRun ----

@bp.post("/plant/runs")
def create_run():
    authorize(["LineScheduler"])
    b = body()
    # shape (400)
    product_id = need_str(b, "product_id")
    line_id = need_str(b, "line_id")
    planned_cases = need_int(b, "planned_cases")
    start_at = need_dt(b, "start_at")
    end_at = need_dt(b, "end_at")
    expected_line_version = need_int(b, "expected_line_version")
    if planned_cases <= 0:
        err("ERR_INVALID_REQUEST", 400, "planned_cases must be greater than zero")
    if end_at <= start_at:
        err("ERR_INVALID_REQUEST", 400, "end_at must be strictly after start_at")
    # existence (404)
    product = D.get_product(product_id)
    line = D.get_line(line_id)
    # state (409/412) — PRD section 3.5 order: product, line, then OCC
    if product["product_status"] != "ACTIVE":
        err("ERR_PRODUCT_DISCONTINUED", 409, "Product is DISCONTINUED")
    if line["line_status"] != "ACTIVE":
        err("ERR_RUN_INVALID_STATE", 409, "Line is DOWN and cannot accept new runs")
    if expected_line_version != line["version"]:
        err("ERR_STALE_VERSION", 412, "expected_line_version does not match line version")
    # business safety (422)
    if (line["allergen_zone"] == "DEDICATED_CORN"
            and product["allergen_class"] in ("WHEAT_FLOUR", "SOY_BLENDED")):
        err("ERR_ALLERGEN_ZONE_VIOLATION", 422,
            "WHEAT_FLOUR/SOY_BLENDED product forbidden on DEDICATED_CORN line")
    # business temporal (409): half-open overlap vs non-CANCELLED siblings
    for r in store.runs.values():
        if r["line_id"] != line["id"]:
            continue
        if r["production_status"] == "CANCELLED":
            continue
        if start_at < r["end_at"] and end_at > r["start_at"]:
            err("ERR_LINE_WINDOW_OVERLAP", 409,
                "Run window overlaps a sibling run on this line")
    # product-switch buffer + auto changeover decision
    prev = D.prev_run_on_line(line["id"], start_at)
    changeover_spec = None
    if prev is not None and prev["product_id"] != product_id:
        from_product = D.get_product(prev["product_id"])
        level, downtime = D.changeover_requirement(from_product, product)
        if start_at < prev["end_at"] + timedelta(minutes=downtime):
            err("ERR_CHANGEOVER_WINDOW_INSUFFICIENT", 409,
                "Product switch requires a larger gap after the previous run")
        changeover_spec = (from_product, level, downtime)
    # business constraint (422): line throughput
    window_seconds = Decimal(str((end_at - start_at).total_seconds()))
    if Decimal(planned_cases) * Decimal(3600) > Decimal(line["cases_per_hour"]) * window_seconds:
        err("ERR_LINE_CAPACITY_EXCEEDED", 422,
            "planned_cases exceeds cases_per_hour * window hours")
    run = mint()
    run.update({
        "product_id": product_id, "line_id": line["id"],
        "planned_cases": planned_cases, "start_at": start_at, "end_at": end_at,
        "masa_required_kg": D.masa_required_kg(product, planned_cases),
        "production_status": "PLANNED", "qc_status": "PENDING",
    })
    store.runs[run["id"]] = run
    if changeover_spec is not None:
        from_product, level, downtime = changeover_spec
        co = mint()
        co.update({
            "line_id": line["id"], "from_product_id": from_product["id"],
            "to_product_id": product_id, "production_run_id": run["id"],
            "required_level": level, "required_downtime_min": downtime,
            "performed_by": None, "fail_count": 0, "changeover_status": "REQUIRED",
        })
        store.changeovers[co["id"]] = co
    touch(line)  # run creation advances the line's version
    return ok(D.run_json(run), 201)


@bp.get("/plant/runs/<rid>")
def get_run(rid):
    authorize(ROLES)
    return ok(D.run_json(D.get_run(rid)))


@bp.post("/plant/runs/<rid>/schedule")
def schedule_run(rid):
    authorize(["LineScheduler"])
    run = D.get_run(rid)
    if run["production_status"] != "PLANNED":
        err("ERR_RUN_INVALID_STATE", 409, "Run must be PLANNED to schedule")
    run["production_status"] = "SCHEDULED"
    touch(run)
    return ok(D.run_json(run))


def _active_gating_changeover(run_id):
    for c in store.changeovers.values():
        if (c["production_run_id"] == run_id
                and c["changeover_status"] in ("REQUIRED", "IN_PROGRESS", "FAILED")):
            return c
    return None


@bp.post("/plant/runs/<rid>/start")
def start_run(rid):
    authorize(["LineScheduler"])
    run = D.get_run(rid)
    if run["production_status"] != "SCHEDULED":
        err("ERR_RUN_INVALID_STATE", 409, "Run must be SCHEDULED to start")
    if _active_gating_changeover(rid) is not None:
        err("ERR_CHANGEOVER_NOT_VERIFIED", 409,
            "Gating changeover is not VERIFIED")
    if D.run_masa_reserved(rid) < run["masa_required_kg"]:
        err("ERR_MASA_INSUFFICIENT", 422,
            "RESERVED masa does not cover masa_required_kg")
    for a in store.allocations.values():
        if a["production_run_id"] == rid and a["allocation_status"] == "RESERVED":
            a["allocation_status"] = "CONSUMED"
            touch(a)
            batch = store.nixtamal_batches.get(a["nixtamal_batch_id"])
            if batch is not None:
                D.maybe_deplete_batch(batch)
    line = store.lines.get(run["line_id"])
    if line is not None:
        line["current_product_id"] = run["product_id"]
        touch(line)
    run["production_status"] = "IN_PROGRESS"
    touch(run)
    return ok(D.run_json(run))


@bp.post("/plant/runs/<rid>/complete")
def complete_run(rid):
    authorize(["LineScheduler"])
    run = D.get_run(rid)
    if run["production_status"] != "IN_PROGRESS":
        err("ERR_RUN_INVALID_STATE", 409, "Run must be IN_PROGRESS to complete")
    for p in store.pack_orders.values():
        if (p["production_run_id"] == rid
                and p["pack_status"] not in ("SEALED", "REJECTED", "CANCELLED")):
            err("ERR_UNRESOLVED_PACK_ORDERS", 409,
                "All child pack orders must be terminal to complete the run")
    produced = D.run_produced_cases(rid)
    needed = D.ceil_int(Decimal(run["planned_cases"]) * Decimal("0.95"))
    if produced < needed:
        err("ERR_RUN_CASE_SHORTFALL", 422,
            "produced_cases below 95 percent of planned_cases")
    run["production_status"] = "COMPLETED"
    touch(run)
    return ok(D.run_json(run))


@bp.post("/plant/runs/<rid>/cancel")
def cancel_run(rid):
    authorize(["LineScheduler"])
    run = D.get_run(rid)
    if run["production_status"] not in ("PLANNED", "SCHEDULED", "IN_PROGRESS"):
        err("ERR_RUN_INVALID_STATE", 409, "Run cannot be cancelled from its current state")
    for a in store.allocations.values():
        if a["production_run_id"] == rid and a["allocation_status"] == "RESERVED":
            a["allocation_status"] = "RELEASED"
            touch(a)
            batch = store.nixtamal_batches.get(a["nixtamal_batch_id"])
            if batch is not None:
                touch(batch)  # masa_available_kg restored
    for p in store.pack_orders.values():
        if (p["production_run_id"] == rid
                and p["pack_status"] not in ("SEALED", "REJECTED", "CANCELLED")):
            p["pack_status"] = "CANCELLED"
            touch(p)
    D.cancel_gating_changeover(run)
    run["production_status"] = "CANCELLED"
    touch(run)
    return ok(D.run_json(run))


@bp.post("/plant/runs/<rid>/qc-hold")
def qc_hold(rid):
    authorize(["QualityInspector"])
    run = D.get_run(rid)
    if run["qc_status"] != "PENDING":
        err("ERR_RUN_INVALID_STATE", 409, "qc_status must be PENDING to hold")
    if run["production_status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_RUN_INVALID_STATE", 409, "Cannot QC-hold a terminal run")
    run["qc_status"] = "ON_HOLD"
    touch(run)
    return ok(D.run_json(run))


@bp.post("/plant/runs/<rid>/qc-release")
def qc_release(rid):
    authorize(["QualityInspector"])
    run = D.get_run(rid)
    if run["qc_status"] != "ON_HOLD":
        err("ERR_RUN_INVALID_STATE", 409, "qc_status must be ON_HOLD to release")
    run["qc_status"] = "PASSED"
    touch(run)
    return ok(D.run_json(run))


@bp.get("/plant/runs/<rid>/allocations")
def run_allocations(rid):
    authorize(ROLES)
    D.get_run(rid)
    items = [a for a in store.allocations.values() if a["production_run_id"] == rid]
    page, limit, offset, total = paginate(items, D.alloc_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/runs/<rid>/pack-orders")
def run_pack_orders(rid):
    authorize(ROLES)
    D.get_run(rid)
    items = [p for p in store.pack_orders.values() if p["production_run_id"] == rid]
    page, limit, offset, total = paginate(items, D.pack_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/runs/<rid>/changeovers")
def run_changeovers(rid):
    authorize(ROLES)
    D.get_run(rid)
    items = [c for c in store.changeovers.values() if c["production_run_id"] == rid]
    page, limit, offset, total = paginate(items, D.changeover_json)
    return ok_list(page, limit, offset, total)


# ---- BatchAllocation ----

@bp.post("/plant/allocations")
def create_allocation():
    authorize(["LineScheduler"])
    b = body()
    nixtamal_batch_id = need_str(b, "nixtamal_batch_id")
    production_run_id = need_str(b, "production_run_id")
    allocated_kg = need_num(b, "allocated_kg")
    if allocated_kg <= 0:
        err("ERR_INVALID_REQUEST", 400, "allocated_kg must be greater than zero")
    batch = D.get_batch(nixtamal_batch_id)
    run = D.get_run(production_run_id)
    if batch["batch_status"] != "MASA_AVAILABLE":
        err("ERR_BATCH_INVALID_STATE", 409, "Batch must be MASA_AVAILABLE to allocate from")
    if run["production_status"] not in ("PLANNED", "SCHEDULED"):
        err("ERR_RUN_INVALID_STATE", 409,
            "Run must be PLANNED or SCHEDULED to receive an allocation")
    if allocated_kg > D.batch_masa_available(batch):
        err("ERR_MASA_INSUFFICIENT", 422, "allocated_kg exceeds batch masa_available_kg")
    alloc = mint()
    alloc.update({"nixtamal_batch_id": batch["id"], "production_run_id": run["id"],
                  "allocated_kg": allocated_kg, "allocation_status": "RESERVED"})
    store.allocations[alloc["id"]] = alloc
    touch(batch)  # masa_available_kg decreased
    touch(run)    # masa_reserved_kg recomputed
    D.maybe_deplete_batch(batch)
    return ok(D.alloc_json(alloc), 201)


@bp.get("/plant/allocations/<aid>")
def get_allocation(aid):
    authorize(ROLES)
    return ok(D.alloc_json(D.get_allocation(aid)))


@bp.post("/plant/allocations/<aid>/release")
def release_allocation(aid):
    authorize(["LineScheduler"])
    alloc = D.get_allocation(aid)
    if alloc["allocation_status"] != "RESERVED":
        err("ERR_ALLOCATION_INVALID_STATE", 409, "Allocation must be RESERVED to release")
    D.release_allocation(alloc)
    return ok(D.alloc_json(alloc))


@bp.post("/plant/allocations/<aid>/consume")
def consume_allocation(aid):
    authorize(["LineScheduler"])
    alloc = D.get_allocation(aid)
    if alloc["allocation_status"] != "RESERVED":
        err("ERR_ALLOCATION_INVALID_STATE", 409, "Allocation must be RESERVED to consume")
    run = D.get_run(alloc["production_run_id"])
    if run["production_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        err("ERR_RUN_INVALID_STATE", 409,
            "Linked run must be SCHEDULED or IN_PROGRESS to consume")
    alloc["allocation_status"] = "CONSUMED"
    touch(alloc)
    batch = store.nixtamal_batches.get(alloc["nixtamal_batch_id"])
    if batch is not None:
        D.maybe_deplete_batch(batch)
    return ok(D.alloc_json(alloc))


# ---- ChangeoverRecord ----

@bp.post("/plant/changeovers")
def create_changeover():
    authorize(["SanitationTech"])
    b = body()
    line_id = need_str(b, "line_id")
    from_product_id = need_str(b, "from_product_id")
    to_product_id = need_str(b, "to_product_id")
    line = D.get_line(line_id)
    from_product = D.get_product(from_product_id)
    to_product = D.get_product(to_product_id)
    level, downtime = D.changeover_requirement(from_product, to_product)
    co = mint()
    co.update({
        "line_id": line["id"], "from_product_id": from_product["id"],
        "to_product_id": to_product["id"], "production_run_id": None,
        "required_level": level, "required_downtime_min": downtime,
        "performed_by": None, "fail_count": 0, "changeover_status": "REQUIRED",
    })
    store.changeovers[co["id"]] = co
    return ok(D.changeover_json(co), 201)


@bp.get("/plant/changeovers")
def list_changeovers():
    authorize(ROLES)
    line_id = request.args.get("line_id")
    from_product_id = request.args.get("from_product_id")
    to_product_id = request.args.get("to_product_id")
    status = request.args.get("changeover_status")
    items = [c for c in store.changeovers.values()
             if (line_id is None or c["line_id"] == line_id)
             and (from_product_id is None or c["from_product_id"] == from_product_id)
             and (to_product_id is None or c["to_product_id"] == to_product_id)
             and (status is None or c["changeover_status"] == status)]
    page, limit, offset, total = paginate(items, D.changeover_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/changeovers/<cid>")
def get_changeover(cid):
    authorize(ROLES)
    return ok(D.changeover_json(D.get_changeover(cid)))


@bp.post("/plant/changeovers/<cid>/begin")
def begin_changeover(cid):
    uid, _ = authorize(["SanitationTech"])
    co = D.get_changeover(cid)
    if co["changeover_status"] not in ("REQUIRED", "FAILED"):
        err("ERR_CHANGEOVER_INVALID_STATE", 409,
            "Changeover must be REQUIRED or FAILED to begin")
    co["performed_by"] = uid
    co["changeover_status"] = "IN_PROGRESS"
    touch(co)
    return ok(D.changeover_json(co))


def _sod_guard(co, uid):
    if co["performed_by"] is not None and co["performed_by"] == uid:
        err("ERR_SOD_VIOLATION", 403,
            "Verifier/failer must differ from the changeover performer")


@bp.post("/plant/changeovers/<cid>/verify")
def verify_changeover(cid):
    uid, _ = authorize(["QualityInspector"])
    co = D.get_changeover(cid)
    _sod_guard(co, uid)
    if co["changeover_status"] != "IN_PROGRESS":
        err("ERR_CHANGEOVER_INVALID_STATE", 409, "Changeover must be IN_PROGRESS to verify")
    co["changeover_status"] = "VERIFIED"
    touch(co)
    return ok(D.changeover_json(co))


@bp.post("/plant/changeovers/<cid>/fail")
def fail_changeover(cid):
    uid, _ = authorize(["QualityInspector"])
    co = D.get_changeover(cid)
    _sod_guard(co, uid)
    if co["changeover_status"] != "IN_PROGRESS":
        err("ERR_CHANGEOVER_INVALID_STATE", 409, "Changeover must be IN_PROGRESS to fail")
    co["changeover_status"] = "FAILED"
    co["fail_count"] += 1
    touch(co)
    return ok(D.changeover_json(co))
