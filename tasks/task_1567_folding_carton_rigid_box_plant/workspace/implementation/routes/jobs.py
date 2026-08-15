"""Job endpoints (PRD §3.2-§3.7): intake, routing, lifecycle transitions."""

from flask import Blueprint

import calc
import db
from errors import (
    ApiError,
    ERR_COLOR_STANDARD_MISSING,
    ERR_CUSTOMER_INACTIVE,
    ERR_DESIGN_NOT_APPROVED,
    ERR_FINISHING_INCOMPLETE,
    ERR_INSUFFICIENT_BOARD_STOCK,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LAYOUT_IMPOSSIBLE,
    ERR_NO_PRESS_BOOKING,
    ERR_OPEN_KIT_ORDERS,
    ERR_OPEN_PRESS_BOOKINGS,
    ERR_PLAN_NOT_LOCKED,
    ERR_PRESS_APPROVAL_MISSING,
    ERR_RRP_NOT_CERTIFIED,
    ERR_SHORT_COUNT,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    available_sheets,
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    locked_plan_for,
    release_job_reservation,
    req_bool,
    req_int,
    req_list,
    req_str,
    ser_job,
)
from util import touch

bp = Blueprint("jobs", __name__)

FINISH_FLAG_TO_OP = (
    ("finish_coat", "COAT"),
    ("finish_foil", "FOIL"),
    ("finish_emboss", "EMBOSS"),
)


@bp.post("/plant/jobs")
def create_job():
    authenticate(("PlantAdmin",))
    data = get_body()
    fk_exists(db.customers, data, "customer_id")

    customer_id = req_str(data, "customer_id")
    quantity_ordered = req_int(data, "quantity_ordered", 1)
    blank_w_cin = req_int(data, "blank_w_cin", 1)
    blank_h_cin = req_int(data, "blank_h_cin", 1)
    grain_rotation_allowed = req_bool(data, "grain_rotation_allowed")
    substrate_code = req_str(data, "substrate_code")
    caliper_pts = req_int(data, "caliper_pts", 1)
    finish_coat = req_bool(data, "finish_coat")
    finish_foil = req_bool(data, "finish_foil")
    finish_emboss = req_bool(data, "finish_emboss")
    required_ink_slots = req_list(data, "required_ink_slots")
    if any(not isinstance(s, str) for s in required_ink_slots):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "required_ink_slots entries must be strings")
    requires_retail_compliance = req_bool(data, "requires_retail_compliance")

    customer = db.customers[customer_id]
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_INACTIVE, 409,
                       "Customer %s is not ACTIVE" % customer_id)

    route_type = calc.route_selection(finish_foil, finish_emboss, quantity_ordered)
    rec = db.new_record()
    rec.update({
        "customer_id": customer_id,
        "quantity_ordered": quantity_ordered,
        "blank_w_cin": blank_w_cin,
        "blank_h_cin": blank_h_cin,
        "grain_rotation_allowed": grain_rotation_allowed,
        "substrate_code": substrate_code,
        "caliper_pts": caliper_pts,
        "finish_coat": finish_coat,
        "finish_foil": finish_foil,
        "finish_emboss": finish_emboss,
        "required_ink_slots": list(required_ink_slots),
        "requires_retail_compliance": requires_retail_compliance,
        "route_type": route_type,
        "status": "QUOTED",
        "board_stock_id": None,
        "locked_ups": None,
        "reserved_sheets": 0,
        "sheets_consumed_actual": 0,
        "good_sheets_actual": 0,
        "allocated_cartons": 0,
    })
    quote = calc.provisional_quote(rec)
    if quote is None:
        raise ApiError(ERR_LAYOUT_IMPOSSIBLE, 409,
                       "Blank does not fit the standard quoting sheet")
    rec["provisional_subtotal_cents"] = quote["subtotal_cents"]
    rec["provisional_total_cents"] = quote["total_cents"]
    db.jobs[rec["id"]] = rec
    return ok_object(ser_job(rec), 201)


