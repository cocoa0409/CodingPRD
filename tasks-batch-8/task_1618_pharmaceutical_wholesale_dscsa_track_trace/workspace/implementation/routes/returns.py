"""Return authorizations (PRD §3.8).

REQUESTED -> RECEIVED -> CREDITED, or REJECTED from REQUESTED/RECEIVED.
The returned quantity may not exceed the order line's quantity_allocated for
the product, checked both at lodgement and at receipt; cold-chain returns must
be lodged within 48 hours of delivery per the logical clock.
"""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from services import credit as credit_service
from validation import get_body, req_int, body_fk, path_entity

bp = Blueprint("returns", __name__)


def _return(return_id):
    return path_entity(store.return_authorizations, return_id, "ReturnAuthorization")


def _allocated_qty(order_id, product_id):
    for line in store.order_lines.values():
        if line["order_id"] == order_id and line["product_id"] == product_id:
            return line["quantity_allocated"] or 0
    return 0


def _check_qty_fits(ret):
    allocated = _allocated_qty(ret["order_id"], ret["product_id"])
    if ret["quantity_returned"] > allocated:
        raise ApiError(errors.ERR_RETURN_QTY_EXCEEDS_ALLOCATED[0],
                       errors.ERR_RETURN_QTY_EXCEEDS_ALLOCATED[1],
                       "quantity_returned exceeds the order line's quantity_allocated for the product")


@bp.route("/wholesale/return-authorizations", methods=["POST"])
@endpoint(["OrderManager"])
def create_return():
    body = get_body()
    order = body_fk(body, "order_id", store.purchase_orders, "PurchaseOrder")
    product = body_fk(body, "product_id", store.products, "Product")
    quantity = req_int(body, "quantity_returned")
    if quantity <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "quantity_returned must be strictly positive")
    # Even at lodgement the quantity may not exceed the line's allocation.
    allocated = _allocated_qty(order["id"], product["id"])
    if quantity > allocated:
        raise ApiError(errors.ERR_RETURN_QTY_EXCEEDS_ALLOCATED[0],
                       errors.ERR_RETURN_QTY_EXCEEDS_ALLOCATED[1],
                       "quantity_returned exceeds the order line's quantity_allocated for the product")
    ret = {
        "id": db.new_id(),
        "order_id": order["id"],
        "product_id": product["id"],
        "quantity_returned": quantity,
        "return_status": "REQUESTED",
        "credit_amount_cents": 0,
    }
    db.new_common(ret)
    store.return_authorizations[ret["id"]] = ret
    return created(ret)


@bp.route("/wholesale/return-authorizations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_returns():
    pg = Paginator()
    rows = list(store.return_authorizations.values())
    rows = pg.filter(rows, "order_id")
    rows = pg.filter(rows, "product_id")
    rows = pg.filter(rows, "return_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/return-authorizations/<returnId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_return(returnId):
    return ok(_return(returnId))


@bp.route("/wholesale/return-authorizations/<returnId>/receive", methods=["POST"])
@endpoint(["WarehouseOperator"])
def receive_return(returnId):
    ret = _return(returnId)
    get_body(required=False)
    if ret["return_status"] != "REQUESTED":
        raise ApiError(errors.ERR_RETURN_NOT_REQUESTED[0], errors.ERR_RETURN_NOT_REQUESTED[1],
                       "Return must be REQUESTED to receive")
    order = store.purchase_orders[ret["order_id"]]
    if order["fulfillment_status"] not in ("SHIPPED", "DELIVERED"):
        raise ApiError(errors.ERR_ORDER_NOT_RETURNABLE[0], errors.ERR_ORDER_NOT_RETURNABLE[1],
                       "Order must be SHIPPED or DELIVERED to return against")
    _check_qty_fits(ret)
    product = store.products[ret["product_id"]]
    if product.get("is_cold_chain") and order.get("_delivered_at") is not None:
        if db.logical_now() - order["_delivered_at"] > credit_service.COLD_CHAIN_WINDOW:
            raise ApiError(errors.ERR_COLD_RETURN_WINDOW_EXPIRED[0],
                           errors.ERR_COLD_RETURN_WINDOW_EXPIRED[1],
                           "Cold-chain return lodged more than 48 hours after delivery")
    ret["return_status"] = "RECEIVED"
    db.touch(ret)
    return ok(ret)


@bp.route("/wholesale/return-authorizations/<returnId>/credit", methods=["POST"])
@endpoint(["BillingClerk"])
def credit_return(returnId):
    ret = _return(returnId)
    get_body(required=False)
    if ret["return_status"] != "RECEIVED":
        raise ApiError(errors.ERR_RETURN_NOT_RECEIVED[0], errors.ERR_RETURN_NOT_RECEIVED[1],
                       "Return must be RECEIVED to credit")
    order = store.purchase_orders[ret["order_id"]]
    if order["financial_status"] not in ("INVOICED", "PARTIALLY_PAID", "PAID"):
        raise ApiError(errors.ERR_INVOICE_NOT_CREDITABLE[0], errors.ERR_INVOICE_NOT_CREDITABLE[1],
                       "Return credit only against INVOICED, PARTIALLY_PAID, or PAID orders")
    credit = credit_service.compute_return_credit(ret)
    ret["return_status"] = "CREDITED"
    ret["credit_amount_cents"] = credit
    db.touch(ret)
    credit_service.apply_return_credit(ret, credit)
    return ok(ret)


@bp.route("/wholesale/return-authorizations/<returnId>/reject", methods=["POST"])
@endpoint(["OrderManager"])
def reject_return(returnId):
    ret = _return(returnId)
    get_body(required=False)
    if ret["return_status"] not in ("REQUESTED", "RECEIVED"):
        raise ApiError(errors.ERR_RETURN_NOT_REJECTABLE[0], errors.ERR_RETURN_NOT_REJECTABLE[1],
                       "Return must be REQUESTED or RECEIVED to reject")
    ret["return_status"] = "REJECTED"
    db.touch(ret)
    return ok(ret)
