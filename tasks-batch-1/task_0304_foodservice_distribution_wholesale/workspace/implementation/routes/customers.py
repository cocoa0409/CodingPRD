"""Customer, credit lifecycle, order-guide, order-guide-item, replenishment routes."""
from flask import Blueprint

import db
import errors
import middleware
import models
import response
from routes.listing import list_response
from services import calc, lookup, serialize

bp = Blueprint("customers", __name__)

READ_ROLES = {"DistributorAdmin", "SalesRep", "WarehouseOp", "CreditManager"}


# --- Customer ----------------------------------------------------------------

@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin", "SalesRep"})
    body = middleware.get_json_body()
    distributor_id = models.require_str(body, "distributor_id")
    route_id = models.require_str(body, "route_id")
    name = models.require_str(body, "name")
    credit_limit_cents = models.require_int(body, "credit_limit_cents", min_value=0)
    split_fee_cents = models.opt_int(body, "split_fee_cents", default=0, min_value=0)
    with db.lock:
        lookup.distributor(distributor_id)
        rt = lookup.route(route_id)
        if rt["distributor_id"] != distributor_id:
            raise errors.cross_distributor("Route belongs to a different distributor.")
        rec = models.base_record({
            "distributor_id": distributor_id,
            "route_id": route_id,
            "name": name,
            "credit_limit_cents": credit_limit_cents,
            "split_fee_cents": split_fee_cents,
            "ar_balance_cents": 0,
            "ar_status": "ACTIVE",
        })
        db.customers[rec["id"]] = rec
        return response.object_response(serialize.customer(rec), 201)


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.customer(customer_id)
    return response.object_response(serialize.customer(rec), 200)


@bp.route("/customers", methods=["GET"])
def list_customers():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.customers.values(), serialize.customer,
                         {"distributor_id": "distributor_id",
                          "route_id": "route_id"})


@bp.route("/customers/<customer_id>/credit-limit", methods=["POST"])
def adjust_credit_limit(customer_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"CreditManager", "DistributorAdmin"})
    body = middleware.get_json_body()
    credit_limit_cents = models.require_int(body, "credit_limit_cents", min_value=0)
    with db.lock:
        cust = lookup.customer(customer_id)
        # Lowering below ar_balance does NOT auto-hold; only the next AR sweep does.
        cust["credit_limit_cents"] = credit_limit_cents
        models.touch(cust)
        return response.object_response(serialize.customer(cust), 200)


@bp.route("/customers/<customer_id>/credit-hold", methods=["POST"])
def credit_hold(customer_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"CreditManager"})
    with db.lock:
        cust = lookup.customer(customer_id)
        if cust["ar_status"] != "ACTIVE":
            raise errors.invalid_state("Customer is not ACTIVE.")
        cust["ar_status"] = "CREDIT_HOLD"
        models.touch(cust)
        return response.object_response(serialize.customer(cust), 200)


@bp.route("/customers/<customer_id>/credit-release", methods=["POST"])
def credit_release(customer_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"CreditManager"})
    with db.lock:
        cust = lookup.customer(customer_id)
        if cust["ar_status"] != "CREDIT_HOLD":
            raise errors.invalid_state("Customer is not on CREDIT_HOLD.")
        if cust["ar_balance_cents"] > cust["credit_limit_cents"]:
            raise errors.ApiError(errors.ERR_OVER_CREDIT_LIMIT, 409,
                                  "AR balance still exceeds the credit limit.")
        cust["ar_status"] = "ACTIVE"
        models.touch(cust)
        _release_on_hold_orders(cust)
        return response.object_response(serialize.customer(cust), 200)


def _release_on_hold_orders(cust):
    """Cascade ON_HOLD orders back to PENDING when they fit remaining headroom.

    Per PRD §3.5: each order with credit_status ON_HOLD whose order_total_cents
    fits under (credit_limit - current balance) -> credit_status PENDING.
    Processed in created_at ASC order for determinism.
    """
    on_hold = [o for o in db.orders.values()
               if o["customer_id"] == cust["id"] and o["credit_status"] == "ON_HOLD"]
    on_hold.sort(key=lambda o: o["created_at"])
    for order in on_hold:
        headroom = cust["credit_limit_cents"] - cust["ar_balance_cents"]
        if order["order_total_cents"] <= headroom:
            order["credit_status"] = "PENDING"
            models.touch(order)


