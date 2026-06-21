"""Return routes: request, reads, approve, reject, issue-credit."""
from flask import Blueprint

import db
import errors
import middleware
import models
import response
from routes.listing import list_response
from services import calc, lookup, serialize

bp = Blueprint("returns", __name__)

READ_ROLES = {"DistributorAdmin", "SalesRep", "WarehouseOp", "CreditManager"}
RETURN_REASONS = {"DAMAGED", "OVERAGE", "QUALITY", "WRONG_ITEM"}


@bp.route("/returns", methods=["POST"])
def request_return():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"SalesRep", "DistributorAdmin", "CreditManager"})
    body = middleware.get_json_body()
    customer_id = models.require_str(body, "customer_id")
    order_id = models.require_str(body, "order_id")
    order_line_id = models.require_str(body, "order_line_id")
    reason = models.require_enum(body, "reason", RETURN_REASONS)
    return_splits = models.require_int(body, "return_splits", min_value=1)
    with db.lock:
        # Existence validated left-to-right: customer, order, order_line.
        cust = lookup.customer(customer_id)
        order = lookup.order(order_id)
        line = lookup.order_line(order_line_id)
        # Customer-closed guard.
        if cust["ar_status"] == "CLOSED":
            raise errors.ApiError(errors.ERR_CUSTOMER_CLOSED, 409, "Customer is CLOSED.")
        # The cited order_line must belong to the cited order.
        if line["order_id"] != order_id:
            raise errors.invalid_state("order_line does not belong to the cited order.")
        rec = models.base_record({
            "customer_id": customer_id,
            "distributor_id": cust["distributor_id"],
            "order_id": order_id,
            "order_line_id": order_line_id,
            "reason": reason,
            "return_splits": return_splits,
            "restock_fee_cents": 0,
            "credit_amount_cents": 0,
            "status": "REQUESTED",
        })
        db.returns[rec["id"]] = rec
        return response.object_response(serialize.return_(rec), 201)


@bp.route("/returns/<return_id>", methods=["GET"])
def get_return(return_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.return_(return_id)
    return response.object_response(serialize.return_(rec), 200)


@bp.route("/returns", methods=["GET"])
def list_returns():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.returns.values(), serialize.return_,
                         {"customer_id": "customer_id",
                          "order_id": "order_id",
                          "order_line_id": "order_line_id",
                          "distributor_id": "distributor_id"})


@bp.route("/returns/<return_id>/approve", methods=["POST"])
def approve_return(return_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"CreditManager"})
    with db.lock:
        ret = lookup.return_(return_id)
        if ret["status"] != "REQUESTED":
            raise errors.invalid_state("Return is not in REQUESTED.")
        order = db.orders[ret["order_id"]]
        if order["fulfillment_status"] != "DELIVERED":
            raise errors.ApiError(errors.ERR_ORDER_NOT_DELIVERED, 409,
                                  "Referenced order is not DELIVERED.")
        line = db.order_lines[ret["order_line_id"]]
        if ret["return_splits"] > line["allocated_splits"]:
            raise errors.ApiError(errors.ERR_RETURN_EXCEEDS_DELIVERED, 422,
                                  "return_splits exceeds the delivered allocated_splits.")
        fulfilled = db.products[line["fulfilled_product_id"]]
        ret["status"] = "APPROVED"
        calc.compute_return_credit(ret, line, fulfilled)
        models.touch(ret)
        return response.object_response(serialize.return_(ret), 200)


@bp.route("/returns/<return_id>/reject", methods=["POST"])
def reject_return(return_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"CreditManager"})
    with db.lock:
        ret = lookup.return_(return_id)
        if ret["status"] != "REQUESTED":
            raise errors.invalid_state("Return is not in REQUESTED.")
        ret["status"] = "REJECTED"
        models.touch(ret)
        return response.object_response(serialize.return_(ret), 200)


@bp.route("/returns/<return_id>/issue-credit", methods=["POST"])
def issue_credit(return_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"CreditManager"})
    with db.lock:
        ret = lookup.return_(return_id)
        if ret["status"] != "APPROVED":
            raise errors.invalid_state("Return is not in APPROVED.")
        ret["status"] = "CREDITED"
        cust = db.customers[ret["customer_id"]]
        cust["ar_balance_cents"] -= ret["credit_amount_cents"]
        models.touch(cust)
        # Transitive cascade: if AR now at/below limit and customer on hold,
        # return to ACTIVE and release fitting ON_HOLD orders to PENDING.
        if cust["ar_status"] == "CREDIT_HOLD" and cust["ar_balance_cents"] <= cust["credit_limit_cents"]:
            cust["ar_status"] = "ACTIVE"
            models.touch(cust)
            _release_on_hold_orders(cust)
        models.touch(ret)
        return response.object_response(serialize.return_(ret), 200)


def _release_on_hold_orders(cust):
    """Cascade ON_HOLD orders back to PENDING when they fit remaining headroom
    (PRD §3.7). Processed created_at ASC for determinism."""
    on_hold = [o for o in db.orders.values()
               if o["customer_id"] == cust["id"] and o["credit_status"] == "ON_HOLD"]
    on_hold.sort(key=lambda o: o["created_at"])
    for order in on_hold:
        headroom = cust["credit_limit_cents"] - cust["ar_balance_cents"]
        if order["order_total_cents"] <= headroom:
            order["credit_status"] = "PENDING"
            models.touch(order)
