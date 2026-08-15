"""WaterAccount endpoints: create, list, get, close."""
from datetime import date
from flask import Blueprint

from db import store, new_id, new_common, touch, iso_out
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity

bp = Blueprint("accounts", __name__)

PRIORITY_CUT_DATE = date(1914, 12, 31)
READ_ROLES = ["DistrictAdmin", "WaterUser", "DitchRider"]

_CREATE_SCHEMA = {
    "holder_name": ("string", True, None, None),
    "parcel_number": ("string", True, None, None),
    "irrigated_acres": ("number", True, None, "gt0"),
    "water_right_priority_date": ("datetime", True, None, None),
}


@bp.post("/district/water-accounts")
def create_account():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    require_roles(["DistrictAdmin"])
    pdate = body["_water_right_priority_date_dt"]
    # SENIOR if the water right's priority date falls on or before 1914-12-31.
    pclass = "SENIOR" if pdate.date() <= PRIORITY_CUT_DATE else "JUNIOR"
    acct = new_common({
        "id": new_id(),
        "holder_name": body["holder_name"],
        "parcel_number": body["parcel_number"],
        "irrigated_acres": body["irrigated_acres"],
        "water_right_priority_date": iso_out(pdate),
        "_priority_dt": pdate,
        "priority_class": pclass,
        "status": "ACTIVE",
    })
    store.water_accounts[acct["id"]] = acct
    return created(acct)


@bp.get("/district/water-accounts")
def list_accounts():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = filter_eq(list(store.water_accounts.values()), "status")
    return list_ok(rows)


@bp.get("/district/water-accounts/<aid>")
def get_account(aid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.water_accounts, aid))


@bp.post("/district/water-accounts/<aid>/close")
def close_account(aid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    acct = require_path_entity(store.water_accounts, aid)
    if acct["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_ACCOUNT_STATE", 409,
                       "Account is already CLOSED (terminal)")
    for o in store.turnout_orders.values():
        if o["water_account_id"] == aid and o["status"] in ("REQUESTED", "SCHEDULED", "FLOWING"):
            raise ApiError("ERR_INVALID_ACCOUNT_STATE", 409,
                           "Account has a non-terminal turnout order")
    for t in store.transfer_requests.values():
        if aid in (t["from_account_id"], t["to_account_id"]) \
                and t["status"] in ("PENDING", "APPROVED"):
            raise ApiError("ERR_INVALID_ACCOUNT_STATE", 409,
                           "Account has a non-terminal transfer request")
    acct["status"] = "CLOSED"
    touch(acct)
    return ok(acct)
