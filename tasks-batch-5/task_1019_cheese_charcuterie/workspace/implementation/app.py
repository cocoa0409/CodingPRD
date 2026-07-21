"""Cheese & Charcuterie Shop API (task_1019) — Python + Flask, in-memory."""
import os
from datetime import timedelta

from flask import Flask, request, jsonify, g

from core import (
    DB, ApiError, err, touch, aging_days, rhu, D, parse_dt, iso_out, now_iso,
    request_id, ROLES,
    WHOLESALE_TIER_1_WEIGHT_G, WHOLESALE_TIER_2_WEIGHT_G,
    WHOLESALE_TIER_1_PCT, WHOLESALE_TIER_2_PCT, MAX_WHOLESALE_DISCOUNT_CENTS,
    DELIVERY_FEE_CENTS, BOARD_ASSEMBLY_FEE_CENTS, LOT_MAX_SHRINK_PCT,
    RAW_MILK_MIN_LEGAL_AGING_DAYS, WHOLESALE_MIN_ORDER_CENTS,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", code=200):
    return jsonify({"meta": _meta(), "response_type": response_type, "data": data}), code


def paginate(items):
    """items: list already sorted oldest-first. Returns (page, meta_extra)."""
    try:
        limit = request.args.get("limit", None)
        limit = 10 if limit is None else int(limit)
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = request.args.get("offset", None)
        offset = 0 if offset is None else int(offset)
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta_extra


def list_ok(objs, serializer):
    page, meta_extra = paginate(objs)
    data = [serializer(o) for o in page]
    return jsonify({"meta": _meta(meta_extra), "response_type": "array", "data": data}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_500(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": str(e)},
    }
    return jsonify(body), 400


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def authctx():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or invalid auth headers")
    g.uid = uid
    g.role = role
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "role not permitted for this operation")


def own_check(role, uid, resource_customer_id):
    if role == "WholesaleCustomer" and resource_customer_id != uid:
        raise err("ERR_UNAUTHORIZED", "wholesale customer may only act on its own resources")


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "request body must be a JSON object")
    return data


def need(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "missing required field: %s" % field)
    return body[field]


def need_str(body, field):
    v = need(body, field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "field %s must be a non-empty string" % field)
    return v


def need_enum(body, field, allowed):
    v = need(body, field)
    if v not in allowed:
        raise err("ERR_VALIDATION", "field %s must be one of %s" % (field, sorted(allowed)))
    return v


def need_int(body, field):
    v = need(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "field %s must be an integer" % field)
    return v


def opt_int(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "field %s must be an integer" % field)
    return v


def opt_num(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", "field %s must be a number" % field)
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", "field %s must be a boolean" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", "field %s must be a string" % field)
    return v


