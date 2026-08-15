"""Rental contract endpoints."""
from flask import Blueprint, request

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_UNIT_NOT_AVAILABLE, ERR_STALE_VERSION, ERR_PM_OVERDUE,
    ERR_ACCOUNT_CREDIT_HOLD, ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_RENTAL_WINDOW_OVERLAP, ERR_HOUR_METER_REGRESSION, ERR_UNIT_DISPOSITION_MISMATCH,
)
from util import (
    body_json, req_str, req_int, req_number, req_date,
    new_record, bump, success_object, list_response, get_or_404,
)
import services

bp = Blueprint("rentals", __name__)


@bp.post("/fleet/rental-contracts")
def create_rental():
    _, role = authenticate()
    authorize(role, ["RentalCoordinator"])
    body = body_json()
    unit_id = req_str(body, "unit_id")
    customer_id = req_str(body, "customer_id")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    expected_version = req_int(body, "expected_unit_version")
    if end_date <= start_date:
        raise_err(ERR_INVALID_REQUEST, "end_date must be > start_date")
    unit = get_or_404(store.units, unit_id, "Unit")
    customer = get_or_404(store.customers, customer_id, "Customer")
    # priority 6: availability gate
    if unit["availability_status"] not in ("AVAILABLE", "ON_RENT"):
        raise_err(ERR_UNIT_NOT_AVAILABLE, "Unit availability does not permit rental create")
    # priority 7: OCC
    if expected_version != unit["version"]:
        raise_err(ERR_STALE_VERSION, "expected_unit_version does not match unit's current version")
    # priority 11: disposition gate
    if unit["disposition"] != "RENTAL_FLEET":
        raise_err(ERR_UNIT_DISPOSITION_MISMATCH, "Rental requires disposition RENTAL_FLEET")
    # priority 17: window overlap
    for other in store.rental_contracts.values():
        if other["unit_id"] != unit["id"]:
            continue
        if other["status"] not in ("RESERVED", "ON_RENT"):
            continue
        # half-open [start, end); adjacency allowed
        if start_date < other["end_date"] and end_date > other["start_date"]:
            raise_err(ERR_RENTAL_WINDOW_OVERLAP, "Requested window overlaps an existing reservation")
    # priority 20: account status
    if customer.get("account_status") != "ACTIVE":
        raise_err(ERR_ACCOUNT_CREDIT_HOLD, "Customer account is on CREDIT_HOLD")
    # compute tier and provisional estimate
    scheduled_days = (end_date - start_date).days
    tier = services.rate_tier_of(scheduled_days)
    provisional = services.provisional_estimate_cents(unit, customer, scheduled_days, tier)
    # priority 21: credit fit
    if provisional > services.customer_available_credit(customer):
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED, "Provisional estimate exceeds available credit")
    rec = new_record()
    rec.update({
        "unit_id": unit_id,
        "customer_id": customer_id,
        "start_date": start_date,
        "end_date": end_date,
        "scheduled_days": scheduled_days,
        "rate_tier": tier,
        "provisional_estimate_cents": provisional,
        "final_charge_cents": None,
        "checkout_hours": None,
        "return_hours": None,
        "actual_return_date": None,
        "status": "RESERVED",
    })
    store.rental_contracts[rec["id"]] = rec
    customer["credit_holds_cents"] = customer.get("credit_holds_cents", 0) + provisional
    bump(customer)
    bump(unit)  # OCC: rental create increments unit version
    return success_object(services.serialize_rental_contract(rec), 201)


