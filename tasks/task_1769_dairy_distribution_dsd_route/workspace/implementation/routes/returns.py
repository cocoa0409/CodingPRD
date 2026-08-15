"""Return endpoints: submit scan (RouteDriver), review (owner), dispute (receiver)."""

from flask import Blueprint, request

from db import DB
from middleware import require_role, require_any, owner_check_store_receiver
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int, opt_enum,
    opt_date_str, paginate, err, apply_changes,
)
from response import success_object, success_list
from errors import (
    ERR_ORDER_NOT_FOUND, ERR_STORE_NOT_FOUND, ERR_TRIP_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND, ERR_RETURN_NOT_FOUND, ERR_OWNERSHIP_MISMATCH,
    ERR_RETURN_PRODUCT_NOT_DELIVERED, ERR_RETURN_STORE_MISMATCH,
    ERR_RETURN_NOT_REVIEWABLE, ERR_RETURN_NOT_DISPUTABLE,
)
from serializers import serialize_return
from services import (
    create_return_record, returned_units_so_far, approve_return_side_effects,
)

bp = Blueprint("returns", __name__)


def get_return_or_404(return_id):
    r = DB.returns.get(return_id)
    if r is None:
        raise err(ERR_RETURN_NOT_FOUND, "Return id not found")
    return r


def owner_check_return(user_id, ret):
    store = DB.stores.get(ret["store_id"])
    route = DB.routes.get(store["route_id"]) if store else None
    if route is None or route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH,
                  "Caller does not own the route serving the return's store")


@bp.post("/dairy/returns")
def create_return():
    user_id, _role = require_role("RouteDriver")
    body = get_json_body()
    check_unknown_fields(body, {"order_id", "store_id", "pickup_trip_id",
                                "product_id", "quantity_units", "reason_code",
                                "scanned_code_date"})
    require_fields(body, ["order_id", "store_id", "pickup_trip_id", "product_id",
                          "quantity_units", "reason_code", "scanned_code_date"])
    order = DB.orders.get(body["order_id"])
    if order is None:
        raise err(ERR_ORDER_NOT_FOUND, "RouteOrder id not found")
    # Ownership (priority 3): caller must be the driver of the order's trip.
    order_trip = DB.trips.get(order["trip_id"])
    if order_trip is None or order_trip["driver_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller must be the driver of the order's trip")
    store = DB.stores.get(body["store_id"])
    if store is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    pickup_trip = DB.trips.get(body["pickup_trip_id"])
    if pickup_trip is None:
        raise err(ERR_TRIP_NOT_FOUND, "TruckTrip id not found")
    product = DB.products.get(body["product_id"])
    if product is None:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product id not found")
    quantity = opt_int(body, "quantity_units", gt=0)
    reason = opt_enum(body, "reason_code",
                      {"OUT_OF_CODE", "PULL_POLICY", "DAMAGED", "COLD_CHAIN"})
    scanned = opt_date_str(body, "scanned_code_date")
    # Referential (priority 10), in scaffold-listed order.
    if order["fulfillment_status"] != "DELIVERED":
        raise err(ERR_RETURN_PRODUCT_NOT_DELIVERED,
                  "The order must be DELIVERED to accept returns")
    line = next((l for l in order["lines"] if l["product_id"] == product["id"]), None)
    if line is None or "delivered_units" not in line:
        raise err(ERR_RETURN_PRODUCT_NOT_DELIVERED,
                  "Product is not among the order's delivered lines")
    already = returned_units_so_far(order["id"], product["id"])
    if already + quantity > line["delivered_units"]:
        raise err(ERR_RETURN_PRODUCT_NOT_DELIVERED,
                  "Cumulative returned units exceed the delivered quantity")
    if store["id"] != order["store_id"]:
        raise err(ERR_RETURN_STORE_MISMATCH,
                  "Caller-supplied store context does not match the order's store")
    r = create_return_record(
        order=order,
        pickup_trip_id=pickup_trip["id"],
        product_id=product["id"],
        quantity_units=quantity,
        reason_code=reason,
        scanned_code_date=scanned,
        initial_status="UNDER_REVIEW",
        system_created=False,
    )
    return success_object(serialize_return(r), status=201)


@bp.get("/dairy/returns/<returnId>")
def get_return(returnId):
    require_any()
    return success_object(serialize_return(get_return_or_404(returnId)))


@bp.get("/dairy/returns")
def list_returns():
    require_any()
    items = list(DB.returns.values())
    for param, field in (("order_id", "order_id"), ("store_id", "store_id"),
                         ("pickup_trip_id", "pickup_trip_id"),
                         ("product_id", "product_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    items.sort(key=lambda r: r["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_return(r) for r in page], limit, offset, total)


@bp.post("/dairy/returns/<returnId>/approve")
def approve_return(returnId):
    user_id, _role = require_role("DistributorOwner")
    r = get_return_or_404(returnId)
    owner_check_return(user_id, r)
    if r["status"] not in ("UNDER_REVIEW", "DISPUTED"):
        raise err(ERR_RETURN_NOT_REVIEWABLE,
                  "Approve requires a return in UNDER_REVIEW or DISPUTED")
    # UNDER_REVIEW/DISPUTED -> APPROVED -> (system) CREDITED with memo auto-apply.
    approve_return_side_effects(r)
    return success_object(serialize_return(r))


@bp.post("/dairy/returns/<returnId>/reject")
def reject_return(returnId):
    user_id, _role = require_role("DistributorOwner")
    r = get_return_or_404(returnId)
    owner_check_return(user_id, r)
    if r["status"] not in ("UNDER_REVIEW", "DISPUTED"):
        raise err(ERR_RETURN_NOT_REVIEWABLE,
                  "Reject requires a return in UNDER_REVIEW or DISPUTED")
    apply_changes(r, {"status": "REJECTED"})
    return success_object(serialize_return(r))


@bp.post("/dairy/returns/<returnId>/dispute")
def dispute_return(returnId):
    user_id, _role = require_role("StoreReceiver")
    r = get_return_or_404(returnId)
    owner_check_store_receiver(user_id, r["store_id"])
    if r["status"] != "REJECTED":
        raise err(ERR_RETURN_NOT_DISPUTABLE, "Dispute requires a REJECTED return")
    apply_changes(r, {"status": "DISPUTED"})
    return success_object(serialize_return(r))
