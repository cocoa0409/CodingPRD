"""Employees and training records (PRD 3.5)."""
from flask import Blueprint

import envelope
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    opt_enum,
    paginate,
    pagination,
    path_row,
    req_enum,
    req_instant,
    req_string,
)
from serialize import employee_out, training_out
from store import db, sorted_rows
from util import add_days

bp = Blueprint("people", __name__)

EMPLOYEE_SCHEMA = (
    frozenset(["facility_id", "full_name", "employment_status"]),
    frozenset(["facility_id", "full_name"]),
)
TRAINING_SCHEMA = (
    frozenset(["employee_id", "topic", "completed_at"]),
    frozenset(["employee_id", "topic", "completed_at"]),
)

TRAINING_VALID_DAYS = 1095  # 3-year refresher cycle


@bp.post("/psm/employees")
@endpoint(["FacilityAdmin"], schema=EMPLOYEE_SCHEMA)
def create_employee(ctx):
    full_name = req_string(ctx.body, "full_name")
    status = opt_enum(ctx.body, "employment_status", "ACTIVE")
    facility = body_row(ctx.body, "facilities", "facility_id")
    row = db.create(
        "employees",
        {
            "facility_id": facility["id"],
            "full_name": full_name,
            "employment_status": status,
        },
    )
    return envelope.created(employee_out(row))


@bp.get("/psm/employees/<employee_id>")
@endpoint(ALL_ROLES)
def get_employee(ctx, employee_id):
    return envelope.ok(employee_out(path_row("employees", employee_id)))


@bp.get("/psm/employees")
@endpoint(ALL_ROLES)
def list_employees(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.employees.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("facility_id", "facility_id", None),
            ("employment_status", "employment_status", ("ACTIVE", "INACTIVE")),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [employee_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/training-records")
@endpoint(["PsCoordinator"], schema=TRAINING_SCHEMA)
def create_training(ctx):
    topic = req_enum(ctx.body, "topic")
    completed_at = req_instant(ctx.body, "completed_at")
    employee = body_row(ctx.body, "employees", "employee_id")
    row = db.create(
        "training_records",
        {
            "employee_id": employee["id"],
            "topic": topic,
            "completed_at": completed_at,
            "expires_at": add_days(completed_at, TRAINING_VALID_DAYS),
        },
    )
    return envelope.created(training_out(row))


@bp.get("/psm/training-records/<record_id>")
@endpoint(ALL_ROLES)
def get_training(ctx, record_id):
    return envelope.ok(training_out(path_row("training_records", record_id)))


@bp.get("/psm/training-records")
@endpoint(ALL_ROLES)
def list_training(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.training_records.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("employee_id", "employee_id", None),
            ("topic", "topic", ("PSM_OVERVIEW", "AMMONIA_OPERATOR", "EMERGENCY_RESPONSE")),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [training_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )
