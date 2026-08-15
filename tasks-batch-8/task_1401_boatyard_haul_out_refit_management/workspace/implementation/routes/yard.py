"""Yard rows and stand assignments (PRD 3.4)."""

from flask import Blueprint, request

import db
import response
from errors import (
    not_found, validation, invalid_state, already_terminal, stale, ApiError,
    ERR_STANDS_EXHAUSTED,
)
from middleware import require_roles
from services import lifecycle
from services.overlap import stands_capacity_exceeded
from validation import (
    get_body, req_str, req_int, req_date, parse_pagination, page,
)
from .jobs import get_job_or_404

bp = Blueprint("yard", __name__)

# Job states in which a stand assignment may be created.
ASSIGNABLE_JOB_STATES = ("INTAKE", "HAUL_SCHEDULED", "ON_HARD", "WORK_IN_PROGRESS")


def get_row_or_404(row_id):
    row = db.rows.get(row_id)
    if row is None:
        raise not_found(f"YardRow '{row_id}' does not exist")
    return row


def get_assignment_or_404(asn_id):
    asn = db.assignments.get(asn_id)
    if asn is None:
        raise not_found(f"StandAssignment '{asn_id}' does not exist")
    return asn


@bp.post("/yard/yard-rows")
@require_roles("YardManager")
def create_row():
    body = get_body()
    code = req_str(body, "code")
    total_stands = req_int(body, "total_stands", gt=0)
    for r in db.rows.values():
        if r["code"] == code:
            raise validation(f"YardRow code '{code}' is already in use")
    now = db.now_iso()
    row = {
        "id": db.new_id(),
        "code": code,
        "total_stands": total_stands,
        "stands_in_use": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.rows[row["id"]] = row
    return response.success_object(db.pub(row), status=201)


@bp.get("/yard/yard-rows/<rowId>")
@require_roles("YardManager", "ServiceWriter")
def get_row(rowId):
    return response.success_object(db.pub(get_row_or_404(rowId)))


@bp.post("/yard/stand-assignments")
@require_roles("YardManager")
def create_assignment():
    body = get_body()
    row_id = req_str(body, "row_id")
    row = get_row_or_404(row_id)
    job_id = req_str(body, "job_id")
    job = get_job_or_404(job_id)
    stands_used = req_int(body, "stands_used", gt=0)
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    if end_date < start_date:
        raise validation("end_date must not precede start_date")
    expected = body.get("expected_yard_row_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("Field 'expected_yard_row_version' is required and must be an integer")

    # OCC (gate 6) precedes state legality (gate 7) and capacity (gate 13).
    if expected != row["version"]:
        raise stale("expected_yard_row_version does not match the row's current version")
    if job["status"] not in ASSIGNABLE_JOB_STATES:
        raise invalid_state(
            f"Stands may be assigned only while the job is INTAKE, HAUL_SCHEDULED, "
            f"ON_HARD, or WORK_IN_PROGRESS (job is {job['status']})")
    if stands_capacity_exceeded(row, start_date, end_date, stands_used):
        raise ApiError(ERR_STANDS_EXHAUSTED, 409,
                       "Projected occupancy plus requested stands exceeds total_stands")

    now = db.now_iso()
    asn = {
        "id": db.new_id(),
        "row_id": row["id"],
        "job_id": job["id"],
        "stands_used": stands_used,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "_start_date": start_date,
        "_end_date": end_date,
    }
    db.assignments[asn["id"]] = asn
    row["stands_in_use"] += stands_used
    db.touch(row)
    return response.success_object(db.pub(asn), status=201)


@bp.get("/yard/stand-assignments/<assignmentId>")
@require_roles("YardManager", "ServiceWriter")
def get_assignment(assignmentId):
    return response.success_object(db.pub(get_assignment_or_404(assignmentId)))


@bp.get("/yard/stand-assignments")
@require_roles("YardManager", "ServiceWriter")
def list_assignments():
    limit, offset = parse_pagination()
    row_id = request.args.get("row_id")
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    items = list(db.assignments.values())
    if row_id is not None:
        items = [a for a in items if a["row_id"] == row_id]
    if job_id is not None:
        items = [a for a in items if a["job_id"] == job_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.post("/yard/stand-assignments/<assignmentId>/release")
@require_roles("YardManager")
def release_assignment(assignmentId):
    asn = get_assignment_or_404(assignmentId)
    if asn["status"] == "RELEASED":
        raise already_terminal("StandAssignment is already RELEASED")
    lifecycle.release_assignment(asn)
    return response.success_object(db.pub(asn))
