"""RecalibrationJob: open (OCC-guarded), pass/fail/retry/cancel, list (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
import errors
import response
import validation as V
from errors import ApiError
from middleware import require_roles
from services import helpers as H

bp = Blueprint("recalibration", __name__)

CALIBRATION_BAY_BUFFER_MIN = 15


def _overlap_with_buffer(a_start, a_end, b_start, b_end):
    """A STATIC recalibration window plus a 15-minute clearance buffer on each
    side must not overlap another. Two collide when the gap between them is
    strictly less than 15 minutes (PRD 3.6)."""
    buf = timedelta(minutes=CALIBRATION_BAY_BUFFER_MIN)
    return (a_start - buf) < b_end and b_start < (a_end + buf)


@bp.route("/recalibration-jobs", methods=["POST"])
@require_roles("Technician")
def create_recalibration():
    body = V.get_json()
    work_order_id = V.require_str(body, "work_order_id")
    technician_id = V.require_str(body, "technician_id")
    service_bay_id = V.opt_str(body, "service_bay_id")
    # Existence: work order, technician, then optional bay.
    wo = H.get_work_order(work_order_id)
    tech = H.get_technician(technician_id)
    bay = None
    if service_bay_id is not None:
        bay = H.get_service_bay(service_bay_id)

    calibration_type = V.require_enum(body, "calibration_type", {"STATIC", "DYNAMIC"})
    start_at = V.require_datetime(body, "start_at")
    end_at = V.require_datetime(body, "end_at")
    expected_version = V.require_int(body, "expected_work_order_version")
    if end_at <= start_at:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "end_at must be strictly after start_at.")

    # State: work order must be AWAITING_RECALIBRATION (priority 5, before OCC).
    if wo["status"] != "AWAITING_RECALIBRATION":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Work order is not AWAITING_RECALIBRATION.")

    # OCC (priority 6).
    if expected_version != wo["version"]:
        raise ApiError(errors.ERR_STALE_WORK_ORDER_VERSION, 412,
                       "expected_work_order_version does not match.")

    # Business safety (priority 9): certified tech; STATIC requires a CALIBRATION bay.
    if not tech["adas_certified"]:
        raise ApiError(errors.ERR_TECH_NOT_CERTIFIED, 422, "Technician is not adas_certified.")
    if calibration_type == "STATIC":
        if bay is None or bay["bay_type"] != "CALIBRATION":
            raise ApiError(errors.ERR_TECH_NOT_CERTIFIED, 422,
                           "STATIC calibration requires a CALIBRATION bay.")

    # Bay double-booking (priority 12), STATIC only, same CALIBRATION bay.
    if calibration_type == "STATIC":
        for rj in db.recalibration_jobs.values():
            if rj["status"] == "CANCELLED":
                continue
            if rj["calibration_type"] != "STATIC":
                continue
            if rj["service_bay_id"] != service_bay_id:
                continue
            existing_start = V.parse_iso(rj["start_at"])
            existing_end = V.parse_iso(rj["end_at"])
            if _overlap_with_buffer(start_at, end_at, existing_start, existing_end):
                raise ApiError(errors.ERR_BAY_DOUBLE_BOOKED, 409,
                               "CALIBRATION bay double-booked within the clearance buffer.")

    rj = db.stamp_new({
        "work_order_id": work_order_id,
        "technician_id": technician_id,
        "service_bay_id": service_bay_id,
        "calibration_type": calibration_type,
        "start_at": V.to_iso(start_at),
        "end_at": V.to_iso(end_at),
        "status": "SCHEDULED",
        "expected_work_order_version": expected_version,
    })
    db.recalibration_jobs[rj["id"]] = rj
    # Creation bumps the work order version (so a stale second create is refused).
    db.touch(wo)
    return response.success(H.view(rj), 201)


@bp.route("/recalibration-jobs/<rid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Technician")
def get_recalibration(rid):
    return response.success(H.view(H.get_recalibration(rid)))


@bp.route("/recalibration-jobs", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Technician")
def list_recalibration():
    limit, offset = V.parse_pagination()
    technician_id = request.args.get("technician_id")
    service_bay_id = request.args.get("service_bay_id")
    work_order_id = request.args.get("work_order_id")
    items = list(db.recalibration_jobs.values())
    if technician_id is not None:
        items = [r for r in items if r["technician_id"] == technician_id]
    if service_bay_id is not None:
        items = [r for r in items if r["service_bay_id"] == service_bay_id]
    if work_order_id is not None:
        items = [r for r in items if r["work_order_id"] == work_order_id]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


@bp.route("/recalibration-jobs/<rid>/pass", methods=["POST"])
@require_roles("Technician")
def pass_recalibration(rid):
    rj = H.get_recalibration(rid)
    if rj["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Recalibration is not SCHEDULED.")
    wo = db.work_orders.get(rj["work_order_id"])
    if wo is None or wo["status"] != "AWAITING_RECALIBRATION":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order is not AWAITING_RECALIBRATION.")
    # The acting technician must be adas_certified (priority 9).
    tech = db.technicians.get(g.user_id)
    if tech is None or not tech["adas_certified"]:
        raise ApiError(errors.ERR_TECH_NOT_CERTIFIED, 422,
                       "Acting technician is not adas_certified.")
    rj["status"] = "PASSED"
    db.touch(rj)
    # Bubble-up: work order AWAITING_RECALIBRATION -> CURING.
    wo["status"] = "CURING"
    db.touch(wo)
    return response.success(H.view(rj))


@bp.route("/recalibration-jobs/<rid>/fail", methods=["POST"])
@require_roles("Technician")
def fail_recalibration(rid):
    rj = H.get_recalibration(rid)
    if rj["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Recalibration is not SCHEDULED.")
    wo = db.work_orders.get(rj["work_order_id"])
    if wo is None or wo["status"] != "AWAITING_RECALIBRATION":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order is not AWAITING_RECALIBRATION.")
    rj["status"] = "FAILED"
    db.touch(rj)
    return response.success(H.view(rj))


@bp.route("/recalibration-jobs/<rid>/retry", methods=["POST"])
@require_roles("Technician")
def retry_recalibration(rid):
    rj = H.get_recalibration(rid)
    if rj["status"] != "FAILED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Recalibration is not FAILED.")
    wo = db.work_orders.get(rj["work_order_id"])
    if wo is None or wo["status"] != "AWAITING_RECALIBRATION":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order is not AWAITING_RECALIBRATION.")
    rj["status"] = "SCHEDULED"
    db.touch(rj)
    return response.success(H.view(rj))


@bp.route("/recalibration-jobs/<rid>/cancel", methods=["POST"])
@require_roles("ServiceAdvisor")
def cancel_recalibration(rid):
    rj = H.get_recalibration(rid)
    if rj["status"] not in {"SCHEDULED", "FAILED"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Recalibration is not SCHEDULED or FAILED.")
    rj["status"] = "CANCELLED"
    db.touch(rj)
    return response.success(H.view(rj))
