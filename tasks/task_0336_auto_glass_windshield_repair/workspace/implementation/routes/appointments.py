"""ServiceAppointment: book, fetch, list, check-in, cancel (PRD 3.4-3.5)."""
from flask import Blueprint, request

import db
import errors
import response
import validation as V
from errors import ApiError
from middleware import require_roles
from services import helpers as H

bp = Blueprint("appointments", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) point overlap. Back-to-back (one ends where the
    next begins) does NOT overlap (PRD 3.4)."""
    return a_start < b_end and b_start < a_end


@bp.route("/service-appointments", methods=["POST"])
@require_roles("ServiceAdvisor")
def create_appointment():
    body = V.get_json()
    work_order_id = V.require_str(body, "work_order_id")
    technician_id = V.require_str(body, "technician_id")
    service_bay_id = V.opt_str(body, "service_bay_id")
    # Existence: work order, technician, then optional bay (FK left-to-right).
    wo = H.get_work_order(work_order_id)
    tech = H.get_technician(technician_id)
    bay = None
    if service_bay_id is not None:
        bay = H.get_service_bay(service_bay_id)

    service_location = V.require_enum(body, "service_location", {"MOBILE", "IN_SHOP"})
    start_at = V.require_datetime(body, "start_at")
    end_at = V.require_datetime(body, "end_at")
    if end_at <= start_at:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "end_at must be strictly after start_at.")

    # Business constraints. Priority 11 (double-booked) before priority 13
    # (mobile tech unavailable) per validation table ordering.
    for appt in db.service_appointments.values():
        if appt["technician_id"] != technician_id:
            continue
        if appt["status"] == "CANCELLED":
            continue
        existing_start = V.parse_iso(appt["start_at"])
        existing_end = V.parse_iso(appt["end_at"])
        if _intervals_overlap(start_at, end_at, existing_start, existing_end):
            raise ApiError(errors.ERR_TECHNICIAN_DOUBLE_BOOKED, 409,
                           "Technician already booked in this window.")

    if service_location == "MOBILE":
        customer = db.customers[wo["customer_id"]]
        if not tech["can_mobile"] or tech["home_state"] != customer["service_address_state"]:
            raise ApiError(errors.ERR_MOBILE_TECH_UNAVAILABLE, 422,
                           "Technician not available for mobile work in the customer's state.")

    appt = db.stamp_new({
        "work_order_id": work_order_id,
        "technician_id": technician_id,
        "service_bay_id": service_bay_id,
        "service_location": service_location,
        "start_at": V.to_iso(start_at),
        "end_at": V.to_iso(end_at),
        "status": "BOOKED",
    })
    db.service_appointments[appt["id"]] = appt
    return response.success(H.view(appt), 201)


@bp.route("/service-appointments/<aid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer", "Technician")
def get_appointment(aid):
    appt = H.get_appointment(aid)
    from flask import g
    if g.role == "Customer":
        wo = db.work_orders.get(appt["work_order_id"])
        if wo is not None:
            H.enforce_work_order_owner(wo)
    return response.success(H.view(appt))


@bp.route("/service-appointments", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Technician")
def list_appointments():
    limit, offset = V.parse_pagination()
    technician_id = request.args.get("technician_id")
    service_bay_id = request.args.get("service_bay_id")
    work_order_id = request.args.get("work_order_id")
    items = list(db.service_appointments.values())
    if technician_id is not None:
        items = [a for a in items if a["technician_id"] == technician_id]
    if service_bay_id is not None:
        items = [a for a in items if a["service_bay_id"] == service_bay_id]
    if work_order_id is not None:
        items = [a for a in items if a["work_order_id"] == work_order_id]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


@bp.route("/service-appointments/<aid>/check-in", methods=["POST"])
@require_roles("Technician")
def check_in(aid):
    appt = H.get_appointment(aid)
    if appt["status"] != "BOOKED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Appointment is not BOOKED.")
    wo = db.work_orders.get(appt["work_order_id"])
    if wo is None or wo["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Linked work order is not SCHEDULED.")
    appt["status"] = "CHECKED_IN"
    db.touch(appt)
    return response.success(H.view(appt))


@bp.route("/service-appointments/<aid>/cancel", methods=["POST"])
@require_roles("ServiceAdvisor")
def cancel_appointment(aid):
    appt = H.get_appointment(aid)
    if appt["status"] != "BOOKED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Appointment is not BOOKED.")
    appt["status"] = "CANCELLED"
    db.touch(appt)
    return response.success(H.view(appt))
