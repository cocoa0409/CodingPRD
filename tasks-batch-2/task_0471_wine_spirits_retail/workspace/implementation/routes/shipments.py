"""Shipments and the delivery/return branch (PRD §3.10)."""
import app as A
import errors
import middleware
import response
import services
from app import app
from db import store


@app.route("/orders/<oid>/shipments", methods=["POST"])
def create_shipment(oid):
    middleware.require_roles({A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    body = A.get_body()
    carrier = A.require_str(body, "carrier")
    if carrier not in A.CARRIERS:
        raise errors.invalid_request("Invalid carrier.")

    # Must be a DELIVERY/SHIP order in READY fulfillment and CAPTURED payment.
    if order["channel"] not in A.SHIPPING_CHANNELS:
        raise errors.shipment_channel_invalid()
    if order["fulfillment_status"] != "READY" or order["payment_status"] != "CAPTURED":
        raise errors.shipment_channel_invalid()

    # At most one non-CANCELLED/RETURNED shipment per order.
    for s in store.shipments.values():
        if s["order_id"] == oid and s["status"] not in ("RETURNED",):
            raise errors.duplicate_active_shipment()

    dest_state = order["dest_state_code"]
    rule = services.state_rule_by_code(dest_state) if dest_state else None
    sig_required = rule.get("requires_adult_signature", True) if rule else True

    rec = {
        "order_id": oid,
        "carrier": carrier,
        "dest_state_code": dest_state,
        "adult_signature_required": sig_required,
        "status": "LABELED",
    }
    A.stamp_create(rec)
    store.shipments[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


def _ship_owner_check(role, uid, shipment):
    if role == A.R_CUSTOMER:
        order = store.orders.get(shipment["order_id"])
        if order is None or uid != order["customer_id"]:
            raise errors.forbidden()


@app.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.shipments, sid)
    _ship_owner_check(role, uid, rec)
    return response.object_response(A.public(rec))


@app.route("/orders/<oid>/shipments", methods=["GET"])
def list_order_shipments(oid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    order = A.get_or_404(store.orders, oid)
    if role == A.R_CUSTOMER and uid != order["customer_id"]:
        raise errors.forbidden()
    limit, offset = A.get_pagination()
    items = [s for s in store.shipments.values() if s["order_id"] == oid]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/shipments/<sid>/dispatch", methods=["POST"])
def dispatch_shipment(sid):
    middleware.require_roles({A.R_ASSOCIATE})
    s = A.get_or_404(store.shipments, sid)
    if s["status"] != "LABELED":
        raise errors.invalid_state()
    order = store.orders.get(s["order_id"])
    if order is None:
        raise errors.not_found()
    if order["fulfillment_status"] != "READY" or order["payment_status"] != "CAPTURED":
        raise errors.invalid_state()
    s["status"] = "DISPATCHED"
    A.touch(s)
    return response.object_response(A.public(s))


@app.route("/shipments/<sid>/confirm-delivery", methods=["POST"])
def confirm_delivery(sid):
    middleware.require_roles({A.R_ASSOCIATE})
    s = A.get_or_404(store.shipments, sid)
    if s["status"] != "DISPATCHED":
        raise errors.invalid_state()
    body = A.get_body()
    if s["adult_signature_required"]:
        if body.get("signature_captured") is not True:
            raise errors.signature_required()
    s["status"] = "DELIVERED"
    A.touch(s)
    return response.object_response(A.public(s))


@app.route("/shipments/<sid>/return", methods=["POST"])
def return_shipment(sid):
    middleware.require_roles({A.R_ASSOCIATE})
    s = A.get_or_404(store.shipments, sid)
    if s["status"] != "DISPATCHED":
        raise errors.invalid_state()
    s["status"] = "RETURNED"
    A.touch(s)
    # Cascade: cancel owning order from READY via compensation.
    order = store.orders.get(s["order_id"])
    if order is not None and order["fulfillment_status"] == "READY":
        services.release_reservations(order)
        services.deactivate_order_windows(order["id"])
        order["fulfillment_status"] = "CANCELLED"
        A.touch(order)
        customer = store.customers.get(order["customer_id"])
        if customer is not None:
            services.recompute_lifetime_spend(customer)
            services.recompute_compliance_status(customer)
    return response.object_response(A.public(s))
