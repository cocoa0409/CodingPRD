"""DeliveryOrder endpoints: DRAFT -> PENDING -> SCHEDULED -> IN_TRANSIT ->
DELIVERED -> CLOSED, with FAILED_DELIVERY reschedule and CANCELLED."""

from decimal import Decimal

from flask import Blueprint, g

import errors
from calc import recompute_station, accepted_design_of
from db import db, create_entity, touch, now
from helpers import list_response, account_of_order, query_filter
from response import success_object
from serializers import delivery_order as ser
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership)

bp = Blueprint("delivery_orders", __name__)


def _is_container_multiple(quantity, container):
    """quantity must be a positive whole multiple of container_size_gal.
    Decimal comparison on the JSON shortest-repr values."""
    try:
        q = Decimal(repr(float(quantity)))
        c = Decimal(repr(float(container)))
    except Exception:
        return False
    if c <= 0 or q <= 0:
        return False
    return q % c == 0


@bp.route("/wt/delivery-orders", methods=["POST"])
def create_order():
    body = get_body()
    # Tier 4 body FKs in declared input order: account_id, then station_id.
    account = resolve_body_fk(body, "account_id", "accounts")
    station = resolve_body_fk(body, "station_id", "feed_stations")
    vals = validate_shape(body, [
        ("account_id", "str", True),
        ("station_id", "str", True),
        ("quantity_gal", "num", True),
    ])
    product = db["products"].get(station["product_id"])
    # Tier 10 field constraints.
    if vals["quantity_gal"] <= 0:
        raise errors.field_constraint("quantity_gal must be > 0")
    if not _is_container_multiple(vals["quantity_gal"], product["container_size_gal"]):
        raise errors.ApiError(errors.ERR_QUANTITY_NOT_CONTAINER_MULTIPLE, 422,
                              "quantity_gal must be a positive whole multiple of container_size_gal")
    # Tier 13 referential integrity: station not LOCKED_OUT, product LISTED.
    if station["status"] == "LOCKED_OUT":
        raise errors.ApiError(errors.ERR_STATION_LOCKED_OUT, 409,
                              "Destination station must not be LOCKED_OUT")
    if product["status"] == "DELISTED":
        raise errors.ApiError(errors.ERR_PRODUCT_DELISTED, 409,
                              "Order references a DELISTED product")
    ent = create_entity("delivery_orders", {
        "account_id": account["id"],
        "station_id": station["id"],
        "quantity_gal": vals["quantity_gal"],
        "scheduled_for": None,
        "delivered_gal": None,
        "returned_residual_gal": None,
        "auto_drafted": False,
        "status": "DRAFT",
    })
    return success_object(ser(ent), 201)


