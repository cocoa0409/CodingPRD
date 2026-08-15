"""PressApproval endpoints (PRD §3.4): submit, brand decision, resubmit loop."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_COLOR_STANDARD_NOT_ACTIVE,
    ERR_CUSTOMER_OWNERSHIP_MISMATCH,
    ERR_DELTA_E_EXCEEDED,
    ERR_INK_SLOT_MISMATCH,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    req_int,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("press_approvals", __name__)


@bp.post("/plant/press-approvals")
def create_press_approval():
    authenticate(("PressOperator",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")
    fk_exists(db.color_standards, data, "color_standard_id")

    job_id = req_str(data, "job_id")
    color_standard_id = req_str(data, "color_standard_id")
    ink_slot = req_str(data, "ink_slot")
    measured_delta_e_milli = req_int(data, "measured_delta_e_milli", 0)

    job = db.jobs[job_id]
    standard = db.color_standards[color_standard_id]

    if standard["status"] != "ACTIVE":
        raise ApiError(ERR_COLOR_STANDARD_NOT_ACTIVE, 409,
                       "Color standard %s is not ACTIVE" % color_standard_id)
    if (ink_slot != standard["ink_slot"]
            or ink_slot not in job["required_ink_slots"]
            or standard["customer_id"] != job["customer_id"]):
        raise ApiError(ERR_INK_SLOT_MISMATCH, 409,
                       "ink_slot disagrees with the standard or the job's requirements")

    rec = db.new_record()
    rec.update({
        "job_id": job_id,
        "color_standard_id": color_standard_id,
        "ink_slot": ink_slot,
        "measured_delta_e_milli": measured_delta_e_milli,
        "submission_index": 1,
        "status": "SUBMITTED",
    })
    db.press_approvals[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/press-approvals")
def list_press_approvals():
    authenticate(ALL_ROLES)
    return list_response(
        db.press_approvals.values(),
        ser_plain,
        [("job_id", "job_id", "str"),
         ("color_standard_id", "color_standard_id", "str"),
         ("status", "status", "str")],
    )


@bp.get("/plant/press-approvals/<approvalId>")
def get_press_approval(approvalId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.press_approvals, approvalId)))


def _brand_decide(approvalId):
    """Shared pipeline for approve/reject: auth, existence, ownership, state."""
    user_id, _role = authenticate(("BrandQuality",))
    rec = get_or_404(db.press_approvals, approvalId)
    job = db.jobs[rec["job_id"]]
    if user_id != job["customer_id"]:
        raise ApiError(ERR_CUSTOMER_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the job's customer_id")
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a SUBMITTED approval can be decided")
    return rec


@bp.post("/plant/press-approvals/<approvalId>/approve")
def approve_press_approval(approvalId):
    rec = _brand_decide(approvalId)
    standard = db.color_standards[rec["color_standard_id"]]
    if rec["measured_delta_e_milli"] > standard["tolerance_delta_e_milli"]:
        raise ApiError(ERR_DELTA_E_EXCEEDED, 409,
                       "measured delta-E %d exceeds tolerance %d"
                       % (rec["measured_delta_e_milli"],
                          standard["tolerance_delta_e_milli"]))
    rec["status"] = "APPROVED"
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/press-approvals/<approvalId>/reject")
def reject_press_approval(approvalId):
    rec = _brand_decide(approvalId)
    rec["status"] = "REJECTED"
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/press-approvals/<approvalId>/resubmit")
def resubmit_press_approval(approvalId):
    authenticate(("PressOperator",))
    rec = get_or_404(db.press_approvals, approvalId)
    data = get_body()
    measured_delta_e_milli = req_int(data, "measured_delta_e_milli", 0)
    if rec["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a REJECTED approval can be resubmitted")
    rec["measured_delta_e_milli"] = measured_delta_e_milli
    rec["submission_index"] += 1
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok_object(ser_plain(rec))
