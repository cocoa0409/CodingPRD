"""Filling line and filling run lifecycle endpoints."""
from flask import Blueprint, request

from core import (body, check_string, err, get_required, list_page,
                  new_entity, require_roles, success, touch)
from services import (consume_batch_allocations, latest_review, must_get,
                      serialize_line, serialize_run)
from store import db

bp = Blueprint("filling", __name__)

LINE_ROLES = ("ProductionPlanner", "QAManager", "PlantDirector")
RUN_ROLES = ("ProductionPlanner", "QAManager", "PlantDirector")


# ---------------------------------------------------------------------------
# Filling lines
# ---------------------------------------------------------------------------


@bp.post("/cosmfg/filling-lines")
@require_roles("ProductionPlanner")
def create_line():
    b = body()
    code = check_string(get_required(b, "line_code"), "line_code")
    for existing in db.lines.values():
        if existing["line_code"] == code:
            err("ERR_VALIDATION", 400, "line_code must be unique")
    line = new_entity()
    line.update({"line_code": code, "status": "IDLE", "current_run_id": None})
    db.lines[line["id"]] = line
    return success(serialize_line(line), status=201)


@bp.get("/cosmfg/filling-lines")
@require_roles(*LINE_ROLES)
def list_lines():
    items = list(db.lines.values())
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    current_run_id = request.args.get("current_run_id")
    if current_run_id is not None:
        items = [l for l in items if l["current_run_id"] == current_run_id]
    return list_page(items, serialize_line)


@bp.get("/cosmfg/filling-lines/<lid>")
@require_roles(*LINE_ROLES)
def get_line(lid):
    return success(serialize_line(must_get(db.lines, lid, "FillingLine")))


@bp.get("/cosmfg/filling-lines/<lid>/runs")
@require_roles("ProductionPlanner", "PlantDirector", "QAManager")
def list_line_runs(lid):
    line = must_get(db.lines, lid, "FillingLine")
    items = [r for r in db.runs.values() if r["line_id"] == line["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_page(items, serialize_run)


@bp.post("/cosmfg/filling-lines/<lid>/finish-cleaning")
@require_roles("ProductionPlanner")
def finish_cleaning(lid):
    line = must_get(db.lines, lid, "FillingLine")
    if line["status"] != "CLEANING":
        err("ERR_INVALID_STATE", 409, "Only a CLEANING line may finish cleaning")
    line["status"] = "IDLE"
    touch(line)
    return success(serialize_line(line))


# ---------------------------------------------------------------------------
# Filling runs
# ---------------------------------------------------------------------------


@bp.get("/cosmfg/filling-runs/<rid>")
@require_roles(*RUN_ROLES)
def get_run(rid):
    return success(serialize_run(must_get(db.runs, rid, "FillingRun")))


@bp.post("/cosmfg/filling-runs/<rid>/start")
@require_roles("ProductionPlanner")
def start_run(rid):
    run = must_get(db.runs, rid, "FillingRun")
    if run["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Only a SCHEDULED run may be started")
    batch = db.batches.get(run["batch_id"])
    if batch is None or batch["status"] != "RELEASED_TO_FILLING":
        err("ERR_BATCH_NOT_RELEASED", 409,
            "Run start requires the referenced batch to be RELEASED_TO_FILLING")
    line = db.lines.get(run["line_id"])
    if line is None or line["status"] != "IDLE":
        err("ERR_INVALID_STATE", 409, "Run start requires the line to be IDLE")
    order = db.orders.get(run["production_order_id"])
    if order is None or order["status"] not in ("IN_PRODUCTION", "FILLING"):
        err("ERR_INVALID_STATE", 409,
            "Run start requires the order in IN_PRODUCTION or FILLING")
    run["status"] = "IN_PROGRESS"
    touch(run)
    line["status"] = "RUNNING"
    line["current_run_id"] = run["id"]
    touch(line)
    # First IN_PROGRESS run moves the order IN_PRODUCTION -> FILLING
    if order["status"] == "IN_PRODUCTION":
        order["status"] = "FILLING"
        touch(order)
    return success(serialize_run(run))


@bp.post("/cosmfg/filling-runs/<rid>/complete")
@require_roles("ProductionPlanner")
def complete_run(rid):
    run = must_get(db.runs, rid, "FillingRun")
    if run["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "Only an IN_PROGRESS run may be completed")
    b = body()
    filled = get_required(b, "filled_units")
    if isinstance(filled, bool) or not isinstance(filled, int) or filled < 0:
        err("ERR_VALIDATION", 400, "filled_units must be an integer >= 0")
    rejected = b.get("rejected_units", 0)
    if isinstance(rejected, bool) or not isinstance(rejected, int) or rejected < 0:
        err("ERR_VALIDATION", 400, "rejected_units must be an integer >= 0")
    order = db.orders.get(run["production_order_id"])
    if order is not None and order["filled_units"] + filled > order["requested_units"]:
        err("ERR_OVER_DELIVERY", 422,
            "Run completion would push order.filled_units above requested_units")
    run["filled_units"] = filled
    run["rejected_units"] = rejected
    run["status"] = "COMPLETED"
    touch(run)
    # Batch RELEASED_TO_FILLING -> CONSUMED with the allocation cascade
    batch = db.batches.get(run["batch_id"])
    if batch is not None and batch["status"] == "RELEASED_TO_FILLING":
        batch["status"] = "CONSUMED"
        consume_batch_allocations(batch)
        touch(batch)
    # Line RUNNING -> CLEANING
    line = db.lines.get(run["line_id"])
    if line is not None and line["status"] == "RUNNING":
        line["status"] = "CLEANING"
        line["current_run_id"] = None
        touch(line)
    if order is not None:
        order["filled_units"] += filled
        touch(order)
        # Auto-complete once filled and the latest LABEL_ARTWORK review is APPROVED
        if (order["status"] == "FILLING"
                and order["filled_units"] >= order["requested_units"]):
            latest_label = latest_review(order["formula_id"], "LABEL_ARTWORK")
            if latest_label is not None and latest_label["status"] == "APPROVED":
                order["status"] = "COMPLETED"
                touch(order)
                customer = db.customers.get(order["customer_id"])
                if customer is not None:
                    customer["outstanding_balance_cents"] = (
                        customer["outstanding_balance_cents"] - order["quote_total_cents"])
                    touch(customer)
    return success(serialize_run(run))


@bp.post("/cosmfg/filling-runs/<rid>/abort")
@require_roles("ProductionPlanner")
def abort_run(rid):
    run = must_get(db.runs, rid, "FillingRun")
    if run["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        err("ERR_INVALID_STATE", 409,
            "Only a SCHEDULED or IN_PROGRESS run may be aborted")
    was_in_progress = run["status"] == "IN_PROGRESS"
    run["status"] = "ABORTED"
    touch(run)
    if was_in_progress:
        # Line RUNNING -> CLEANING; the batch remains RELEASED_TO_FILLING
        line = db.lines.get(run["line_id"])
        if line is not None and line["status"] == "RUNNING":
            line["status"] = "CLEANING"
            line["current_run_id"] = None
            touch(line)
    return success(serialize_run(run))
