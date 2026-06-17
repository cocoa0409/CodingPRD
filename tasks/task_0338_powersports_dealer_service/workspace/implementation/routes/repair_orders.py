"""Repair orders (PRD 3.6, 3.7, 3.8) — two-dimension state machine."""

from datetime import timedelta

from flask import Blueprint, request

import errors
import calculations as calc
from common import get_body, stamp_new, serialize, touch, paginate, as_int, as_bool, as_str
from db import db, parse_iso
from lookups import get_repair_order, get_unit, get_customer, get_technician
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("repair_orders", __name__)

READ_ROLES = {"ServiceAdvisor", "PartsClerk", "DealerPrincipal", "SalesManager"}


def _windows_conflict(new_start, new_end, ex_start, ex_end, buffer_minutes):
    """Closed-interval overlap with a cleanup buffer gap between appointments.

    Two appointments conflict unless separated by at least buffer_minutes.
    """
    buf = timedelta(minutes=buffer_minutes)
    # conflict if new starts within buffer of existing end AND existing starts
    # within buffer of new end (closed: touching/within-buffer counts).
    return (new_start <= ex_end + buf) and (ex_start <= new_end + buf)


@bp.route("/repair-orders", methods=["POST"])
def create_ro():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    body = get_body()
    # existence in declared order: unit_id, customer_id, technician_id
    unit_id = as_str(body, "unit_id")
    get_unit(unit_id)
    customer_id = as_str(body, "customer_id")
    get_customer(customer_id)
    technician_id = as_str(body, "technician_id")
    tech = get_technician(technician_id)

    # body validation
    appt_start = as_str(body, "appointment_start")
    appt_end = as_str(body, "appointment_end")
    start_dt = parse_iso(appt_start)
    end_dt = parse_iso(appt_end)
    if start_dt is None or end_dt is None:
        errors.err(errors.ERR_INVALID_REQUEST, "appointment_start/appointment_end must be valid timestamps")
    if not (end_dt > start_dt):
        errors.err(errors.ERR_INVALID_REQUEST, "appointment_end must be after appointment_start")
    is_warranty = as_bool(body, "is_warranty", default=False)
    authorized = as_int(body, "authorized_amount_cents", required=False, default=0, minimum=0)

    # temporal conflict: same technician, buffered windows overlap
    buffer_minutes = tech.get("cleanup_buffer_minutes", 30)
    for ro in db.repair_orders.values():
        if ro["technician_id"] != technician_id:
            continue
        if ro["work_status"] == "CANCELLED":
            continue
        ex_start = parse_iso(ro["appointment_start"])
        ex_end = parse_iso(ro["appointment_end"])
        if _windows_conflict(start_dt, end_dt, ex_start, ex_end, buffer_minutes):
            errors.err(errors.ERR_TECH_SCHEDULE_CONFLICT, "Technician appointment conflict")

    rec = stamp_new({
        "unit_id": unit_id,
        "customer_id": customer_id,
        "technician_id": technician_id,
        "appointment_start": appt_start,
        "appointment_end": appt_end,
        "is_warranty": is_warranty,
        "authorized_amount_cents": authorized,
        "labor_total_cents": 0,
        "parts_total_cents": 0,
        "shop_supplies_cents": 0,
        "ro_total_cents": 0,
        "work_status": "OPEN",
        "billing_status": "UNBILLED",
    })
    db.repair_orders[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/repair-orders", methods=["GET"])
def list_ros():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    f = request.args
    records = []
    for ro in db.repair_orders.values():
        if f.get("unit_id") is not None and ro["unit_id"] != f.get("unit_id"):
            continue
        if f.get("customer_id") is not None and ro["customer_id"] != f.get("customer_id"):
            continue
        if f.get("technician_id") is not None and ro["technician_id"] != f.get("technician_id"):
            continue
        if f.get("work_status") is not None and ro["work_status"] != f.get("work_status"):
            continue
        if f.get("billing_status") is not None and ro["billing_status"] != f.get("billing_status"):
            continue
        records.append(ro)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/repair-orders/<rid>", methods=["GET"])
def get_ro_route(rid):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    rec = get_repair_order(rid)
    return ok(serialize(rec), 200)


@bp.route("/repair-orders/<rid>/start", methods=["POST"])
def start_ro(rid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    ro = get_repair_order(rid)
    if ro["work_status"] != "OPEN":
        errors.err(errors.ERR_INVALID_STATE, "RepairOrder is not OPEN")
    lines = [sl for sl in db.service_lines.values() if sl["repair_order_id"] == rid]
    if not lines:
        errors.err(errors.ERR_NO_SERVICE_LINES, "RepairOrder has no service lines")
    ro["work_status"] = "IN_PROGRESS"
    touch(ro)
    return ok(serialize(ro), 200)


@bp.route("/repair-orders/<rid>/complete", methods=["POST"])
def complete_ro(rid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    ro = get_repair_order(rid)
    if ro["work_status"] != "IN_PROGRESS":
        errors.err(errors.ERR_INVALID_STATE, "RepairOrder is not IN_PROGRESS")

    # consume reserved part lines first (so parts_total reflects consumed lines)
    for pl in db.part_lines.values():
        if pl["repair_order_id"] == rid and pl["status"] == "RESERVED":
            part = db.parts.get(pl["part_id"])
            if part is not None:
                part["reserved_qty"] = part.get("reserved_qty", 0) - pl["quantity"]
                part["consumed_qty"] = part.get("consumed_qty", 0) + pl["quantity"]
                touch(part)
            pl["status"] = "CONSUMED"

    # finalize totals
    labor_total, shop_supplies = calc.ro_labor_total(ro)
    parts_total = calc.ro_parts_total(rid)
    ro["labor_total_cents"] = labor_total
    ro["shop_supplies_cents"] = shop_supplies
    ro["parts_total_cents"] = parts_total
    ro["ro_total_cents"] = labor_total + parts_total + shop_supplies

    ro["work_status"] = "WORK_COMPLETE"
    touch(ro)
    return ok(serialize(ro), 200)


@bp.route("/repair-orders/<rid>/invoice", methods=["POST"])
def invoice_ro(rid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    ro = get_repair_order(rid)
    # billing from-state
    if ro["billing_status"] != "UNBILLED":
        errors.err(errors.ERR_INVALID_STATE, "RepairOrder billing is not UNBILLED")
    # requires work complete
    if ro["work_status"] != "WORK_COMPLETE":
        errors.err(errors.ERR_WORK_NOT_COMPLETE, "Work is not complete")
    # fiscal gate (non-warranty)
    if not ro.get("is_warranty", False):
        if ro["ro_total_cents"] > ro["authorized_amount_cents"] and role != "DealerPrincipal":
            errors.err(errors.ERR_OVER_AUTHORIZATION, "RO total exceeds authorized amount")
    ro["billing_status"] = "INVOICED"
    touch(ro)
    return ok(serialize(ro), 200)


@bp.route("/repair-orders/<rid>/pay", methods=["POST"])
def pay_ro(rid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    ro = get_repair_order(rid)
    if ro["billing_status"] != "INVOICED":
        errors.err(errors.ERR_INVALID_STATE, "RepairOrder billing is not INVOICED")
    ro["billing_status"] = "PAID"
    touch(ro)
    return ok(serialize(ro), 200)


@bp.route("/repair-orders/<rid>/cancel", methods=["POST"])
def cancel_ro(rid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    ro = get_repair_order(rid)
    # PRD 3.6: cancelling is permitted only while billing_status is still
    # UNBILLED, otherwise it is rejected with ERR_RO_ALREADY_BILLED. This
    # named billing gate takes precedence over the generic work-state error.
    if ro["billing_status"] != "UNBILLED":
        errors.err(errors.ERR_RO_ALREADY_BILLED, "RepairOrder is already billed")
    if ro["work_status"] not in ("OPEN", "IN_PROGRESS"):
        errors.err(errors.ERR_INVALID_STATE, "RepairOrder is not cancellable")

    # release reserved part lines
    for pl in db.part_lines.values():
        if pl["repair_order_id"] == rid and pl["status"] == "RESERVED":
            part = db.parts.get(pl["part_id"])
            if part is not None:
                part["reserved_qty"] = part.get("reserved_qty", 0) - pl["quantity"]
                part["available_qty"] = part.get("available_qty", 0) + pl["quantity"]
                touch(part)
            pl["status"] = "RELEASED"

    ro["work_status"] = "CANCELLED"
    # coupled effect: billing UNBILLED -> VOID
    ro["billing_status"] = "VOID"
    touch(ro)
    return ok(serialize(ro), 200)
