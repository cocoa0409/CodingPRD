"""Tow scheduling and the three-way pickup fork (PRD section 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import domain

bp = Blueprint("pickups", __name__)

PICKUP_STATUSES = {"SCHEDULED", "COMPLETED", "FAILED", "CANCELLED"}
READ_ROLES = ("IntakeAgent", "ProgramAdmin", "FinanceOfficer")


@bp.post("/api/pickup-orders")
def create_pickup_order():
    mw.auth("IntakeAgent")
    data = mw.body()
    donation_id = mw.req_string(data, "donation_id")
    vendor_id = mw.req_string(data, "tow_vendor_id")
    start = mw.req_datetime(data, "scheduled_start_utc")
    end = mw.req_datetime(data, "scheduled_end_utc")
    expected_version = mw.req_int(data, "expected_donation_version")

    donation = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    vendor = mw.resolve(db.tow_vendors, vendor_id, "ERR_TOW_VENDOR_NOT_FOUND")

    if expected_version != donation["version"]:
        raise ApiError(
            "ERR_STALE_DONATION_VERSION", "The donation has advanced since it was read."
        )
    if donation["status"] not in ("ACCEPTED", "PICKUP_BLOCKED"):
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "This donation is not awaiting collection."
        )
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED", "This tow vendor is suspended.")
    if end <= start:
        raise ApiError(
            "ERR_PICKUP_WINDOW_INVALID", "The window end must be strictly after its start."
        )
    if start < db.now():
        raise ApiError("ERR_PICKUP_IN_PAST", "A tow window may not be backdated.")

    buffer = timedelta(minutes=db.PICKUP_BUFFER_MINUTES)
    for other in db.pickup_orders.values():
        if other["tow_vendor_id"] != vendor_id or other["status"] != "SCHEDULED":
            continue
        if (
            start < other["scheduled_end_utc"] + buffer
            and other["scheduled_start_utc"] < end + buffer
        ):
            raise ApiError(
                "ERR_VENDOR_WINDOW_CONFLICT",
                "The requested window is within the vendor's turnaround buffer.",
            )

    if vendor["booked_slots_count"] + 1 > vendor["daily_capacity_slots"]:
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED", "The vendor has no free slot.")
    if donation["pickup_attempts"] >= db.MAX_PICKUP_ATTEMPTS:
        raise ApiError(
            "ERR_PICKUP_ATTEMPTS_EXCEEDED", "This donation has exhausted its tow attempts."
        )

    rec = db.new_record()
    rec["donation_id"] = donation_id
    rec["tow_vendor_id"] = vendor_id
    rec["scheduled_start_utc"] = start
    rec["scheduled_end_utc"] = end
    rec["status"] = "SCHEDULED"
    rec["attempt_number"] = donation["pickup_attempts"] + 1
    rec["actual_pickup_utc"] = None
    rec["actual_tow_cost_cents"] = 0
    rec["failure_reason"] = None
    db.pickup_orders[rec["id"]] = rec

    vendor["booked_slots_count"] += 1
    db.touch(vendor)
    db.touch(donation)
    return resp.created(rec)


@bp.get("/api/pickup-orders/<order_id>")
def get_pickup_order(order_id):
    mw.auth(*READ_ROLES)
    rec = mw.resolve(db.pickup_orders, order_id, "ERR_PICKUP_ORDER_NOT_FOUND")
    return resp.ok(rec)


@bp.get("/api/pickup-orders")
def list_pickup_orders():
    mw.auth(*READ_ROLES)
    donation_filter = request.args.get("donation_id")
    vendor_filter = request.args.get("tow_vendor_id")
    status = mw.query_enum("status", PICKUP_STATUSES)
    limit, offset = mw.pagination()
    rows = []
    for rec in db.pickup_orders.values():
        if donation_filter is not None and rec["donation_id"] != donation_filter:
            continue
        if vendor_filter is not None and rec["tow_vendor_id"] != vendor_filter:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return resp.listing(db.ordered(rows), limit, offset)


@bp.post("/api/pickup-orders/<order_id>/complete")
def complete_pickup(order_id):
    mw.auth("IntakeAgent")
    rec = mw.resolve(db.pickup_orders, order_id, "ERR_PICKUP_ORDER_NOT_FOUND")
    data = mw.body()
    cost = mw.req_int(data, "actual_tow_cost_cents", minimum=0)

    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PICKUP_STATE", "This pickup order is not scheduled.")
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "The donation is not awaiting collection."
        )
    vendor = db.tow_vendors.get(rec["tow_vendor_id"])
    if vendor is not None and vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED", "This tow vendor is suspended.")

    rec["status"] = "COMPLETED"
    rec["actual_pickup_utc"] = db.now()
    rec["actual_tow_cost_cents"] = cost
    db.touch(rec)

    if vendor is not None:
        vendor["booked_slots_count"] -= 1
        db.touch(vendor)

    donation["status"] = "IN_CUSTODY"
    db.touch(donation)
    return resp.ok(rec)


@bp.post("/api/pickup-orders/<order_id>/fail")
def fail_pickup(order_id):
    mw.auth("IntakeAgent")
    rec = mw.resolve(db.pickup_orders, order_id, "ERR_PICKUP_ORDER_NOT_FOUND")
    data = mw.body()
    reason = mw.req_string(data, "failure_reason")

    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PICKUP_STATE", "This pickup order is not scheduled.")
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "The donation is not awaiting collection."
        )

    rec["status"] = "FAILED"
    rec["failure_reason"] = reason
    db.touch(rec)

    vendor = db.tow_vendors.get(rec["tow_vendor_id"])
    if vendor is not None:
        vendor["booked_slots_count"] -= 1
        db.touch(vendor)

    donation["pickup_attempts"] += 1
    blocked = donation["pickup_attempts"] >= db.MAX_PICKUP_ATTEMPTS
    if blocked:
        donation["status"] = "PICKUP_BLOCKED"
    db.touch(donation)
    if blocked:
        domain.create_task(
            donation["id"],
            "PICKUP_ESCALATION",
            "ProgramAdmin",
            db.now() + db.days(db.REMITTANCE_FOLLOWUP_DAYS),
        )
    return resp.ok(rec)


@bp.post("/api/pickup-orders/<order_id>/cancel")
def cancel_pickup(order_id):
    mw.auth("IntakeAgent")
    rec = mw.resolve(db.pickup_orders, order_id, "ERR_PICKUP_ORDER_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")

    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PICKUP_STATE", "This pickup order is not scheduled.")

    rec["status"] = "CANCELLED"
    db.touch(rec)

    vendor = db.tow_vendors.get(rec["tow_vendor_id"])
    if vendor is not None:
        vendor["booked_slots_count"] -= 1
        db.touch(vendor)
    return resp.ok(rec)