def get_or_404(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return obj


# ---------------------------------------------------------------------------
# Computed helpers
# ---------------------------------------------------------------------------

LIVE_ORDER_STATES = ("DRAFT", "SUBMITTED")


def lot_lines(lot_id):
    return [l for l in DB.order_lines.values() if l.get("lot_id") == lot_id]


def lot_reserved(lot):
    total = 0
    for l in lot_lines(lot["id"]):
        order = DB.orders.get(l["order_id"])
        if order and order["fulfillment_status"] in LIVE_ORDER_STATES:
            total += l.get("requested_weight_g", 0) or 0
    return total


def lot_current(lot):
    return lot["received_weight_g"] - lot["cumulative_shrink_g"] - lot["consumed_weight_g"]


def lot_available(lot):
    return max(0, lot_current(lot) - lot_reserved(lot))


def cave_used(cave_id):
    total = 0
    for lot in DB.lots.values():
        if lot["cave_id"] == cave_id and lot["status"] in ("AGING", "READY"):
            total += lot_current(lot)
    return total


def cave_available(cave):
    return max(0, cave["capacity_g"] - cave_used(cave["id"]))


def order_lines_of(order_id):
    lines = [l for l in DB.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda x: x["_seq"])
    return lines


def compute_order_totals(order):
    lines = order_lines_of(order["id"])
    fulfilled = order["fulfillment_status"] in ("FULFILLED", "RETURNED")
    billable = 0
    subtotal = 0
    for l in lines:
        if fulfilled:
            price = l.get("final_price_cents", 0) or 0
        else:
            price = l.get("provisional_price_cents", 0) or 0
        subtotal += price
        if l["line_type"] == "PRODUCT" and l.get("product_id"):
            product = DB.products.get(l["product_id"])
            if product and product["pricing_mode"] == "BY_WEIGHT":
                w = l.get("actual_cut_weight_g", 0) if fulfilled else l.get("requested_weight_g", 0)
                billable += w or 0

    if order["order_type"] == "WHOLESALE":
        if billable < WHOLESALE_TIER_1_WEIGHT_G:
            pct = D(0)
        elif billable < WHOLESALE_TIER_2_WEIGHT_G:
            pct = WHOLESALE_TIER_1_PCT
        else:
            pct = WHOLESALE_TIER_2_PCT
        discount = min(rhu(D(subtotal) * pct), MAX_WHOLESALE_DISCOUNT_CENTS)
    else:
        discount = 0

    delivery = DELIVERY_FEE_CENTS if order["order_type"] == "CATERING" else 0
    total = subtotal - discount + delivery
    return {
        "billable_weight_g": billable,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "delivery_fee_cents": delivery,
        "total_cents": total,
    }


def line_provisional_price(line):
    if line["line_type"] == "BOARD":
        board = DB.boards.get(line["board_id"])
        return board["base_price_cents"] if board else 0
    product = DB.products.get(line["product_id"])
    if product is None:
        return 0
    if product["pricing_mode"] == "BY_WEIGHT":
        return rhu(D(line.get("requested_weight_g", 0)) / D(1000) * D(product["price_per_kg_cents"]))
    return (line.get("requested_qty", 0) or 0) * product["unit_price_cents"]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

COMMON = ("id", "created_at", "updated_at", "version")


def _common(e):
    return {k: e[k] for k in COMMON}


def ser_customer(c):
    d = _common(c)
    d.update({
        "account_type": c["account_type"],
        "name": c["name"],
        "region_code": c["region_code"],
        "wholesale_tier": c["wholesale_tier"],
        "credit_limit_cents": c["credit_limit_cents"],
        "store_credit_cents": c["store_credit_cents"],
        "status": c["status"],
    })
    return d


def ser_product(p):
    d = _common(p)
    d.update({
        "name": p["name"], "category": p["category"], "milk_type": p["milk_type"],
        "pasteurized": p["pasteurized"], "form": p["form"], "pricing_mode": p["pricing_mode"],
        "price_per_kg_cents": p["price_per_kg_cents"], "unit_price_cents": p["unit_price_cents"],
        "allergens": p["allergens"], "min_aging_days": p["min_aging_days"],
        "target_aging_days": p["target_aging_days"], "shrink_pct_per_day": p["shrink_pct_per_day"],
    })
    return d


def ser_cave(c):
    d = _common(c)
    used = cave_used(c["id"])
    d.update({
        "name": c["name"], "temp_c": c["temp_c"], "humidity_pct": c["humidity_pct"],
        "capacity_g": c["capacity_g"], "used_g": used,
        "available_g": max(0, c["capacity_g"] - used),
    })
    return d


def ser_lot(l):
    d = _common(l)
    d.update({
        "product_id": l["product_id"], "cave_id": l["cave_id"],
        "received_weight_g": l["received_weight_g"],
        "current_weight_g": lot_current(l),
        "reserved_weight_g": lot_reserved(l),
        "available_weight_g": lot_available(l),
        "consumed_weight_g": l["consumed_weight_g"],
        "cumulative_shrink_g": l["cumulative_shrink_g"],
        "projected_ready_weight_g": l["projected_ready_weight_g"],
        "aging_start_date": l["aging_start_date"],
        "last_aged_days": l["last_aged_days"],
        "aging_days": aging_days(l),
        "status": l["status"],
    })
    return d


def ser_order(o):
    d = _common(o)
    totals = compute_order_totals(o)
    d.update({
        "order_type": o["order_type"], "customer_id": o["customer_id"],
        "prep_station_id": o["prep_station_id"],
        "prep_window_start": o["prep_window_start"],
        "prep_window_end": o["prep_window_end"],
        "event_date": o["event_date"],
        "fulfillment_status": o["fulfillment_status"],
        "payment_status": o["payment_status"],
        "payment_method": o["payment_method"],
        "store_credit_applied_cents": o["store_credit_applied_cents"],
    })
    d.update(totals)
    return d


def ser_line(l):
    d = _common(l)
    d.update({
        "order_id": l["order_id"], "line_type": l["line_type"],
        "product_id": l["product_id"], "board_id": l["board_id"], "lot_id": l["lot_id"],
        "requested_weight_g": l["requested_weight_g"], "requested_qty": l["requested_qty"],
        "actual_cut_weight_g": l["actual_cut_weight_g"],
        "reserved_weight_g": l.get("reserved_weight_g", 0),
        "provisional_price_cents": l["provisional_price_cents"],
        "final_price_cents": l["final_price_cents"],
    })
    return d


def ser_board(b):
    d = _common(b)
    d.update({
        "name": b["name"], "components": b["components"], "pairing_notes": b["pairing_notes"],
        "assembly_fee_cents": b["assembly_fee_cents"], "base_price_cents": b["base_price_cents"],
    })
    return d


def ser_subscription(s):
    d = _common(s)
    d.update({
        "customer_id": s["customer_id"], "board_id": s["board_id"], "tier": s["tier"],
        "cadence_days": s["cadence_days"], "monthly_price_cents": s["monthly_price_cents"],
        "is_gift": s["is_gift"], "gift_recipient_email": s["gift_recipient_email"],
        "status": s["status"], "next_ship_date": s["next_ship_date"],
    })
    return d


def ser_prep(p):
    d = _common(p)
    d.update({"name": p["name"]})
    return d


def ser_room(r):
    d = _common(r)
    d.update({"name": r["name"], "seat_capacity": r["seat_capacity"],
              "buffer_minutes": r["buffer_minutes"]})
    return d


def ser_event(e):
    d = _common(e)
    d.update({
        "tasting_room_id": e["tasting_room_id"], "customer_id": e["customer_id"],
        "start_at": e["start_at"], "end_at": e["end_at"], "seats": e["seats"],
        "pairing_product_ids": e["pairing_product_ids"], "status": e["status"],
    })
    return d


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@app.route("/api/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    iso = need_str(body, "to_iso8601")
    DB.clock = parse_dt(iso)
    return ok({}, "object", 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


@app.route("/api/customers", methods=["POST"])
def customer_create():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    account_type = need_enum(body, "account_type", {"RETAIL", "WHOLESALE_RESTAURANT"})
    name = need_str(body, "name")
    region_code = need_str(body, "region_code")
    wholesale_tier = body.get("wholesale_tier", "NONE") or "NONE"
    if wholesale_tier not in {"NONE", "BRONZE", "SILVER", "GOLD"}:
        raise err("ERR_VALIDATION", "invalid wholesale_tier")
    credit_limit = opt_int(body, "credit_limit_cents", 0)
    store_credit = opt_int(body, "store_credit_cents", 0)
    if store_credit < 0:
        raise err("ERR_VALIDATION", "store_credit_cents must be >= 0")
    c = DB.new_common()
    c.update({
        "account_type": account_type, "name": name, "region_code": region_code,
        "wholesale_tier": wholesale_tier, "credit_limit_cents": credit_limit,
        "store_credit_cents": store_credit, "status": "ACTIVE",
    })
    DB.customers[c["id"]] = c
    return ok(ser_customer(c), "object", 201)


@app.route("/api/customers/<customer_id>", methods=["GET"])
def customer_get(customer_id):
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    c = get_or_404(DB.customers, customer_id)
    own_check(role, uid, c["id"])
    return ok(ser_customer(c), "object", 200)


@app.route("/api/customers/<customer_id>/set-status", methods=["POST"])
def customer_set_status(customer_id):
    _, role = authctx()
    require_role(role, {"ShopManager"})
    c = get_or_404(DB.customers, customer_id)
    body = body_json()
    target = need_enum(body, "status", {"ACTIVE", "DELINQUENT", "CLOSED"})
    cur = c["status"]
    allowed = {
        "ACTIVE": {"DELINQUENT", "CLOSED"},
        "DELINQUENT": {"ACTIVE", "CLOSED"},
        "CLOSED": set(),
    }
    if target not in allowed.get(cur, set()):
        raise err("ERR_INVALID_STATE", "cannot move customer %s -> %s" % (cur, target))
    c["status"] = target
    touch(c)
    return ok(ser_customer(c), "object", 200)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@app.route("/api/products", methods=["POST"])
def product_create():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = need_str(body, "name")
    category = need_enum(body, "category", {"CHEESE", "CHARCUTERIE"})
    milk_type = need_enum(body, "milk_type", {"COW", "GOAT", "SHEEP", "BUFFALO", "NONE"})
    pasteurized = need(body, "pasteurized")
    if not isinstance(pasteurized, bool):
        raise err("ERR_VALIDATION", "pasteurized must be boolean")
    form = need_enum(body, "form", {"WHEEL", "WEDGE", "BLOCK", "WHOLE_MUSCLE", "SLICED"})
    pricing_mode = need_enum(body, "pricing_mode", {"BY_WEIGHT", "BY_UNIT"})
    price_per_kg = opt_int(body, "price_per_kg_cents", 0)
    unit_price = opt_int(body, "unit_price_cents", 0)
    allergens = body.get("allergens", []) or []
    if not isinstance(allergens, list):
        raise err("ERR_VALIDATION", "allergens must be an array")
    min_aging = opt_int(body, "min_aging_days", 0)
    target_aging = opt_int(body, "target_aging_days", 0)
    shrink = opt_num(body, "shrink_pct_per_day", 0)
    if min_aging < 0 or target_aging < 0 or shrink < 0:
        raise err("ERR_VALIDATION", "aging/shrink values must be >= 0")

    # Pricing coherence (priority 5)
    if pricing_mode == "BY_WEIGHT":
        if not (price_per_kg > 0 and unit_price == 0):
            raise err("ERR_INVALID_PRICING_CONFIG", "BY_WEIGHT requires price_per_kg_cents>0 and unit_price_cents==0")
    else:
        if not (unit_price > 0 and price_per_kg == 0):
            raise err("ERR_INVALID_PRICING_CONFIG", "BY_UNIT requires unit_price_cents>0 and price_per_kg_cents==0")

    p = DB.new_common()
    p.update({
        "name": name, "category": category, "milk_type": milk_type,
        "pasteurized": pasteurized, "form": form, "pricing_mode": pricing_mode,
        "price_per_kg_cents": price_per_kg, "unit_price_cents": unit_price,
        "allergens": allergens, "min_aging_days": min_aging,
        "target_aging_days": target_aging, "shrink_pct_per_day": shrink,
    })
    DB.products[p["id"]] = p
    return ok(ser_product(p), "object", 201)


@app.route("/api/products/<product_id>", methods=["GET"])
def product_get(product_id):
    _, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    p = get_or_404(DB.products, product_id)
    return ok(ser_product(p), "object", 200)


# ---------------------------------------------------------------------------
# Caves
# ---------------------------------------------------------------------------


@app.route("/api/caves", methods=["POST"])
def cave_create():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = need_str(body, "name")
    temp_c = opt_num(body, "temp_c", 0)
    humidity = opt_num(body, "humidity_pct", 0)
    capacity = need_int(body, "capacity_g")
    if capacity <= 0:
        raise err("ERR_VALIDATION", "capacity_g must be > 0")
    c = DB.new_common()
    c.update({"name": name, "temp_c": temp_c, "humidity_pct": humidity, "capacity_g": capacity})
    DB.caves[c["id"]] = c
    return ok(ser_cave(c), "object", 201)


@app.route("/api/caves/<cave_id>", methods=["GET"])
def cave_get(cave_id):
    _, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff"})
    c = get_or_404(DB.caves, cave_id)
    return ok(ser_cave(c), "object", 200)


@app.route("/api/caves/<cave_id>/rotate", methods=["POST"])
def cave_rotate(cave_id):
    _, role = authctx()
    require_role(role, {"ShopManager"})
    cave = get_or_404(DB.caves, cave_id)
    lots = [l for l in DB.lots.values()
            if l["cave_id"] == cave_id and l["status"] in ("AGING", "READY")]
    lots.sort(key=lambda x: x["_seq"])
    for lot in lots:
        product = DB.products.get(lot["product_id"])
        ad = aging_days(lot)
        delta = ad - lot["last_aged_days"]
        if delta < 0:
            delta = 0
        rate = product["shrink_pct_per_day"] if product else 0
        cur = lot_current(lot)
        shrink_g = rhu(D(cur) * D(rate) * D(delta))
        lot["cumulative_shrink_g"] += shrink_g
        lot["last_aged_days"] = ad
        # Resolve state
        ceiling = D(lot["received_weight_g"]) * LOT_MAX_SHRINK_PCT
        if D(lot["cumulative_shrink_g"]) >= ceiling:
            lot["status"] = "DISCARDED"
        elif lot["status"] == "AGING" and product and ad >= product["min_aging_days"]:
            lot["status"] = "READY"
        touch(lot)
    touch(cave)
    return ok(ser_cave(cave), "object", 200)


# ---------------------------------------------------------------------------
# Lots
# ---------------------------------------------------------------------------


@app.route("/api/lots", methods=["POST"])
def lot_create():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    product_id = need(body, "product_id")
    cave_id = need(body, "cave_id")
    product = DB.products.get(product_id)
    if product is None:
        raise err("ERR_NOT_FOUND", "product not found")
    cave = DB.caves.get(cave_id)
    if cave is None:
        raise err("ERR_NOT_FOUND", "cave not found")
    received = need_int(body, "received_weight_g")
    if received <= 0:
        raise err("ERR_VALIDATION", "received_weight_g must be > 0")
    # Capacity check (priority 14)
    if received > cave_available(cave):
        raise err("ERR_CAVE_CAPACITY_EXCEEDED", "receiving would exceed cave capacity")

    projected = rhu(D(received) * (D(1) - D(product["shrink_pct_per_day"]) * D(product["target_aging_days"])))
    l = DB.new_common()
    l.update({
        "product_id": product_id, "cave_id": cave_id, "received_weight_g": received,
        "consumed_weight_g": 0, "cumulative_shrink_g": 0, "last_aged_days": 0,
        "projected_ready_weight_g": projected,
        "aging_start_date": iso_out(DB.clock), "_aging_start_dt": DB.clock,
        "status": "AGING",
    })
    DB.lots[l["id"]] = l
    return ok(ser_lot(l), "object", 201)


@app.route("/api/lots/<lot_id>", methods=["GET"])
def lot_get(lot_id):
    _, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    l = get_or_404(DB.lots, lot_id)
    return ok(ser_lot(l), "object", 200)


@app.route("/api/lots", methods=["GET"])
def lot_list():
    _, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    items = list(DB.lots.values())
    pid = request.args.get("product_id")
    cid = request.args.get("cave_id")
    status = request.args.get("status")
    if pid:
        items = [i for i in items if i["product_id"] == pid]
    if cid:
        items = [i for i in items if i["cave_id"] == cid]
    if status:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda x: x["_seq"])
    return list_ok(items, ser_lot)


@app.route("/api/lots/<lot_id>/discard", methods=["POST"])
def lot_discard(lot_id):
    _, role = authctx()
    require_role(role, {"ShopManager"})
    l = get_or_404(DB.lots, lot_id)
    if l["status"] in ("DEPLETED", "DISCARDED"):
        raise err("ERR_INVALID_STATE", "lot already terminal")
    if l["status"] == "READY" and lot_reserved(l) != 0:
        raise err("ERR_INVALID_STATE", "cannot discard a lot with live reservations")
    l["status"] = "DISCARDED"
    touch(l)
    return ok(ser_lot(l), "object", 200)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def prep_conflict(prep_station_id, start, end, exclude_order_id):
    """True if [start,end) overlaps any live catering order on this station."""
    for o in DB.orders.values():
        if o["id"] == exclude_order_id:
            continue
        if o["order_type"] != "CATERING":
            continue
        if o["prep_station_id"] != prep_station_id:
            continue
        if o["fulfillment_status"] not in ("DRAFT", "SUBMITTED", "FULFILLED"):
            continue
        os_, oe = o.get("_pw_start"), o.get("_pw_end")
        if os_ is None or oe is None:
            continue
        if start < oe and os_ < end:  # half-open overlap; adjacency allowed
            return True
    return False


@app.route("/api/orders", methods=["POST"])
def order_create():
    uid, role = authctx()
    require_role(role, {"CounterStaff", "WholesaleCustomer"})
    body = body_json()
    order_type = body.get("order_type")
    customer_id = body.get("customer_id")
    # Ownership (before existence) for wholesale principals
    if role == "WholesaleCustomer" and customer_id is not None and customer_id != uid:
        raise err("ERR_UNAUTHORIZED", "wholesale customer may only create own orders")
    # Existence of FKs
    if customer_id is None:
        raise err("ERR_VALIDATION", "missing required field: customer_id")
    if customer_id not in DB.customers:
        raise err("ERR_NOT_FOUND", "customer not found")
    prep_station_id = body.get("prep_station_id")
    if prep_station_id is not None and prep_station_id not in DB.prep_stations:
        raise err("ERR_NOT_FOUND", "prep station not found")
    # Body validation
    if order_type not in ("RETAIL", "BOARD", "CATERING", "WHOLESALE"):
        raise err("ERR_VALIDATION", "invalid order_type")

    pw_start = pw_end = event_date = None
    raw_start = body.get("prep_window_start")
    raw_end = body.get("prep_window_end")
    raw_event = body.get("event_date")
    if order_type == "CATERING":
        if prep_station_id is None:
            raise err("ERR_VALIDATION", "CATERING order requires prep_station_id")
        if raw_start is None or raw_end is None:
            raise err("ERR_VALIDATION", "CATERING order requires prep window")
        pw_start = parse_dt(raw_start)
        pw_end = parse_dt(raw_end)
        event_date = parse_dt(raw_event) if raw_event is not None else None
        # Temporal conflict (immediate at create)
        if prep_conflict(prep_station_id, pw_start, pw_end, None):
            raise err("ERR_PREP_STATION_CONFLICT", "prep window overlaps a live catering order")
    else:
        prep_station_id = None

    o = DB.new_common()
    o.update({
        "order_type": order_type, "customer_id": customer_id,
        "prep_station_id": prep_station_id,
        "prep_window_start": raw_start if order_type == "CATERING" else None,
        "prep_window_end": raw_end if order_type == "CATERING" else None,
        "event_date": raw_event if order_type == "CATERING" else None,
        "_pw_start": pw_start, "_pw_end": pw_end,
        "fulfillment_status": "DRAFT", "payment_status": "UNPAID",
        "payment_method": "NONE", "store_credit_applied_cents": 0,
    })
    DB.orders[o["id"]] = o
    return ok(ser_order(o), "object", 201)


@app.route("/api/orders/<order_id>", methods=["GET"])
def order_get(order_id):
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    o = get_or_404(DB.orders, order_id)
    own_check(role, uid, o["customer_id"])
    return ok(ser_order(o), "object", 200)


@app.route("/api/orders", methods=["GET"])
def order_list():
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    items = list(DB.orders.values())
    if role == "WholesaleCustomer":
        items = [i for i in items if i["customer_id"] == uid]
    cid = request.args.get("customer_id")
    psid = request.args.get("prep_station_id")
    otype = request.args.get("order_type")
    fstatus = request.args.get("fulfillment_status")
    if cid:
        items = [i for i in items if i["customer_id"] == cid]
    if psid:
        items = [i for i in items if i["prep_station_id"] == psid]
    if otype:
        items = [i for i in items if i["order_type"] == otype]
    if fstatus:
        items = [i for i in items if i["fulfillment_status"] == fstatus]
    items.sort(key=lambda x: x["_seq"])
    return list_ok(items, ser_order)


@app.route("/api/orders/<order_id>/lines", methods=["POST"])
def order_add_line(order_id):
    uid, role = authctx()
    require_role(role, {"CounterStaff", "WholesaleCustomer"})
    o = get_or_404(DB.orders, order_id)
    own_check(role, uid, o["customer_id"])
    body = body_json()
    line_type = body.get("line_type")
    # Existence of body FKs (left to right)
    product_id = body.get("product_id")
    board_id = body.get("board_id")
    if line_type == "PRODUCT":
        if product_id is None:
            raise err("ERR_VALIDATION", "PRODUCT line requires product_id")
        if product_id not in DB.products:
            raise err("ERR_NOT_FOUND", "product not found")
    elif line_type == "BOARD":
        if board_id is None:
            raise err("ERR_VALIDATION", "BOARD line requires board_id")
        if board_id not in DB.boards:
            raise err("ERR_NOT_FOUND", "board not found")
    else:
        raise err("ERR_VALIDATION", "invalid line_type")

    # State: order must be DRAFT
    if o["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_DRAFT", "order is not DRAFT")

    requested_weight = opt_int(body, "requested_weight_g", 0)
    requested_qty = opt_int(body, "requested_qty", 0)

    l = DB.new_common()
    l.update({
        "order_id": order_id, "line_type": line_type,
        "product_id": product_id if line_type == "PRODUCT" else None,
        "board_id": board_id if line_type == "BOARD" else None,
        "lot_id": None,
        "requested_weight_g": requested_weight, "requested_qty": requested_qty,
        "actual_cut_weight_g": 0, "reserved_weight_g": 0,
    })
    prov = line_provisional_price(l)
    l["provisional_price_cents"] = prov
    l["final_price_cents"] = prov
    DB.order_lines[l["id"]] = l
    touch(o)
    return ok(ser_line(l), "object", 201)


@app.route("/api/order-lines/<line_id>/allocate", methods=["POST"])
def line_allocate(line_id):
    _, role = authctx()
    require_role(role, {"CounterStaff"})
    line = get_or_404(DB.order_lines, line_id)
    body = body_json()
    lot_id = body.get("lot_id")
    if lot_id is None:
        raise err("ERR_VALIDATION", "missing required field: lot_id")
    lot = DB.lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "lot not found")
    if "expected_lot_version" not in body or body["expected_lot_version"] is None:
        raise err("ERR_VALIDATION", "missing required field: expected_lot_version")
    expected = body["expected_lot_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_VALIDATION", "expected_lot_version must be an integer")

    order = DB.orders.get(line["order_id"])
    # priority 7: order DRAFT
    if order is None or order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_DRAFT", "order is not DRAFT")
    # priority 8: lot READY
    if lot["status"] != "READY":
        raise err("ERR_LOT_NOT_READY", "lot is not READY")
    # priority 15: sufficient weight
    if lot_available(lot) < (line.get("requested_weight_g", 0) or 0):
        raise err("ERR_INSUFFICIENT_LOT_WEIGHT", "insufficient lot weight")
    # priority 19: OCC
    if expected != lot["version"]:
        raise err("ERR_STALE_LOT_VERSION", "expected_lot_version does not match")

    line["lot_id"] = lot_id
    line["reserved_weight_g"] = line.get("requested_weight_g", 0) or 0
    touch(line)
    touch(lot)  # bumps Lot.version by 1
    return ok(ser_line(line), "object", 200)


@app.route("/api/order-lines/<line_id>", methods=["GET"])
def line_get(line_id):
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    line = get_or_404(DB.order_lines, line_id)
    order = DB.orders.get(line["order_id"])
    if order is not None:
        own_check(role, uid, order["customer_id"])
    return ok(ser_line(line), "object", 200)


@app.route("/api/order-lines", methods=["GET"])
def line_list():
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    items = list(DB.order_lines.values())
    if role == "WholesaleCustomer":
        own_ids = {o["id"] for o in DB.orders.values() if o["customer_id"] == uid}
        items = [i for i in items if i["order_id"] in own_ids]
    oid = request.args.get("order_id")
    pid = request.args.get("product_id")
    lid = request.args.get("lot_id")
    bid = request.args.get("board_id")
    if oid:
        items = [i for i in items if i["order_id"] == oid]
    if pid:
        items = [i for i in items if i["product_id"] == pid]
    if lid:
        items = [i for i in items if i["lot_id"] == lid]
    if bid:
        items = [i for i in items if i["board_id"] == bid]
    items.sort(key=lambda x: x["_seq"])
    return list_ok(items, ser_line)


def raw_milk_violation(order):
    for l in order_lines_of(order["id"]):
        if l["line_type"] != "PRODUCT" or not l.get("lot_id"):
            continue
        lot = DB.lots.get(l["lot_id"])
        if lot is None:
            continue
        product = DB.products.get(lot["product_id"])
        if product and product["pasteurized"] is False:
            if aging_days(lot) < RAW_MILK_MIN_LEGAL_AGING_DAYS:
                return True
    return False


@app.route("/api/orders/<order_id>/submit", methods=["POST"])
def order_submit(order_id):
    uid, role = authctx()
    require_role(role, {"CounterStaff", "WholesaleCustomer"})
    o = get_or_404(DB.orders, order_id)
    own_check(role, uid, o["customer_id"])
    # State: must be DRAFT
    if o["fulfillment_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "order is not DRAFT")
    lines = order_lines_of(order_id)
    # 1. empty order
    if len(lines) == 0:
        raise err("ERR_EMPTY_ORDER", "order has no lines")
    # 2. every BY_WEIGHT PRODUCT line allocated
    for l in lines:
        if l["line_type"] == "PRODUCT" and l.get("product_id"):
            product = DB.products.get(l["product_id"])
            if product and product["pricing_mode"] == "BY_WEIGHT" and not l.get("lot_id"):
                raise err("ERR_INVALID_STATE", "by-weight line not allocated to a lot")
    # 3. raw-milk safety
    if raw_milk_violation(o):
        raise err("ERR_RAW_MILK_AGING", "allocated raw-milk lot below legal aging")
    # 4. catering temporal
    if o["order_type"] == "CATERING":
        if prep_conflict(o["prep_station_id"], o["_pw_start"], o["_pw_end"], o["id"]):
            raise err("ERR_PREP_STATION_CONFLICT", "prep window overlaps a live catering order")
    # 5. wholesale fiscal floor
    if o["order_type"] == "WHOLESALE":
        totals = compute_order_totals(o)
        if totals["subtotal_cents"] < WHOLESALE_MIN_ORDER_CENTS:
            raise err("ERR_WHOLESALE_MIN_ORDER", "wholesale order below minimum")

    o["fulfillment_status"] = "SUBMITTED"
    touch(o)
    return ok(ser_order(o), "object", 200)


@app.route("/api/orders/<order_id>/pay", methods=["POST"])
def order_pay(order_id):
    uid, role = authctx()
    require_role(role, {"CounterStaff", "WholesaleCustomer"})
    o = get_or_404(DB.orders, order_id)
    own_check(role, uid, o["customer_id"])
    body = body_json()
    payment_method = need_enum(body, "payment_method", {"STORE_CREDIT", "EXTERNAL"})
    if o["fulfillment_status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "order is not SUBMITTED")
    if o["payment_status"] != "UNPAID":
        raise err("ERR_ALREADY_PAID", "order already paid")
    totals = compute_order_totals(o)
    total = totals["total_cents"]
    if payment_method == "STORE_CREDIT":
        customer = DB.customers.get(o["customer_id"])
        if customer is None or customer["store_credit_cents"] < total:
            raise err("ERR_INSUFFICIENT_STORE_CREDIT", "insufficient store credit")
        customer["store_credit_cents"] -= total
        touch(customer)
        o["store_credit_applied_cents"] = total
    o["payment_method"] = payment_method
    o["payment_status"] = "PAID"
    touch(o)
    return ok(ser_order(o), "object", 200)


def parse_line_actuals(raw):
    m = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                lid = item.get("line_id") or item.get("order_line_id") or item.get("id")
                w = item.get("actual_cut_weight_g")
                if w is None:
                    w = item.get("actual_weight_g", item.get("weight_g", item.get("actual")))
                if lid is not None:
                    m[lid] = w
    elif isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                m[k] = v.get("actual_cut_weight_g", v.get("actual_weight_g"))
            else:
                m[k] = v
    return m


@app.route("/api/orders/<order_id>/fulfill", methods=["POST"])
def order_fulfill(order_id):
    _, role = authctx()
    require_role(role, {"CounterStaff"})
    o = get_or_404(DB.orders, order_id)
    body = body_json()
    if o["fulfillment_status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "order is not SUBMITTED")
    if o["payment_status"] != "PAID":
        raise err("ERR_ORDER_NOT_PAID", "order is not PAID")
    if raw_milk_violation(o):
        raise err("ERR_RAW_MILK_AGING", "allocated raw-milk lot below legal aging")

    actuals = parse_line_actuals(body.get("line_actuals"))
    lines = order_lines_of(order_id)
    # Validate all by-weight product lines have an actual weight
    for l in lines:
        if l["line_type"] == "PRODUCT" and l.get("product_id"):
            product = DB.products.get(l["product_id"])
            if product and product["pricing_mode"] == "BY_WEIGHT":
                w = actuals.get(l["id"])
                if w is None or isinstance(w, bool) or not isinstance(w, int):
                    raise err("ERR_VALIDATION", "missing actual_cut_weight_g for line %s" % l["id"])
                if w < 0:
                    raise err("ERR_VALIDATION", "actual_cut_weight_g must be >= 0")

    affected_lots = set()
    for l in lines:
        if l["line_type"] == "PRODUCT" and l.get("product_id"):
            product = DB.products.get(l["product_id"])
            if product and product["pricing_mode"] == "BY_WEIGHT":
                w = actuals.get(l["id"])
                l["actual_cut_weight_g"] = w
                l["final_price_cents"] = rhu(D(w) / D(1000) * D(product["price_per_kg_cents"]))
                lot = DB.lots.get(l["lot_id"]) if l.get("lot_id") else None
                if lot is not None:
                    lot["consumed_weight_g"] += w
                    affected_lots.add(lot["id"])
                l["reserved_weight_g"] = 0
                touch(l)
            elif product and product["pricing_mode"] == "BY_UNIT":
                l["final_price_cents"] = l["provisional_price_cents"]
        # BOARD lines keep provisional == final

    o["fulfillment_status"] = "FULFILLED"
    touch(o)

    # Cascade: deplete lots that hit zero availability
    for lot_id in affected_lots:
        lot = DB.lots.get(lot_id)
        if lot and lot["status"] == "READY" and lot_available(lot) <= 0:
            lot["status"] = "DEPLETED"
            touch(lot)
    return ok(ser_order(o), "object", 200)


@app.route("/api/orders/<order_id>/cancel", methods=["POST"])
def order_cancel(order_id):
    uid, role = authctx()
    require_role(role, {"CounterStaff", "WholesaleCustomer"})
    o = get_or_404(DB.orders, order_id)
    own_check(role, uid, o["customer_id"])
    if o["fulfillment_status"] not in ("DRAFT", "SUBMITTED"):
        raise err("ERR_INVALID_STATE", "order cannot be cancelled from its current state")
    was_paid = o["payment_status"] == "PAID"
    o["fulfillment_status"] = "CANCELLED"
    # Reservations released automatically (order no longer live)
    if was_paid:
        _refund(o)
    touch(o)
    return ok(ser_order(o), "object", 200)


def _refund(o):
    o["payment_status"] = "REFUNDED"
    if o["payment_method"] == "STORE_CREDIT":
        customer = DB.customers.get(o["customer_id"])
        if customer is not None:
            customer["store_credit_cents"] += o["store_credit_applied_cents"]
            touch(customer)


@app.route("/api/orders/<order_id>/return", methods=["POST"])
def order_return(order_id):
    _, role = authctx()
    require_role(role, {"CounterStaff"})
    o = get_or_404(DB.orders, order_id)
    if o["fulfillment_status"] != "FULFILLED":
        raise err("ERR_ORDER_NOT_FULFILLED", "order is not FULFILLED")
    if o["payment_status"] != "PAID":
        raise err("ERR_ORDER_NOT_PAID", "order is not PAID")
    for l in order_lines_of(order_id):
        if l["line_type"] == "PRODUCT" and l.get("lot_id"):
            lot = DB.lots.get(l["lot_id"])
            if lot is not None:
                lot["consumed_weight_g"] -= (l.get("actual_cut_weight_g", 0) or 0)
                if lot["status"] == "DEPLETED" and lot_available(lot) > 0:
                    lot["status"] = "READY"
                touch(lot)
    o["fulfillment_status"] = "RETURNED"
    _refund(o)
    touch(o)
    return ok(ser_order(o), "object", 200)


@app.route("/api/orders/<order_id>/label", methods=["GET"])
def order_label(order_id):
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    o = get_or_404(DB.orders, order_id)
    own_check(role, uid, o["customer_id"])
    lines = order_lines_of(order_id)
    allergens = set()
    contains_raw = False
    for l in lines:
        products = []
        if l["line_type"] == "PRODUCT" and l.get("product_id"):
            p = DB.products.get(l["product_id"])
            if p:
                products.append(p)
        elif l["line_type"] == "BOARD" and l.get("board_id"):
            board = DB.boards.get(l["board_id"])
            if board:
                for comp in board.get("components", []):
                    p = DB.products.get(comp.get("product_id"))
                    if p:
                        products.append(p)
        for p in products:
            for a in p.get("allergens", []):
                allergens.add(a)
            if p["pasteurized"] is False:
                contains_raw = True
    data = {
        "order_id": order_id,
        "allergens": sorted(allergens),
        "contains_raw_milk": contains_raw,
        "line_count": len(lines),
    }
    return ok(data, "object", 200)


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


@app.route("/api/boards", methods=["POST"])
def board_create():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = need_str(body, "name")
    components = need(body, "components")
    if not isinstance(components, list) or len(components) == 0:
        raise err("ERR_VALIDATION", "components must be a non-empty array")
    pairing_notes = opt_str(body, "pairing_notes", None)
    # Existence of component products first (left to right)
    for comp in components:
        if not isinstance(comp, dict):
            raise err("ERR_VALIDATION", "each component must be an object")
        pid = comp.get("product_id")
        if pid is None:
            raise err("ERR_VALIDATION", "component requires product_id")
        if pid not in DB.products:
            raise err("ERR_NOT_FOUND", "component product not found")
    components_sum = 0
    for comp in components:
        pid = comp.get("product_id")
        portion = comp.get("portion_g")
        if portion is None or isinstance(portion, bool) or not isinstance(portion, int):
            raise err("ERR_VALIDATION", "component requires integer portion_g")
        product = DB.products[pid]
        if product["pricing_mode"] != "BY_WEIGHT":
            raise err("ERR_VALIDATION", "board components must be BY_WEIGHT products")
        components_sum += rhu(D(portion) / D(1000) * D(product["price_per_kg_cents"]))
    base_price = components_sum + BOARD_ASSEMBLY_FEE_CENTS

    b = DB.new_common()
    b.update({
        "name": name, "components": components, "pairing_notes": pairing_notes,
        "assembly_fee_cents": BOARD_ASSEMBLY_FEE_CENTS, "base_price_cents": base_price,
    })
    DB.boards[b["id"]] = b
    return ok(ser_board(b), "object", 201)


@app.route("/api/boards/<board_id>", methods=["GET"])
def board_get(board_id):
    _, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    b = get_or_404(DB.boards, board_id)
    return ok(ser_board(b), "object", 200)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@app.route("/api/subscriptions", methods=["POST"])
def subscription_create():
    uid, role = authctx()
    require_role(role, {"CounterStaff", "WholesaleCustomer"})
    body = body_json()
    customer_id = body.get("customer_id")
    if role == "WholesaleCustomer" and customer_id is not None and customer_id != uid:
        raise err("ERR_UNAUTHORIZED", "wholesale customer may only create own subscriptions")
    if customer_id is None:
        raise err("ERR_VALIDATION", "missing required field: customer_id")
    if customer_id not in DB.customers:
        raise err("ERR_NOT_FOUND", "customer not found")
    board_id = body.get("board_id")
    if board_id is None:
        raise err("ERR_VALIDATION", "missing required field: board_id")
    if board_id not in DB.boards:
        raise err("ERR_NOT_FOUND", "board not found")
    tier = need_enum(body, "tier", {"CLASSIC", "PREMIUM"})
    monthly = need_int(body, "monthly_price_cents")
    if monthly <= 0:
        raise err("ERR_VALIDATION", "monthly_price_cents must be > 0")
    cadence = opt_int(body, "cadence_days", 30)
    if cadence <= 0:
        raise err("ERR_VALIDATION", "cadence_days must be > 0")
    is_gift = opt_bool(body, "is_gift", False)
    gift_email = opt_str(body, "gift_recipient_email", None)

    next_ship = DB.clock + timedelta(days=cadence)
    s = DB.new_common()
    s.update({
        "customer_id": customer_id, "board_id": board_id, "tier": tier,
        "cadence_days": cadence, "monthly_price_cents": monthly,
        "is_gift": is_gift, "gift_recipient_email": gift_email,
        "status": "ACTIVE", "next_ship_date": iso_out(next_ship), "_next_ship_dt": next_ship,
    })
    DB.subscriptions[s["id"]] = s
    return ok(ser_subscription(s), "object", 201)


@app.route("/api/subscriptions/<subscription_id>", methods=["GET"])
def subscription_get(subscription_id):
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    s = get_or_404(DB.subscriptions, subscription_id)
    own_check(role, uid, s["customer_id"])
    return ok(ser_subscription(s), "object", 200)


@app.route("/api/subscriptions", methods=["GET"])
def subscription_list():
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    items = list(DB.subscriptions.values())
    if role == "WholesaleCustomer":
        items = [i for i in items if i["customer_id"] == uid]
    cid = request.args.get("customer_id")
    bid = request.args.get("board_id")
    status = request.args.get("status")
    if cid:
        items = [i for i in items if i["customer_id"] == cid]
    if bid:
        items = [i for i in items if i["board_id"] == bid]
    if status:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda x: x["_seq"])
    return list_ok(items, ser_subscription)


def _sub_transition(subscription_id, action):
    uid, role = authctx()
    require_role(role, {"CounterStaff", "WholesaleCustomer"})
    s = get_or_404(DB.subscriptions, subscription_id)
    own_check(role, uid, s["customer_id"])
    if action == "pause":
        if s["status"] != "ACTIVE":
            raise err("ERR_SUBSCRIPTION_INVALID_STATE", "subscription is not ACTIVE")
        s["status"] = "PAUSED"
    elif action == "resume":
        if s["status"] != "PAUSED":
            raise err("ERR_SUBSCRIPTION_INVALID_STATE", "subscription is not PAUSED")
        s["status"] = "ACTIVE"
        s["_next_ship_dt"] = s["_next_ship_dt"] + timedelta(days=s["cadence_days"])
        s["next_ship_date"] = iso_out(s["_next_ship_dt"])
    elif action == "cancel":
        if s["status"] not in ("ACTIVE", "PAUSED"):
            raise err("ERR_SUBSCRIPTION_INVALID_STATE", "subscription is terminal")
        s["status"] = "CANCELLED"
    touch(s)
    return ok(ser_subscription(s), "object", 200)


@app.route("/api/subscriptions/<subscription_id>/pause", methods=["POST"])
def subscription_pause(subscription_id):
    return _sub_transition(subscription_id, "pause")


@app.route("/api/subscriptions/<subscription_id>/resume", methods=["POST"])
def subscription_resume(subscription_id):
    return _sub_transition(subscription_id, "resume")


@app.route("/api/subscriptions/<subscription_id>/cancel", methods=["POST"])
def subscription_cancel(subscription_id):
    return _sub_transition(subscription_id, "cancel")


# ---------------------------------------------------------------------------
# Prep stations
# ---------------------------------------------------------------------------


@app.route("/api/prep-stations", methods=["POST"])
def prep_create():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = need_str(body, "name")
    p = DB.new_common()
    p.update({"name": name})
    DB.prep_stations[p["id"]] = p
    return ok(ser_prep(p), "object", 201)


@app.route("/api/prep-stations/<prep_station_id>", methods=["GET"])
def prep_get(prep_station_id):
    _, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff"})
    p = get_or_404(DB.prep_stations, prep_station_id)
    return ok(ser_prep(p), "object", 200)


# ---------------------------------------------------------------------------
# Tasting rooms & events
# ---------------------------------------------------------------------------


@app.route("/api/tasting-rooms", methods=["POST"])
def room_create():
    _, role = authctx()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = need_str(body, "name")
    seat_capacity = need_int(body, "seat_capacity")
    if seat_capacity <= 0:
        raise err("ERR_VALIDATION", "seat_capacity must be > 0")
    buffer_minutes = opt_int(body, "buffer_minutes", 30)
    if buffer_minutes < 0:
        raise err("ERR_VALIDATION", "buffer_minutes must be >= 0")
    r = DB.new_common()
    r.update({"name": name, "seat_capacity": seat_capacity, "buffer_minutes": buffer_minutes})
    DB.tasting_rooms[r["id"]] = r
    return ok(ser_room(r), "object", 201)


@app.route("/api/tasting-rooms/<tasting_room_id>", methods=["GET"])
def room_get(tasting_room_id):
    _, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff"})
    r = get_or_404(DB.tasting_rooms, tasting_room_id)
    return ok(ser_room(r), "object", 200)


def _intervals_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/api/tasting-events", methods=["POST"])
def event_create():
    _, role = authctx()
    require_role(role, {"CounterStaff"})
    body = body_json()
    room_id = body.get("tasting_room_id")
    customer_id = body.get("customer_id")
    if room_id is None:
        raise err("ERR_VALIDATION", "missing required field: tasting_room_id")
    if room_id not in DB.tasting_rooms:
        raise err("ERR_NOT_FOUND", "tasting room not found")
    if customer_id is None:
        raise err("ERR_VALIDATION", "missing required field: customer_id")
    if customer_id not in DB.customers:
        raise err("ERR_NOT_FOUND", "customer not found")
    room = DB.tasting_rooms[room_id]
    customer = DB.customers[customer_id]

    start_at = parse_dt(need_str(body, "start_at"))
    end_at = parse_dt(need_str(body, "end_at"))
    seats = need_int(body, "seats")
    if seats <= 0:
        raise err("ERR_VALIDATION", "seats must be > 0")
    pairing = body.get("pairing_product_ids", []) or []
    if not isinstance(pairing, list):
        raise err("ERR_VALIDATION", "pairing_product_ids must be an array")

    # priority 9: customer ACTIVE
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_NOT_ACTIVE", "hosting customer is not ACTIVE")

    same_room = [e for e in DB.tasting_events.values()
                 if e["tasting_room_id"] == room_id and e["status"] == "SCHEDULED"]

    # priority 12: buffer for non-overlapping neighbours
    buffer_seconds = room["buffer_minutes"] * 60
    for e in same_room:
        es, ee = e["_start_dt"], e["_end_dt"]
        if _intervals_overlap(start_at, end_at, es, ee):
            continue
        if start_at >= ee:
            gap = (start_at - ee).total_seconds()
        else:
            gap = (es - end_at).total_seconds()
        if gap < buffer_seconds:
            raise err("ERR_TASTING_ROOM_CONFLICT", "non-overlapping event within buffer")

    # priority 13: aggregate seats over overlapping events
    seat_sum = seats
    for e in same_room:
        if _intervals_overlap(start_at, end_at, e["_start_dt"], e["_end_dt"]):
            seat_sum += e["seats"]
    if seat_sum > room["seat_capacity"]:
        raise err("ERR_TASTING_SEATS_EXCEEDED", "aggregate seats exceed capacity")

    ev = DB.new_common()
    ev.update({
        "tasting_room_id": room_id, "customer_id": customer_id,
        "start_at": body["start_at"], "end_at": body["end_at"],
        "_start_dt": start_at, "_end_dt": end_at,
        "seats": seats, "pairing_product_ids": pairing, "status": "SCHEDULED",
    })
    DB.tasting_events[ev["id"]] = ev
    return ok(ser_event(ev), "object", 201)


@app.route("/api/tasting-events/<event_id>", methods=["GET"])
def event_get(event_id):
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    e = get_or_404(DB.tasting_events, event_id)
    own_check(role, uid, e["customer_id"])
    return ok(ser_event(e), "object", 200)


@app.route("/api/tasting-events", methods=["GET"])
def event_list():
    uid, role = authctx()
    require_role(role, {"ShopManager", "CounterStaff", "WholesaleCustomer"})
    items = list(DB.tasting_events.values())
    if role == "WholesaleCustomer":
        items = [i for i in items if i["customer_id"] == uid]
    rid = request.args.get("tasting_room_id")
    cid = request.args.get("customer_id")
    if rid:
        items = [i for i in items if i["tasting_room_id"] == rid]
    if cid:
        items = [i for i in items if i["customer_id"] == cid]
    items.sort(key=lambda x: x["_seq"])
    return list_ok(items, ser_event)


@app.route("/api/tasting-events/<event_id>/cancel", methods=["POST"])
def event_cancel(event_id):
    _, role = authctx()
    require_role(role, {"CounterStaff"})
    e = get_or_404(DB.tasting_events, event_id)
    if e["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "event is not SCHEDULED")
    e["status"] = "CANCELLED"
    touch(e)
    return ok(ser_event(e), "object", 200)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
