from flask import Blueprint, request

from db import CLOCK, db, new_entity, public, touch
from errors import ApiError
from logic import (compute_changeover_needs, compute_introduced,
                   covering_changeover, get_or_404, intervals_overlap)
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from util import body, parse_dt, req_dt_str, req_int, req_str

bp = Blueprint("runs", __name__)

COVERING_STATES = ("PLANNED", "IN_EXECUTION", "SWAB_PENDING",
                   "REWORK_REQUIRED", "VALIDATED")


def _overlap_check(line_id, start, end, exclude_id=None):
    for r in db["runs"].values():
        if r["id"] == exclude_id:
            continue
        if r["line_id"] != line_id:
            continue
        if r["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if intervals_overlap(start, end,
                             parse_dt(r["planned_start_utc"]),
                             parse_dt(r["planned_end_utc"])):
            raise ApiError("ERR_RUN_OVERLAP", 409,
                           "Run interval overlaps another scheduled/in-progress run on this line")


@bp.post("/qa/production-runs")
@require_roles("QaSupervisor")
def create_run():
    b = body()
    line_id = req_str(b, "line_id")
    product_id = req_str(b, "product_id")
    start_s = req_dt_str(b, "planned_start_utc")
    end_s = req_dt_str(b, "planned_end_utc")
    line = get_or_404("lines", line_id)
    product = get_or_404("products", product_id)
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    # Optimistic preview: SCHEDULED runs count toward the baseline.
    introduced = compute_introduced(line["id"], product, optimistic=True)
    required, minutes = compute_changeover_needs(line, introduced)
    _overlap_check(line["id"], start, end)
    if not end > start:
        raise ApiError("ERR_INVALID_TIME_RANGE", 400,
                       "planned_end_utc must be strictly greater than planned_start_utc")
    ent = new_entity({
        "line_id": line["id"],
        "product_id": product["id"],
        "planned_start_utc": start_s,
        "planned_end_utc": end_s,
        "introduced_allergens": introduced,
        "changeover_required": required,
        "scheduled_changeover_minutes": minutes,
        "label_revision_snapshot": product["label_revision"],
        "status": "DRAFT",
    })
    db["runs"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/production-runs")
@require_roles(*ALL_ROLES)
def list_runs():
    line_id = request.args.get("line_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = list(db["runs"].values())
    if line_id is not None:
        items = [r for r in items if r["line_id"] == line_id]
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return ok_list(items)


@bp.get("/qa/production-runs/<runId>")
@require_roles(*ALL_ROLES)
def get_run(runId):
    return ok(public(get_or_404("runs", runId)))


@bp.post("/qa/production-runs/<runId>/schedule")
@require_roles("QaSupervisor")
def schedule_run(runId):
    b = body()
    run = get_or_404("runs", runId)
    expected = req_int(b, "expected_line_version")
    line = get_or_404("lines", run["line_id"])
    if expected != line["version"]:
        raise ApiError("ERR_STALE_LINE_VERSION", 412,
                       "expected_line_version does not match the line's current version")
    if run["status"] != "DRAFT":
        raise ApiError("ERR_RUN_NOT_DRAFT", 409, "Run is not in DRAFT")
    product = get_or_404("products", run["product_id"])
    if not product["is_active"]:
        raise ApiError("ERR_PRODUCT_INACTIVE", 422, "Product is inactive")
    if line["posture"] != "OPEN":
        raise ApiError("ERR_LINE_NOT_OPEN", 409, "Line posture is not OPEN")
    # Gate reads the run's stored changeover_required (the optimistic value
    # pinned at creation); the strict recompute below is an on-success effect.
    if run["changeover_required"] and covering_changeover(run["id"], COVERING_STATES) is None:
        raise ApiError("ERR_CHANGEOVER_MISSING", 409,
                       "changeover_required run lacks a covering changeover")
    # Strict variant: only COMPLETED / IN_PROGRESS runs form the baseline.
    introduced = compute_introduced(line["id"], product, optimistic=False)
    required, minutes = compute_changeover_needs(line, introduced)
    _overlap_check(line["id"], parse_dt(run["planned_start_utc"]),
                   parse_dt(run["planned_end_utc"]), exclude_id=run["id"])
    run["introduced_allergens"] = introduced
    run["changeover_required"] = required
    run["scheduled_changeover_minutes"] = minutes
    run["status"] = "SCHEDULED"
    touch(run)
    touch(line)
    return ok(public(run))


@bp.post("/qa/production-runs/<runId>/unschedule")
@require_roles("QaSupervisor")
def unschedule_run(runId):
    run = get_or_404("runs", runId)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_NOT_SCHEDULED", 409, "Run is not in SCHEDULED")
    run["status"] = "DRAFT"
    run["introduced_allergens"] = []
    run["changeover_required"] = False
    run["scheduled_changeover_minutes"] = 0
    touch(run)
    return ok(public(run))


@bp.post("/qa/production-runs/<runId>/start")
@require_roles("LineOperator")
def start_run(runId):
    run = get_or_404("runs", runId)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_NOT_SCHEDULED", 409, "Run is not in SCHEDULED")
    line = get_or_404("lines", run["line_id"])
    if line["posture"] != "OPEN":
        raise ApiError("ERR_LINE_NOT_OPEN", 409, "Line posture is not OPEN")
    cov = None
    if run["changeover_required"]:
        cov = covering_changeover(run["id"], ("VALIDATED",))
        if cov is None:
            raise ApiError("ERR_CHANGEOVER_NOT_VALIDATED", 409,
                           "Covering changeover is not VALIDATED")
    if CLOCK["current"] < parse_dt(run["planned_start_utc"]):
        raise ApiError("ERR_RUN_NOT_DUE", 409,
                       "Logical clock has not reached planned_start_utc")
    run["status"] = "IN_PROGRESS"
    touch(run)
    if cov is not None:
        line["last_validated_changeover_id"] = cov["id"]
        touch(line)
    return ok(public(run))


@bp.post("/qa/production-runs/<runId>/complete")
@require_roles("LineOperator")
def complete_run(runId):
    run = get_or_404("runs", runId)
    if run["status"] != "IN_PROGRESS":
        raise ApiError("ERR_RUN_NOT_IN_PROGRESS", 409, "Run is not in IN_PROGRESS")
    for rec in db["recons"].values():
        if rec["run_id"] != run["id"]:
            continue
        if not (rec["verdict"] == "MATCH" or rec["status"] == "RESOLVED"):
            raise ApiError("ERR_LABEL_RECONCILIATION_OPEN", 409,
                           "An unresolved non-MATCH label reconciliation blocks completion")
    run["status"] = "COMPLETED"
    touch(run)
    return ok(public(run))


@bp.post("/qa/production-runs/<runId>/reject")
@require_roles("QaSupervisor")
def reject_run(runId):
    run = get_or_404("runs", runId)
    if run["status"] != "DRAFT":
        raise ApiError("ERR_RUN_NOT_DRAFT", 409, "Run is not in DRAFT")
    run["status"] = "REJECTED"
    touch(run)
    return ok(public(run))


@bp.post("/qa/production-runs/<runId>/cancel")
@require_roles("QaSupervisor")
def cancel_run(runId):
    run = get_or_404("runs", runId)
    if run["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_RUN_NOT_CANCELLABLE", 409,
                       "Run is not in DRAFT or SCHEDULED")
    was = run["status"]
    run["status"] = "CANCELLED"
    touch(run)
    for c in db["changeovers"].values():
        if c["to_run_id"] != run["id"]:
            continue
        cancellable = c["status"] == "PLANNED" or (
            was == "SCHEDULED" and c["status"] == "IN_EXECUTION")
        if not cancellable:
            continue
        if c["status"] == "IN_EXECUTION":
            for s in db["swabs"].values():
                if s["changeover_id"] == c["id"] and s["outcome"] != "INVALIDATED":
                    s["outcome"] = "INVALIDATED"
                    s["invalidated_reason"] = "CHANGEOVER_CANCELLED"
                    touch(s)
        c["status"] = "CANCELLED"
        touch(c)
    return ok(public(run))
