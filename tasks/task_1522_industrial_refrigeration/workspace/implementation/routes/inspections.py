"""Mechanical-integrity inspections: scheduling, completion with PASS/FAIL,
the next-due-date variants, and the FAIL -> permit-suspend cascade (PRD 3.3)."""
from flask import Blueprint

import calc
import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    opt_present,
    opt_string,
    paginate,
    pagination,
    path_row,
    req_enum,
    req_instant,
)
from serialize import inspection_out
from store import db, sorted_rows, touch

bp = Blueprint("inspections", __name__)

CREATE_SCHEMA = (
    frozenset(["equipment_id", "due_at"]),
    frozenset(["equipment_id", "due_at"]),
)
COMPLETE_SCHEMA = (
    frozenset(["result", "findings"]),
    frozenset(["result"]),
)

STATUS_VALUES = ("SCHEDULED", "OVERDUE", "COMPLETED")


@bp.post("/psm/inspections")
@endpoint(["MaintenanceLead"], schema=CREATE_SCHEMA)
def schedule_inspection(ctx):
    due_at = req_instant(ctx.body, "due_at")
    equipment = body_row(ctx.body, "equipment", "equipment_id")
    row = db.create(
        "inspections",
        {
            "equipment_id": equipment["id"],
            "due_at": due_at,
            "status": "SCHEDULED",
            "result": None,
            "findings": None,
            "completed_at": None,
            "completed_late": False,
        },
    )
    return envelope.created(inspection_out(row))


@bp.get("/psm/inspections/<inspection_id>")
@endpoint(ALL_ROLES)
def get_inspection(ctx, inspection_id):
    return envelope.ok(inspection_out(path_row("inspections", inspection_id)))


@bp.get("/psm/inspections")
@endpoint(ALL_ROLES)
def list_inspections(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.inspections.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("equipment_id", "equipment_id", None),
            ("status", "status", STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [inspection_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/inspections/<inspection_id>/complete")
@endpoint(["MaintenanceLead"], schema=COMPLETE_SCHEMA)
def complete_inspection(ctx, inspection_id):
    # step 0 -- payload values
    result = req_enum(ctx.body, "result", "inspection_result")
    findings = opt_string(ctx.body, "findings")
    # step 3 -- existence
    inspection = path_row("inspections", inspection_id)
    # step 5 -- completion is accepted from SCHEDULED or OVERDUE only
    if inspection["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE")

    now = db.now()
    was_overdue = inspection["status"] == "OVERDUE"
    inspection["status"] = "COMPLETED"
    inspection["result"] = result
    if findings is not None:
        inspection["findings"] = findings
    inspection["completed_at"] = now
    inspection["completed_late"] = was_overdue
    touch(inspection)

    # Equipment absorbs the outcome and recomputes its next due date.
    equipment = db.equipment.get(inspection["equipment_id"])
    if equipment is not None:
        equipment["last_completed_at"] = now
        equipment["last_result"] = result
        equipment["next_due_at"] = calc.next_due_at(equipment, now, result)
        touch(equipment)

        # FAIL safety cascade: suspend the system's active hot work permits.
        if result == "FAIL":
            for permit in db.hot_work_permits.values():
                if (
                    permit["system_id"] == equipment["system_id"]
                    and permit["status"] in ("ISSUED", "IN_PROGRESS")
                ):
                    permit["status"] = "SUSPENDED"
                    touch(permit)
    return envelope.ok(inspection_out(inspection))
