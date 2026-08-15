"""Growers and Buyers: creation, read, suspension cascades."""

from flask import Blueprint

from auth import authorize
from db import store, new_id, stamp_new, touch
from errors import (
    ApiError, ERR_GROWER_NOT_FOUND, ERR_BUYER_NOT_FOUND, ERR_INVALID_STATE,
    ERR_FORBIDDEN_OWNERSHIP,
)
from response import success
from serializers import grower_out, buyer_out
from util import req, as_str, as_int, get_body, invalid

bp = Blueprint("parties", __name__)


# --- Grower -----------------------------------------------------------------

@bp.post("/api/growers")
def create_grower():
    authorize(["PlatformAdmin"])
    body = get_body()
    name = as_str(req(body, "name"), "name")
    region_code = as_str(req(body, "region_code"), "region_code")
    grower = stamp_new({
        "id": new_id(),
        "name": name,
        "region_code": region_code,
        "status": "ACTIVE",
        "settled_tons_ytd": 0.0,
        "outstanding_balance_cents": 0,
    })
    from decimal import Decimal
    grower["settled_tons_ytd"] = Decimal("0.0")
    store["growers"][grower["id"]] = grower
    return success(grower_out(grower), "object", 201)


@bp.get("/api/growers/<grower_id>")
def get_grower(grower_id):
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Grower"])
    grower = store["growers"].get(grower_id)
    if grower is None:
        raise ApiError(ERR_GROWER_NOT_FOUND, 404, "grower not found")
    if role == "Grower" and grower["id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "growers may only read their own record")
    return success(grower_out(grower), "object", 200)


@bp.post("/api/growers/<grower_id>/suspend")
def suspend_grower(grower_id):
    authorize(["PlatformAdmin"])
    grower = store["growers"].get(grower_id)
    if grower is None:
        raise ApiError(ERR_GROWER_NOT_FOUND, 404, "grower not found")
    if grower["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "grower must be ACTIVE to suspend")
    grower["status"] = "SUSPENDED"
    touch(grower)
    # Conditional cascade: cancel their unstarted baling service orders.
    for order in list(store["baling_service_orders"].values()):
        if order["grower_id"] == grower["id"] and order["status"] in ("REQUESTED", "SCHEDULED"):
            order["status"] = "CANCELLED"
            touch(order)
    return success(grower_out(grower), "object", 200)


# --- Buyer ------------------------------------------------------------------

@bp.post("/api/buyers")
def create_buyer():
    authorize(["PlatformAdmin"])
    body = get_body()
    name = as_str(req(body, "name"), "name")
    region_code = as_str(req(body, "region_code"), "region_code")
    credit_limit = as_int(req(body, "credit_limit_cents"), "credit_limit_cents")
    if credit_limit <= 0:
        invalid("credit_limit_cents must be greater than zero")
    buyer = stamp_new({
        "id": new_id(),
        "name": name,
        "region_code": region_code,
        "credit_limit_cents": credit_limit,
        "credit_used_cents": 0,
        "status": "ACTIVE",
    })
    store["buyers"][buyer["id"]] = buyer
    return success(buyer_out(buyer), "object", 201)


@bp.get("/api/buyers/<buyer_id>")
def get_buyer(buyer_id):
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Buyer"])
    buyer = store["buyers"].get(buyer_id)
    if buyer is None:
        raise ApiError(ERR_BUYER_NOT_FOUND, 404, "buyer not found")
    if role == "Buyer" and buyer["id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "buyers may only read their own record")
    return success(buyer_out(buyer), "object", 200)


@bp.post("/api/buyers/<buyer_id>/suspend")
def suspend_buyer(buyer_id):
    authorize(["PlatformAdmin"])
    buyer = store["buyers"].get(buyer_id)
    if buyer is None:
        raise ApiError(ERR_BUYER_NOT_FOUND, 404, "buyer not found")
    if buyer["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "buyer must be ACTIVE to suspend")
    buyer["status"] = "SUSPENDED"
    touch(buyer)
    # Cascade: ACTIVE contracts -> SUSPENDED; the credit reserve stays held.
    for contract in list(store["contracts"].values()):
        if contract["buyer_id"] == buyer["id"] and contract["status"] == "ACTIVE":
            contract["status"] = "SUSPENDED"
            touch(contract)
    return success(buyer_out(buyer), "object", 200)
