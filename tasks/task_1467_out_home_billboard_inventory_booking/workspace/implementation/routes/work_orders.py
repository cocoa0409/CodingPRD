"""MaintenanceWorkOrder endpoints (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success
from serializers import work_order_out
from util import D, clock_now, req_str, req_enum, opt_str, parse_dt, rhu_places

bp = Blueprint("work_orders", __name__, url_prefix="/api")

ORDER_TYPES = ("ILLUMINATION_OUTAGE", "STRUCTURAL_REPAIR",
               "VEGETATION_CLEARANCE", "POSTING_DAMAGE")


def get_work_order_or_404(wid):
    w = db.work_orders.get(wid)
    if w is None:
        raise ApiError("ERR_WORK_ORDER_NOT_FOUND", 404,
                       "Maintenance work order not found")
    return w


@bp.route("/maintenance-work-orders", methods=["POST"])
def create_work_order():
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    face_id = body.get("face_id")
    if isinstance(face_id, str) and face_id not in db.faces:
        raise ApiError("ERR_FACE_NOT_FOUND", 404, "Face not found")

    face_id = req_str(body, "face_id")
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    description = opt_str(body, "description", default="")

    w = db.new_resource()
    w.update({
        "face_id": face_id,
        "order_type": order_type,
        "description": description,
        "scheduled_start": None,
        "scheduled_end": None,
        "started_at": None,
        "completed_at": None,
        "status": "OPEN",
        "reopen_count": 0,
        "downtime_hours": None,
    })
    db.work_orders[w["id"]] = w
    return success(work_order_out(w), code=201)


def _window_conflicts(face_id, start_dt, end_dt):
    """Half-open [start, end) covers dates date(start)..date(end - 1s)."""
    first = start_dt.date()
    last = (end_dt - timedelta(seconds=1)).date()
    for f in domain.face_flights(face_id):
        if f["status"] in domain.BLOCKING:
            if f["start_date"] <= last and f["end_date"] >= first:
                return True
    return False


@bp.route("/maintenance-work-orders/<wid>", methods=["PUT"])
def update_work_order(wid):
    require_roles("ComplianceOfficer")
    w = get_work_order_or_404(wid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_status = body.get("status")
    allowed_statuses = ("OPEN", "SCHEDULED", "IN_PROGRESS", "COMPLETED",
                        "REOPENED", "CANCELLED")
    if not isinstance(new_status, str) or new_status not in allowed_statuses:
        raise err_invalid_request("status is required and must be a valid "
                                  "work-order status")

    scheduled_start = None
    scheduled_end = None
    if "scheduled_start" in body and body["scheduled_start"] is not None:
        scheduled_start = parse_dt(body["scheduled_start"], "scheduled_start")
    if "scheduled_end" in body and body["scheduled_end"] is not None:
        scheduled_end = parse_dt(body["scheduled_end"], "scheduled_end")

    cur = w["status"]
    face = db.faces.get(w["face_id"])
    now = clock_now()

    if new_status == "SCHEDULED" and cur == "OPEN":
        if scheduled_start is None or scheduled_end is None:
            raise err_invalid_request(
                "Scheduling requires scheduled_start and scheduled_end")
        if not scheduled_end > scheduled_start:
            raise err_invalid_request(
                "scheduled_end must be strictly after scheduled_start")
        if w["order_type"] != "ILLUMINATION_OUTAGE" \
                and _window_conflicts(w["face_id"], scheduled_start,
                                      scheduled_end):
            raise ApiError("ERR_MAINTENANCE_WINDOW_CONFLICT", 409,
                           "The planned window touches dates occupied by a "
                           "booked flight on this face")
        w["scheduled_start"] = scheduled_start
        w["scheduled_end"] = scheduled_end
        w["status"] = "SCHEDULED"
        db.touch(w)
    elif new_status == "IN_PROGRESS" and cur in ("SCHEDULED", "REOPENED"):
        w["started_at"] = now
        w["completed_at"] = None
        w["downtime_hours"] = None
        w["status"] = "IN_PROGRESS"
        db.touch(w)
        if face is not None and face["status"] == "AVAILABLE":
            face["status"] = "UNDER_MAINTENANCE"
            face["booking_posture"] = "RESTRICTED"
            db.touch(face)
    elif new_status == "COMPLETED" and cur == "IN_PROGRESS":
        w["completed_at"] = now
        hours = D(str((now - w["started_at"]).total_seconds())) / D(3600)
        w["downtime_hours"] = float(rhu_places(hours, 2))
        w["status"] = "COMPLETED"
        db.touch(w)
        if face is not None and face["status"] == "UNDER_MAINTENANCE":
            siblings = [x for x in domain.face_work_orders(face["id"])
                        if x["id"] != w["id"] and x["status"] == "IN_PROGRESS"]
            if not siblings:
                face["status"] = "AVAILABLE"
                face["booking_posture"] = "OPEN"
                db.touch(face)
        # ILLUMINATION_OUTAGE revenue side effect (PRD 3.3)
        if w["order_type"] == "ILLUMINATION_OUTAGE" and face is not None \
                and face["illuminated"]:
            span_start = w["started_at"].date()
            span_end = w["completed_at"].date()
            for f in domain.face_flights(face["id"]):
                if f["status"] in ("LIVE", "MISSED", "HOLDOVER"):
                    days = calc.interval_intersect_days(
                        f["start_date"], f["end_date"], span_start, span_end)
                    if days > 0:
                        domain.auto_make_good(
                            f, "ILLUMINATION_OUTAGE",
                            calc.mg_illumination_outage(f, days))
    elif new_status == "REOPENED" and cur == "COMPLETED":
        w["reopen_count"] += 1
        w["status"] = "REOPENED"
        db.touch(w)
    elif new_status == "CANCELLED" and cur in ("OPEN", "SCHEDULED"):
        w["status"] = "CANCELLED"
        db.touch(w)
    else:
        raise err_invalid_state(
            "Work order cannot transition %s -> %s" % (cur, new_status))

    return success(work_order_out(w))