@bp.get("/plant/jobs")
def list_jobs():
    authenticate(ALL_ROLES)
    return list_response(
        db.jobs.values(),
        ser_job,
        [("customer_id", "customer_id", "str"), ("status", "status", "str")],
    )


@bp.get("/plant/jobs/<jobId>")
def get_job(jobId):
    authenticate(ALL_ROLES)
    return ok_object(ser_job(get_or_404(db.jobs, jobId)))


def _transition(job, from_status):
    if job["status"] != from_status:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Job is %s, not %s" % (job["status"], from_status))


@bp.post("/plant/jobs/<jobId>/start-engineering")
def start_engineering(jobId):
    authenticate(("PlantAdmin",))
    job = get_or_404(db.jobs, jobId)
    _transition(job, "QUOTED")
    job["status"] = "ENGINEERING"
    touch(job)
    return ok_object(ser_job(job))


@bp.post("/plant/jobs/<jobId>/mark-press-ready")
def mark_press_ready(jobId):
    authenticate(("StructuralDesigner",))
    job = get_or_404(db.jobs, jobId)
    _transition(job, "ENGINEERING")

    approved = any(r["job_id"] == job["id"] and r["status"] == "BRAND_APPROVED"
                   for r in db.design_revisions.values())
    if not approved:
        raise ApiError(ERR_DESIGN_NOT_APPROVED, 409,
                       "No BRAND_APPROVED design revision exists for the job")

    plan = locked_plan_for(job["id"])
    if plan is None:
        raise ApiError(ERR_PLAN_NOT_LOCKED, 409,
                       "No LOCKED imposition plan exists for the job")

    for slot in job["required_ink_slots"]:
        has_standard = any(
            s["customer_id"] == job["customer_id"]
            and s["ink_slot"] == slot
            and s["status"] == "ACTIVE"
            for s in db.color_standards.values()
        )
        if not has_standard:
            raise ApiError(ERR_COLOR_STANDARD_MISSING, 409,
                           "Ink slot %s lacks an ACTIVE color standard" % slot)

    candidates = [
        s for s in db.board_stocks.values()
        if s["substrate_code"] == job["substrate_code"]
        and s["caliper_pts"] == job["caliper_pts"]
        and available_sheets(s) >= plan["gross_sheets"]
    ]
    if not candidates:
        raise ApiError(ERR_INSUFFICIENT_BOARD_STOCK, 409,
                       "No board stock covers the reservation")
    candidates.sort(key=lambda s: (s["unit_cost_cents"], s["created_at"], s["_seq"]))
    winner = candidates[0]

    job["board_stock_id"] = winner["id"]
    job["locked_ups"] = plan["ups"]
    job["reserved_sheets"] = plan["gross_sheets"]
    job["status"] = "PRESS_READY"
    touch(job)
    winner["reserved_sheets"] += plan["gross_sheets"]
    touch(winner)
    return ok_object(ser_job(job))


@bp.post("/plant/jobs/<jobId>/start-production")
def start_production(jobId):
    authenticate(("PressOperator",))
    job = get_or_404(db.jobs, jobId)
    _transition(job, "PRESS_READY")

    for slot in job["required_ink_slots"]:
        ok = False
        for approval in db.press_approvals.values():
            if (approval["job_id"] == job["id"]
                    and approval["ink_slot"] == slot
                    and approval["status"] == "APPROVED"):
                standard = db.color_standards.get(approval["color_standard_id"])
                if standard is not None and standard["status"] == "ACTIVE":
                    ok = True
                    break
        if not ok:
            raise ApiError(ERR_PRESS_APPROVAL_MISSING, 409,
                           "Ink slot %s lacks an APPROVED press approval pinned to an "
                           "ACTIVE standard" % slot)

    has_booking = any(b["job_id"] == job["id"] and b["status"] == "SCHEDULED"
                      for b in db.press_bookings.values())
    if not has_booking:
        raise ApiError(ERR_NO_PRESS_BOOKING, 409,
                       "No SCHEDULED press booking exists for the job")

    job["status"] = "IN_PRODUCTION"
    touch(job)
    return ok_object(ser_job(job))


