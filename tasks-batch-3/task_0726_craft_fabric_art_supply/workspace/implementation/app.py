import os
from decimal import Decimal
from datetime import timedelta
from flask import Flask, request

from errors import ApiError
from response import ok, created, ok_list, error_body
from store import store, new_id, now_iso, fmt_ts, parse_ts
from common import (
    auth, get_json, require_fields, pagination, paginate,
    base_entity, touch, serialize, sort_created, round_half_up,
)
import services as svc

app = Flask(__name__)


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_body("ERR_INVALID_REQUEST", "Not found"), 400


@app.errorhandler(405)
def handle_405(e):
    return error_body("ERR_INVALID_REQUEST", "Method not allowed"), 400


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_body(e.error_id, e.message), e.http_status
    return error_body("ERR_INVALID_REQUEST", str(e)), 400


def api_err(error_id, message=None):
    from errors import err
    raise err(error_id, message)


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------
def get_or_404(coll, ident, error_id):
    ent = coll.get(ident)
    if ent is None:
        api_err(error_id)
    return ent


def as_number(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        api_err("ERR_INVALID_REQUEST", f"{field} must be a number")
    return v


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        api_err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        api_err("ERR_INVALID_REQUEST", f"{field} must be a string")
    return v


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["StoreManager"])
    body = get_json()
    require_fields(body, ["to_iso8601"])
    try:
        dt = parse_ts(body["to_iso8601"])
    except Exception:
        api_err("ERR_INVALID_REQUEST", "invalid to_iso8601")
    store.clock.set(dt)
    return ok({})


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------
@app.route("/customers", methods=["POST"])
def create_customer():
    auth(["StoreAssociate", "StoreManager"])
    body = get_json()
    require_fields(body, ["email", "full_name", "home_store_code"])
    cust = base_entity({
        "email": as_str(body["email"], "email"),
        "full_name": as_str(body["full_name"], "full_name"),
        "home_store_code": as_str(body["home_store_code"], "home_store_code"),
    })
    store.customers[cust["id"]] = cust
    acct = base_entity({
        "customer_id": cust["id"],
        "points_earned": 0,
        "points_redeemed": 0,
        "spend_ytd_cents": 0,
    })
    store.loyalty_accounts[acct["id"]] = acct
    return created(serialize(cust))


