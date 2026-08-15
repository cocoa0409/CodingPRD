"""Fleet accounts (PRD 3.3)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import authorized, scope_fleet
from response import success_object
from routes.helpers import list_from, public
from services.core import new_record, recompute_fleet_rolling_and_tier, touch
from validate import (
    get_body, opt_int, query_filter, req_enum, req_int, req_str,
    require_path_resource,
)

bp = Blueprint("fleets", __name__)

TIERS = ["T1", "T2", "T3"]
READ_ROLES = ["GeneralManager", "FleetManager"]
CONTRACT_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED"]


@bp.post("/fleet-accounts")
def create_fleet():
    authorized(["GeneralManager"])
    body = get_body()
    name = req_str(body, "name")
    credit_limit = req_int(body, "credit_limit_cents", non_negative=True)
    tier = req_enum(body, "pricing_tier", TIERS)
    rec = new_record("fleet_accounts", {
        "name": name,
        "credit_limit_cents": credit_limit,
        "current_balance_cents": 0,
        "pricing_tier": tier,
        "rolling_30d_gallons": 0.0,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/fleet-accounts/<rid>")
def get_fleet(rid):
    caller = authorized(READ_ROLES)
    fleet = require_path_resource("fleet_accounts", rid)
    scope_fleet(caller, fleet["id"])
    return success_object(public(fleet))


@bp.patch("/fleet-accounts/<rid>")
def patch_fleet(rid):
    authorized(["GeneralManager"])
    fleet = require_path_resource("fleet_accounts", rid)
    body = get_body()
    new_limit = opt_int(body, "credit_limit_cents", None, non_negative=True)
    if new_limit is not None and new_limit != fleet["credit_limit_cents"]:
        fleet["credit_limit_cents"] = new_limit
        touch(fleet)
    return success_object(public(fleet))


@bp.post("/fleet-accounts/<rid>/credit-hold")
def credit_hold(rid):
    authorized(["GeneralManager"])
    fleet = require_path_resource("fleet_accounts", rid)
    if fleet["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "fleet is not ACTIVE")
    fleet["status"] = "CREDIT_HOLD"
    touch(fleet)
    return success_object(public(fleet))


@bp.post("/fleet-accounts/<rid>/credit-reinstate")
def credit_reinstate(rid):
    authorized(["GeneralManager"])
    fleet = require_path_resource("fleet_accounts", rid)
    if fleet["status"] != "CREDIT_HOLD":
        raise_error(ERR_INVALID_STATE, "fleet is not CREDIT_HOLD")
    fleet["status"] = "ACTIVE"
    touch(fleet)
    return success_object(public(fleet))


@bp.post("/fleet-accounts/<rid>/close")
def close_fleet(rid):
    authorized(["GeneralManager"])
    fleet = require_path_resource("fleet_accounts", rid)
    if fleet["status"] not in ("ACTIVE", "CREDIT_HOLD"):
        raise_error(ERR_INVALID_STATE, "fleet cannot be closed from its current state")
    if fleet["current_balance_cents"] != 0:
        raise_error(ERR_INVALID_STATE, "fleet balance must be zero to close")
    fleet["status"] = "CLOSED"
    touch(fleet)
    for contract in db["contracts"].values():
        if contract["fleet_account_id"] == fleet["id"] \
                and contract["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            contract["status"] = "TERMINATED"
            touch(contract)
    return success_object(public(fleet))


@bp.post("/fleet-accounts/<rid>/tier-recompute")
def tier_recompute(rid):
    authorized(["GeneralManager"])
    fleet = require_path_resource("fleet_accounts", rid)
    recompute_fleet_rolling_and_tier(fleet)
    return success_object(public(fleet))


@bp.get("/fleet-accounts/<rid>/contracts")
def fleet_contracts(rid):
    caller = authorized(READ_ROLES)
    fleet = require_path_resource("fleet_accounts", rid)
    scope_fleet(caller, fleet["id"])
    contracts = [c for c in db["contracts"].values() if c["fleet_account_id"] == fleet["id"]]
    return list_from(contracts, {"status": query_filter("status", CONTRACT_STATUSES)})


@bp.get("/fleet-accounts/<rid>/loyalty-members")
def fleet_members(rid):
    caller = authorized(READ_ROLES)
    fleet = require_path_resource("fleet_accounts", rid)
    scope_fleet(caller, fleet["id"])
    members = [m for m in db["loyalty_members"].values() if m["fleet_account_id"] == fleet["id"]]
    return list_from(members)


@bp.get("/fleet-accounts/<rid>/fuel-sales")
def fleet_fuel_sales(rid):
    caller = authorized(READ_ROLES)
    fleet = require_path_resource("fleet_accounts", rid)
    scope_fleet(caller, fleet["id"])
    sales = [s for s in db["fuel_sales"].values() if s["fleet_account_id"] == fleet["id"]]
    return list_from(sales)


@bp.get("/fleet-accounts/<rid>/work-orders")
def fleet_work_orders(rid):
    caller = authorized(READ_ROLES + ["MaintenanceTech"])
    fleet = require_path_resource("fleet_accounts", rid)
    scope_fleet(caller, fleet["id"])
    wos = [w for w in db["work_orders"].values() if w["fleet_account_id"] == fleet["id"]]
    return list_from(wos)
