"""Position, Worker, PositionAssignment endpoints."""
from flask import Blueprint, request

from errors import ApiError
from serialize import ser_assignment, ser_position, ser_worker
from services import (
    bump, derive_row_status, get_or_404, make_row, position_depth, row_covers,
    subtree_headcount,
)
from store import db
from util import (
    ALL_ROLES, auth, body, clock_date, inv, list_page, new_entity, ok,
    parse_date_val, parse_int_val, req_field,
)

bp = Blueprint("org", __name__)


# ------------------------------------------------------------------ positions
@bp.post("/hris/positions")
def create_position():
    auth(["HrisAnalyst"])
    b = body()
    title = req_field(b, "title")
    department = req_field(b, "department")
    headcount_budget = parse_int_val(req_field(b, "headcount_budget"), "headcount_budget")
    parent_id = b.get("parent_position_id")
    parent = None
    if parent_id is not None:
        if not isinstance(parent_id, str):
            raise inv("Invalid parent_position_id")
        parent = get_or_404(db.positions, parent_id, "ERR_POSITION_NOT_FOUND")
    if headcount_budget < 0:
        raise inv("headcount_budget must be >= 0")
    if parent is not None:
        if parent["status"] != "ACTIVE":
            raise ApiError("ERR_POSITION_NOT_ACTIVE", 409, "Parent position is not ACTIVE")
        if position_depth(parent) + 1 > 10:
            raise ApiError("ERR_HIERARCHY_DEPTH_EXCEEDED", 422,
                           "Resulting reporting chain deeper than 10 levels")
    p = new_entity(db.positions)
    p.update({"title": title, "department": department,
              "parent_position_id": parent_id, "headcount_budget": headcount_budget,
              "status": "ACTIVE"})
    db.positions[p["id"]] = p
    return ok(ser_position(p), code=201)


@bp.get("/hris/positions")
def list_positions():
    auth(ALL_ROLES)
    items = list(db.positions.values())
    parent = request.args.get("parent_position_id")
    if parent is not None:
        items = [p for p in items if p["parent_position_id"] == parent]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_page(items, ser_position)


@bp.get("/hris/positions/<positionId>")
def get_position(positionId):
    auth(ALL_ROLES)
    p = get_or_404(db.positions, positionId, "ERR_POSITION_NOT_FOUND")
    return ok(ser_position(p))


@bp.post("/hris/positions/<positionId>/close")
def close_position(positionId):
    auth(["HrisAnalyst"])
    p = get_or_404(db.positions, positionId, "ERR_POSITION_NOT_FOUND")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_POSITION_NOT_ACTIVE", 409, "Close requires ACTIVE")
    if subtree_headcount(positionId, "FILLED_ONLY") > 0:
        raise ApiError("ERR_POSITION_SUBTREE_OCCUPIED", 409,
                       "Subtree has workers assigned on the current clock date")
    p["status"] = "CLOSED"
    bump(p)
    return ok(ser_position(p))


@bp.get("/hris/positions/<positionId>/subtree-metrics")
def subtree_metrics(positionId):
    auth(ALL_ROLES)
    get_or_404(db.positions, positionId, "ERR_POSITION_NOT_FOUND")
    mode = request.args.get("mode")
    if mode not in ("FILLED_ONLY", "BUDGETED_CAPACITY"):
        raise inv("mode must be FILLED_ONLY or BUDGETED_CAPACITY")
    return ok({"mode": mode, "headcount": subtree_headcount(positionId, mode)})


# -------------------------------------------------------------------- workers
@bp.post("/hris/workers")
def create_worker():
    auth(["HrisAnalyst"])
    b = body()
    legal_name = req_field(b, "legal_name")
    worker_number = req_field(b, "worker_number")
    hire_date = parse_date_val(req_field(b, "hire_date"), "hire_date")
    initial_position_id = req_field(b, "initial_position_id")
    initial_salary = parse_int_val(req_field(b, "initial_salary_cents"), "initial_salary_cents")
    if not isinstance(initial_position_id, str):
        raise inv("Invalid initial_position_id")
    get_or_404(db.positions, initial_position_id, "ERR_POSITION_NOT_FOUND")
    if not isinstance(worker_number, str) or not worker_number:
        raise inv("Invalid worker_number")
    if any(w["worker_number"] == worker_number for w in db.workers.values()):
        raise inv("worker_number must be unique")
    if initial_salary < 0:
        raise inv("initial_salary_cents must be >= 0")
    pay_grade = b.get("initial_pay_grade")
    location_code = b.get("initial_location_code")
    w = new_entity(db.workers)
    w.update({"legal_name": legal_name, "worker_number": worker_number,
              "hire_date": hire_date, "initial_position_id": initial_position_id,
              "initial_salary_cents": initial_salary, "status": "ACTIVE",
              "termination_date": None})
    db.workers[w["id"]] = w
    make_row(w["id"], None, initial_position_id, initial_salary, pay_grade,
             location_code, hire_date, None)
    return ok(ser_worker(w), code=201)