@app.route("/customers", methods=["GET"])
def list_customers():
    auth(["StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.customers.values())
    email = request.args.get("email")
    if email is not None:
        items = [c for c in items if c["email"] == email]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(c) for c in page], limit, offset, total)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    cust = get_or_404(store.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    return ok(serialize(cust))


@app.route("/customers/<cid>/loyalty-account", methods=["GET"])
def get_loyalty(cid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    get_or_404(store.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    acct = svc.loyalty_by_customer(cid)
    items = [svc.loyalty_view(acct)] if acct else []
    return ok_list(items, 10, 0, len(items))


# --------------------------------------------------------------------------
# Products / Inventory
# --------------------------------------------------------------------------
@app.route("/products", methods=["POST"])
def create_product():
    auth(["StoreManager"])
    body = get_json()
    require_fields(body, ["sku", "name", "sell_mode", "unit_price_cents"])
    sell_mode = as_str(body["sell_mode"], "sell_mode")
    if sell_mode not in ("UNIT", "BY_YARD", "BULK"):
        api_err("ERR_INVALID_REQUEST", "invalid sell_mode")
    prod = base_entity({
        "sku": as_str(body["sku"], "sku"),
        "name": as_str(body["name"], "name"),
        "sell_mode": sell_mode,
        "unit_price_cents": as_int(body["unit_price_cents"], "unit_price_cents"),
        "min_cut_increment_yards": body.get("min_cut_increment_yards", 0.25),
        "is_clearance": bool(body.get("is_clearance", False)),
        "special_order_only": bool(body.get("special_order_only", False)),
    })
    store.products[prod["id"]] = prod
    return created(serialize(prod))


@app.route("/products", methods=["GET"])
def list_products():
    auth(["Customer", "StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.products.values())
    sku = request.args.get("sku")
    if sku is not None:
        items = [p for p in items if p["sku"] == sku]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(p) for p in page], limit, offset, total)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    prod = get_or_404(store.products, pid, "ERR_PRODUCT_NOT_FOUND")
    return ok(serialize(prod))


@app.route("/products/<pid>/inventory-lots", methods=["POST"])
def create_lot(pid):
    auth(["StoreManager"])
    get_or_404(store.products, pid, "ERR_PRODUCT_NOT_FOUND")
    body = get_json()
    require_fields(body, ["on_hand_yards"])
    lot = base_entity({
        "product_id": pid,
        "on_hand_yards": as_number(body["on_hand_yards"], "on_hand_yards"),
        "reserved_yards": 0,
    })
    store.inventory_lots[lot["id"]] = lot
    return created(svc.lot_view(lot))


@app.route("/products/<pid>/inventory-lots", methods=["GET"])
def list_product_lots(pid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    get_or_404(store.products, pid, "ERR_PRODUCT_NOT_FOUND")
    limit, offset = pagination()
    items = [l for l in store.inventory_lots.values() if l["product_id"] == pid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([svc.lot_view(l) for l in page], limit, offset, total)


@app.route("/inventory-lots/<lid>", methods=["GET"])
def get_lot(lid):
    auth(["StoreAssociate", "StoreManager"])
    lot = store.inventory_lots.get(lid)
    if lot is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "inventory lot not found")
    return ok(svc.lot_view(lot))


# --------------------------------------------------------------------------
# Coupons
# --------------------------------------------------------------------------
@app.route("/coupons", methods=["POST"])
def create_coupon():
    auth(["StoreManager"])
    body = get_json()
    require_fields(body, ["code", "discount_type", "value", "priority",
                          "valid_from", "valid_to"])
    dtype = as_str(body["discount_type"], "discount_type")
    if dtype not in ("PERCENT", "FIXED"):
        api_err("ERR_INVALID_REQUEST", "invalid discount_type")
    try:
        vf = parse_ts(body["valid_from"])
        vt = parse_ts(body["valid_to"])
    except Exception:
        api_err("ERR_INVALID_REQUEST", "invalid validity window")
    coupon = base_entity({
        "code": as_str(body["code"], "code"),
        "discount_type": dtype,
        "value": as_number(body["value"], "value"),
        "min_basket_cents": body.get("min_basket_cents", 0),
        "stackable": bool(body.get("stackable", False)),
        "excludes_clearance": bool(body.get("excludes_clearance", True)),
        "priority": as_int(body["priority"], "priority"),
        "valid_from": fmt_ts(vf),
        "valid_to": fmt_ts(vt),
        "_valid_from": vf,
        "_valid_to": vt,
    })
    store.coupons[coupon["id"]] = coupon
    return created(serialize(coupon))


@app.route("/coupons", methods=["GET"])
def list_coupons():
    auth(["Customer", "StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.coupons.values())
    code = request.args.get("code")
    if code is not None:
        items = [c for c in items if c["code"] == code]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(c) for c in page], limit, offset, total)


@app.route("/coupons/<cid>", methods=["GET"])
def get_coupon(cid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    coupon = store.coupons.get(cid)
    if coupon is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "coupon not found")
    return ok(serialize(coupon))


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
def order_view(order):
    return serialize(order)


@app.route("/orders", methods=["POST"])
def create_order():
    auth(["Customer", "StoreAssociate"])
    body = get_json()
    require_fields(body, ["customer_id"])
    cid = body["customer_id"]
    if cid not in store.customers:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "customer not found")
    bundle_id = body.get("project_bundle_id")
    bundle = None
    if bundle_id is not None:
        bundle = store.project_bundles.get(bundle_id)
        if bundle is None:
            api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "project bundle not found")
    order = base_entity({
        "customer_id": cid,
        "coupon_id": None,
        "project_bundle_id": bundle_id,
        "fulfillment_status": "BUILDING",
        "payment_status": "UNPAID",
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "points_redeemed_on_order": 0,
        "_applied_coupons": [],
        "_picked_up_at": None,
    })
    store.orders[order["id"]] = order
    if bundle is not None:
        for entry in bundle.get("bom", []):
            line = base_entity({
                "order_id": order["id"],
                "product_id": entry.get("product_id"),
                "workshop_registration_id": None,
                "requested_yards": entry.get("quantity"),
                "actual_cut_yards": None,
                "line_subtotal_cents": 0,
                "status": "DRAFT",
            })
            store.order_lines[line["id"]] = line
    return created(order_view(order))


@app.route("/orders", methods=["GET"])
def list_orders():
    auth(["Customer", "StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.orders.values())
    for key in ("customer_id", "coupon_id", "project_bundle_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([order_view(o) for o in page], limit, offset, total)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    return ok(order_view(order))


@app.route("/orders/<oid>/lines", methods=["POST"])
def add_line(oid):
    auth(["Customer", "StoreAssociate"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    body = get_json()
    require_fields(body, ["product_id", "requested_yards"])
    pid = body["product_id"]
    product = store.products.get(pid)
    if product is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "product not found")
    wr_id = body.get("workshop_registration_id")
    if wr_id is not None and wr_id not in store.registrations:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "registration not found")
    req = as_number(body["requested_yards"], "requested_yards")
    if product["sell_mode"] == "BY_YARD":
        inc = product.get("min_cut_increment_yards") or 0.25
        if req <= 0 or not _is_multiple(req, inc):
            api_err("ERR_INVALID_CUT_INCREMENT",
                    "requested_yards must be a positive multiple of min_cut_increment_yards")
    line = base_entity({
        "order_id": oid,
        "product_id": pid,
        "workshop_registration_id": wr_id,
        "requested_yards": req,
        "actual_cut_yards": None,
        "line_subtotal_cents": 0,
        "status": "DRAFT",
    })
    store.order_lines[line["id"]] = line
    return created(serialize(line))


def _is_multiple(value, increment):
    v = Decimal(str(value))
    inc = Decimal(str(increment))
    if inc == 0:
        return False
    q = v / inc
    return q == q.to_integral_value()


@app.route("/orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    limit, offset = pagination()
    items = [l for l in store.order_lines.values() if l["order_id"] == oid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(l) for l in page], limit, offset, total)


@app.route("/order-lines", methods=["GET"])
def filter_order_lines():
    auth(["StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.order_lines.values())
    pid = request.args.get("product_id")
    if pid is not None:
        items = [l for l in items if l["product_id"] == pid]
    wr = request.args.get("workshop_registration_id")
    if wr is not None:
        items = [l for l in items if l.get("workshop_registration_id") == wr]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(l) for l in page], limit, offset, total)


@app.route("/order-lines/<lid>", methods=["GET"])
def get_order_line(lid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    line = store.order_lines.get(lid)
    if line is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "order line not found")
    return ok(serialize(line))


@app.route("/order-lines/<lid>/record-cut", methods=["PATCH"])
def record_cut(lid):
    auth(["StoreAssociate"])
    line = store.order_lines.get(lid)
    if line is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "order line not found")
    body = get_json()
    require_fields(body, ["actual_cut_yards"])
    line["actual_cut_yards"] = as_number(body["actual_cut_yards"], "actual_cut_yards")
    touch(line)
    return ok(serialize(line))


@app.route("/orders/<oid>/coupons", methods=["POST"])
def apply_coupon(oid):
    auth(["Customer", "StoreAssociate"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    body = get_json()
    require_fields(body, ["code", "expected_order_version"])
    code = body["code"]
    coupon = next((c for c in store.coupons.values() if c["code"] == code), None)
    if coupon is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "coupon not found")
    expected = body["expected_order_version"]
    # OCC (priority 5)
    if expected != order["version"]:
        api_err("ERR_STALE_VERSION", "order version mismatch")
    # temporal window (priority 6)
    now = store.clock.now
    if now < coupon["_valid_from"] or now >= coupon["_valid_to"]:
        api_err("ERR_COUPON_EXPIRED", "coupon outside validity window")
    # stackability (priority 10)
    prospective = list(order.get("_applied_coupons", [])) + [coupon["id"]]
    if len(prospective) > 1:
        cps = [store.coupons[c] for c in prospective]
        if any(not c["stackable"] for c in cps):
            api_err("ERR_COUPON_NOT_STACKABLE", "not all coupons stackable")
    # min basket (priority 11) — current running subtotal
    subtotal = svc.order_subtotal(order, "provisional") \
        if _has_priced_lines(order) else _apply_time_subtotal(order)
    if subtotal < coupon["min_basket_cents"]:
        api_err("ERR_COUPON_MIN_NOT_MET", "minimum basket not met")
    # apply
    order["_applied_coupons"].append(coupon["id"])
    order["coupon_id"] = coupon["id"]
    touch(order)
    order["provisional_total_cents"] = svc.price_order(
        order, "provisional", statuses=("DRAFT", "RESERVED", "FULFILLED"))
    return ok(order_view(order))


def _has_priced_lines(order):
    return any(l["order_id"] == order["id"] and l["status"] in ("RESERVED", "FULFILLED")
               for l in store.order_lines.values())


def _apply_time_subtotal(order):
    lines = [l for l in store.order_lines.values()
             if l["order_id"] == order["id"] and l["status"] in ("DRAFT", "RESERVED", "FULFILLED")]
    subtotal = 0
    for line in sort_created(lines):
        subtotal += svc.compute_line_subtotal(line, "provisional")
    return subtotal


@app.route("/orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    auth(["Customer", "StoreAssociate"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    if order["fulfillment_status"] != "BUILDING":
        api_err("ERR_INVALID_STATE", "order not BUILDING")
    lines = [l for l in svc.order_lines_for(oid) if l["status"] != "CANCELLED"]
    if not lines:
        api_err("ERR_EMPTY_ORDER", "order has no lines")
    # inventory check for BY_YARD lines
    for line in lines:
        product = store.products.get(line["product_id"])
        if product and product["sell_mode"] == "BY_YARD":
            lot = svc.product_lot(line["product_id"])
            avail = svc.lot_available(lot) if lot else 0
            if avail < line["requested_yards"]:
                api_err("ERR_INSUFFICIENT_INVENTORY", "insufficient inventory")
    # commit
    for line in lines:
        line["status"] = "RESERVED"
        touch(line)
        lot = svc.product_lot(line["product_id"])
        if lot is not None:
            lot["reserved_yards"] += line["requested_yards"]
            touch(lot)
    order["fulfillment_status"] = "SUBMITTED"
    touch(order)
    order["provisional_total_cents"] = svc.price_order(order, "provisional")
    return ok(order_view(order))


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    auth(["Customer"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    body = get_json()
    if order["fulfillment_status"] != "SUBMITTED":
        api_err("ERR_INVALID_STATE", "order not SUBMITTED")
    pts = body.get("points_redeemed_on_order", 0)
    if pts is None:
        pts = 0
    pts = as_int(pts, "points_redeemed_on_order")
    if pts > 0:
        acct = svc.loyalty_by_customer(order["customer_id"])
        balance = (acct["points_earned"] - acct["points_redeemed"]) if acct else 0
        if balance < pts:
            api_err("ERR_INSUFFICIENT_POINTS", "insufficient loyalty points")
        acct["points_redeemed"] += pts
        touch(acct)
    order["points_redeemed_on_order"] = pts
    order["payment_status"] = "PAID"
    touch(order)
    # recompute provisional to reflect redemption
    order["provisional_total_cents"] = svc.price_order(order, "provisional")
    return ok(order_view(order))


@app.route("/orders/<oid>/ready", methods=["POST"])
def ready_order(oid):
    auth(["StoreAssociate"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    if order["fulfillment_status"] != "SUBMITTED":
        api_err("ERR_INVALID_STATE", "order not SUBMITTED")
    if order["payment_status"] != "PAID":
        api_err("ERR_ORDER_NOT_PAID", "order not paid")
    for line in svc.order_lines_for(oid, statuses=("RESERVED",)):
        product = store.products.get(line["product_id"])
        if product and product["sell_mode"] == "BY_YARD" and line["actual_cut_yards"] is None:
            api_err("ERR_CUT_NOT_RECORDED", "cut not recorded")
    order["fulfillment_status"] = "READY_FOR_PICKUP"
    touch(order)
    order["final_total_cents"] = svc.price_order(order, "final")
    return ok(order_view(order))


@app.route("/orders/<oid>/pickup", methods=["POST"])
def pickup_order(oid):
    auth(["StoreAssociate"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    if order["fulfillment_status"] != "READY_FOR_PICKUP":
        api_err("ERR_INVALID_STATE", "order not READY_FOR_PICKUP")
    if order["payment_status"] != "PAID":
        api_err("ERR_ORDER_NOT_PAID", "order not paid")
    for line in svc.order_lines_for(oid, statuses=("RESERVED",)):
        product = store.products.get(line["product_id"])
        lot = svc.product_lot(line["product_id"])
        if product and lot is not None:
            if product["sell_mode"] == "BY_YARD":
                draw = line["actual_cut_yards"] or 0
            else:
                draw = line["requested_yards"]
            lot["on_hand_yards"] -= draw
            lot["reserved_yards"] -= line["requested_yards"]
            touch(lot)
        line["status"] = "FULFILLED"
        touch(line)
    order["fulfillment_status"] = "PICKED_UP"
    order["_picked_up_at"] = store.clock.now
    touch(order)
    final = order.get("final_total_cents") or 0
    acct = svc.loyalty_by_customer(order["customer_id"])
    if acct is not None:
        acct["points_earned"] += final // 100
        acct["spend_ytd_cents"] += final
        touch(acct)
    return ok(order_view(order))


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    auth(["Customer", "StoreAssociate"])
    order = get_or_404(store.orders, oid, "ERR_ORDER_NOT_FOUND")
    if order["fulfillment_status"] in ("PICKED_UP", "CANCELLED"):
        api_err("ERR_INVALID_STATE", "order already terminal")
    for line in svc.order_lines_for(oid):
        if line["status"] == "CANCELLED":
            continue
        was_reserved = line["status"] == "RESERVED"
        line["status"] = "CANCELLED"
        touch(line)
        if was_reserved:
            lot = svc.product_lot(line["product_id"])
            if lot is not None:
                lot["reserved_yards"] -= line["requested_yards"]
                touch(lot)
    pts = order.get("points_redeemed_on_order", 0)
    if pts and pts > 0:
        acct = svc.loyalty_by_customer(order["customer_id"])
        if acct is not None:
            acct["points_redeemed"] -= pts
            touch(acct)
    for fo in store.framing_orders.values():
        if fo["order_id"] == oid and fo["status"] in ("QUOTED", "APPROVED"):
            fo["status"] = "CANCELLED"
            touch(fo)
    if order["payment_status"] == "PAID":
        order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return ok(order_view(order))


# --------------------------------------------------------------------------
# Rooms
# --------------------------------------------------------------------------
@app.route("/rooms", methods=["POST"])
def create_room():
    auth(["StoreManager"])
    body = get_json()
    require_fields(body, ["name"])
    room = base_entity({
        "name": as_str(body["name"], "name"),
        "cleanup_buffer_min": body.get("cleanup_buffer_min", 30),
    })
    store.rooms[room["id"]] = room
    return created(serialize(room))


@app.route("/rooms", methods=["GET"])
def list_rooms():
    auth(["StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = sort_created(list(store.rooms.values()))
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(r) for r in page], limit, offset, total)


@app.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    auth(["StoreAssociate", "StoreManager"])
    room = store.rooms.get(rid)
    if room is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "room not found")
    return ok(serialize(room))


# --------------------------------------------------------------------------
# Workshops / Sessions / Registrations
# --------------------------------------------------------------------------
@app.route("/workshops", methods=["POST"])
def create_workshop():
    auth(["StoreManager"])
    body = get_json()
    require_fields(body, ["title"])
    kit = body.get("kit_product_id")
    if kit is not None and kit not in store.products:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "kit product not found")
    ws = base_entity({
        "title": as_str(body["title"], "title"),
        "status": "DRAFT",
        "kit_product_id": kit,
    })
    store.workshops[ws["id"]] = ws
    return created(serialize(ws))


@app.route("/workshops", methods=["GET"])
def list_workshops():
    auth(["Customer", "StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.workshops.values())
    kit = request.args.get("kit_product_id")
    if kit is not None:
        items = [w for w in items if w.get("kit_product_id") == kit]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(w) for w in page], limit, offset, total)


@app.route("/workshops/<wid>", methods=["GET"])
def get_workshop(wid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    ws = get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    return ok(serialize(ws))


@app.route("/workshops/<wid>/open", methods=["POST"])
def open_workshop(wid):
    auth(["StoreManager"])
    ws = get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    if ws["status"] != "DRAFT":
        api_err("ERR_INVALID_STATE", "workshop not DRAFT")
    has_session = any(s["workshop_id"] == wid for s in store.sessions.values())
    if not has_session:
        api_err("ERR_NO_SESSIONS", "workshop has no sessions")
    ws["status"] = "OPEN"
    touch(ws)
    return ok(serialize(ws))


@app.route("/workshops/<wid>/close", methods=["POST"])
def close_workshop(wid):
    auth(["StoreManager"])
    ws = get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    if ws["status"] != "OPEN":
        api_err("ERR_INVALID_STATE", "workshop not OPEN")
    ws["status"] = "CLOSED"
    touch(ws)
    return ok(serialize(ws))


@app.route("/workshops/<wid>/cancel", methods=["POST"])
def cancel_workshop(wid):
    auth(["StoreManager"])
    ws = get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    if ws["status"] == "CANCELLED":
        api_err("ERR_INVALID_STATE", "workshop already cancelled")
    for reg in store.registrations.values():
        if reg["workshop_id"] == wid and reg["status"] in ("REGISTERED", "WAITLISTED"):
            reg["status"] = "CANCELLED"
            touch(reg)
            # cancel supply-kit lines referencing this registration
            for line in store.order_lines.values():
                if line.get("workshop_registration_id") == reg["id"] and line["status"] != "CANCELLED":
                    was_reserved = line["status"] == "RESERVED"
                    line["status"] = "CANCELLED"
                    touch(line)
                    if was_reserved:
                        lot = svc.product_lot(line["product_id"])
                        if lot is not None:
                            lot["reserved_yards"] -= line["requested_yards"]
                            touch(lot)
    ws["status"] = "CANCELLED"
    touch(ws)
    return ok(serialize(ws))


@app.route("/workshops/<wid>/sessions", methods=["POST"])
def create_session(wid):
    auth(["StoreManager"])
    ws = get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    body = get_json()
    require_fields(body, ["room_id", "instructor_code", "starts_at", "ends_at", "capacity"])
    room = store.rooms.get(body["room_id"])
    if room is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "room not found")
    try:
        starts = parse_ts(body["starts_at"])
        ends = parse_ts(body["ends_at"])
    except Exception:
        api_err("ERR_INVALID_REQUEST", "invalid session times")
    # room conflict (priority 8)
    buffer = timedelta(minutes=room.get("cleanup_buffer_min", 30))
    for s in store.sessions.values():
        if s["room_id"] != room["id"]:
            continue
        s0, s1 = s["_starts_at"], s["_ends_at"]
        # require gap >= buffer in either direction
        if not (starts >= s1 + buffer or s0 >= ends + buffer):
            api_err("ERR_ROOM_CONFLICT", "room scheduling conflict")
    session = base_entity({
        "workshop_id": wid,
        "room_id": room["id"],
        "instructor_code": as_str(body["instructor_code"], "instructor_code"),
        "starts_at": fmt_ts(starts),
        "ends_at": fmt_ts(ends),
        "capacity": as_int(body["capacity"], "capacity"),
        "registered_count": 0,
        "_starts_at": starts,
        "_ends_at": ends,
    })
    store.sessions[session["id"]] = session
    return created(serialize(session))


@app.route("/workshops/<wid>/sessions", methods=["GET"])
def list_workshop_sessions(wid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    limit, offset = pagination()
    items = [s for s in store.sessions.values() if s["workshop_id"] == wid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(s) for s in page], limit, offset, total)


@app.route("/workshop-sessions", methods=["GET"])
def filter_sessions():
    auth(["StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.sessions.values())
    rid = request.args.get("room_id")
    if rid is not None:
        items = [s for s in items if s["room_id"] == rid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(s) for s in page], limit, offset, total)


@app.route("/workshop-sessions/<sid>", methods=["GET"])
def get_session(sid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    session = get_or_404(store.sessions, sid, "ERR_SESSION_NOT_FOUND")
    return ok(serialize(session))


@app.route("/workshops/<wid>/register", methods=["POST"])
def register(wid):
    auth(["Customer", "StoreAssociate"])
    ws = get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    body = get_json()
    require_fields(body, ["session_id", "customer_id"])
    session = store.sessions.get(body["session_id"])
    if session is None or session["workshop_id"] != wid:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "session not found")
    cust_id = body["customer_id"]
    if cust_id not in store.customers:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "customer not found")
    order_id = body.get("order_id")
    order = None
    if order_id is not None:
        order = store.orders.get(order_id)
        if order is None:
            api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "order not found")
    # registration window (priority 6)
    now = store.clock.now
    if ws["status"] != "OPEN" or now >= session["_starts_at"]:
        api_err("ERR_REGISTRATION_CLOSED", "registration closed")
    # customer session overlap (priority 9) — over REGISTERED registrations
    for reg in store.registrations.values():
        if reg["customer_id"] == cust_id and reg["status"] == "REGISTERED":
            other = store.sessions.get(reg["session_id"])
            if other is None:
                continue
            if session["_starts_at"] < other["_ends_at"] and other["_starts_at"] < session["_ends_at"]:
                api_err("ERR_CUSTOMER_SESSION_OVERLAP", "customer session overlap")
    if session["registered_count"] < session["capacity"]:
        status = "REGISTERED"
    else:
        status = "WAITLISTED"
    reg = base_entity({
        "workshop_id": wid,
        "session_id": session["id"],
        "customer_id": cust_id,
        "status": status,
        "waitlist_rank": None,
    })
    store.registrations[reg["id"]] = reg
    if status == "REGISTERED":
        session["registered_count"] += 1
        touch(session)
    # supply-kit line
    if ws.get("kit_product_id") and order is not None:
        line = base_entity({
            "order_id": order["id"],
            "product_id": ws["kit_product_id"],
            "workshop_registration_id": reg["id"],
            "requested_yards": 1,
            "actual_cut_yards": None,
            "line_subtotal_cents": 0,
            "status": "DRAFT",
        })
        store.order_lines[line["id"]] = line
    return created(svc.registration_view(reg))


@app.route("/workshops/<wid>/registrations", methods=["GET"])
def list_workshop_registrations(wid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    get_or_404(store.workshops, wid, "ERR_WORKSHOP_NOT_FOUND")
    limit, offset = pagination()
    items = [r for r in store.registrations.values() if r["workshop_id"] == wid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([svc.registration_view(r) for r in page], limit, offset, total)


@app.route("/workshop-registrations", methods=["GET"])
def filter_registrations():
    auth(["Customer", "StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.registrations.values())
    sid = request.args.get("session_id")
    if sid is not None:
        items = [r for r in items if r["session_id"] == sid]
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [r for r in items if r["customer_id"] == cid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([svc.registration_view(r) for r in page], limit, offset, total)


@app.route("/workshop-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    reg = get_or_404(store.registrations, rid, "ERR_REGISTRATION_NOT_FOUND")
    return ok(svc.registration_view(reg))


@app.route("/workshop-registrations/<rid>/cancel", methods=["POST"])
def cancel_registration(rid):
    auth(["Customer", "StoreAssociate"])
    reg = get_or_404(store.registrations, rid, "ERR_REGISTRATION_NOT_FOUND")
    if reg["status"] != "REGISTERED":
        api_err("ERR_INVALID_STATE", "registration not REGISTERED")
    reg["status"] = "CANCELLED"
    touch(reg)
    session = store.sessions.get(reg["session_id"])
    if session is not None:
        session["registered_count"] -= 1
        touch(session)
        # promote earliest WAITLISTED
        if session["registered_count"] < session["capacity"]:
            waitlisted = [r for r in store.registrations.values()
                          if r["session_id"] == session["id"] and r["status"] == "WAITLISTED"]
            waitlisted = sort_created(waitlisted)
            if waitlisted:
                promoted = waitlisted[0]
                promoted["status"] = "REGISTERED"
                touch(promoted)
                session["registered_count"] += 1
                touch(session)
    return ok(svc.registration_view(reg))


# --------------------------------------------------------------------------
# Framing Orders
# --------------------------------------------------------------------------
def framing_quote(width, height):
    united = width + height
    if united <= 40:
        rate = 15
    elif united <= 80:
        rate = 25
    else:
        rate = 40
    perimeter = 2 * (width + height)
    return round_half_up(Decimal("2000") + Decimal(str(rate)) * Decimal(str(perimeter)))


@app.route("/framing-orders", methods=["POST"])
def create_framing():
    auth(["Customer", "FramingSpecialist"])
    body = get_json()
    require_fields(body, ["order_id", "customer_id", "width_in", "height_in"])
    if body["order_id"] not in store.orders:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "order not found")
    if body["customer_id"] not in store.customers:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "customer not found")
    width = as_number(body["width_in"], "width_in")
    height = as_number(body["height_in"], "height_in")
    fo = base_entity({
        "order_id": body["order_id"],
        "customer_id": body["customer_id"],
        "width_in": width,
        "height_in": height,
        "quoted_price_cents": framing_quote(width, height),
        "status": "QUOTED",
    })
    store.framing_orders[fo["id"]] = fo
    return created(serialize(fo))


@app.route("/framing-orders", methods=["GET"])
def list_framing():
    auth(["Customer", "FramingSpecialist", "StoreManager"])
    limit, offset = pagination()
    items = list(store.framing_orders.values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [f for f in items if f["order_id"] == oid]
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [f for f in items if f["customer_id"] == cid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(f) for f in page], limit, offset, total)


@app.route("/framing-orders/<fid>", methods=["GET"])
def get_framing(fid):
    auth(["Customer", "FramingSpecialist", "StoreManager"])
    fo = get_or_404(store.framing_orders, fid, "ERR_FRAMING_NOT_FOUND")
    return ok(serialize(fo))


@app.route("/framing-orders/<fid>/approve", methods=["POST"])
def approve_framing(fid):
    auth(["Customer"])
    fo = get_or_404(store.framing_orders, fid, "ERR_FRAMING_NOT_FOUND")
    if fo["status"] != "QUOTED":
        api_err("ERR_INVALID_STATE", "framing not QUOTED")
    order = store.orders.get(fo["order_id"])
    if order is None or order["fulfillment_status"] not in ("SUBMITTED", "READY_FOR_PICKUP"):
        api_err("ERR_LINKED_ORDER_NOT_READY", "linked order not ready")
    fo["status"] = "APPROVED"
    touch(fo)
    return ok(serialize(fo))


@app.route("/framing-orders/<fid>/start", methods=["POST"])
def start_framing(fid):
    auth(["FramingSpecialist"])
    fo = get_or_404(store.framing_orders, fid, "ERR_FRAMING_NOT_FOUND")
    if fo["status"] != "APPROVED":
        api_err("ERR_INVALID_STATE", "framing not APPROVED")
    fo["status"] = "IN_PRODUCTION"
    touch(fo)
    return ok(serialize(fo))


@app.route("/framing-orders/<fid>/complete", methods=["POST"])
def complete_framing(fid):
    auth(["FramingSpecialist"])
    fo = get_or_404(store.framing_orders, fid, "ERR_FRAMING_NOT_FOUND")
    if fo["status"] != "IN_PRODUCTION":
        api_err("ERR_INVALID_STATE", "framing not IN_PRODUCTION")
    fo["status"] = "READY"
    touch(fo)
    return ok(serialize(fo))


@app.route("/framing-orders/<fid>/cancel", methods=["POST"])
def cancel_framing(fid):
    auth(["Customer", "FramingSpecialist"])
    fo = get_or_404(store.framing_orders, fid, "ERR_FRAMING_NOT_FOUND")
    if fo["status"] not in ("QUOTED", "APPROVED"):
        api_err("ERR_INVALID_STATE", "framing not cancellable")
    fo["status"] = "CANCELLED"
    touch(fo)
    return ok(serialize(fo))


# --------------------------------------------------------------------------
# Project Bundles
# --------------------------------------------------------------------------
@app.route("/project-bundles", methods=["POST"])
def create_bundle():
    auth(["Customer", "StoreAssociate"])
    body = get_json()
    require_fields(body, ["customer_id", "name", "bom"])
    if body["customer_id"] not in store.customers:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "customer not found")
    bom = body["bom"]
    if not isinstance(bom, list):
        api_err("ERR_INVALID_REQUEST", "bom must be an array")
    for entry in bom:
        if not isinstance(entry, dict) or "product_id" not in entry or "quantity" not in entry:
            api_err("ERR_INVALID_REQUEST", "invalid bom entry")
        if entry["product_id"] not in store.products:
            api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "bom product not found")
    bundle = base_entity({
        "customer_id": body["customer_id"],
        "name": as_str(body["name"], "name"),
        "bom": bom,
        "status": "DRAFT",
    })
    store.project_bundles[bundle["id"]] = bundle
    return created(serialize(bundle))


@app.route("/project-bundles", methods=["GET"])
def list_bundles():
    auth(["Customer", "StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.project_bundles.values())
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [b for b in items if b["customer_id"] == cid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(b) for b in page], limit, offset, total)


@app.route("/project-bundles/<bid>", methods=["GET"])
def get_bundle(bid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    bundle = store.project_bundles.get(bid)
    if bundle is None:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "project bundle not found")
    return ok(serialize(bundle))


# --------------------------------------------------------------------------
# Special Orders
# --------------------------------------------------------------------------
@app.route("/special-orders", methods=["POST"])
def create_special_order():
    auth(["Customer", "StoreAssociate"])
    body = get_json()
    require_fields(body, ["customer_id", "product_id", "quantity"])
    if body["customer_id"] not in store.customers:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "customer not found")
    if body["product_id"] not in store.products:
        api_err("ERR_REFERENCED_ENTITY_NOT_FOUND", "product not found")
    so = base_entity({
        "customer_id": body["customer_id"],
        "product_id": body["product_id"],
        "quantity": as_number(body["quantity"], "quantity"),
        "quoted_unit_price_cents": None,
        "deposit_cents": None,
        "status": "REQUESTED",
    })
    store.special_orders[so["id"]] = so
    return created(serialize(so))


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    auth(["Customer", "StoreAssociate", "StoreManager"])
    limit, offset = pagination()
    items = list(store.special_orders.values())
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [s for s in items if s["customer_id"] == cid]
    pid = request.args.get("product_id")
    if pid is not None:
        items = [s for s in items if s["product_id"] == pid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([serialize(s) for s in page], limit, offset, total)


@app.route("/special-orders/<sid>", methods=["GET"])
def get_special_order(sid):
    auth(["Customer", "StoreAssociate", "StoreManager"])
    so = get_or_404(store.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    return ok(serialize(so))


@app.route("/special-orders/<sid>/quote", methods=["POST"])
def quote_special_order(sid):
    auth(["StoreManager"])
    so = get_or_404(store.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    body = get_json()
    if so["status"] != "REQUESTED":
        api_err("ERR_INVALID_STATE", "special order not REQUESTED")
    if "quoted_unit_price_cents" not in body or body["quoted_unit_price_cents"] is None:
        api_err("ERR_INVALID_REQUEST", "quoted_unit_price_cents required")
    price = as_int(body["quoted_unit_price_cents"], "quoted_unit_price_cents")
    so["quoted_unit_price_cents"] = price
    line_value = Decimal(str(price)) * Decimal(str(so["quantity"]))
    so["deposit_cents"] = round_half_up(line_value * Decimal("0.50"))
    so["status"] = "QUOTED"
    touch(so)
    return ok(serialize(so))


@app.route("/special-orders/<sid>/confirm", methods=["POST"])
def confirm_special_order(sid):
    auth(["Customer"])
    so = get_or_404(store.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if so["status"] != "QUOTED":
        api_err("ERR_INVALID_STATE", "special order not QUOTED")
    so["status"] = "CONFIRMED"
    touch(so)
    return ok(serialize(so))


@app.route("/special-orders/<sid>/receive", methods=["POST"])
def receive_special_order(sid):
    auth(["StoreAssociate"])
    so = get_or_404(store.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if so["status"] != "CONFIRMED":
        api_err("ERR_INVALID_STATE", "special order not CONFIRMED")
    lot = svc.product_lot(so["product_id"])
    if lot is not None:
        lot["on_hand_yards"] += so["quantity"]
        touch(lot)
    else:
        lot = base_entity({
            "product_id": so["product_id"],
            "on_hand_yards": so["quantity"],
            "reserved_yards": 0,
        })
        store.inventory_lots[lot["id"]] = lot
    so["status"] = "RECEIVED"
    touch(so)
    return ok(serialize(so))


@app.route("/special-orders/<sid>/cancel", methods=["POST"])
def cancel_special_order(sid):
    auth(["Customer", "StoreAssociate"])
    so = get_or_404(store.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if so["status"] not in ("REQUESTED", "QUOTED", "CONFIRMED"):
        api_err("ERR_INVALID_STATE", "special order not cancellable")
    so["status"] = "CANCELLED"
    touch(so)
    return ok(serialize(so))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
