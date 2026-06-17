"""WorkOrder endpoints (PRD §3.4–§3.10) — creation, claim, lines, lifecycle."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, optional_str, require_int,
                    parse_pagination, paginate, sort_by_created, touch)
from errors import (ApiError, ERR_BAY_NOT_OPEN, ERR_COUPON_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_COUPON_EXPIRED, ERR_COUPON_USAGE_EXCEEDED,
                    ERR_COUPON_MIN_SUBTOTAL_NOT_MET, ERR_STALE_WORK_ORDER_VERSION,
                    ERR_STICKER_NOT_FOUND, ERR_FORBIDDEN, ERR_VALIDATION)
from response import success_object, success_array
from services import lookup, pricing, workorder
from services import fleet as fleet_svc
from services.serialize import (work_order_out, work_order_line_out,
                                service_sticker_out, payment_out)

bp = Blueprint("work_orders", __name__)

ALL_ROLES = ("ShopManager", "ServiceAdvisor", "Technician", "FleetManager")


# --------------------------------------------------------------------------
# Creation & reads
# --------------------------------------------------------------------------

@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    require_role("ServiceAdvisor")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    vehicle_id = require_str(body, "vehicle_id")
    bay_id = require_str(body, "bay_id")
    package_id = require_str(body, "package_id")
    odometer_in = require_int(body, "odometer_in", minimum=0)
    coupon_code = optional_str(body, "coupon_code", None)

    # existence (404) — path/body FK resolution, left to right.
    lookup.get_shop(shop_id)
    vehicle = lookup.get_vehicle(vehicle_id)
    bay = lookup.get_bay(bay_id)
    package = lookup.get_package(package_id)

    # referential (priority 4): coupon_code must resolve on the same shop —
    # this wins over the bay-open temporal check (priority 8).
    if coupon_code is not None:
        if pricing.find_coupon(coupon_code, shop_id) is None:
            raise ApiError(ERR_COUPON_NOT_FOUND, 404, "coupon_code does not resolve")

    # temporal (priority 8): the bay must be OPEN (one live occupancy at a time).
    if bay["status"] != "OPEN":
        raise ApiError(ERR_BAY_NOT_OPEN, 409, "bay is not OPEN")

    w = workorder.create_work_order(
        shop_id=shop_id, vehicle=vehicle, bay=bay, package=package,
        odometer_in=odometer_in, coupon_code=coupon_code,
    )
    return success_object(work_order_out(w), 201)


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    role, uid = require_role(*ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.work_orders.values())
    if role == "FleetManager":
        veh_ids = {v["id"] for v in db.vehicles.values()
                   if v.get("fleet_account_id") == uid}
        rows = [w for w in rows if w["vehicle_id"] in veh_ids]
    for field in ("shop_id", "vehicle_id", "bay_id", "package_id",
                  "technician_id", "service_status", "payment_status"):
        val = request.args.get(field)
        if val is not None:
            rows = [w for w in rows if w.get(field) == val]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([work_order_out(w) for w in page], limit, offset, total)


@bp.route("/work-orders/<wo_id>", methods=["GET"])
def get_work_order(wo_id):
    role, uid = require_role(*ALL_ROLES)
    w = lookup.get_work_order(wo_id)
    _fleet_read_scope(role, uid, w)
    return success_object(work_order_out(w), 200)


# --------------------------------------------------------------------------
# Claim
# --------------------------------------------------------------------------

@bp.route("/work-orders/<wo_id>/claim", methods=["POST"])
def claim_work_order(wo_id):
    require_role("Technician")
    w = lookup.get_work_order(wo_id)
    body = get_json_or_400()
    technician_id = require_str(body, "technician_id")
    technician = lookup.get_technician(technician_id)
    workorder.claim(w, technician)
    return success_object(work_order_out(w), 200)


# --------------------------------------------------------------------------
# Coupon application
# --------------------------------------------------------------------------

@bp.route("/work-orders/<wo_id>/apply-coupon", methods=["POST"])
def apply_coupon(wo_id):
    require_role("ServiceAdvisor")
    w = lookup.get_work_order(wo_id)
    body = get_json_or_400()
    coupon_code = require_str(body, "coupon_code")
    # referential: resolve coupon on the same shop.
    coupon = pricing.find_coupon(coupon_code, w["shop_id"])
    if coupon is None:
        raise ApiError(ERR_COUPON_NOT_FOUND, 404, "coupon_code does not resolve")
    # coupon eligibility (priority 9), in the documented order.
    if coupon["status"] != "ACTIVE":
        raise ApiError(ERR_COUPON_EXPIRED, 409, "coupon is not ACTIVE")
    if fleet_svc.coupon_redeemed_count(coupon["code"], coupon["shop_id"]) >= coupon["usage_limit"]:
        raise ApiError(ERR_COUPON_USAGE_EXCEEDED, 409, "coupon usage limit reached")
    if w["subtotal_cents"] < coupon["min_subtotal_cents"]:
        raise ApiError(ERR_COUPON_MIN_SUBTOTAL_NOT_MET, 409, "subtotal below coupon minimum")
    w["coupon_code"] = coupon_code
    pricing.recompute_pricing(w)
    touch(w)
    return success_object(work_order_out(w), 200)


# --------------------------------------------------------------------------
# Lines
# --------------------------------------------------------------------------

@bp.route("/work-orders/<wo_id>/lines", methods=["POST"])
def add_line(wo_id):
    require_role("Technician")
    w = lookup.get_work_order(wo_id)
    body = get_json_or_400()
    inspection_item_id = require_str(body, "inspection_item_id")
    expected_version = require_int(body, "expected_work_order_version")
    item = lookup.get_inspection_item(inspection_item_id)
    # OCC (priority 6): echoed version must match the order's current version.
    if expected_version != w["version"]:
        raise ApiError(ERR_STALE_WORK_ORDER_VERSION, 412, "work order version is stale")
    line = workorder.add_line(w, item)
    return success_object(work_order_line_out(line), 201)


@bp.route("/work-orders/<wo_id>/lines", methods=["GET"])
def list_lines(wo_id):
    role, uid = require_role(*ALL_ROLES)
    w = lookup.get_work_order(wo_id)
    _fleet_read_scope(role, uid, w)
    limit, offset = parse_pagination()
    rows = [ln for ln in db.work_order_lines.values() if ln["work_order_id"] == wo_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([work_order_line_out(ln) for ln in page], limit, offset, total)


@bp.route("/work-orders/<wo_id>/lines/<line_id>", methods=["DELETE"])
def remove_line(wo_id, line_id):
    require_role("Technician")
    w = lookup.get_work_order(wo_id)
    line = lookup.get_line_on_order(wo_id, line_id)
    workorder.remove_line(w, line)
    return success_object(work_order_out(w), 200)


# --------------------------------------------------------------------------
# Service-status transitions
# --------------------------------------------------------------------------

@bp.route("/work-orders/<wo_id>/start", methods=["POST"])
def start(wo_id):
    require_role("Technician")
    w = lookup.get_work_order(wo_id)
    workorder.start(w)
    return success_object(work_order_out(w), 200)


@bp.route("/work-orders/<wo_id>/begin-inspection", methods=["POST"])
def begin_inspection(wo_id):
    require_role("Technician")
    w = lookup.get_work_order(wo_id)
    workorder.begin_inspection(w)
    return success_object(work_order_out(w), 200)


@bp.route("/work-orders/<wo_id>/finish-inspection", methods=["POST"])
def finish_inspection(wo_id):
    require_role("Technician")
    w = lookup.get_work_order(wo_id)
    workorder.finish_inspection(w)
    return success_object(work_order_out(w), 200)


@bp.route("/work-orders/<wo_id>/mark-ready", methods=["POST"])
def mark_ready(wo_id):
    require_role("Technician")
    w = lookup.get_work_order(wo_id)
    workorder.mark_ready(w)
    return success_object(work_order_out(w), 200)


# --------------------------------------------------------------------------
# Payment-status transitions
# --------------------------------------------------------------------------

@bp.route("/work-orders/<wo_id>/authorize", methods=["POST"])
def authorize(wo_id):
    require_role("ServiceAdvisor")
    w = lookup.get_work_order(wo_id)
    body = get_json_or_400()
    payment_method = body.get("payment_method")
    workorder.authorize(w, payment_method)
    return success_object(work_order_out(w), 200)


@bp.route("/work-orders/<wo_id>/capture-payment", methods=["POST"])
def capture_payment(wo_id):
    require_role("ServiceAdvisor")
    w = lookup.get_work_order(wo_id)
    workorder.capture_payment(w)
    return success_object(work_order_out(w), 200)


@bp.route("/work-orders/<wo_id>/void-payment", methods=["POST"])
def void_payment(wo_id):
    require_role("ServiceAdvisor")
    w = lookup.get_work_order(wo_id)
    workorder.void_payment(w)
    return success_object(work_order_out(w), 200)


@bp.route("/work-orders/<wo_id>/complete", methods=["POST"])
def complete(wo_id):
    require_role("ServiceAdvisor")
    w = lookup.get_work_order(wo_id)
    workorder.complete(w)
    return success_object(work_order_out(w), 200)


@bp.route("/work-orders/<wo_id>/cancel", methods=["POST"])
def cancel(wo_id):
    require_role("ServiceAdvisor")
    w = lookup.get_work_order(wo_id)
    workorder.cancel(w)
    return success_object(work_order_out(w), 200)


# --------------------------------------------------------------------------
# Reverse-lookup reads
# --------------------------------------------------------------------------

@bp.route("/work-orders/<wo_id>/sticker", methods=["GET"])
def get_sticker(wo_id):
    role, uid = require_role(*ALL_ROLES)
    w = lookup.get_work_order(wo_id)
    _fleet_read_scope(role, uid, w)
    stickers = [s for s in db.service_stickers.values()
                if s["work_order_id"] == wo_id]
    if not stickers:
        raise ApiError(ERR_STICKER_NOT_FOUND, 404, "no sticker for this order yet")
    stickers = sort_by_created(stickers)
    limit, offset = parse_pagination()
    page, total = paginate(stickers, limit, offset)
    return success_array([service_sticker_out(s) for s in page], limit, offset, total)


@bp.route("/work-orders/<wo_id>/payments", methods=["GET"])
def list_payments(wo_id):
    role, uid = require_role("ShopManager", "ServiceAdvisor", "FleetManager")
    w = lookup.get_work_order(wo_id)
    _fleet_read_scope(role, uid, w)
    limit, offset = parse_pagination()
    rows = [p for p in db.payments.values() if p["work_order_id"] == wo_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([payment_out(p) for p in page], limit, offset, total)


def _fleet_read_scope(role, uid, w):
    """A FleetManager may only read work orders of vehicles on its own account."""
    if role != "FleetManager":
        return
    vehicle = db.vehicles.get(w["vehicle_id"])
    if vehicle is None or vehicle.get("fleet_account_id") != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "fleet manager may only read its own data")
