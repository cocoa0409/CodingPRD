"""ServiceOrder routes."""
from flask import Blueprint

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    req_str, req_enum, req_num, req_int, req_dt, opt_int, check_owner, ApiError,
)
from services import ser_service_order, service_estimate, service_final

bp = Blueprint("service_orders", __name__)

SERVICE_TYPES = {"DETAIL", "START_ENGINE", "CHECKOUT", "CHECKIN", "FUEL"}


@bp.post("/service-orders")
def create_service_order():
    uid, role = require("Member", "VaultManager")
    body = get_body()
    agreement_id = req_str(body, "agreement_id")
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    estimated_labor_hours = req_num(body, "estimated_labor_hours", minimum=0)
    agr = get_or_404(db.agreements, agreement_id)
    check_owner(role, uid, agr["member_id"])
    member = db.members.get(agr["member_id"])
    if member is not None and member["billing_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", 402, "Member is suspended")
    rec = base_record()
    rec.update({
        "agreement_id": agreement_id,
        "service_type": service_type,
        "estimated_labor_hours": estimated_labor_hours,
        "actual_labor_hours": None,
        "parts_cents": 0,
        "estimated_cost_cents": None,
        "final_cost_cents": None,
        "scheduled_at": None,
        "status": "REQUESTED",
    })
    db.service_orders[rec["id"]] = rec
    return success(ser_service_order(rec), status=201)


@bp.get("/service-orders/<oid>")
def get_service_order(oid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.service_orders, oid)
    return success(ser_service_order(rec))


@bp.post("/service-orders/<oid>/approve")
def approve(oid):
    require("VaultManager")
    order = get_or_404(db.service_orders, oid)
    body = get_body()
    scheduled_at = req_dt(body, "scheduled_at")
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not REQUESTED")
    agr = db.agreements.get(order["agreement_id"])
    if agr is None or agr["status"] not in ("IN_STORAGE", "CHECKED_OUT"):
        raise ApiError("ERR_CROSS_ENTITY_STATE", 409, "Agreement is not in storage")
    order["scheduled_at"] = scheduled_at
    order["estimated_cost_cents"] = service_estimate(order)
    order["status"] = "APPROVED"
    touch(order)
    return success(ser_service_order(order))


@bp.post("/service-orders/<oid>/reject")
def reject(oid):
    require("VaultManager")
    order = get_or_404(db.service_orders, oid)
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not REQUESTED")
    order["status"] = "REJECTED"
    touch(order)
    return success(ser_service_order(order))


@bp.post("/service-orders/<oid>/start")
def start(oid):
    require("ConciergeTech")
    order = get_or_404(db.service_orders, oid)
    if order["status"] not in ("APPROVED", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not APPROVED or ON_HOLD")
    agr = db.agreements.get(order["agreement_id"])
    if agr is None or agr["status"] != "IN_STORAGE":
        raise ApiError("ERR_CROSS_ENTITY_STATE", 409, "Agreement is not IN_STORAGE")
    vehicle = db.vehicles.get(agr["vehicle_id"]) if agr else None
    if vehicle is not None and vehicle["condition_status"] == "DAMAGE_HOLD":
        raise ApiError("ERR_CROSS_ENTITY_STATE", 409, "Vehicle is on DAMAGE_HOLD")
    order["status"] = "IN_PROGRESS"
    touch(order)
    return success(ser_service_order(order))


@bp.post("/service-orders/<oid>/hold")
def hold(oid):
    require("ConciergeTech")
    order = get_or_404(db.service_orders, oid)
    if order["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not IN_PROGRESS")
    order["status"] = "ON_HOLD"
    touch(order)
    return success(ser_service_order(order))


@bp.post("/service-orders/<oid>/complete")
def complete(oid):
    require("ConciergeTech")
    order = get_or_404(db.service_orders, oid)
    body = get_body()
    actual_labor_hours = req_num(body, "actual_labor_hours", minimum=0)
    parts_cents = opt_int(body, "parts_cents", 0, minimum=0)
    if order["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not IN_PROGRESS")
    order["actual_labor_hours"] = actual_labor_hours
    order["parts_cents"] = parts_cents
    order["final_cost_cents"] = service_final(order)
    order["status"] = "COMPLETED"
    touch(order)
    return success(ser_service_order(order))


@bp.post("/service-orders/<oid>/cancel")
def cancel(oid):
    uid, role = require("Member", "VaultManager")
    order = get_or_404(db.service_orders, oid)
    agr = db.agreements.get(order["agreement_id"])
    check_owner(role, uid, agr["member_id"] if agr else None)
    if order["status"] not in ("REQUESTED", "APPROVED", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled")
    order["status"] = "CANCELLED"
    touch(order)
    return success(ser_service_order(order))
