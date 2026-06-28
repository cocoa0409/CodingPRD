"""Special orders: cyclic negotiation loop and conversion (PRD §3.9)."""
import app as A
import errors
import middleware
import response
import services
from app import app
from db import store


@app.route("/special-orders", methods=["POST"])
def create_special_order():
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    body = A.get_body()
    customer_id = A.require_str(body, "customer_id")
    description = A.require_str(body, "description")
    requested_qty = A.require_int(body, "requested_qty")

    customer = A.get_or_404(store.customers, customer_id)
    if role == A.R_CUSTOMER and uid != customer_id:
        raise errors.forbidden()
    if requested_qty < 1:
        raise errors.invalid_request("requested_qty must be >= 1.")

    rec = {
        "customer_id": customer_id,
        "description": description,
        "requested_qty": requested_qty,
        "quoted_unit_price_cents": None,
        "customer_counter_price_cents": None,
        "round_count": 0,
        "status": "REQUESTED",
        "converted_order_id": None,
    }
    A.stamp_create(rec)
    store.special_orders[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


def _owner_check(role, uid, so):
    if role == A.R_CUSTOMER and uid != so["customer_id"]:
        raise errors.forbidden()


@app.route("/special-orders/<sid>", methods=["GET"])
def get_special_order(sid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.special_orders, sid)
    _owner_check(role, uid, rec)
    return response.object_response(A.public(rec))


@app.route("/customers/<cid>/special-orders", methods=["GET"])
def list_customer_special_orders(cid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    A.get_or_404(store.customers, cid)
    if role == A.R_CUSTOMER and uid != cid:
        raise errors.forbidden()
    limit, offset = A.get_pagination()
    items = [s for s in store.special_orders.values() if s["customer_id"] == cid]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    middleware.require_roles({A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    limit, offset = A.get_pagination()
    items = list(store.special_orders.values())
    converted = A.request.args.get("converted_order_id")
    status = A.request.args.get("status")
    if converted is not None:
        items = [s for s in items if s["converted_order_id"] == converted]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/special-orders/<sid>/quote", methods=["POST"])
def quote_special_order(sid):
    middleware.require_roles({A.R_ASSOCIATE})
    so = A.get_or_404(store.special_orders, sid)
    if so["status"] not in ("REQUESTED", "COUNTERED"):
        raise errors.invalid_state()
    body = A.get_body()
    price = A.require_int(body, "quoted_unit_price_cents")
    if price < 1:
        raise errors.invalid_request("quoted_unit_price_cents must be >= 1.")
    # A re-quote from COUNTERED is permitted; the round limit is enforced on the
    # counter step (a counter pushes round_count to 3, and the next counter is
    # what gets rejected). See test_special_order_negotiation_rounds_exceeded.
    so["quoted_unit_price_cents"] = price
    so["status"] = "QUOTED"
    A.touch(so)
    return response.object_response(A.public(so))


@app.route("/special-orders/<sid>/counter", methods=["POST"])
def counter_special_order(sid):
    role, uid = middleware.require_roles({A.R_CUSTOMER})
    so = A.get_or_404(store.special_orders, sid)
    _owner_check(role, uid, so)
    if so["status"] != "QUOTED":
        raise errors.invalid_state()
    if so["round_count"] >= 3:
        raise errors.negotiation_rounds_exceeded()
    body = A.get_body()
    price = A.require_int(body, "customer_counter_price_cents")
    if price < 1:
        raise errors.invalid_request("customer_counter_price_cents must be >= 1.")
    so["customer_counter_price_cents"] = price
    so["round_count"] += 1
    so["status"] = "COUNTERED"
    A.touch(so)
    return response.object_response(A.public(so))


@app.route("/special-orders/<sid>/accept", methods=["POST"])
def accept_special_order(sid):
    role, uid = middleware.require_roles({A.R_CUSTOMER})
    so = A.get_or_404(store.special_orders, sid)
    _owner_check(role, uid, so)
    if so["status"] != "QUOTED":
        raise errors.invalid_state()
    so["status"] = "ACCEPTED"
    A.touch(so)
    return response.object_response(A.public(so))


@app.route("/special-orders/<sid>/decline", methods=["POST"])
def decline_special_order(sid):
    role, uid = middleware.require_roles({A.R_CUSTOMER})
    so = A.get_or_404(store.special_orders, sid)
    _owner_check(role, uid, so)
    if so["status"] not in ("REQUESTED", "QUOTED", "COUNTERED"):
        raise errors.invalid_state()
    so["status"] = "DECLINED"
    A.touch(so)
    return response.object_response(A.public(so))


@app.route("/special-orders/<sid>/convert", methods=["POST"])
def convert_special_order(sid):
    middleware.require_roles({A.R_ASSOCIATE})
    so = A.get_or_404(store.special_orders, sid)
    if so["status"] != "ACCEPTED":
        raise errors.invalid_state()
    customer = store.customers.get(so["customer_id"])
    if customer is None:
        raise errors.not_found()
    if not customer.get("age_verified", False):
        raise errors.age_not_verified()
    if services.compliance_status_value(customer) == "BLOCKED":
        raise errors.customer_blocked()

    # Create a PICKUP order with one line derived from the special order.
    order = {
        "customer_id": so["customer_id"],
        "channel": "PICKUP",
        "dest_state_code": None,
        "payment_status": "UNPAID",
        "fulfillment_status": "CART",
        "provisional_total_cents": 0,
        "settled_total_cents": 0,
        "discount_cents": 0,
    }
    A.stamp_create(order)
    store.orders[order["id"]] = order

    line = {
        "order_id": order["id"],
        "vintage_id": None,
        "qty": so["requested_qty"],
        "lot_id": None,
        "reservation_state": "PENDING",
        "unit_price_cents": so["quoted_unit_price_cents"] or 0,
        "line_excise_cents": 0,
    }
    A.stamp_create(line)
    store.order_lines[line["id"]] = line

    so["status"] = "CONVERTED"
    so["converted_order_id"] = order["id"]
    A.touch(so)
    return response.object_response(A.public(so))
