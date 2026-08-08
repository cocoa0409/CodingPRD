"""Transporter and DeliveryJob routes."""
from datetime import timedelta

from flask import Blueprint, request

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    list_response, req_str, req_int, req_dt, opt_int, check_owner, ApiError,
    now_clock,
)
from services import ser_transporter, ser_delivery, vehicle_insurance_status

bp = Blueprint("delivery", __name__)

DELIVERY_STATUSES = {"SCHEDULED", "OUT_FOR_EVENT", "RETURNED", "CANCELLED"}
ACTIVE_JOB_STATES = ("SCHEDULED", "OUT_FOR_EVENT")


@bp.post("/transporters")
def create_transporter():
    require("VaultManager")
    body = get_body()
    name = req_str(body, "name")
    buffer_minutes = opt_int(body, "buffer_minutes", 60, minimum=0)
    rec = base_record()
    rec.update({"name": name, "buffer_minutes": buffer_minutes, "status": "ACTIVE"})
    db.transporters[rec["id"]] = rec
    return success(ser_transporter(rec), status=201)


@bp.get("/transporters/<tid>")
def get_transporter(tid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.transporters, tid)
    return success(ser_transporter(rec))


def _covering_active_coverage(vehicle_id):
    """Max coverage_amount_cents among ACTIVE COIs covering the clock, or None."""
    clock = now_clock()
    best = None
    for c in db.cois.values():
        if (c["vehicle_id"] == vehicle_id and c["status"] == "ACTIVE"
                and c["effective_at"] <= clock < c["expiry_at"]):
            if best is None or c["coverage_amount_cents"] > best:
                best = c["coverage_amount_cents"]
    return best


@bp.post("/delivery-jobs")
def create_delivery():
    uid, role = require("Member", "VaultManager")
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    transporter_id = req_str(body, "transporter_id")
    event_name = req_str(body, "event_name")
    pickup_at = req_dt(body, "pickup_at")
    dropoff_at = req_dt(body, "dropoff_at")
    vehicle = get_or_404(db.vehicles, vehicle_id)
    transporter = get_or_404(db.transporters, transporter_id)
    check_owner(role, uid, vehicle["member_id"])
    # Fiscal gate.
    member = db.members.get(vehicle["member_id"])
    if member is not None and member["billing_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", 402, "Member is suspended")
    # Transporter conflict: occupied window [pickup, dropoff + buffer] (closed).
    buf = timedelta(minutes=transporter["buffer_minutes"])
    new_end = dropoff_at + buf
    for job in db.delivery_jobs.values():
        if job["transporter_id"] == transporter_id and job["status"] in ACTIVE_JOB_STATES:
            ex_end = job["dropoff_at"] + buf
            if pickup_at <= ex_end and job["pickup_at"] <= new_end:
                raise ApiError("ERR_TRANSPORTER_CONFLICT", 409, "Transporter already booked")
    # Insurance must be ACTIVE.
    if vehicle_insurance_status(vehicle_id) != "ACTIVE":
        raise ApiError("ERR_INSURANCE_LAPSED", 409, "Vehicle insurance is not ACTIVE")
    # Coverage adequacy.
    coverage = _covering_active_coverage(vehicle_id)
    if coverage is None or coverage < vehicle["declared_value_cents"]:
        raise ApiError("ERR_COVERAGE_INSUFFICIENT", 409, "Coverage is insufficient")
    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "transporter_id": transporter_id,
        "event_name": event_name,
        "pickup_at": pickup_at,
        "dropoff_at": dropoff_at,
        "status": "SCHEDULED",
    })
    db.delivery_jobs[rec["id"]] = rec
    return success(ser_delivery(rec), status=201)


@bp.get("/delivery-jobs/<jid>")
def get_delivery(jid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.delivery_jobs, jid)
    return success(ser_delivery(rec))


@bp.get("/delivery-jobs")
def list_delivery():
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    vehicle_id = request.args.get("vehicle_id")
    transporter_id = request.args.get("transporter_id")
    status = request.args.get("status")
    items = [d for d in db.delivery_jobs.values()
             if (vehicle_id is None or d["vehicle_id"] == vehicle_id)
             and (transporter_id is None or d["transporter_id"] == transporter_id)
             and (status is None or d["status"] == status)]
    return list_response(items, ser_delivery)


@bp.post("/delivery-jobs/<jid>/dispatch")
def dispatch(jid):
    require("ConciergeTech")
    job = get_or_404(db.delivery_jobs, jid)
    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Job is not SCHEDULED")
    if vehicle_insurance_status(job["vehicle_id"]) != "ACTIVE":
        raise ApiError("ERR_INSURANCE_LAPSED", 409, "Vehicle insurance is not ACTIVE")
    job["status"] = "OUT_FOR_EVENT"
    touch(job)
    return success(ser_delivery(job))


@bp.post("/delivery-jobs/<jid>/return")
def return_job(jid):
    require("ConciergeTech")
    job = get_or_404(db.delivery_jobs, jid)
    if job["status"] != "OUT_FOR_EVENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Job is not OUT_FOR_EVENT")
    job["status"] = "RETURNED"
    touch(job)
    return success(ser_delivery(job))


@bp.post("/delivery-jobs/<jid>/cancel")
def cancel_delivery(jid):
    uid, role = require("Member", "VaultManager")
    job = get_or_404(db.delivery_jobs, jid)
    vehicle = db.vehicles.get(job["vehicle_id"])
    check_owner(role, uid, vehicle["member_id"] if vehicle else None)
    if job["status"] not in ACTIVE_JOB_STATES:
        raise ApiError("ERR_INVALID_STATE", 409, "Job cannot be cancelled")
    job["status"] = "CANCELLED"
    touch(job)
    return success(ser_delivery(job))
