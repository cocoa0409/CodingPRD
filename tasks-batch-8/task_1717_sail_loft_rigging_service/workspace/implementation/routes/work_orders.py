"""LoftWorkOrder endpoints."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles, require_owner
from response import success_object, success_list, now_iso
from services import domain, calculations as calc

bp = Blueprint("work_orders", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
ORDER_KINDS = ("NEW_SAIL", "RIGGING_SERVICE", "MAST_SERVICE", "STORAGE_PROGRAM", "REPAIR")
OPTION_CODES = ("BATTENS", "REEF_POINTS", "UV_STRIP", "NUMBERS", "LOGO")
WARRANTY_WINDOW_DAYS = 730


@bp.post("/lofts/work-orders")
def create_work_order():
    require_roles("LoftManager")
    body = util.get_body()
    customer_id = util.as_string(util.require_field(body, "customer_id"), "customer_id")
    boat_id = util.as_string(util.require_field(body, "boat_id"), "boat_id")
    order_kind = util.as_enum(util.require_field(body, "order_kind"), "order_kind", ORDER_KINDS)
    sail_design_id = util.opt_field(body, "sail_design_id", None)
    warranty_flag = util.as_bool(util.opt_field(body, "warranty_flag", False), "warranty_flag")
    customer = domain.get_customer_or_404(customer_id)
    boat = domain.get_boat_or_404(boat_id)
    if sail_design_id is not None:
        sail_design_id = util.as_string(sail_design_id, "sail_design_id")
        domain.get_design_or_404(sail_design_id)
    wo = util.stamp_new({
        "customer_id": customer["id"],
        "boat_id": boat["id"],
        "sail_design_id": sail_design_id,
        "order_kind": order_kind,
        "quoted_total_cents": 0,
        "invoiced_total_cents": 0,
        "warranty_flag": warranty_flag,
        "order_status": "OPEN",
        "delivered_at": None,
    })
    db.work_orders[wo["id"]] = wo
    return success_object(domain.serialize(wo), 201)


@bp.get("/lofts/work-orders")
def list_work_orders():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.work_orders.values()))
    items = util.filter_exact(items, "customer_id", request.args.get("customer_id"))
    items = util.filter_exact(items, "boat_id", request.args.get("boat_id"))
    items = util.filter_exact(items, "sail_design_id", request.args.get("sail_design_id"))
    items = util.filter_exact(items, "order_status", request.args.get("order_status"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(w) for w in page], limit, offset, total)


@bp.get("/lofts/work-orders/<workOrderId>")
def get_work_order(workOrderId):
    require_roles(*READ_ROLES)
    wo = domain.get_work_order_or_404(workOrderId)
    return success_object(domain.serialize(wo))


@bp.post("/lofts/work-orders/<workOrderId>/lock-design")
def lock_design(workOrderId):
    require_roles("LoftManager")
    wo = domain.get_work_order_or_404(workOrderId)
    if wo["order_status"] != "OPEN":
        raise errors.invalid_state(f"Work order must be OPEN to lock-design (is {wo['order_status']})")
    if wo["order_kind"] != "NEW_SAIL":
        raise errors.invalid_state(f"order_kind must be NEW_SAIL to lock-design (is {wo['order_kind']})")
    design_id = wo.get("sail_design_id")
    design = db.sail_designs.get(design_id) if design_id else None
    if design is None or design["design_status"] != "APPROVED":
        raise errors.design_not_in_required_state(
            "Pinned SailDesign must be APPROVED for lock-design"
        )
    customer = domain.get_customer_or_404(wo["customer_id"])
    if customer["status"] != "ACTIVE":
        raise errors.invalid_state("Customer must be ACTIVE to lock-design")
    boat = domain.get_boat_or_404(wo["boat_id"])
    sheet = domain.get_sheet_or_404(design["measurement_sheet_id"])
    quote = calc.sail_price_provisional(design, sheet, boat)
    wo["order_status"] = "DESIGN_LOCKED"
    wo["quoted_total_cents"] = quote
    util.touch(wo)
    return success_object(domain.serialize(wo))


@bp.post("/lofts/work-orders/<workOrderId>/confirm-delivery")
def confirm_delivery(workOrderId):
    user_id, _ = require_roles("Customer")
    wo = domain.get_work_order_or_404(workOrderId)
    if wo["order_status"] != "READY_FOR_FIT_CHECK":
        raise errors.invalid_state(f"Work order must be READY_FOR_FIT_CHECK (is {wo['order_status']})")
    boat = domain.get_boat_or_404(wo["boat_id"])
    require_owner(user_id, boat["customer_id"])
    body = util.get_body()
    fitted_option_codes = util.as_enum_array(
        util.opt_field(body, "fitted_option_codes", []), "fitted_option_codes", OPTION_CODES
    )
    design = domain.get_design_or_404(wo["sail_design_id"])
    qc_jobs = [
        j for j in db.production_jobs.values()
        if j["work_order_id"] == wo["id"] and j["job_status"] == "QC_PASSED"
    ]
    qc_jobs.sort(key=lambda j: (j["scheduled_start_date"], j["created_at"]))
    invoiced = calc.final_invoice(wo, design, qc_jobs, fitted_option_codes)
    wo["order_status"] = "DELIVERED"
    wo["invoiced_total_cents"] = invoiced
    wo["delivered_at"] = now_iso()
    util.touch(wo)
    customer = domain.get_customer_or_404(wo["customer_id"])
    customer["outstanding_balance_cents"] += invoiced
    util.touch(customer)
    return success_object(domain.serialize(wo))


@bp.post("/lofts/work-orders/<workOrderId>/open-warranty-claim")
def open_warranty_claim(workOrderId):
    user_id, _ = require_roles("Customer")
    wo = domain.get_work_order_or_404(workOrderId)
    if wo["order_status"] != "DELIVERED":
        raise errors.invalid_state(f"Work order must be DELIVERED to open a warranty claim (is {wo['order_status']})")
    boat = domain.get_boat_or_404(wo["boat_id"])
    require_owner(user_id, boat["customer_id"])
    body = util.get_body()
    util.as_string(util.require_field(body, "claim_reason"), "claim_reason")
    delivered_at = wo.get("delivered_at")
    if delivered_at:
        delivered_dt = util.parse_iso_datetime(delivered_at, "delivered_at")
        if datetime.now(timezone.utc) > delivered_dt + timedelta(days=WARRANTY_WINDOW_DAYS):
            raise errors.warranty_window_expired()
    wo["order_status"] = "WARRANTY_REVIEW"
    util.touch(wo)
    return success_object(domain.serialize(wo))


@bp.post("/lofts/work-orders/<workOrderId>/rule-warranty")
def rule_warranty(workOrderId):
    require_roles("LoftManager")
    wo = domain.get_work_order_or_404(workOrderId)
    if wo["order_status"] != "WARRANTY_REVIEW":
        raise errors.invalid_state(f"Work order must be in WARRANTY_REVIEW to rule (is {wo['order_status']})")
    body = util.get_body()
    ruling = util.as_enum(util.require_field(body, "ruling"), "ruling", ("REPAIR", "REPLACE"))
    customer = domain.get_customer_or_404(wo["customer_id"])
    if ruling == "REPAIR":
        wo["order_status"] = "WARRANTY_REPAIR"
        wo["warranty_flag"] = True
        customer["outstanding_balance_cents"] = max(
            0, customer["outstanding_balance_cents"] - wo["invoiced_total_cents"]
        )
        util.touch(customer)
        util.touch(wo)
        return success_object(domain.serialize(wo))
    # REPLACE
    wo["order_status"] = "CLOSED"
    util.touch(wo)
    replacement = util.stamp_new({
        "customer_id": wo["customer_id"],
        "boat_id": wo["boat_id"],
        "sail_design_id": wo.get("sail_design_id"),
        "order_kind": "NEW_SAIL",
        "quoted_total_cents": 0,
        "invoiced_total_cents": 0,
        "warranty_flag": True,
        "order_status": "OPEN",
        "delivered_at": None,
    })
    db.work_orders[replacement["id"]] = replacement
    return success_object(domain.serialize(wo))


@bp.post("/lofts/work-orders/<workOrderId>/close")
def close_work_order(workOrderId):
    require_roles("LoftManager")
    wo = domain.get_work_order_or_404(workOrderId)
    if wo["order_status"] not in ("DELIVERED", "WARRANTY_REPAIR"):
        raise errors.invalid_state(
            f"Work order must be DELIVERED or WARRANTY_REPAIR to close (is {wo['order_status']})"
        )
    wo["order_status"] = "CLOSED"
    util.touch(wo)
    return success_object(domain.serialize(wo))


@bp.post("/lofts/work-orders/<workOrderId>/cancel")
def cancel_work_order(workOrderId):
    require_roles("LoftManager")
    wo = domain.get_work_order_or_404(workOrderId)
    if wo["order_status"] != "OPEN":
        raise errors.invalid_state(f"Work order must be OPEN to cancel (is {wo['order_status']})")
    wo["order_status"] = "CANCELLED"
    util.touch(wo)
    domain.cancel_work_order_cascade(wo)
    return success_object(domain.serialize(wo))