@bp.post("/plant/jobs/<jobId>/complete-press")
def complete_press(jobId):
    authenticate(("PressOperator",))
    job = get_or_404(db.jobs, jobId)
    _transition(job, "IN_PRODUCTION")

    if any(b["job_id"] == job["id"] and b["status"] == "SCHEDULED"
           for b in db.press_bookings.values()):
        raise ApiError(ERR_OPEN_PRESS_BOOKINGS, 409,
                       "A press booking is still SCHEDULED")

    good_cartons = job["good_sheets_actual"] * (job["locked_ups"] or 0)
    if good_cartons < job["quantity_ordered"]:
        raise ApiError(ERR_SHORT_COUNT, 409,
                       "good_cartons_actual %d < quantity_ordered %d"
                       % (good_cartons, job["quantity_ordered"]))

    job["status"] = "FINISHING"
    touch(job)
    return ok_object(ser_job(job))


@bp.post("/plant/jobs/<jobId>/complete-finishing")
def complete_finishing(jobId):
    authenticate(("FinishingOperator",))
    job = get_or_404(db.jobs, jobId)
    _transition(job, "FINISHING")

    for flag, op in FINISH_FLAG_TO_OP:
        if not job[flag]:
            continue
        completed = any(fb["job_id"] == job["id"] and fb["operation"] == op
                        and fb["status"] == "COMPLETED"
                        for fb in db.finishing_bookings.values())
        if not completed:
            raise ApiError(ERR_FINISHING_INCOMPLETE, 409,
                           "Operation %s lacks a COMPLETED finishing booking" % op)

    job["status"] = "FINISHED"
    touch(job)
    return ok_object(ser_job(job))


@bp.post("/plant/jobs/<jobId>/complete")
def complete_job(jobId):
    authenticate(("PlantAdmin",))
    job = get_or_404(db.jobs, jobId)
    _transition(job, "FINISHED")

    if job["requires_retail_compliance"]:
        certified = any(a["job_id"] == job["id"] and a["status"] == "CERTIFIED"
                        for a in db.retail_audits.values())
        if not certified:
            raise ApiError(ERR_RRP_NOT_CERTIFIED, 409,
                           "No CERTIFIED retail-ready audit exists for the job")

    if any(k["job_id"] == job["id"] and k["status"] in ("PLANNED", "IN_PROGRESS")
           for k in db.kit_orders.values()):
        raise ApiError(ERR_OPEN_KIT_ORDERS, 409,
                       "Kit orders are still PLANNED or IN_PROGRESS")

    release_job_reservation(job, clear_stock_ref=False)
    job["status"] = "COMPLETE"
    touch(job)
    return ok_object(ser_job(job))


@bp.post("/plant/jobs/<jobId>/cancel")
def cancel_job(jobId):
    authenticate(("PlantAdmin",))
    job = get_or_404(db.jobs, jobId)
    if job["status"] not in ("QUOTED", "ENGINEERING", "PRESS_READY"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Job in %s cannot be cancelled" % job["status"])

    # CASCADE L1: release board reservation if any (board_stock_id retained)
    release_job_reservation(job, clear_stock_ref=False)
    job["status"] = "CANCELLED"
    touch(job)

    # CASCADE L2: every SCHEDULED press/finishing booking of the job -> CANCELLED
    for booking in db.press_bookings.values():
        if booking["job_id"] == job["id"] and booking["status"] == "SCHEDULED":
            booking["status"] = "CANCELLED"
            touch(booking)
    for booking in db.finishing_bookings.values():
        if booking["job_id"] == job["id"] and booking["status"] == "SCHEDULED":
            booking["status"] = "CANCELLED"
            touch(booking)
    return ok_object(ser_job(job))
