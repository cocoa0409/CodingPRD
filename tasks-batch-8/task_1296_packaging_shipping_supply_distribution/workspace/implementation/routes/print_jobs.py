"""Custom print job endpoints (PRD §3.6)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import err_invalid_request, err_not_found, err_invalid_state, err_press_occupied
from middleware import require_roles, get_json_body
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_job
from services import pricing, sourcing
from util import business_days_after_date, business_days_after_dt, is_int, to_decimal

bp = Blueprint("print_jobs", __name__)
PREFIX = "/packaging-distribution"

READ_ROLES = ("PlatformAdmin", "WarehouseOps", "CustomerService")
JOB_STATUSES = {"QUEUED", "PLATING", "PRINTING", "COMPLETED", "SCRAPPED"}


def _get_job(job_id):
    j = db.custom_print_jobs.get(job_id)
    if j is None:
        raise err_not_found("Custom print job not found.")
    return j


@bp.route(f"{PREFIX}/custom-print-jobs", methods=["GET"])
@require_roles(*READ_ROLES)
def list_jobs():
    limit, offset = parse_pagination(request.args)
    line_f = request.args.get("order_line_id")
    wh_f = request.args.get("warehouse_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in JOB_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    items = sorted(db.custom_print_jobs.values(), key=lambda j: (j["created_at"], j["_seq"]))
    if line_f is not None:
        items = [j for j in items if j["order_line_id"] == line_f]
    if wh_f is not None:
        items = [j for j in items if j["warehouse_id"] == wh_f]
    if status_f is not None:
        items = [j for j in items if j["status"] == status_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_job(j) for j in page], pagination)


@bp.route(f"{PREFIX}/custom-print-jobs/<job_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_job(job_id):
    return success_object(ser_job(_get_job(job_id)))


@bp.route(f"{PREFIX}/custom-print-jobs/<job_id>/start", methods=["POST"])
@require_roles("WarehouseOps")
def start_job(job_id):
    job = _get_job(job_id)
    if job["status"] != "QUEUED":
        raise err_invalid_state("Only a QUEUED job can be started.")
    line = db.order_lines[job["order_line_id"]]
    product = db.products[line["product_id"]]
    warehouse = db.warehouses[job["warehouse_id"]]
    if sourcing.press_occupancy_conflict(job, warehouse, product):
        raise err_press_occupied()
    now = db.now()
    job["started_at"] = now
    job["occupied_until"] = business_days_after_dt(now, product["lead_time_days"])
    job["status"] = "PLATING"
    db.touch(job)
    return success_object(ser_job(job))


@bp.route(f"{PREFIX}/custom-print-jobs/<job_id>/advance", methods=["POST"])
@require_roles("WarehouseOps")
def advance_job(job_id):
    job = _get_job(job_id)
    if job["status"] != "PLATING":
        raise err_invalid_state("Only a PLATING job can be advanced.")
    job["status"] = "PRINTING"
    db.touch(job)
    return success_object(ser_job(job))


def _tolerance_band(qty, tolerance_pct):
    """Band edges: qty * (1 +/- pct/100), Decimal half-up to whole units."""
    pct = to_decimal(tolerance_pct if tolerance_pct is not None else 0)
    lower = (Decimal(qty) * (Decimal(100) - pct) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    upper = (Decimal(qty) * (Decimal(100) + pct) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(lower), int(upper)


@bp.route(f"{PREFIX}/custom-print-jobs/<job_id>/receive", methods=["POST"])
@require_roles("WarehouseOps")
def receive_job(job_id):
    job = _get_job(job_id)
    body = get_json_body(required=True)
    actual_qty = body.get("actual_qty")
    if not is_int(actual_qty):
        raise err_invalid_request("Field 'actual_qty' must be an integer.")
    if actual_qty < 0:
        raise err_invalid_request("Field 'actual_qty' must be >= 0.")
    receive_note = body.get("receive_note")
    if receive_note is not None and not isinstance(receive_note, str):
        raise err_invalid_request("Field 'receive_note' must be a string.")
    if job["status"] != "PRINTING":
        raise err_invalid_state("Only a PRINTING job can be received.")

    line = db.order_lines[job["order_line_id"]]
    order = db.orders[line["order_id"]]
    product = db.products[line["product_id"]]
    lower, upper = _tolerance_band(line["qty"], line["over_under_tolerance_pct"])

    if lower <= actual_qty <= upper:
        # In tolerance: COMPLETED; line ALLOCATED at produced qty; reservation.
        job["status"] = "COMPLETED"
        job["actual_qty"] = actual_qty
        if receive_note is not None:
            job["receive_note"] = receive_note
        db.touch(job)

        line["qty"] = actual_qty
        line["status"] = "ALLOCATED"
        db.touch(line)
        inv_id = db.inventory_by_pair.get((line["product_id"], line["allocated_warehouse_id"]))
        if inv_id is not None:
            inv = db.inventory[inv_id]
            inv["reserved_qty"] += actual_qty
            db.touch(inv)
        # Order totals recomputed on the new quantity (no lifecycle transition).
        pricing.calc_order_pricing(order)
    else:
        # Out of tolerance: SCRAPPED + replacement QUEUED; line cycles
        # IN_PRODUCTION -> OPEN -> IN_PRODUCTION; lead-time baseline resets.
        job["status"] = "SCRAPPED"
        if receive_note is not None:
            job["receive_note"] = receive_note
        db.touch(job)

        warehouse = db.warehouses[job["warehouse_id"]]
        sourcing.create_print_job(line, warehouse)
        line["status"] = "IN_PRODUCTION"
        db.touch(line)
        line["_ready_date"] = business_days_after_date(db.now().date(),
                                                       product["lead_time_days"])
        order["promised_ship_date"] = sourcing.compute_order_promise(order)

    return success_object(ser_job(db.custom_print_jobs[job["id"]]))