@bp.get("/hris/workers")
def list_workers():
    auth(ALL_ROLES)
    items = list(db.workers.values())
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_page(items, ser_worker)


@bp.get("/hris/workers/<workerId>")
def get_worker(workerId):
    auth(ALL_ROLES)
    w = get_or_404(db.workers, workerId, "ERR_WORKER_NOT_FOUND")
    return ok(ser_worker(w))


@bp.post("/hris/workers/<workerId>/terminate")
def terminate_worker(workerId):
    auth(["HrisAnalyst"])
    w = get_or_404(db.workers, workerId, "ERR_WORKER_NOT_FOUND")
    b = body()
    term = parse_date_val(req_field(b, "termination_date"), "termination_date")
    if term < w["hire_date"]:
        raise inv("termination_date earlier than hire_date")
    if w["status"] != "ACTIVE":
        raise ApiError("ERR_WORKER_NOT_ACTIVE", 409, "Worker is not ACTIVE")
    rows = [r for r in db.assignments.values()
            if r["worker_id"] == w["id"] and r["row_status"] != "VOIDED"]
    for r in rows:
        if row_covers(r, term):
            r["effective_end_date"] = term  # row_status re-derives on next sweep
            bump(r)
        elif r["effective_start_date"] > term:
            r["row_status"] = "VOIDED"
            bump(r)
    w["status"] = "TERMINATED"
    w["termination_date"] = term
    bump(w)
    return ok(ser_worker(w))


@bp.get("/hris/workers/<workerId>/field-history")
def field_history(workerId):
    auth(ALL_ROLES)
    w = get_or_404(db.workers, workerId, "ERR_WORKER_NOT_FOUND")
    field_id = request.args.get("field_id")
    if not field_id:
        raise inv("field_id query parameter is required")
    field = get_or_404(db.data_fields, field_id, "ERR_DATA_FIELD_NOT_FOUND")
    as_of_raw = request.args.get("as_of_date")
    if not as_of_raw:
        raise inv("as_of_date query parameter is required")
    as_of = parse_date_val(as_of_raw, "as_of_date")
    mode = request.args.get("mode")
    if mode not in ("AS_IS", "AS_WAS"):
        raise inv("mode must be AS_IS or AS_WAS")
    base_row = None
    for r in db.assignments.values():
        if r["worker_id"] == w["id"] and r["row_status"] != "VOIDED" and row_covers(r, as_of):
            base_row = r
            break
    if base_row is None:
        return ok({"value": None, "row_id": None, "mode": mode})
    from services import GOV_ATTR
    attr = GOV_ATTR.get(field["field_key"])
    value = base_row[attr] if attr else None
    value_str = None if value is None else str(value)
    if mode == "AS_WAS":
        earliest = None
        for a in db.audit_entries.values():
            if a["action"] != "CORRECT" or a["worker_id"] != w["id"] or \
                    a["field_id"] != field["id"] or not a["change_request_id"]:
                continue
            cr = db.change_requests.get(a["change_request_id"])
            if cr is None or cr["target_row_id"] != base_row["id"]:
                continue
            if earliest is None or (a["created_at"], a["_seq"]) < (earliest["created_at"], earliest["_seq"]):
                earliest = a
        if earliest is not None:
            value_str = earliest["old_value"]
    return ok({"value": value_str, "row_id": base_row["id"], "mode": mode})


# ------------------------------------------------------------- assignments
@bp.get("/hris/position-assignments")
def list_assignments():
    auth(ALL_ROLES)
    items = list(db.assignments.values())
    for key in ("worker_id", "position_id", "change_request_id", "row_status"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r[key] == v]
    return list_page(items, ser_assignment)


@bp.get("/hris/position-assignments/<assignmentId>")
def get_assignment(assignmentId):
    auth(ALL_ROLES)
    r = get_or_404(db.assignments, assignmentId, "ERR_ASSIGNMENT_NOT_FOUND")
    return ok(ser_assignment(r))
