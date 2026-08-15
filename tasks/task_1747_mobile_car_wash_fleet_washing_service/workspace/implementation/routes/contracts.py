"""FleetContract endpoints."""

from flask import Blueprint, request

from db import store
from serialize import ser_contract
from services import early_termination_fee, parse_d
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_int, opt_int, opt_num, stamp_new, touch, parse_date, ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_STALE_VERSION,
)

bp = Blueprint("contracts", __name__)

RATE_FIELDS = ("sedan_rate_cents", "suv_pickup_rate_cents",
               "van_boxtruck_rate_cents", "heavy_fleet_rate_cents")


def _validate_dates(start, end):
    if end <= start:
        raise ApiError(ERR_VALIDATION, "end_date must fall after start_date")


@bp.post("/fleet-wash/fleet-contracts")
def create_contract():
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_NOT_FOUND, "Customer %s not found" % customer_id)
    start = req_str(body, "start_date")
    end = req_str(body, "end_date")
    start_d = parse_date(start, "start_date")
    end_d = parse_date(end, "end_date")
    _validate_dates(start_d, end_d)
    minimum = req_int(body, "monthly_minimum_cents")
    if minimum < 0:
        raise ApiError(ERR_VALIDATION, "monthly_minimum_cents must be >= 0")
    rates = {}
    for f in RATE_FIELDS:
        v = req_int(body, f)
        if v <= 0:
            raise ApiError(ERR_VALIDATION, "%s must be > 0" % f)
        rates[f] = v
    loyalty = opt_num(body, "loyalty_credit_pct", 0)
    if loyalty < 0:
        raise ApiError(ERR_VALIDATION, "loyalty_credit_pct must be >= 0")
    if customer["customer_type"] != "FLEET":
        raise ApiError(ERR_VALIDATION,
                       "FleetContract customer must be a FLEET customer")
    rec = {
        "customer_id": customer_id,
        "start_date": start,
        "end_date": end,
        "monthly_minimum_cents": minimum,
        "sedan_rate_cents": rates["sedan_rate_cents"],
        "suv_pickup_rate_cents": rates["suv_pickup_rate_cents"],
        "van_boxtruck_rate_cents": rates["van_boxtruck_rate_cents"],
        "heavy_fleet_rate_cents": rates["heavy_fleet_rate_cents"],
        "loyalty_credit_pct": loyalty,
        "status": "DRAFT",
        "early_termination_fee_cents": None,
    }
    stamp_new(rec)
    store.contracts[rec["id"]] = rec
    return respond(ser_contract(rec), 201)


@bp.get("/fleet-wash/fleet-contracts/<cid>")
def get_contract(cid):
    uid, role = caller()
    rec = store.contracts.get(cid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "FleetContract %s not found" % cid)
    if role == "Customer" and rec["customer_id"] != uid:
        forbid("Customers may only access their own fleet contracts")
    return respond(ser_contract(rec), 200)


@bp.get("/fleet-wash/fleet-contracts")
def list_contracts():
    uid, role = caller()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            forbid("Customers may only list their own fleet contracts")
        customer_id = uid
    recs = list(store.contracts.values())
    if customer_id is not None:
        recs = [c for c in recs if c["customer_id"] == customer_id]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate(recs, ser_contract)


@bp.put("/fleet-wash/fleet-contracts/<cid>")
def amend_contract(cid):
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    rec = store.contracts.get(cid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "FleetContract %s not found" % cid)
    body = get_body()
    expected = req_int(body, "expected_fleet_contract_version")
    updates = {}
    for f in RATE_FIELDS:
        v = opt_int(body, f)
        if v is not None:
            if v <= 0:
                raise ApiError(ERR_VALIDATION, "%s must be > 0" % f)
            updates[f] = v
    v = opt_int(body, "monthly_minimum_cents")
    if v is not None:
        if v < 0:
            raise ApiError(ERR_VALIDATION, "monthly_minimum_cents must be >= 0")
        updates["monthly_minimum_cents"] = v
    v = opt_num(body, "loyalty_credit_pct")
    if v is not None:
        if v < 0:
            raise ApiError(ERR_VALIDATION, "loyalty_credit_pct must be >= 0")
        updates["loyalty_credit_pct"] = v
    new_start = rec["start_date"]
    new_end = rec["end_date"]
    if body.get("start_date") is not None:
        parse_date(body["start_date"], "start_date")
        new_start = body["start_date"]
    if body.get("end_date") is not None:
        parse_date(body["end_date"], "end_date")
        new_end = body["end_date"]
    _validate_dates(parse_d(new_start), parse_d(new_end))
    if expected != rec["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_fleet_contract_version does not match current version")
    if rec["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE,
                       "FleetContract may only be amended while DRAFT or ACTIVE")
    rec.update(updates)
    rec["start_date"] = new_start
    rec["end_date"] = new_end
    touch(rec)
    return respond(ser_contract(rec), 200)


@bp.post("/fleet-wash/fleet-contracts/<cid>/events")
def contract_event(cid):
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    rec = store.contracts.get(cid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "FleetContract %s not found" % cid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("ACTIVATE", "SUSPEND", "REINSTATE", "TERMINATE"):
        raise ApiError(ERR_VALIDATION,
                       "event_type must be ACTIVATE, SUSPEND, REINSTATE, or TERMINATE")
    if event == "ACTIVATE":
        if rec["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "FleetContract is not DRAFT")
        rec["status"] = "ACTIVE"
    elif event == "SUSPEND":
        if rec["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "FleetContract is not ACTIVE")
        rec["status"] = "SUSPENDED"
    elif event == "REINSTATE":
        if rec["status"] != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, "FleetContract is not SUSPENDED")
        rec["status"] = "ACTIVE"
    else:  # TERMINATE
        if rec["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_INVALID_STATE,
                           "FleetContract is not ACTIVE or SUSPENDED")
        rec["early_termination_fee_cents"] = early_termination_fee(rec)
        rec["status"] = "TERMINATED"
    touch(rec)
    return respond(ser_contract(rec), 200)