@bp.route("/customers/<customer_id>/close", methods=["POST"])
def close_customer(customer_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin"})
    with db.lock:
        cust = lookup.customer(customer_id)
        if cust["ar_status"] == "CLOSED":
            # Transition CLOSED -> CLOSED is not defined.
            raise errors.invalid_state("Customer is already CLOSED.")
        if cust["ar_balance_cents"] != 0:
            raise errors.ApiError(errors.ERR_CUSTOMER_NOT_SETTLED, 409,
                                  "Customer AR balance is not zero.")
        for o in db.orders.values():
            if o["customer_id"] == customer_id and o["fulfillment_status"] in (
                    "SUBMITTED", "PICKING", "LOADED"):
                raise errors.ApiError(errors.ERR_CUSTOMER_HAS_OPEN_ORDERS, 409,
                                      "Customer has open orders.")
        cust["ar_status"] = "CLOSED"
        models.touch(cust)
        return response.object_response(serialize.customer(cust), 200)


# --- OrderGuide --------------------------------------------------------------

@bp.route("/order-guides", methods=["POST"])
def create_order_guide():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin", "SalesRep"})
    body = middleware.get_json_body()
    customer_id = models.require_str(body, "customer_id")
    name = models.require_str(body, "name")
    with db.lock:
        cust = lookup.customer(customer_id)
        if cust["ar_status"] == "CLOSED":
            raise errors.ApiError(errors.ERR_CUSTOMER_CLOSED, 409,
                                  "Customer is CLOSED.")
        rec = models.base_record({
            "customer_id": customer_id,
            "distributor_id": cust["distributor_id"],
            "name": name,
        })
        db.order_guides[rec["id"]] = rec
        return response.object_response(serialize.order_guide(rec), 201)


@bp.route("/order-guides/<order_guide_id>", methods=["GET"])
def get_order_guide(order_guide_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.order_guide(order_guide_id)
    return response.object_response(serialize.order_guide(rec), 200)


@bp.route("/order-guides", methods=["GET"])
def list_order_guides():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.order_guides.values(), serialize.order_guide,
                         {"customer_id": "customer_id",
                          "distributor_id": "distributor_id"})


@bp.route("/order-guides/<order_guide_id>/replenishment", methods=["GET"])
def replenishment(order_guide_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin", "SalesRep"})
    guide = lookup.order_guide(order_guide_id)
    items = [i for i in db.order_guide_items.values()
             if i["order_guide_id"] == guide["id"]]
    items.sort(key=lambda i: i["created_at"])
    out = []
    for item in items:
        product = db.products.get(item["product_id"])
        suggestion = calc.replenishment_suggestion(item, product)
        if suggestion is None:
            continue  # items already at/over par are omitted
        out.append(serialize.order_guide_item(item, suggestion))
    # Read-only; not paginated by the PRD (returns the qualifying items).
    return response.array_response(out, limit=len(out), offset=0,
                                   total_count=len(out), has_more=False)


# --- OrderGuideItem ----------------------------------------------------------

@bp.route("/order-guide-items", methods=["POST"])
def create_order_guide_item():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"DistributorAdmin", "SalesRep"})
    body = middleware.get_json_body()
    order_guide_id = models.require_str(body, "order_guide_id")
    product_id = models.require_str(body, "product_id")
    par_level_splits = models.require_int(body, "par_level_splits", min_value=0)
    on_hand_splits = models.opt_int(body, "on_hand_splits", default=0, min_value=0)
    with db.lock:
        guide = lookup.order_guide(order_guide_id)
        product = lookup.product(product_id)
        if product["distributor_id"] != guide["distributor_id"]:
            raise errors.cross_distributor("Product belongs to a different distributor.")
        rec = models.base_record({
            "order_guide_id": order_guide_id,
            "product_id": product_id,
            "par_level_splits": par_level_splits,
            "on_hand_splits": on_hand_splits,
        })
        db.order_guide_items[rec["id"]] = rec
        return response.object_response(serialize.order_guide_item(rec), 201)


@bp.route("/order-guide-items/<order_guide_item_id>", methods=["GET"])
def get_order_guide_item(order_guide_item_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.order_guide_item(order_guide_item_id)
    return response.object_response(serialize.order_guide_item(rec), 200)


@bp.route("/order-guide-items", methods=["GET"])
def list_order_guide_items():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.order_guide_items.values(), serialize.order_guide_item,
                         {"order_guide_id": "order_guide_id",
                          "product_id": "product_id"})