@bp.get("/fleet/rental-contracts/<rid>")
def get_rental(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rc = get_or_404(store.rental_contracts, rid, "RentalContract")
    return success_object(services.serialize_rental_contract(rc), 200)


@bp.get("/fleet/rental-contracts")
def list_rentals():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.rental_contracts.values())
    unit_id = request.args.get("unit_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if unit_id:
        records = [r for r in records if r["unit_id"] == unit_id]
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return list_response(records, services.serialize_rental_contract)


@bp.post("/fleet/rental-contracts/<rid>/checkout")
def checkout_rental(rid):
    _, role = authenticate()
    authorize(role, ["RentalCoordinator"])
    rc = get_or_404(store.rental_contracts, rid, "RentalContract")
    if rc["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE, "RentalContract must be RESERVED to check out")
    unit = get_or_404(store.units, rc["unit_id"], "Unit")
    customer = get_or_404(store.customers, rc["customer_id"], "Customer")
    if unit["availability_status"] != "AVAILABLE":
        raise_err(ERR_UNIT_NOT_AVAILABLE, "Unit must be AVAILABLE for checkout")
    if unit["maintenance_posture"] != "PM_OK":
        raise_err(ERR_PM_OVERDUE, "Unit is PM_DUE")
    if customer.get("account_status") != "ACTIVE":
        raise_err(ERR_ACCOUNT_CREDIT_HOLD, "Customer account is on CREDIT_HOLD")
    rc["status"] = "ON_RENT"
    rc["checkout_hours"] = unit["hour_meter"]
    bump(rc)
    unit["availability_status"] = "ON_RENT"
    bump(unit)
    return success_object(services.serialize_rental_contract(rc), 200)


@bp.post("/fleet/rental-contracts/<rid>/return")
def return_rental(rid):
    _, role = authenticate()
    authorize(role, ["RentalCoordinator"])
    body = body_json()
    return_date_raw = body.get("return_date")
    from util import parse_date_or_datetime
    return_date = parse_date_or_datetime(return_date_raw)
    if return_date is None:
        raise_err(ERR_INVALID_REQUEST, "return_date must be an ISO date or datetime")
    return_hours = req_number(body, "return_hours")
    rc = get_or_404(store.rental_contracts, rid, "RentalContract")
    if rc["status"] != "ON_RENT":
        raise_err(ERR_INVALID_STATE, "RentalContract must be ON_RENT to return")
    unit = get_or_404(store.units, rc["unit_id"], "Unit")
    customer = get_or_404(store.customers, rc["customer_id"], "Customer")
    if return_hours <= unit["hour_meter"]:
        raise_err(ERR_HOUR_METER_REGRESSION, "return_hours must be strictly greater than current hour_meter")
    actual_days = (return_date - rc["start_date"]).days
    rc["return_hours"] = return_hours
    rc["actual_return_date"] = return_date
    rc["final_charge_cents"] = services.final_charge_cents(
        unit, customer, rc["scheduled_days"], rc["rate_tier"], actual_days
    )
    rc["status"] = "RETURNED"
    bump(rc)
    # financial cascade: release hold, post final charge
    customer["credit_holds_cents"] = max(0, customer.get("credit_holds_cents", 0) - rc["provisional_estimate_cents"])
    services.post_charge_to_customer(customer, rc["final_charge_cents"])
    bump(customer)
    # mechanical cascade: advance hour meter, possibly trigger PM
    unit["hour_meter"] = return_hours
    unit["_last_pm_trigger_customer_id"] = rc["customer_id"]
    services.recompute_posture(unit)
    unit["_last_pm_trigger_customer_id"] = None
    if unit["maintenance_posture"] == "PM_DUE":
        unit["availability_status"] = "IN_SHOP"
    else:
        unit["availability_status"] = "AVAILABLE"
    bump(unit)
    return success_object(services.serialize_rental_contract(rc), 200)


@bp.post("/fleet/rental-contracts/<rid>/cancel")
def cancel_rental(rid):
    _, role = authenticate()
    authorize(role, ["RentalCoordinator"])
    rc = get_or_404(store.rental_contracts, rid, "RentalContract")
    if rc["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE, "RentalContract must be RESERVED to cancel")
    customer = get_or_404(store.customers, rc["customer_id"], "Customer")
    rc["status"] = "CANCELLED"
    bump(rc)
    customer["credit_holds_cents"] = max(0, customer.get("credit_holds_cents", 0) - rc["provisional_estimate_cents"])
    bump(customer)
    return success_object(services.serialize_rental_contract(rc), 200)