@bp.route("/wt/delivery-orders", methods=["GET"])
def list_orders():
    user = (g.role, g.user_id)
    items = list(db["delivery_orders"].values())
    account_id = query_filter("account_id")
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    station_id = query_filter("station_id")
    if station_id is not None:
        items = [o for o in items if o["station_id"] == station_id]
    status = query_filter("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, ser, account_of_order, user)


@bp.route("/wt/delivery-orders/<orderId>", methods=["GET"])
def get_order(orderId):
    ent = db["delivery_orders"].get(orderId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, ent["account_id"])
    ent = resolve("delivery_orders", orderId)
    return success_object(ser(ent), 200)


@bp.route("/wt/delivery-orders/<orderId>/submit", methods=["POST"])
def submit_order(orderId):
    ent = resolve("delivery_orders", orderId)
    get_body()
    if ent["status"] != "DRAFT":
        raise errors.invalid_state("Order must be DRAFT to submit")
    ent["status"] = "PENDING"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/delivery-orders/<orderId>/schedule", methods=["POST"])
def schedule_order(orderId):
    ent = resolve("delivery_orders", orderId)
    body = get_body()
    vals = validate_shape(body, [
        ("scheduled_for", "iso", True),
        ("expected_delivery_order_version", "int", True),
    ])
    if ent["status"] not in ("PENDING", "FAILED_DELIVERY"):
        raise errors.invalid_state("Order must be PENDING or FAILED_DELIVERY to schedule")
    account = db["accounts"].get(ent["account_id"])
    station = db["feed_stations"].get(ent["station_id"])
    asset = db["assets"].get(station["asset_id"]) if station else None
    if ent["status"] == "PENDING":
        # Tier 7 cross-entity gates (PENDING branch only): ACCEPTED design,
        # then ACTIVE account.
        if asset is None or accepted_design_of(asset["id"]) is None:
            raise errors.ApiError(errors.ERR_PROGRAM_NOT_ACCEPTED, 409,
                                  "Scheduling requires an ACCEPTED program design on the destination asset")
        if account is None or account["status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_ACCOUNT_NOT_ACTIVE, 409,
                                  "Scheduling requires an ACTIVE account")
    # Tier 11 temporal: scheduled_for strictly in the future.
    if not vals["scheduled_for"] > now():
        raise errors.ApiError(errors.ERR_SCHEDULE_IN_PAST, 422,
                              "scheduled_for must be strictly in the future")
    # Tier 14 fiscal gate: credit_hold (both branches).
    if account is not None and account["credit_hold"]:
        raise errors.ApiError(errors.ERR_CREDIT_HOLD, 409,
                              "Account credit_hold blocks delivery scheduling")
    # Tier 15 OCC.
    if vals["expected_delivery_order_version"] != ent["version"]:
        raise errors.stale_version()
    ent["scheduled_for"] = vals["scheduled_for"]
    ent["status"] = "SCHEDULED"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/delivery-orders/<orderId>/dispatch", methods=["POST"])
def dispatch_order(orderId):
    ent = resolve("delivery_orders", orderId)
    get_body()
    if ent["status"] != "SCHEDULED":
        raise errors.invalid_state("Order must be SCHEDULED to dispatch")
    if now() < ent["scheduled_for"]:
        raise errors.ApiError(errors.ERR_TOO_EARLY_TO_DISPATCH, 422,
                              "Dispatch is not permitted before scheduled_for")
    ent["status"] = "IN_TRANSIT"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/delivery-orders/<orderId>/confirm-delivery", methods=["POST"])
def confirm_delivery(orderId):
    ent = resolve("delivery_orders", orderId)
    body = get_body()
    vals = validate_shape(body, [("delivered_gal", "num", True)])
    if ent["status"] != "IN_TRANSIT":
        raise errors.invalid_state("Order must be IN_TRANSIT to confirm delivery")
    if not (vals["delivered_gal"] > 0) or vals["delivered_gal"] > ent["quantity_gal"]:
        raise errors.ApiError(errors.ERR_DELIVERY_QUANTITY, 422,
                              "delivered_gal must be > 0 and <= quantity_gal")
    ent["delivered_gal"] = vals["delivered_gal"]
    ent["status"] = "DELIVERED"
    touch(ent)
    station = db["feed_stations"].get(ent["station_id"])
    if station is not None:
        recompute_station(station)
    return success_object(ser(ent), 200)


@bp.route("/wt/delivery-orders/<orderId>/fail", methods=["POST"])
def fail_delivery(orderId):
    ent = resolve("delivery_orders", orderId)
    get_body()
    if ent["status"] != "IN_TRANSIT":
        raise errors.invalid_state("Order must be IN_TRANSIT to fail")
    ent["status"] = "FAILED_DELIVERY"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/delivery-orders/<orderId>/close", methods=["POST"])
def close_order(orderId):
    ent = resolve("delivery_orders", orderId)
    body = get_body()
    vals = validate_shape(body, [("returned_residual_gal", "num", True)])
    if ent["status"] != "DELIVERED":
        raise errors.invalid_state("Order must be DELIVERED to close")
    station = db["feed_stations"].get(ent["station_id"])
    product = db["products"].get(station["product_id"]) if station else None
    if vals["returned_residual_gal"] < 0 or \
            (product is not None and vals["returned_residual_gal"] > product["container_size_gal"]):
        raise errors.ApiError(errors.ERR_RESIDUAL_EXCEEDS_CONTAINER, 422,
                              "returned_residual_gal must be >= 0 and <= container_size_gal")
    ent["returned_residual_gal"] = vals["returned_residual_gal"]
    ent["status"] = "CLOSED"
    touch(ent)
    if station is not None:
        recompute_station(station)
    return success_object(ser(ent), 200)


@bp.route("/wt/delivery-orders/<orderId>/cancel", methods=["POST"])
def cancel_order(orderId):
    ent = resolve("delivery_orders", orderId)
    get_body()
    if ent["status"] not in ("DRAFT", "PENDING", "SCHEDULED"):
        raise errors.invalid_state("Order must be DRAFT, PENDING, or SCHEDULED to cancel")
    # Cancelling a SCHEDULED order releases its tote allocation (pure
    # compensation; no inventory has moved).
    ent["status"] = "CANCELLED"
    touch(ent)
    return success_object(ser(ent), 200)
