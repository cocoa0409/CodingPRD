"""Medication order lifecycle + administration events. PRD §3.6."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c

bp = Blueprint("medications", __name__)

OUTCOMES = {"GIVEN", "REFUSED", "HELD"}


def order_view(o):
    return dict(o)


def admin_view(a):
    return dict(a)


# --- Orders ---
@bp.post("/pace/medication-orders")
@require_roles("MedicalDirector", "NurseStaff")
def create_order():
    body = c.get_body()
    participant_id = c.as_str(body, "participant_id")
    care_plan_id = c.as_str(body, "care_plan_id")
    drug_name = c.as_str(body, "drug_name")
    daily_doses = c.as_int(body, "daily_doses", min_val=1)
    c.find_or_404(db.participants, participant_id)
    c.find_or_404(db.care_plans, care_plan_id)

    o = c.base_fields()
    o.update({
        "participant_id": participant_id,
        "care_plan_id": care_plan_id,
        "drug_name": drug_name,
        "daily_doses": daily_doses,
        "administered_count": 0,
        "status": "ORDERED",
    })
    db.medication_orders[o["id"]] = o
    return success(order_view(o), status=201)


@bp.get("/pace/medication-orders/<order_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def get_order(order_id):
    o = c.find_or_404(db.medication_orders, order_id)
    return success(order_view(o))


@bp.get("/pace/medication-orders")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def list_orders():
    limit, offset = c.get_pagination()
    items = list(db.medication_orders.values())
    for key in ("participant_id", "care_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([order_view(o) for o in page], limit, offset, total)


def _require_plan_active(order):
    plan = db.care_plans.get(order["care_plan_id"])
    if not plan or plan["status"] != "ACTIVE":
        raise err("ERR_CARE_PLAN_NOT_ACTIVE", "Care plan not ACTIVE")


@bp.post("/pace/medication-orders/<order_id>/activate")
@require_roles("NurseStaff")
def activate_order(order_id):
    o = c.find_or_404(db.medication_orders, order_id)
    if o["status"] != "ORDERED":
        raise err("ERR_INVALID_STATE", "Order not ORDERED")
    _require_plan_active(o)
    o["status"] = "ACTIVE"
    c.touch(o)
    return success(order_view(o))


@bp.post("/pace/medication-orders/<order_id>/hold")
@require_roles("NurseStaff")
def hold_order(order_id):
    o = c.find_or_404(db.medication_orders, order_id)
    if o["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Order not ACTIVE")
    o["status"] = "HELD"
    c.touch(o)
    return success(order_view(o))


@bp.post("/pace/medication-orders/<order_id>/resume")
@require_roles("NurseStaff")
def resume_order(order_id):
    o = c.find_or_404(db.medication_orders, order_id)
    if o["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Order not HELD")
    _require_plan_active(o)
    o["status"] = "ACTIVE"
    c.touch(o)
    return success(order_view(o))


@bp.post("/pace/medication-orders/<order_id>/discontinue")
@require_roles("NurseStaff", "MedicalDirector")
def discontinue_order(order_id):
    o = c.find_or_404(db.medication_orders, order_id)
    if o["status"] not in ("ORDERED", "ACTIVE", "HELD"):
        raise err("ERR_INVALID_STATE", "Order not in ORDERED/ACTIVE/HELD")
    o["status"] = "DISCONTINUED"
    c.touch(o)
    return success(order_view(o))


# --- Administrations (append-only; id + created_at only) ---
@bp.post("/pace/medication-administrations")
@require_roles("NurseStaff")
def create_admin():
    body = c.get_body()
    order_id = c.as_str(body, "medication_order_id")
    day_id = c.as_str(body, "attendance_day_id")
    outcome = c.as_enum(body, "outcome", OUTCOMES)
    administered_at = c.parse_datetime(body, "administered_at")
    order = c.find_or_404(db.medication_orders, order_id)
    day = c.find_or_404(db.attendance_days, day_id)

    # Day must be CHECKED_IN or COMPLETED (priority 13) → ERR_CARE_PLAN_NOT_ACTIVE
    if day["status"] not in ("CHECKED_IN", "COMPLETED"):
        raise err("ERR_CARE_PLAN_NOT_ACTIVE", "Attendance day not CHECKED_IN/COMPLETED")

    a = c.base_fields(with_version=False)  # append-only: id + created_at only
    a.pop("updated_at", None)
    a.update({
        "medication_order_id": order_id,
        "attendance_day_id": day_id,
        "outcome": outcome,
        "administered_at": c.iso_out(administered_at),
    })
    db.medication_administrations[a["id"]] = a

    if outcome == "GIVEN":
        order["administered_count"] = order["administered_count"] + 1
        c.touch(order)
    return success(admin_view(a), status=201)


@bp.get("/pace/medication-administrations/<administration_id>")
@require_roles("ProgramAdmin", "MedicalDirector", "NurseStaff", "BillingSpecialist")
def get_admin(administration_id):
    a = c.find_or_404(db.medication_administrations, administration_id)
    return success(admin_view(a))


@bp.get("/pace/medication-administrations")
@require_roles("ProgramAdmin", "MedicalDirector", "NurseStaff", "BillingSpecialist")
def list_admins():
    limit, offset = c.get_pagination()
    items = list(db.medication_administrations.values())
    for key in ("medication_order_id", "attendance_day_id", "outcome"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([admin_view(a) for a in page], limit, offset, total)
