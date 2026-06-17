"""Brokerage and Broker endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db, new_full_record, touch
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from serialize import serialize, serialize_many
from services.access import resolve
from validate import (parse_body, check_str_type, check_number_type,
                      parse_pagination, paginate)

bp = Blueprint("brokerages", __name__)

VALID_SIDES = {"LISTING", "TENANT_REP", "DUAL"}
VALID_BROKER_ROLES = {"LISTING_BROKER", "TENANT_BROKER", "ADMIN"}


@bp.post("/brokerages")
def create_brokerage():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin"])
    body = parse_body()
    name = check_str_type(body, "name", required=True)
    side = check_str_type(body, "side", required=True)
    commission = check_number_type(body, "default_commission_pct",
                                   required=False, default=0.06)
    if side not in VALID_SIDES:
        raise err("ERR_INVALID_REQUEST", "Invalid side")
    if not (0 < commission <= 0.15):
        raise err("ERR_INVALID_REQUEST", "default_commission_pct out of range")
    rec = new_full_record({
        "name": name,
        "side": side,
        "default_commission_pct": commission,
    })
    db.brokerages[rec["id"]] = rec
    return success(serialize("Brokerage", rec), status=201)


@bp.get("/brokerages/<brokerage_id>")
def get_brokerage(brokerage_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.brokerages, brokerage_id)
    return success(serialize("Brokerage", rec), status=200)


@bp.post("/brokers")
def create_broker():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin"])
    body = parse_body()
    brokerage_id = check_str_type(body, "brokerage_id", required=True)
    full_name = check_str_type(body, "full_name", required=True)
    license_no = check_str_type(body, "license_no", required=True)
    broker_role = check_str_type(body, "role", required=True)
    if broker_role not in VALID_BROKER_ROLES:
        raise err("ERR_INVALID_REQUEST", "Invalid broker role")
    # FK existence (priority 3)
    resolve(db.brokerages, brokerage_id)
    # license_no uniqueness (priority 5)
    for b in db.brokers.values():
        if b["license_no"] == license_no:
            raise err("ERR_INVALID_REQUEST", "license_no already in use")
    rec = new_full_record({
        "brokerage_id": brokerage_id,
        "full_name": full_name,
        "license_no": license_no,
        "role": broker_role,
        "status": "ACTIVE",
    })
    db.brokers[rec["id"]] = rec
    return success(serialize("Broker", rec), status=201)


@bp.get("/brokers/<broker_id>")
def get_broker(broker_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.brokers, broker_id)
    return success(serialize("Broker", rec), status=200)


@bp.get("/brokers")
def list_brokers():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    from flask import request
    brokerage_id = request.args.get("brokerage_id")
    items = list(db.brokers.values())
    if brokerage_id is not None:
        items = [b for b in items if b["brokerage_id"] == brokerage_id]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Broker", page), limit, offset, total)


@bp.post("/brokers/<broker_id>/suspend")
def suspend_broker(broker_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin"])
    rec = resolve(db.brokers, broker_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Broker is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(serialize("Broker", rec), status=200)
