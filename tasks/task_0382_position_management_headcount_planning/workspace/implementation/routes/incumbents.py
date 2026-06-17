"""Incumbent endpoints: fill (nested under position), vacate, get, list
(PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize, calc
from services.common import (
    get_body, fetch, paginate, base_common_fields, bump,
)
from util import parse_datetime

bp = Blueprint("incumbents", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval [start, end] overlap with inclusive endpoints (PRD §3.4):
    a start_date is the inclusive occupancy start and a vacated end_date is the
    inclusive vacate_date, so two intervals that merely touch at a shared boundary
    instant DO overlap. end == None means an open-ended (still-active) interval.
    Two closed intervals overlap when each starts at or before the other ends."""
    def le(x, y):
        if x is None:
            return False  # open-ended start never occurs here
        if y is None:
            return True   # other side open-ended -> always within its (infinite) end
        return x <= y
    return le(a_start, b_end) and le(b_start, a_end)


@bp.post("/positions/<position_id>/incumbents")
def fill_position(position_id):
    require_auth(["HRBP"])
    pos = fetch(db.positions, position_id)
    body = get_body()

    # Well-formedness (priority 4).
    employee_id = body.get("employee_id")
    if not isinstance(employee_id, str) or employee_id == "":
        raise err("ERR_INVALID_REQUEST", "employee_id is required")
    start_raw = body.get("start_date")
    if start_raw is None:
        raise err("ERR_INVALID_REQUEST", "start_date is required")
    start_dt = parse_datetime(start_raw)
    if start_dt is None:
        raise err("ERR_INVALID_REQUEST", "start_date is malformed")

    # Existence (priority 3): body FK employee.
    emp = fetch(db.employees, employee_id)
    grade = db.grades.get(pos["grade_id"])

    # Fill preconditions (priority 7 frozen, priority 10 business) — ordered per
    # §2.5 / §3.4: NOT_FUNDED, ALREADY_FILLED, FROZEN, EMPLOYEE_UNAVAILABLE,
    # SALARY_OUT_OF_BAND, INCUMBENCY_OVERLAP.
    if pos["lifecycle_status"] != "FUNDED":
        raise err("ERR_POSITION_NOT_FUNDED", "position must be FUNDED to fill")
    if pos["occupancy_status"] != "VACANT":
        raise err("ERR_POSITION_ALREADY_FILLED", "position is already filled")
    if calc.cost_center_posture(pos["cost_center_id"]) == "FROZEN":
        raise err("ERR_COST_CENTER_FROZEN", "owning cost center is frozen")
    if emp["status"] != "AVAILABLE":
        raise err("ERR_EMPLOYEE_UNAVAILABLE", "employee is not AVAILABLE")
    if grade is not None:
        if emp["annual_salary_cents"] < grade["band_min_cents"] or \
                emp["annual_salary_cents"] > grade["band_max_cents"]:
            raise err("ERR_SALARY_OUT_OF_BAND", "salary outside grade band")

    # Overlap against any prior incumbency interval (ACTIVE or VACATED) on this
    # position. New interval is [start_dt, open).
    for inc in db.incumbents.values():
        if inc["position_id"] != position_id:
            continue
        prior_start = parse_datetime(inc["start_date"])
        prior_end = parse_datetime(inc["end_date"]) if inc["end_date"] else None
        if _intervals_overlap(start_dt, None, prior_start, prior_end):
            raise err("ERR_INCUMBENCY_OVERLAP", "incumbency interval overlaps an existing one")

    rec = base_common_fields()
    rec.update({
        "position_id": position_id,
        "employee_id": employee_id,
        "start_date": start_raw,
        "end_date": None,
        "status": "ACTIVE",
    })
    db.incumbents[rec["id"]] = rec

    pos["occupancy_status"] = "FILLED"
    bump(pos)
    emp["status"] = "ASSIGNED"
    bump(emp)
    return success(serialize.incumbent_out(rec), status=201)


@bp.get("/positions/<position_id>/incumbents")
def list_position_incumbents(position_id):
    require_auth(ALL_ROLES)
    fetch(db.positions, position_id)
    records = [i for i in db.incumbents.values() if i["position_id"] == position_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.incumbent_out(r) for r in page], limit, offset, total)


@bp.get("/incumbents/<incumbent_id>")
def get_incumbent(incumbent_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.incumbents, incumbent_id)
    return success(serialize.incumbent_out(rec))


@bp.get("/incumbents")
def list_incumbents():
    require_auth(ALL_ROLES)
    records = list(db.incumbents.values())
    for field in ("employee_id", "position_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.incumbent_out(r) for r in page], limit, offset, total)


@bp.post("/incumbents/<incumbent_id>/vacate")
def vacate_incumbent(incumbent_id):
    require_auth(["HRBP"])
    inc = fetch(db.incumbents, incumbent_id)
    body = get_body()
    vacate_raw = body.get("vacate_date")
    if vacate_raw is None:
        raise err("ERR_INVALID_REQUEST", "vacate_date is required")
    if parse_datetime(vacate_raw) is None:
        raise err("ERR_INVALID_REQUEST", "vacate_date is malformed")

    pos = db.positions.get(inc["position_id"])

    # State (priority 6): position FILLED and incumbency ACTIVE.
    if pos is None or pos["occupancy_status"] != "FILLED" or inc["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "position not FILLED or incumbency not ACTIVE")

    inc["status"] = "VACATED"
    inc["end_date"] = vacate_raw
    bump(inc)
    pos["occupancy_status"] = "VACANT"
    bump(pos)
    emp = db.employees.get(inc["employee_id"])
    if emp is not None:
        emp["status"] = "AVAILABLE"
        bump(emp)
    return success(serialize.incumbent_out(inc))
