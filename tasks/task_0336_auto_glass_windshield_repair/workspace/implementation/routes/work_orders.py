"""WorkOrder spine: create, fetch, assessments, transitions, sub-resource lists."""
from flask import Blueprint, g

import db
import errors
import response
import validation as V
from errors import ApiError
from middleware import require_roles
from services import calculations as C
from services import helpers as H
from services import workorder_sm as SM

bp = Blueprint("work_orders", __name__)


# ---------------------------------------------------------------------------
# Open / fetch a work order
# ---------------------------------------------------------------------------
@bp.route("/work-orders", methods=["POST"])
@require_roles("ServiceAdvisor", "Customer")
def create_work_order():
    body = V.get_json()
    customer_id = V.require_str(body, "customer_id")
    vehicle_id = V.require_str(body, "vehicle_id")
    # Ownership (PRD 2.8: authorization precedes existence): a Customer may only
    # open work orders for their own customer_id, checked before existence lookups.
    H.enforce_customer_owns(customer_id)
    # Existence (left-to-right): customer then vehicle.
    customer = H.get_customer(customer_id)
    vehicle = H.get_vehicle(vehicle_id)

    wo = db.stamp_new({
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "status": "OPEN",
        "service_decision": None,
        "service_location": None,
        "recalibration_required": False,
        "assessment_version": 0,
        "total_charge_cents": 0,
        "amount_paid_cents": 0,
        "safe_drive_away_at": None,
    })
    db.work_orders[wo["id"]] = wo
    return response.success(H.view(wo), 201)


@bp.route("/work-orders/<wid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer", "Technician")
def get_work_order(wid):
    wo = H.get_work_order(wid)
    H.enforce_work_order_owner(wo)
    return response.success(H.view(wo))


# ---------------------------------------------------------------------------
# Damage assessments
# ---------------------------------------------------------------------------
@bp.route("/work-orders/<wid>/damage-assessments", methods=["POST"])
@require_roles("ServiceAdvisor")
def create_assessment(wid):
    wo = H.get_work_order(wid)
    body = V.get_json()
    chip_count = V.require_int(body, "chip_count")
    longest_crack_mm = V.require_number(body, "longest_crack_mm")
    edge_distance_mm = V.require_number(body, "edge_distance_mm")
    in_driver_primary_view = V.opt_bool(body, "in_driver_primary_view", False)

    if chip_count < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "chip_count must be >= 0.")
    if longest_crack_mm < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "longest_crack_mm must be >= 0.")
    if edge_distance_mm < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "edge_distance_mm must be >= 0.")

    recommendation = C.repair_vs_replace_decision(
        chip_count, longest_crack_mm, in_driver_primary_view, edge_distance_mm)

    assessment = db.stamp_new({
        "work_order_id": wid,
        "chip_count": chip_count,
        "longest_crack_mm": longest_crack_mm,
        "in_driver_primary_view": in_driver_primary_view,
        "edge_distance_mm": edge_distance_mm,
        "recommendation": recommendation,
        "status": "DRAFT",
    })
    db.damage_assessments[assessment["id"]] = assessment
    return response.success(H.view(assessment), 201)


@bp.route("/work-orders/<wid>/damage-assessments", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def list_assessments(wid):
    wo = H.get_work_order(wid)
    H.enforce_work_order_owner(wo)
    limit, offset = V.parse_pagination()
    items = [a for a in db.damage_assessments.values() if a["work_order_id"] == wid]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
@bp.route("/work-orders/<wid>/accept-assessment", methods=["POST"])
@require_roles("ServiceAdvisor")
def accept_assessment(wid):
    wo = H.get_work_order(wid)
    body = V.get_json()
    assessment_id = V.require_str(body, "assessment_id")
    assessment = db.damage_assessments.get(assessment_id)
    if assessment is None or assessment["work_order_id"] != wid:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Assessment not found for this work order.")
    SM.accept_assessment(wo, assessment)
    return response.success(H.view(wo))


@bp.route("/work-orders/<wid>/schedule", methods=["POST"])
@require_roles("ServiceAdvisor")
def schedule(wid):
    wo = H.get_work_order(wid)
    body = V.get_json()
    appointment_id = V.require_str(body, "appointment_id")
    appt = db.service_appointments.get(appointment_id)
    if appt is None or appt["work_order_id"] != wid:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Appointment not found for this work order.")
    if appt["status"] != "BOOKED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Appointment is not BOOKED.")
    SM.schedule(wo, appt)
    return response.success(H.view(wo))


@bp.route("/work-orders/<wid>/start-service", methods=["POST"])
@require_roles("Technician")
def start_service(wid):
    wo = H.get_work_order(wid)
    appt = SM.linked_appointment_for(wid)
    SM.start_service(wo, appt)
    return response.success(H.view(wo))


@bp.route("/work-orders/<wid>/finish-install", methods=["POST"])
@require_roles("Technician")
def finish_install(wid):
    wo = H.get_work_order(wid)
    body = V.get_json()
    temp_c = V.require_number(body, "temp_c")
    humidity_pct = V.require_number(body, "humidity_pct")
    SM.finish_install(wo, temp_c, humidity_pct)
    return response.success(H.view(wo))


@bp.route("/work-orders/<wid>/complete", methods=["POST"])
@require_roles("ServiceAdvisor")
def complete(wid):
    wo = H.get_work_order(wid)
    SM.complete(wo)
    return response.success(H.view(wo))


@bp.route("/work-orders/<wid>/cancel", methods=["POST"])
@require_roles("ServiceAdvisor")
def cancel(wid):
    wo = H.get_work_order(wid)
    SM.cancel(wo)
    return response.success(H.view(wo))


# ---------------------------------------------------------------------------
# Computed read: sdat-estimate (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.route("/work-orders/<wid>/sdat-estimate", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer", "Technician")
def sdat_estimate(wid):
    wo = H.get_work_order(wid)
    H.enforce_work_order_owner(wo)
    minutes = C.posted_sdat_minutes()
    from datetime import timedelta
    posted = db.current_utc() + timedelta(minutes=minutes)
    return response.success({
        "posted_sdat_minutes": minutes,
        "posted_safe_drive_away_at": V.to_iso(posted),
    })


# ---------------------------------------------------------------------------
# Sub-resource lists (FK reverse-reachability)
# ---------------------------------------------------------------------------
def _wo_list(wid, store, owner_check):
    wo = H.get_work_order(wid)
    if owner_check:
        H.enforce_work_order_owner(wo)
    limit, offset = V.parse_pagination()
    items = [o for o in store.values() if o["work_order_id"] == wid]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


@bp.route("/work-orders/<wid>/part-orders", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager")
def list_wo_part_orders(wid):
    return _wo_list(wid, db.part_orders, owner_check=False)


@bp.route("/work-orders/<wid>/payments", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def list_wo_payments(wid):
    return _wo_list(wid, db.payments, owner_check=True)


@bp.route("/work-orders/<wid>/appointments", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def list_wo_appointments(wid):
    return _wo_list(wid, db.service_appointments, owner_check=True)


@bp.route("/work-orders/<wid>/recalibration-jobs", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Technician")
def list_wo_recal(wid):
    return _wo_list(wid, db.recalibration_jobs, owner_check=False)


@bp.route("/work-orders/<wid>/warranties", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def list_wo_warranties(wid):
    return _wo_list(wid, db.warranties, owner_check=True)
