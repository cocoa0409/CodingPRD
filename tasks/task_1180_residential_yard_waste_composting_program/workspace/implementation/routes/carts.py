"""Cart endpoints (PRD §3.3)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_CART_LIMIT_EXCEEDED, ERR_HOUSEHOLD_NOT_FOUND,
                    ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_SUBSCRIPTION_NOT_FOUND,
                    err_invalid_state, err_not_found, err_resident_not_owner)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (base_record, touch, cart_out, recompute_cart_fees,
                           SIZE_SURCHARGE)
from services.validate import require_body, check_unknown_fields, req_str, req_int

bp = Blueprint("carts", __name__)

READ_ROLES = ("Resident", "ProgramAdmin", "RouteSupervisor")


@bp.post("/carts")
def create_cart():
    user_id, role = require_roles("Resident")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"household_id", "subscription_id", "size_gallons"})
    household_id = req_str(data, "household_id")
    subscription_id = req_str(data, "subscription_id")
    size = req_int(data, "size_gallons")
    if size not in (35, 64, 96):
        from errors import err_invalid_request
        raise err_invalid_request("size_gallons must be one of 35, 64, 96")

    if user_id != household_id:
        raise err_resident_not_owner()

    hh = STORE.households.get(household_id)
    if not hh:
        raise err_not_found(ERR_HOUSEHOLD_NOT_FOUND, "Household not found")
    sub = STORE.subscriptions.get(subscription_id)
    if not sub:
        raise err_not_found(ERR_SUBSCRIPTION_NOT_FOUND, "Subscription not found")

    # State: subscription ACTIVE required
    if sub["status"] != "ACTIVE":
        raise ApiError(ERR_SUBSCRIPTION_NOT_ACTIVE,
                       "Subscription must be ACTIVE to request a cart", 409)

    # Cart limit: max 2 in REQUESTED/DELIVERED per household
    active_carts = [c for c in STORE.carts.values()
                    if c["household_id"] == household_id and c["status"] in ("REQUESTED", "DELIVERED")]
    if len(active_carts) >= 2:
        raise ApiError(ERR_CART_LIMIT_EXCEEDED,
                       "Household already has 2 carts in REQUESTED/DELIVERED", 409)

    c = base_record()
    c.update({
        "household_id": household_id,
        "subscription_id": subscription_id,
        "size_gallons": size,
        "status": "REQUESTED",
        "delivered_at": None,
        "surcharge_cents": SIZE_SURCHARGE[size],
    })
    STORE.carts[c["id"]] = c
    recompute_cart_fees(subscription_id)
    return success_object(cart_out(c), 201)


@bp.get("/carts")
def list_carts():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.carts.values())
    hid = request.args.get("household_id")
    sid = request.args.get("subscription_id")
    st = request.args.get("status")
    if hid is not None:
        items = [c for c in items if c["household_id"] == hid]
    if sid is not None:
        items = [c for c in items if c["subscription_id"] == sid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([cart_out(c) for c in page], limit, offset, total)


@bp.get("/carts/<cid>")
def get_cart(cid):
    user_id, role = require_roles(*READ_ROLES)
    c = STORE.carts.get(cid)
    if not c:
        raise err_not_found()
    if role == "Resident" and user_id != c["household_id"]:
        raise err_resident_not_owner()
    return success_object(cart_out(c))


@bp.post("/carts/<cid>/deliver")
def deliver_cart(cid):
    require_roles("RouteSupervisor")
    c = STORE.carts.get(cid)
    if not c:
        raise err_not_found()
    if c["status"] != "REQUESTED":
        raise err_invalid_state("Cart is not REQUESTED")
    c["status"] = "DELIVERED"
    c["delivered_at"] = STORE.clock_iso()
    touch(c)
    recompute_cart_fees(c["subscription_id"])
    return success_object(cart_out(c))
