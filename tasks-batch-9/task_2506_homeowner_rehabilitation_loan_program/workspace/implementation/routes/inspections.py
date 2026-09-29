"""Property standards, draw and final inspections (PRD 3.2, 3.7)."""

from flask import Blueprint

import clock
import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import calc, serializers
from services import constants as C

bp = Blueprint("inspections", __name__)

READ_ROLES = middleware.STAFF_ROLES


@bp.post(API_PREFIX + "/inspections")
@middleware.roles(middleware.INSPECTOR)
def create_inspection():
    body = validation.json_body()
    application = validation.body_fk(
        body, "application_id", db.applications, errors.ERR_APPLICATION_NOT_FOUND
    )
    validation.field_id(body, "application_id")
    draw = validation.body_fk(
        body, "draw_request_id", db.draw_requests, errors.ERR_DRAW_NOT_FOUND
    )

    inspection_type = validation.field_enum(body, "inspection_type", C.INSPECTION_TYPES)
    start = validation.field_datetime(body, "scheduled_start_at")
    end = validation.field_datetime(body, "scheduled_end_at")
    if end <= start:
        fail(
            errors.ERR_INVALID_REQUEST,
            "Field 'scheduled_end_at' must be strictly after 'scheduled_start_at'.",
        )
    if inspection_type == "DRAW" and draw is None:
        fail(errors.ERR_INVALID_REQUEST, "Field 'draw_request_id' is required for a DRAW visit.")
    if inspection_type != "DRAW" and draw is not None:
        fail(
            errors.ERR_INVALID_REQUEST,
            "Field 'draw_request_id' is only accepted for a DRAW visit.",
        )

    if application["ownership_verification_status"] != "VERIFIED":
        fail(errors.ERR_OWNERSHIP_NOT_VERIFIED)

    for existing in db.inspections.values():
        if existing["application_id"] != application["id"]:
            continue
        if existing["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if start < existing["scheduled_end_at"] and existing["scheduled_start_at"] < end:
            fail(errors.ERR_INSPECTION_WINDOW_CONFLICT)

    row = db.new_row()
    row.update(
        {
            "application_id": application["id"],
            "draw_request_id": draw["id"] if draw else None,
            "inspection_type": inspection_type,
            "scheduled_start_at": start,
            "scheduled_end_at": end,
            "performed_by_user_id": middleware.user_id(),
            "status": "SCHEDULED",
            "result": None,
            "deficiency_count": 0,
            "xrf_reading_mg_cm2": None,
            "lead_hazard_present": False,
        }
    )
    db.inspections[row["id"]] = row
    return response.object_response(serializers.inspection(row), 201)


@bp.post(API_PREFIX + "/inspections/<inspection_id>/record-result")
@middleware.roles(middleware.INSPECTOR)
def record_result(inspection_id):
    row = validation.path_row(db.inspections, inspection_id, errors.ERR_INSPECTION_NOT_FOUND)
    body = validation.json_body()
    result = validation.field_enum(body, "result", C.INSPECTION_RESULTS)
    deficiency_count = validation.field_int(body, "deficiency_count", minimum=0)
    xrf = validation.field_number(
        body, "xrf_reading_mg_cm2", required=False, default=None, minimum=0
    )

    if row["status"] != "SCHEDULED":
        fail(errors.ERR_INVALID_STATE, "The inspection finding has already been recorded.")
    if row["performed_by_user_id"] != middleware.user_id():
        fail(
            errors.ERR_INVALID_STATE,
            "Only the inspector who reserved the visit may record its result.",
        )

    row["status"] = "COMPLETED"
    row["result"] = result
    row["deficiency_count"] = deficiency_count
    row["xrf_reading_mg_cm2"] = xrf
    hazard = xrf is not None and calc.Decimal(str(xrf)) >= calc.Decimal(C.XRF_HAZARD_THRESHOLD)
    row["lead_hazard_present"] = bool(hazard)
    db.touch(row)

    application = db.applications.get(row["application_id"])
    if row["inspection_type"] == "INITIAL_STANDARDS" and application is not None:
        changed = False
        if hazard and not application["lead_hazard_detected"]:
            application["lead_hazard_detected"] = True
            changed = True
        if application["workflow_state"] == "OWNERSHIP_VERIFIED":
            application["initial_deficiency_count"] = deficiency_count
            application["workflow_state"] = (
                "INSPECTED" if deficiency_count >= 1 else "DENIED"
            )
            changed = True
        if changed:
            db.touch(application)

    if row["inspection_type"] == "DRAW" and row["draw_request_id"]:
        draw = db.draw_requests.get(row["draw_request_id"])
        if draw is not None:
            if result == "PASS" and draw["status"] in ("SUBMITTED", "INSPECTION_FAILED"):
                draw["status"] = "INSPECTION_PASSED"
                db.touch(draw)
            elif result == "FAIL" and draw["status"] == "SUBMITTED":
                draw["status"] = "INSPECTION_FAILED"
                db.touch(draw)

    return response.object_response(serializers.inspection(row))


@bp.get(API_PREFIX + "/inspections/<inspection_id>")
@middleware.roles(*READ_ROLES)
def read_inspection(inspection_id):
    row = validation.path_row(db.inspections, inspection_id, errors.ERR_INSPECTION_NOT_FOUND)
    return response.object_response(serializers.inspection(row))


@bp.get(API_PREFIX + "/inspections")
@middleware.roles(*READ_ROLES)
def list_inspections():
    application_id = validation.filter_str("application_id")
    draw_request_id = validation.filter_str("draw_request_id")
    inspection_type = validation.filter_enum("inspection_type", C.INSPECTION_TYPES)
    status = validation.filter_enum("status", C.INSPECTION_STATUSES)
    rows = []
    for row in db.inspections.values():
        if application_id is not None and row["application_id"] != application_id:
            continue
        if draw_request_id is not None and row["draw_request_id"] != draw_request_id:
            continue
        if inspection_type is not None and row["inspection_type"] != inspection_type:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.inspection)
