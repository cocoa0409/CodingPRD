"""The inspection program: scheduling and result recording (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import constants as C
import serialization as ser
from db import D, base_row, db, now
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    collection_filtered,
    require_assigned_inspector,
    require_permit_status,
    require_state,
)
from validation import (
    authorize,
    datetime_field,
    enum_field,
    get_body,
    lookup,
    number_field,
    resolve,
    str_field,
)

bp = Blueprint("inspections", __name__)

LIST_FILTERS = [
    ("permit_id", "permit_id", None),
    ("inspector_id", "inspector_id", None),
    ("status", "status", C.INSPECTION_STATUSES),
    ("inspection_type", "inspection_type", C.INSPECTION_TYPES),
]


@bp.post("/mining/inspections")
def create_inspection():
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    permit_id = str_field(body, "permit_id")
    inspector_id = str_field(body, "inspector_id")
    inspection_type = enum_field(body, "inspection_type", C.INSPECTION_TYPES)
    scheduled_start = datetime_field(body, "scheduled_start")
    duration_hours = number_field(body, "duration_hours", gt=0)

    # Band 5 — permit first, then the inspector.
    permit = resolve(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    resolve(db.inspector_profiles, inspector_id, "ERR_INSPECTOR_PROFILE_NOT_FOUND")

    # Band 10.
    require_permit_status(permit, C.PERMIT_STATUSES_INSPECTION)

    scheduled_end = scheduled_start + timedelta(seconds=float(D(duration_hours) * 3600))

    # Band 15 — an inspector's calendar is exclusive; abutment is allowed.
    for other in db.inspections.values():
        if other["inspector_id"] != inspector_id or other["status"] != "SCHEDULED":
            continue
        if scheduled_start < other["scheduled_end"] and other["scheduled_start"] < scheduled_end:
            raise ApiError(
                "ERR_INSPECTOR_DOUBLE_BOOKED",
                "The inspector already has a scheduled inspection overlapping this window.",
            )

    row = base_row()
    row.update(
        {
            "permit_id": permit_id,
            "inspector_id": inspector_id,
            "inspection_type": inspection_type,
            "scheduled_start": scheduled_start,
            "duration_hours": duration_hours,
            "scheduled_end": scheduled_end,
            "status": "SCHEDULED",
            "result": None,
            "findings_note": None,
            "completed_at": None,
        }
    )
    db.inspections[row["id"]] = row
    return created_response(ser.inspection_out(row))


@bp.get("/mining/inspections/<inspection_id>")
def get_inspection(inspection_id):
    authorize(C.ALL_ROLES)
    row = lookup(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    return object_response(ser.inspection_out(row))


@bp.get("/mining/inspections")
def list_inspections():
    authorize(C.ALL_ROLES)
    return collection_filtered(db.inspections.values(), LIST_FILTERS, ser.inspection_out)


@bp.post("/mining/inspections/<inspection_id>/record-result")
def record_result(inspection_id):
    user_id, role = authorize([C.ROLE_INSPECTOR])
    body = get_body()
    result = enum_field(body, "result", C.INSPECTION_RESULTS)
    findings_note = str_field(body, "findings_note")

    row = lookup(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")

    # Band 6, then band 9.
    require_assigned_inspector(role, user_id, row)
    require_state(row, "status", ["SCHEDULED"], "ERR_INSPECTION_STATE_INVALID")

    row["status"] = "COMPLETED"
    row["result"] = result
    row["findings_note"] = findings_note
    row["completed_at"] = now()
    bump(row)
    return object_response(ser.inspection_out(row))
