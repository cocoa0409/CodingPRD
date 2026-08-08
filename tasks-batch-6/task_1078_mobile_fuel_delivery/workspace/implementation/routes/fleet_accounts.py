from flask import Blueprint, request

import store
from store import DB
from core import (ApiError, get_auth, require_role, get_body, require_fields,
                  as_int, ok, ok_list, paginate, sorted_records, base_record,
                  touch, deny)
from serializers import ser_fleet_account
from domain import get_customer, get_fleet_account, NON_TERMINAL_ORDER

bp = Blueprint("fleet_accounts", __name__)


def _validate_fuel_types(arr):
    if not isinstance(arr, list):
        raise ApiError("ERR_VALIDATION", "allowed_fuel_types must be an array")
    for x in arr:
        if x not in store.FUEL_TYPES:
            raise ApiError("ERR_VALIDATION", "Invalid fuel type: %s" % x)
    return list(arr)


def _validate_addons(arr):
    if not isinstance(arr, list):
        raise ApiError("ERR_VALIDATION", "allowed_addons must be an array")
    for x in arr:
        if x not in store.ADDON_TYPES:
            raise ApiError("ERR_VALIDATION", "Invalid addon type: %s" % x)
    return list(arr)


@bp.post("/fleet-accounts")
def create_fleet_account():
    uid, role = get_auth()
    require_role(role, {"FleetManager"})
    body = get_body()
    require_fields(body, ["customer_id", "monthly_budget_cap_cents",
                          "allowed_fuel_types", "allowed_addons"])
    as_int(body["monthly_budget_cap_cents"], "monthly_budget_cap_cents", minimum=0)
    fuel_types = _validate_fuel_types(body["allowed_fuel_types"])
    addons = _validate_addons(body["allowed_addons"])
    if body["customer_id"] != uid:
        deny()
    cust = get_customer(body["customer_id"])
    if cust["customer_type"] != "FLEET":
        raise ApiError("ERR_CUSTOMER_NOT_FLEET", "Customer is not a FLEET customer")
    rec = base_record()
    rec.update({
        "customer_id": body["customer_id"],
        "monthly_budget_cap_cents": body["monthly_budget_cap_cents"],
        "allowed_fuel_types": fuel_types,
        "allowed_addons": addons,
        "committed_budget_cents": 0,
        "settled_budget_cents": 0,
        "active_vehicle_count": 0,
        "suspended_vehicle_count": 0,
        "status": "ACTIVE",
    })
    DB.fleet_accounts[rec["id"]] = rec
    return ok(ser_fleet_account(rec), status=201)


@bp.get("/fleet-accounts")
def list_fleet_accounts():
    uid, role = get_auth()
    require_role(role, {"FleetManager", "PlatformAdmin", "BillingOfficer"})
    items = sorted_records(DB.fleet_accounts)
    if role == "FleetManager":
        items = [f for f in items if f["customer_id"] == uid]
    cid = request.args.get("customer_id")
    st = request.args.get("status")
    if cid:
        items = [f for f in items if f["customer_id"] == cid]
    if st:
        items = [f for f in items if f["status"] == st]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_fleet_account(f) for f in page], total, limit, offset)


@bp.get("/fleet-accounts/<fid>")
def get_fleet_account_ep(fid):
    uid, role = get_auth()
    require_role(role, {"FleetManager", "PlatformAdmin", "BillingOfficer"})
    f = get_fleet_account(fid)
    if role == "FleetManager" and f["customer_id"] != uid:
        deny()
    return ok(ser_fleet_account(f))


@bp.patch("/fleet-accounts/<fid>")
def update_fleet_account(fid):
    uid, role = get_auth()
    require_role(role, {"FleetManager"})
    f = get_fleet_account(fid)
    if f["customer_id"] != uid:
        deny()
    body = get_body()
    require_fields(body, ["expected_fleet_account_version"])
    as_int(body["expected_fleet_account_version"], "expected_fleet_account_version")
    if body["expected_fleet_account_version"] != f["version"]:
        raise ApiError("ERR_STALE_FLEET_ACCOUNT_VERSION", "Stale fleet account version")
    if "monthly_budget_cap_cents" in body and body["monthly_budget_cap_cents"] is not None:
        as_int(body["monthly_budget_cap_cents"], "monthly_budget_cap_cents", minimum=0)
        f["monthly_budget_cap_cents"] = body["monthly_budget_cap_cents"]
    if "allowed_fuel_types" in body and body["allowed_fuel_types"] is not None:
        f["allowed_fuel_types"] = _validate_fuel_types(body["allowed_fuel_types"])
    if "allowed_addons" in body and body["allowed_addons"] is not None:
        f["allowed_addons"] = _validate_addons(body["allowed_addons"])
    touch(f)
    return ok(ser_fleet_account(f))


@bp.post("/fleet-accounts/<fid>/suspend")
def suspend_fleet_account(fid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    f = get_fleet_account(fid)
    if f["status"] != "ACTIVE":
        raise ApiError("ERR_FLEET_ACCOUNT_SUSPENDED", "Fleet account not ACTIVE")
    f["status"] = "SUSPENDED"
    touch(f)
    return ok(ser_fleet_account(f))


@bp.post("/fleet-accounts/<fid>/reactivate")
def reactivate_fleet_account(fid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    f = get_fleet_account(fid)
    if f["status"] != "SUSPENDED":
        raise ApiError("ERR_FLEET_ACCOUNT_SUSPENDED", "Fleet account not SUSPENDED")
    f["status"] = "ACTIVE"
    touch(f)
    return ok(ser_fleet_account(f))


@bp.post("/fleet-accounts/<fid>/close")
def close_fleet_account(fid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    f = get_fleet_account(fid)
    if f["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_FLEET_ACCOUNT_SUSPENDED", "Fleet account cannot be closed from %s" % f["status"])
    for o in DB.orders.values():
        if o["fleet_account_id"] == fid and o["status"] in NON_TERMINAL_ORDER:
            raise ApiError("ERR_FLEET_ACCOUNT_HAS_ACTIVE_ORDERS", "Fleet account has active orders")
    f["status"] = "CLOSED"
    touch(f)
    return ok(ser_fleet_account(f))
