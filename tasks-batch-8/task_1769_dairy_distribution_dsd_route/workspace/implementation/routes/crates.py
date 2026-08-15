"""CrateTransaction endpoints: PICKUP (driver of the route's owner) and
ADJUSTMENT (owner); DROP is system-only. Ledger rules per PRD §2.8."""

from flask import Blueprint, request

from clock import today_date
from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int, opt_enum,
    opt_string, event_fields, paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_STORE_NOT_FOUND, ERR_OWNERSHIP_MISMATCH,
    ERR_INSUFFICIENT_PERMISSIONS, ERR_INSUFFICIENT_CRATE_BALANCE,
)
from serializers import serialize_crate_tx
from services import refresh_store_crates

bp = Blueprint("crate_transactions", __name__)


@bp.post("/dairy/stores/<storeId>/crate-transactions")
def create_crate_tx(storeId):
    user_id, role = require_role("RouteDriver", "DistributorOwner")
    store = DB.stores.get(storeId)
    if store is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    body = get_json_body()
    check_unknown_fields(body, {"kind", "crate_count", "note"})
    require_fields(body, ["kind", "crate_count"])
    kind = opt_enum(body, "kind", {"PICKUP", "ADJUSTMENT", "DROP"})
    if kind == "DROP":
        raise err(ERR_INVALID_REQUEST, "DROP is system-created at delivery only")
    # Kind-restricted role enforcement (RBAC matrix): PICKUP is a RouteDriver
    # operation; ADJUSTMENT is DistributorOwner-only.
    if kind == "PICKUP" and role != "RouteDriver":
        raise err(ERR_INSUFFICIENT_PERMISSIONS,
                  "Only a RouteDriver may record a PICKUP")
    if kind == "ADJUSTMENT" and role != "DistributorOwner":
        raise err(ERR_INSUFFICIENT_PERMISSIONS,
                  "Only a DistributorOwner may record an ADJUSTMENT")
    route = DB.routes.get(store["route_id"])
    if role == "DistributorOwner":
        if route is None or route["distributor_id"] != user_id:
            raise err(ERR_OWNERSHIP_MISMATCH, "Caller does not own the store's route")
    else:  # RouteDriver must belong to the store's route owner
        driver = DB.drivers.get(user_id)
        if (driver is None or route is None
                or driver["distributor_id"] != route["distributor_id"]):
            raise err(ERR_OWNERSHIP_MISMATCH,
                      "Driver's ownership chain must resolve to the store's route owner")
    if kind == "PICKUP":
        count = opt_int(body, "crate_count", gt=0)
    else:  # ADJUSTMENT: signed, non-zero
        count = opt_int(body, "crate_count", ne=0)
    note = opt_string(body, "note")
    new_balance = store["crate_balance"] - count if kind == "PICKUP" \
        else store["crate_balance"] + count
    if new_balance < 0:
        raise err(ERR_INSUFFICIENT_CRATE_BALANCE,
                  "Transaction would drive the crate balance below zero")
    c = event_fields()
    c.update({
        "store_id": store["id"],
        "kind": kind,
        "crate_count": count,
        "service_date": today_date().strftime("%Y-%m-%d"),
        "note": note,
    })
    DB.crate_transactions[c["id"]] = c
    refresh_store_crates(store)
    touch(store)  # each recorded transaction increments the store's version
    return success_object(serialize_crate_tx(c), status=201)


@bp.get("/dairy/stores/<storeId>/crate-transactions")
def list_crate_tx(storeId):
    require_any()
    store = DB.stores.get(storeId)
    if store is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    items = [c for c in DB.crate_transactions.values() if c["store_id"] == storeId]
    kind = request.args.get("kind")
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    items.sort(key=lambda c: c["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_crate_tx(c) for c in page], limit, offset, total)
