"""Repair Requests + replacement spin-off (PRD §3.8)."""
from flask import Blueprint, request

from db import db, base_common_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object, ok_array
from validation import (get_json_body, require_str, require_int, lookup,
                        parse_pagination, paginate)
from clock import parse_iso
from services import touch, LABOR_FLAT_CENTS
from serializers import repair_request_out

bp = Blueprint("repairs", __name__)


@bp.route("/op/repair-requests", methods=["POST"])
def report_repair():
    _, role = get_auth()
    require_roles(role, {"Practitioner", "BillingSpecialist"})
    body = get_json_body()

    device_order_id = require_str(body, "device_order_id")
    order = lookup(db.device_orders, device_order_id)

    # Must be against a DELIVERED order.
    if order["status"] != "DELIVERED":
        raise ApiError("ERR_NOT_DELIVERED", "Repair can only be reported on a DELIVERED order.")

    rr = base_common_fields()
    rr.update({
        "device_order_id": device_order_id,
        "replaces_order_id": None,
        "status": "REPORTED",
        "cost_cents": 0,
        "warranty_applies": False,
    })
    db.repair_requests[rr["id"]] = rr
    return ok_object(repair_request_out(rr), 201)


@bp.route("/op/repair-requests/<rid>", methods=["GET"])
def get_repair(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner", "BillingSpecialist", "ComplianceOfficer"})
    rr = lookup(db.repair_requests, rid)
    return ok_object(repair_request_out(rr), 200)


@bp.route("/op/repair-requests", methods=["GET"])
def list_repairs():
    _, role = get_auth()
    require_roles(role, {"Practitioner", "BillingSpecialist", "ComplianceOfficer"})
    limit, offset = parse_pagination()

    items = list(db.repair_requests.values())
    device_order_id = request.args.get("device_order_id")
    replaces_order_id = request.args.get("replaces_order_id")
    if device_order_id is not None:
        items = [r for r in items if r["device_order_id"] == device_order_id]
    if replaces_order_id is not None:
        items = [r for r in items if r["replaces_order_id"] == replaces_order_id]
    page, total = paginate(items, limit, offset)
    return ok_array([repair_request_out(r) for r in page], limit, offset, total, 200)


@bp.route("/op/repair-requests/<rid>/assess", methods=["POST"])
def assess(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    rr = lookup(db.repair_requests, rid)
    body = get_json_body()

    if rr["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", "RepairRequest is not in REPORTED.")

    parts_cents = require_int(body, "parts_cents")
    if parts_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", "parts_cents must be >= 0.")

    order = db.device_orders.get(rr["device_order_id"])
    # repair_cost: warranty applies when report date (created_at) <=
    # warranty_expiry, inclusive boundary.
    report_dt = parse_iso(rr["created_at"])
    warranty_expiry = order.get("warranty_expiry")
    warranty_applies = warranty_expiry is not None and report_dt <= parse_iso(warranty_expiry)

    rr["warranty_applies"] = warranty_applies
    rr["cost_cents"] = 0 if warranty_applies else (LABOR_FLAT_CENTS + parts_cents)
    rr["status"] = "ASSESSED"
    touch(rr)
    return ok_object(repair_request_out(rr), 200)


@bp.route("/op/repair-requests/<rid>/complete-repair", methods=["POST"])
def complete_repair(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    rr = lookup(db.repair_requests, rid)
    if rr["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", "RepairRequest is not in ASSESSED.")
    rr["status"] = "REPAIRED"
    touch(rr)
    return ok_object(repair_request_out(rr), 200)


@bp.route("/op/repair-requests/<rid>/authorize-replacement", methods=["POST"])
def authorize_replacement(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    rr = lookup(db.repair_requests, rid)

    if rr["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", "RepairRequest is not in ASSESSED.")
    # Replacement only outside warranty (priority 13).
    if rr["warranty_applies"]:
        raise ApiError("ERR_REPLACEMENT_IN_WARRANTY", "Replacement cannot be authorized while warranty applies.")

    order = db.device_orders.get(rr["device_order_id"])
    # CASCADE: create a new DeviceOrder in INTAKE cloning prescription/supplier.
    new_order = base_common_fields()
    new_order.update({
        "prescription_id": order["prescription_id"],
        "supplier_id": order["supplier_id"],
        "fitting_practitioner_id": order["fitting_practitioner_id"],
        "status": "INTAKE",
        "requires_prior_auth": order["requires_prior_auth"],
        "milestone_progress_pct": 0,
        "delivery_date": None,
        "warranty_expiry": None,
        "allowed_total_cents": 0,
    })
    db.device_orders[new_order["id"]] = new_order

    rr["replaces_order_id"] = new_order["id"]
    rr["status"] = "REPLACEMENT_AUTHORIZED"
    touch(rr)
    return ok_object(repair_request_out(rr), 200)


@bp.route("/op/repair-requests/<rid>/close", methods=["POST"])
def close_repair(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    rr = lookup(db.repair_requests, rid)
    if rr["status"] not in ("REPAIRED", "REPLACEMENT_AUTHORIZED"):
        raise ApiError("ERR_INVALID_STATE", "RepairRequest cannot be closed from its current state.")
    rr["status"] = "CLOSED"
    touch(rr)
    return ok_object(repair_request_out(rr), 200)
