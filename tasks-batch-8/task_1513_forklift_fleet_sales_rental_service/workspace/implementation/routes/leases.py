"""Lease contract and inspection endpoints."""
from flask import Blueprint, request

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_UNIT_NOT_AVAILABLE, ERR_UNIT_DISPOSITION_MISMATCH,
    ERR_INSPECTION_NOT_APPROVED,
)
from util import (
    body_json, req_str, req_int, req_number, req_date, parse_date_or_datetime,
    new_record, new_child_record, bump, success_object, list_response, get_or_404,
)
import services

bp = Blueprint("leases", __name__)


@bp.post("/fleet/lease-contracts")
def create_lease():
    _, role = authenticate()
    authorize(role, ["LeaseManager"])
    body = body_json()
    unit_id = req_str(body, "unit_id")
    customer_id = req_str(body, "customer_id")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    allowed_hours = req_int(body, "allowed_hours")
    excess_rate = req_int(body, "excess_hour_rate_cents")
    residual = req_int(body, "residual_value_cents")
    if end_date <= start_date:
        raise_err(ERR_INVALID_REQUEST, "end_date must be > start_date")
    if allowed_hours < 0:
        raise_err(ERR_INVALID_REQUEST, "allowed_hours must be >= 0")
    if excess_rate < 0:
        raise_err(ERR_INVALID_REQUEST, "excess_hour_rate_cents must be >= 0")
    if residual < 0:
        raise_err(ERR_INVALID_REQUEST, "residual_value_cents must be >= 0")
    unit = get_or_404(store.units, unit_id, "Unit")
    customer = get_or_404(store.customers, customer_id, "Customer")
    if unit["availability_status"] != "AVAILABLE":
        raise_err(ERR_UNIT_NOT_AVAILABLE, "Unit must be AVAILABLE for lease creation")
    if unit["disposition"] not in ("NEW_SALE", "RENTAL_FLEET"):
        raise_err(ERR_UNIT_DISPOSITION_MISMATCH, "Lease requires disposition NEW_SALE or RENTAL_FLEET")
    rec = new_record()
    rec.update({
        "unit_id": unit_id,
        "customer_id": customer_id,
        "start_date": start_date,
        "end_date": end_date,
        "allowed_hours": allowed_hours,
        "excess_hour_rate_cents": excess_rate,
        "residual_value_cents": residual,
        "return_date": None,
        "settlement_total_cents": None,
        "status": "ACTIVE",
    })
    store.lease_contracts[rec["id"]] = rec
    unit["availability_status"] = "ON_LEASE"
    bump(unit)
    return success_object(services.serialize_lease_contract(rec), 201)


@bp.get("/fleet/lease-contracts/<lid>")
def get_lease(lid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    lc = get_or_404(store.lease_contracts, lid, "LeaseContract")
    return success_object(services.serialize_lease_contract(lc), 200)


@bp.get("/fleet/lease-contracts")
def list_leases():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.lease_contracts.values())
    unit_id = request.args.get("unit_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if unit_id:
        records = [r for r in records if r["unit_id"] == unit_id]
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return list_response(records, services.serialize_lease_contract)


@bp.post("/fleet/lease-contracts/<lid>/return")
def return_lease(lid):
    _, role = authenticate()
    authorize(role, ["LeaseManager"])
    body = body_json()
    return_date_raw = body.get("return_date")
    return_date = parse_date_or_datetime(return_date_raw)
    if return_date is None:
        raise_err(ERR_INVALID_REQUEST, "return_date must be an ISO date or datetime")
    lc = get_or_404(store.lease_contracts, lid, "LeaseContract")
    if lc["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "LeaseContract must be ACTIVE to return")
    unit = get_or_404(store.units, lc["unit_id"], "Unit")
    lc["return_date"] = return_date
    lc["status"] = "RETURNED"
    bump(lc)
    unit["availability_status"] = "AVAILABLE"
    unit["disposition"] = "USED_SALE"
    bump(unit)
    return success_object(services.serialize_lease_contract(lc), 200)


@bp.post("/fleet/lease-contracts/<lid>/inspections")
def create_inspection(lid):
    _, role = authenticate()
    authorize(role, ["LeaseManager"])
    body = body_json()
    grade = req_str(body, "condition_grade")
    if grade not in ("A", "B", "C", "D"):
        raise_err(ERR_INVALID_REQUEST, "condition_grade must be A, B, C, or D")
    hours_at_return = req_number(body, "hours_at_return")
    appraised = req_int(body, "appraised_value_cents")
    if hours_at_return < 0:
        raise_err(ERR_INVALID_REQUEST, "hours_at_return must be >= 0")
    if appraised < 0:
        raise_err(ERR_INVALID_REQUEST, "appraised_value_cents must be >= 0")
    lc = get_or_404(store.lease_contracts, lid, "LeaseContract")
    if lc["status"] != "RETURNED":
        raise_err(ERR_INVALID_STATE, "Lease must be RETURNED to record an inspection")
    rec = new_child_record()
    rec.update({
        "lease_id": lc["id"],
        "condition_grade": grade,
        "hours_at_return": hours_at_return,
        "appraised_value_cents": appraised,
        "wear_charge_cents": services.WEAR_TABLE[grade],
        "status": "SUBMITTED",
    })
    store.lease_inspections[rec["id"]] = rec
    return success_object(services.serialize_lease_inspection(rec), 201)


@bp.get("/fleet/lease-contracts/<lid>/inspections")
def list_inspections(lid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    lc = get_or_404(store.lease_contracts, lid, "LeaseContract")
    insps = [i for i in store.lease_inspections.values() if i["lease_id"] == lc["id"]]
    return list_response(insps, services.serialize_lease_inspection)


@bp.post("/fleet/inspections/<iid>/approve")
def approve_inspection(iid):
    _, role = authenticate()
    authorize(role, ["LeaseManager"])
    insp = get_or_404(store.lease_inspections, iid, "LeaseInspection")
    if insp["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Inspection must be SUBMITTED to approve")
    for other in store.lease_inspections.values():
        if other["lease_id"] == insp["lease_id"] and other["status"] == "APPROVED":
            raise_err(ERR_INVALID_STATE, "Lease already has an APPROVED inspection")
    insp["status"] = "APPROVED"
    return success_object(services.serialize_lease_inspection(insp), 200)


@bp.post("/fleet/lease-contracts/<lid>/settle")
def settle_lease(lid):
    _, role = authenticate()
    authorize(role, ["LeaseManager"])
    lc = get_or_404(store.lease_contracts, lid, "LeaseContract")
    # priority 5: state must be RETURNED first
    if lc["status"] != "RETURNED":
        raise_err(ERR_INVALID_STATE, "Lease must be RETURNED to settle")
    # then the approved-inspection requirement
    approved = [i for i in store.lease_inspections.values()
                if i["lease_id"] == lc["id"] and i["status"] == "APPROVED"]
    if len(approved) != 1:
        raise_err(ERR_INSPECTION_NOT_APPROVED, "Lease must have exactly one APPROVED inspection")
    inspection = approved[0]
    total = services.lease_settlement_total(lc, inspection)
    lc["settlement_total_cents"] = total
    lc["status"] = "SETTLED"
    bump(lc)
    customer = get_or_404(store.customers, lc["customer_id"], "Customer")
    services.post_charge_to_customer(customer, total)
    bump(customer)
    return success_object(services.serialize_lease_contract(lc), 200)
