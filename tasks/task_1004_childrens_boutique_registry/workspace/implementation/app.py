"""Children's Boutique & Baby Registry API — Flask entry point.

In-memory only. Store starts EMPTY on every boot; no seeding.
"""
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

import db
import calc
from http_util import (
    ApiError,
    ok,
    ok_list,
    register_error_handlers,
    require_auth,
    require_owner,
    get_json_body,
    get_user_id,
)

app = Flask(__name__)
register_error_handlers(app)

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
CATEGORY = {"CLOTHING", "GEAR", "TOY", "FEEDING", "NURSERY"}
SIZE_STAGE = {"NEWBORN", "M0_3", "M3_6", "M6_12", "M12_24", "T2", "T3", "T4"}
REGISTRY_KIND = {"BABY_REGISTRY", "WISHLIST"}
SHELF_SEASON = {"SPRING_SUMMER", "FALL_WINTER"}
ITEM_CONDITION = {"LIKE_NEW", "GOOD", "FAIR"}
ITEM_SEASON = {"IN_SEASON", "OFF_SEASON"}
PAYMENT_METHOD = {"STORE_CREDIT", "CARD"}


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------
def verr(msg="Invalid request body"):
    raise ApiError("ERR_VALIDATION", 422, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        verr("Missing or invalid field '%s'" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str) or v == "":
        verr("Invalid field '%s'" % key)
    return v


def req_int(body, key, minimum=0):
    v = body.get(key)
    if key not in body or v is None or isinstance(v, bool) or not isinstance(v, int):
        verr("Missing or invalid integer field '%s'" % key)
    if minimum is not None and v < minimum:
        verr("Field '%s' must be >= %d" % (key, minimum))
    return v


def opt_int(body, key, default, minimum=0):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        verr("Invalid integer field '%s'" % key)
    if minimum is not None and v < minimum:
        verr("Field '%s' must be >= %d" % (key, minimum))
    return v


def req_enum(body, key, choices):
    v = req_str(body, key)
    if v not in choices:
        verr("Field '%s' not a recognized value" % key)
    return v


def opt_enum(body, key, choices, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str) or v not in choices:
        verr("Field '%s' not a recognized value" % key)
    return v


def req_dt(body, key):
    v = req_str(body, key)
    if db.parse_iso(v) is None:
        verr("Field '%s' is not a valid ISO-8601 datetime" % key)
    return v


def must_exist(table, entity_id, error_id):
    e = table.get(entity_id)
    if e is None:
        raise ApiError(error_id, 404, "Referenced resource not found")
    return e


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_int_param(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        verr("Invalid integer query parameter")


def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10 if limit_raw is None else parse_int_param(limit_raw)
    offset = 0 if offset_raw is None else parse_int_param(offset_raw)
    if limit < 1 or limit > 100:
        verr("limit must be between 1 and 100")
    if offset < 0:
        verr("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sorted_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(records, filters):
    """Apply equality filters (skip None), sort, paginate, and build response."""
    filtered = []
    for r in records:
        keep = True
        for key, val in filters.items():
            if val is not None and str(r.get(key)) != str(val):
                keep = False
                break
        if keep:
            filtered.append(r)
    filtered = sorted_by_created(filtered)
    page, limit, offset, total = paginate(filtered)
    return ok_list([db.public(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Domain recompute / cascade helpers
# ---------------------------------------------------------------------------
def recompute_sku_availability(sku):
    sku["availability_status"] = calc.availability_status(
        sku["on_hand_qty"], sku["reserved_qty"]
    )


def recompute_registry_completion(reg):
    items = [ri for ri in db.registry_items.values() if ri["registry_id"] == reg["id"]]
    desired = 0
    fulfilled = 0
    for ri in items:
        sku = db.skus.get(ri["sku_id"])
        base = sku["base_price_cents"] if sku else 0
        desired += ri["desired_qty"] * base
        fulfilled += min(ri["fulfilled_qty"], ri["desired_qty"]) * base
    reg["desired_value_cents"] = desired
    reg["fulfilled_value_cents"] = fulfilled
    pct = calc.completion_pct(fulfilled, desired)
    reg["completion_pct"] = pct

    if reg["kind"] == "BABY_REGISTRY":
        if reg["status"] == "ACTIVE" and pct >= calc.COMPLETION_THRESHOLD:
            reg["status"] = "COMPLETION_UNLOCKED"
            registrant = db.customers.get(reg["registrant_customer_id"])
            if registrant is not None:
                registrant["loyalty_points"] += calc.REGISTRY_COMPLETION_BONUS
                registrant["loyalty_tier"] = calc.loyalty_tier(
                    registrant["lifetime_spend_cents"]
                )
                db.touch(registrant)
            reg["updated_at"] = db.now_iso()
        elif reg["status"] == "COMPLETION_UNLOCKED" and pct < calc.COMPLETION_THRESHOLD:
            reg["status"] = "ACTIVE"
            reg["updated_at"] = db.now_iso()


def promote_waitlist(sku):
    """Head-of-line waitlist drain for a SKU as availability rises."""
    while True:
        waiting = [
            so for so in db.special_orders.values()
            if so["sku_id"] == sku["id"] and so["status"] == "WAITLISTED"
        ]
        if not waiting:
            break
        waiting = sorted_by_created(waiting)
        head = waiting[0]
        available = sku["on_hand_qty"] - sku["reserved_qty"]
        if available >= head["qty"]:
            sku["reserved_qty"] += head["qty"]
            recompute_sku_availability(sku)
            db.touch(sku)
            head["status"] = "ALLOCATED"
            db.touch(head)
        else:
            break


def max_overlap(intervals):
    events = []
    for s, e in intervals:
        events.append((s, 0))
        events.append((e, 1))
    events.sort(key=lambda x: (x[0], x[1]))
    cur = 0
    mx = 0
    for _, typ in events:
        if typ == 0:
            cur += 1
            mx = max(mx, cur)
        else:
            cur -= 1
    return mx


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------
def compute_completion_discount(lines, buyer, registry, created_dt):
    if registry is None:
        return 0
    if buyer["id"] != registry["registrant_customer_id"]:
        return 0
    if registry["kind"] != "BABY_REGISTRY":
        return 0
    items = {}
    for ri in db.registry_items.values():
        if ri["registry_id"] == registry["id"]:
            items.setdefault(ri["sku_id"], ri)
    event_dt = db.parse_iso(registry["event_date"])
    provisional = created_dt < event_dt
    if provisional and registry["status"] != "COMPLETION_UNLOCKED":
        return 0
    total = 0
    for ln in lines:
        ri = items.get(ln["sku_id"])
        if ri is None:
            continue
        needed = max(0, ri["desired_qty"] - ri["fulfilled_qty"])
        discountable = min(ln["qty"], needed)
        if discountable <= 0:
            continue
        sku = db.skus[ln["sku_id"]]
        total += calc.rhu(
            Decimal(discountable) * Decimal(sku["base_price_cents"]) * calc.COMPLETION_DISCOUNT_PCT
        )
    return total


def compute_order_pricing(order, buyer, registry, created_dt):
    lines = order["lines"]
    subtotal = sum(ln["line_total_cents"] for ln in lines)
    loyalty = calc.loyalty_discount(lines, buyer["loyalty_tier"])
    completion = compute_completion_discount(lines, buyer, registry, created_dt)
    gross = loyalty + completion
    cap = calc.rhu(Decimal(subtotal) * calc.MAX_DISCOUNT_PCT)
    applied = min(gross, cap)
    total_before_credit = subtotal - applied
    order["subtotal_cents"] = subtotal
    order["loyalty_discount_cents"] = loyalty
    order["completion_discount_cents"] = completion
    order["applied_discount_cents"] = applied
    order["total_before_credit_cents"] = total_before_credit
    order["store_credit_applied_cents"] = 0
    order["amount_due_cents"] = total_before_credit - 0


# ===========================================================================
# STORE
# ===========================================================================
@app.route("/stores", methods=["POST"])
def create_store():
    require_auth(["PlatformAdmin"])
    body = get_json_body()
    name = req_str(body, "name")
    state_code = req_str(body, "state_code")
    open_minute = opt_int(body, "open_minute", 540)
    close_minute = opt_int(body, "close_minute", 1200)
    pickup_station_count = opt_int(body, "pickup_station_count", 2)
    store = db.new_entity(
        name=name,
        state_code=state_code,
        open_minute=open_minute,
        close_minute=close_minute,
        pickup_station_count=pickup_station_count,
    )
    db.stores[store["id"]] = store
    return ok(db.public(store), 201)


@app.route("/stores/<sid>", methods=["GET"])
def get_store(sid):
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    store = must_exist(db.stores, sid, "ERR_STORE_NOT_FOUND")
    return ok(db.public(store), 200)


# ===========================================================================
# CUSTOMER
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    require_auth(["Anonymous"])
    body = get_json_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    lifetime = opt_int(body, "initial_lifetime_spend_cents", 0)
    credit = opt_int(body, "initial_store_credit_cents", 0)
    points = opt_int(body, "initial_loyalty_points", 0)
    customer = db.new_entity(
        full_name=full_name,
        email=email,
        lifetime_spend_cents=lifetime,
        store_credit_balance_cents=credit,
        loyalty_points=points,
        loyalty_tier=calc.loyalty_tier(lifetime),
    )
    db.customers[customer["id"]] = customer
    return ok(db.public(customer), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    customer = must_exist(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    return ok(db.public(customer), 200)


# ===========================================================================
# SKU
# ===========================================================================
@app.route("/skus", methods=["POST"])
def create_sku():
    require_auth(["StoreStaff", "PlatformAdmin"])
    body = get_json_body()
    store_id = req_str(body, "store_id")
    must_exist(db.stores, store_id, "ERR_STORE_NOT_FOUND")
    sku_code = req_str(body, "sku_code")
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORY)
    size_stage = req_enum(body, "size_stage", SIZE_STAGE)
    base_price_cents = req_int(body, "base_price_cents")
    on_hand = opt_int(body, "initial_on_hand_qty", 0)
    sku = db.new_entity(
        store_id=store_id,
        sku_code=sku_code,
        name=name,
        category=category,
        size_stage=size_stage,
        base_price_cents=base_price_cents,
        on_hand_qty=on_hand,
        reserved_qty=0,
        availability_status=calc.availability_status(on_hand, 0),
    )
    db.skus[sku["id"]] = sku
    return ok(db.public(sku), 201)


@app.route("/skus/<sid>", methods=["GET"])
def get_sku(sid):
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    sku = must_exist(db.skus, sid, "ERR_SKU_NOT_FOUND")
    return ok(db.public(sku), 200)


@app.route("/skus", methods=["GET"])
def list_skus():
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "store_id": request.args.get("store_id"),
        "category": request.args.get("category"),
        "size_stage": request.args.get("size_stage"),
        "availability_status": request.args.get("availability_status"),
    }
    return list_response(list(db.skus.values()), filters)


@app.route("/skus/<sid>/restock", methods=["POST"])
def restock_sku(sid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    sku = must_exist(db.skus, sid, "ERR_SKU_NOT_FOUND")
    body = get_json_body()
    add_qty = req_int(body, "add_qty")
    sku["on_hand_qty"] += add_qty
    recompute_sku_availability(sku)
    db.touch(sku)
    promote_waitlist(sku)
    return ok(db.public(sku), 200)


# ===========================================================================
# REGISTRY
# ===========================================================================
@app.route("/registries", methods=["POST"])
def create_registry():
    require_auth(["Customer"])
    body = get_json_body()
    registrant_customer_id = req_str(body, "registrant_customer_id")
    must_exist(db.customers, registrant_customer_id, "ERR_CUSTOMER_NOT_FOUND")
    title = req_str(body, "title")
    event_date = req_dt(body, "event_date")
    kind = opt_enum(body, "kind", REGISTRY_KIND, "BABY_REGISTRY")
    reg = db.new_entity(
        registrant_customer_id=registrant_customer_id,
        kind=kind,
        title=title,
        event_date=event_date,
        status="DRAFT",
        desired_value_cents=0,
        fulfilled_value_cents=0,
        completion_pct=0.0,
    )
    db.registries[reg["id"]] = reg
    return ok(db.public(reg), 201)


@app.route("/registries/<rid>", methods=["GET"])
def get_registry(rid):
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    reg = must_exist(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
    return ok(db.public(reg), 200)


@app.route("/registries", methods=["GET"])
def list_registries():
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "registrant_customer_id": request.args.get("registrant_customer_id"),
        "kind": request.args.get("kind"),
        "status": request.args.get("status"),
    }
    return list_response(list(db.registries.values()), filters)


@app.route("/registries/<rid>/activate", methods=["POST"])
def activate_registry(rid):
    role = require_auth(["Customer"])
    reg = must_exist(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
    require_owner(role, reg["registrant_customer_id"])
    if reg["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_REGISTRY_STATE", 409, "Registry is not in DRAFT")
    reg["status"] = "ACTIVE"
    recompute_registry_completion(reg)
    db.touch(reg)
    return ok(db.public(reg), 200)


@app.route("/registries/<rid>/archive", methods=["POST"])
def archive_registry(rid):
    role = require_auth(["Customer"])
    reg = must_exist(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
    require_owner(role, reg["registrant_customer_id"])
    if reg["status"] == "ARCHIVED":
        raise ApiError("ERR_REGISTRY_ALREADY_ARCHIVED", 409, "Registry already archived")
    reg["status"] = "ARCHIVED"
    db.touch(reg)
    return ok(db.public(reg), 200)


@app.route("/registries/<rid>/items", methods=["POST"])
def add_registry_item(rid):
    role = require_auth(["Customer"])
    reg = must_exist(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
    require_owner(role, reg["registrant_customer_id"])
    body = get_json_body()
    sku_id = req_str(body, "sku_id")
    desired_qty = req_int(body, "desired_qty")
    must_exist(db.skus, sku_id, "ERR_SKU_NOT_FOUND")
    if reg["status"] == "ARCHIVED":
        raise ApiError("ERR_REGISTRY_ALREADY_ARCHIVED", 409, "Registry already archived")
    item = db.new_entity(
        registry_id=reg["id"],
        sku_id=sku_id,
        desired_qty=desired_qty,
        fulfilled_qty=0,
    )
    db.registry_items[item["id"]] = item
    recompute_registry_completion(reg)
    db.touch(reg)
    return ok(db.public(item), 201)


@app.route("/registry-items/<iid>", methods=["GET"])
def get_registry_item(iid):
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    item = must_exist(db.registry_items, iid, "ERR_REGISTRY_ITEM_NOT_FOUND")
    return ok(db.public(item), 200)


@app.route("/registry-items", methods=["GET"])
def list_registry_items():
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "registry_id": request.args.get("registry_id"),
        "sku_id": request.args.get("sku_id"),
    }
    return list_response(list(db.registry_items.values()), filters)


# ===========================================================================
# REGISTRY GIFT
# ===========================================================================
@app.route("/registries/<rid>/gifts", methods=["POST"])
def create_gift(rid):
    require_auth(["Customer"])
    reg = must_exist(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
    body = get_json_body()
    registry_item_id = req_str(body, "registry_item_id")
    item = db.registry_items.get(registry_item_id)
    if item is None or item["registry_id"] != reg["id"]:
        raise ApiError("ERR_REGISTRY_ITEM_NOT_FOUND", 404, "Registry item not found")
    qty = req_int(body, "qty")
    expected_version = req_int(body, "expected_registry_version")

    if reg["status"] not in ("ACTIVE", "COMPLETION_UNLOCKED"):
        raise ApiError("ERR_REGISTRY_NOT_ACTIVE", 409, "Registry is not active")

    remaining = item["desired_qty"] - item["fulfilled_qty"]
    if qty > remaining:
        raise ApiError("ERR_GIFT_EXCEEDS_REMAINING", 422, "Gift exceeds remaining need")

    if expected_version != reg["version"]:
        raise ApiError("ERR_STALE_REGISTRY_VERSION", 412, "Registry version is stale")

    sku = db.skus[item["sku_id"]]
    amount_cents = qty * sku["base_price_cents"]
    gift = db.new_entity(
        registry_id=reg["id"],
        registry_item_id=item["id"],
        gifter_customer_id=get_user_id(),
        qty=qty,
        amount_cents=amount_cents,
    )
    db.registry_gifts[gift["id"]] = gift

    item["fulfilled_qty"] += qty
    db.touch(item)
    recompute_registry_completion(reg)
    db.touch(reg)
    return ok(db.public(gift), 201)


@app.route("/registry-gifts/<gid>", methods=["GET"])
def get_gift(gid):
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    gift = must_exist(db.registry_gifts, gid, "ERR_REGISTRY_GIFT_NOT_FOUND")
    return ok(db.public(gift), 200)


@app.route("/registry-gifts", methods=["GET"])
def list_gifts():
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "registry_id": request.args.get("registry_id"),
        "registry_item_id": request.args.get("registry_item_id"),
        "gifter_customer_id": request.args.get("gifter_customer_id"),
    }
    return list_response(list(db.registry_gifts.values()), filters)


# ===========================================================================
# ORDER (BOPIS)
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    require_auth(["Customer"])
    body = get_json_body()

    customer_id = req_str(body, "customer_id")
    buyer = must_exist(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    store_id = req_str(body, "store_id")
    store = must_exist(db.stores, store_id, "ERR_STORE_NOT_FOUND")
    registry = None
    if body.get("registry_id") is not None:
        registry_id = req_str(body, "registry_id")
        registry = must_exist(db.registries, registry_id, "ERR_REGISTRY_NOT_FOUND")

    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list):
        verr("lines must be an array")
    if len(raw_lines) == 0:
        raise ApiError("ERR_EMPTY_ORDER", 422, "Order must contain at least one line")

    parsed_lines = []
    for ln in raw_lines:
        if not isinstance(ln, dict):
            verr("each line must be an object")
        sku_id = req_str(ln, "sku_id")
        qty = req_int(ln, "qty")
        parsed_lines.append({"sku_id": sku_id, "qty": qty})

    pickup_start = req_dt(body, "pickup_start")
    pickup_end = req_dt(body, "pickup_end")
    station_no = req_int(body, "station_no")

    # existence of line SKUs
    line_skus = []
    for ln in parsed_lines:
        sku = must_exist(db.skus, ln["sku_id"], "ERR_SKU_NOT_FOUND")
        line_skus.append(sku)

    # referential: every line SKU belongs to the order store
    for sku in line_skus:
        if sku["store_id"] != store_id:
            raise ApiError("ERR_SKU_STORE_MISMATCH", 409, "SKU does not belong to store")

    ps = db.parse_iso(pickup_start)
    pe = db.parse_iso(pickup_end)
    if not (pe > ps):
        raise ApiError("ERR_INVALID_PICKUP_WINDOW", 422, "pickup_end must be after pickup_start")

    start_min = ps.hour * 60 + ps.minute
    end_min = pe.hour * 60 + pe.minute
    if start_min < store["open_minute"] or end_min > store["close_minute"]:
        raise ApiError("ERR_PICKUP_OUTSIDE_HOURS", 422, "Pickup window outside store hours")

    if station_no < 1 or station_no > store["pickup_station_count"]:
        raise ApiError("ERR_INVALID_STATION", 422, "Invalid pickup station")

    buf = timedelta(minutes=calc.PICKUP_BUFFER_MIN)
    for o in db.orders.values():
        if o["store_id"] != store_id or o["station_no"] != station_no:
            continue
        if o["fulfillment_status"] == "CANCELLED":
            continue
        os_ = db.parse_iso(o["pickup_start"])
        oe = db.parse_iso(o["pickup_end"])
        if (ps - buf) < (oe + buf) and (os_ - buf) < (pe + buf):
            raise ApiError("ERR_PICKUP_SLOT_CONFLICT", 409, "Pickup slot conflict")

    for sku, ln in zip(line_skus, parsed_lines):
        available = sku["on_hand_qty"] - sku["reserved_qty"]
        if available < ln["qty"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "Insufficient stock")

    # build order lines with augmented fields
    order_lines = []
    for sku, ln in zip(line_skus, parsed_lines):
        unit = sku["base_price_cents"]
        order_lines.append({
            "sku_id": sku["id"],
            "qty": ln["qty"],
            "unit_price_cents": unit,
            "line_total_cents": unit * ln["qty"],
            "fulfilled_qty": 0,
        })

    order = db.new_entity(
        customer_id=customer_id,
        store_id=store_id,
        registry_id=(registry["id"] if registry else None),
        lines=order_lines,
        pickup_start=pickup_start,
        pickup_end=pickup_end,
        station_no=station_no,
        payment_status="UNPAID",
        fulfillment_status="RESERVED",
    )

    # reserve stock
    for sku, ln in zip(line_skus, parsed_lines):
        sku["reserved_qty"] += ln["qty"]
        recompute_sku_availability(sku)
        db.touch(sku)

    compute_order_pricing(order, buyer, registry, db.now())
    db.orders[order["id"]] = order
    return ok(db.public(order), 201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    order = must_exist(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    return ok(db.public(order), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "customer_id": request.args.get("customer_id"),
        "store_id": request.args.get("store_id"),
        "registry_id": request.args.get("registry_id"),
    }
    return list_response(list(db.orders.values()), filters)


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    role = require_auth(["Customer"])
    order = must_exist(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    require_owner(role, order["customer_id"])
    body = get_json_body()
    payment_method = req_enum(body, "payment_method", PAYMENT_METHOD)
    if order["payment_status"] != "UNPAID":
        raise ApiError("ERR_ORDER_ALREADY_PAID", 409, "Order is not UNPAID")
    buyer = db.customers[order["customer_id"]]
    total = order["total_before_credit_cents"]
    if payment_method == "STORE_CREDIT":
        if buyer["store_credit_balance_cents"] < total:
            raise ApiError("ERR_INSUFFICIENT_STORE_CREDIT", 402, "Insufficient store credit")
        order["store_credit_applied_cents"] = total
        buyer["store_credit_balance_cents"] -= total
    else:  # CARD
        order["store_credit_applied_cents"] = 0
    order["amount_due_cents"] = total - order["store_credit_applied_cents"]
    order["payment_status"] = "PAID"

    buyer["lifetime_spend_cents"] += total
    buyer["loyalty_points"] += total // 100
    buyer["loyalty_tier"] = calc.loyalty_tier(buyer["lifetime_spend_cents"])
    db.touch(buyer)
    db.touch(order)
    return ok(db.public(order), 200)


@app.route("/orders/<oid>/mark-ready", methods=["POST"])
def mark_ready_order(oid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    order = must_exist(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    if order["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_ORDER_NOT_RESERVED", 409, "Order is not RESERVED")
    order["fulfillment_status"] = "READY"
    db.touch(order)
    return ok(db.public(order), 200)


@app.route("/orders/<oid>/complete-pickup", methods=["POST"])
def complete_pickup_order(oid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    order = must_exist(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    if order["fulfillment_status"] != "READY" or order["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_READY", 409, "Order is not READY and PAID")
    order["fulfillment_status"] = "PICKED_UP"
    for ln in order["lines"]:
        sku = db.skus.get(ln["sku_id"])
        if sku is not None:
            sku["on_hand_qty"] -= ln["qty"]
            sku["reserved_qty"] -= ln["qty"]
            recompute_sku_availability(sku)
            db.touch(sku)
    db.touch(order)
    return ok(db.public(order), 200)


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    role = require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    order = must_exist(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    require_owner(role, order["customer_id"])
    if order["fulfillment_status"] not in ("RESERVED", "READY"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE", 409, "Order cannot be cancelled")
    order["fulfillment_status"] = "CANCELLED"
    for ln in order["lines"]:
        sku = db.skus.get(ln["sku_id"])
        if sku is not None:
            sku["reserved_qty"] -= ln["qty"]
            recompute_sku_availability(sku)
            db.touch(sku)
            promote_waitlist(sku)
    if order["payment_status"] == "PAID":
        buyer = db.customers.get(order["customer_id"])
        if buyer is not None:
            buyer["store_credit_balance_cents"] += order["store_credit_applied_cents"]
            total = order["total_before_credit_cents"]
            buyer["lifetime_spend_cents"] -= total
            buyer["loyalty_points"] -= total // 100
            buyer["loyalty_tier"] = calc.loyalty_tier(buyer["lifetime_spend_cents"])
            db.touch(buyer)
        order["payment_status"] = "REFUNDED"
    db.touch(order)
    return ok(db.public(order), 200)


# ===========================================================================
# CONSIGNMENT SHELF
# ===========================================================================
@app.route("/stores/<sid>/consignment-shelves", methods=["POST"])
def create_shelf(sid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    store = must_exist(db.stores, sid, "ERR_STORE_NOT_FOUND")
    body = get_json_body()
    shelf_code = req_str(body, "shelf_code")
    capacity = req_int(body, "capacity")
    season = req_enum(body, "season", SHELF_SEASON)
    shelf = db.new_entity(
        store_id=store["id"],
        shelf_code=shelf_code,
        capacity=capacity,
        season=season,
        status="OPEN",
    )
    db.consignment_shelves[shelf["id"]] = shelf
    return ok(db.public(shelf), 201)


@app.route("/consignment-shelves/<shid>", methods=["GET"])
def get_shelf(shid):
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    shelf = must_exist(db.consignment_shelves, shid, "ERR_SHELF_NOT_FOUND")
    return ok(db.public(shelf), 200)


@app.route("/consignment-shelves", methods=["GET"])
def list_shelves():
    require_auth(["Anonymous", "Customer", "StoreStaff", "PlatformAdmin"])
    filters = {"store_id": request.args.get("store_id")}
    return list_response(list(db.consignment_shelves.values()), filters)


@app.route("/consignment-shelves/<shid>/close", methods=["POST"])
def close_shelf(shid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    shelf = must_exist(db.consignment_shelves, shid, "ERR_SHELF_NOT_FOUND")
    if shelf["status"] != "OPEN":
        raise ApiError("ERR_SHELF_CLOSED", 409, "Shelf is not OPEN")
    shelf["status"] = "CLOSED"
    db.touch(shelf)
    return ok(db.public(shelf), 200)


# ===========================================================================
# CONSIGNMENT ITEM
# ===========================================================================
@app.route("/consignment-items", methods=["POST"])
def create_consignment_item():
    require_auth(["Customer"])
    body = get_json_body()
    consignor_customer_id = req_str(body, "consignor_customer_id")
    must_exist(db.customers, consignor_customer_id, "ERR_CUSTOMER_NOT_FOUND")
    store_id = req_str(body, "store_id")
    must_exist(db.stores, store_id, "ERR_STORE_NOT_FOUND")
    title = req_str(body, "title")
    condition = req_enum(body, "condition", ITEM_CONDITION)
    season = req_enum(body, "season", ITEM_SEASON)
    list_price_cents = req_int(body, "list_price_cents")
    item = db.new_entity(
        consignor_customer_id=consignor_customer_id,
        store_id=store_id,
        shelf_id=None,
        title=title,
        condition=condition,
        season=season,
        list_price_cents=list_price_cents,
        display_start=None,
        display_end=None,
        payout_cents=0,
        status="RECEIVED",
    )
    db.consignment_items[item["id"]] = item
    return ok(db.public(item), 201)


@app.route("/consignment-items/<cid>", methods=["GET"])
def get_consignment_item(cid):
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    item = must_exist(db.consignment_items, cid, "ERR_CONSIGNMENT_ITEM_NOT_FOUND")
    return ok(db.public(item), 200)


@app.route("/consignment-items", methods=["GET"])
def list_consignment_items():
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "consignor_customer_id": request.args.get("consignor_customer_id"),
        "store_id": request.args.get("store_id"),
        "shelf_id": request.args.get("shelf_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(db.consignment_items.values()), filters)


@app.route("/consignment-items/<cid>/display", methods=["POST"])
def display_consignment_item(cid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    item = must_exist(db.consignment_items, cid, "ERR_CONSIGNMENT_ITEM_NOT_FOUND")
    body = get_json_body()
    shelf_id = req_str(body, "shelf_id")
    shelf = must_exist(db.consignment_shelves, shelf_id, "ERR_SHELF_NOT_FOUND")
    display_start = req_dt(body, "display_start")
    display_end = req_dt(body, "display_end")
    if item["status"] != "RECEIVED":
        raise ApiError("ERR_CONSIGNMENT_NOT_RECEIVED", 409, "Item is not RECEIVED")
    if shelf["status"] != "OPEN":
        raise ApiError("ERR_SHELF_CLOSED", 409, "Shelf is closed")

    new_start = db.parse_iso(display_start)
    new_end = db.parse_iso(display_end)
    intervals = [(new_start, new_end)]
    for other in db.consignment_items.values():
        if other["id"] == item["id"]:
            continue
        if other["status"] == "ON_DISPLAY" and other["shelf_id"] == shelf["id"]:
            intervals.append((db.parse_iso(other["display_start"]), db.parse_iso(other["display_end"])))
    if max_overlap(intervals) > shelf["capacity"]:
        raise ApiError("ERR_SHELF_CAPACITY_EXCEEDED", 409, "Shelf capacity exceeded")

    item["shelf_id"] = shelf["id"]
    item["display_start"] = display_start
    item["display_end"] = display_end
    item["status"] = "ON_DISPLAY"
    db.touch(item)
    return ok(db.public(item), 200)


@app.route("/consignment-items/<cid>/sell", methods=["POST"])
def sell_consignment_item(cid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    item = must_exist(db.consignment_items, cid, "ERR_CONSIGNMENT_ITEM_NOT_FOUND")
    body = get_json_body()
    sale_price_cents = req_int(body, "sale_price_cents")
    if item["status"] != "ON_DISPLAY":
        raise ApiError("ERR_CONSIGNMENT_NOT_ON_DISPLAY", 409, "Item is not ON_DISPLAY")
    payout = calc.consignor_payout(sale_price_cents, item["season"], item["condition"])
    item["payout_cents"] = payout
    item["status"] = "SOLD"
    consignor = db.customers.get(item["consignor_customer_id"])
    if consignor is not None:
        consignor["store_credit_balance_cents"] += payout
        db.touch(consignor)
    db.touch(item)
    return ok(db.public(item), 200)


# ===========================================================================
# TRADE-IN
# ===========================================================================
@app.route("/trade-ins", methods=["POST"])
def create_trade_in():
    require_auth(["Customer"])
    body = get_json_body()
    customer_id = req_str(body, "customer_id")
    must_exist(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    sku_id = req_str(body, "sku_id")
    sku = must_exist(db.skus, sku_id, "ERR_SKU_NOT_FOUND")
    submitted_condition = req_enum(body, "submitted_condition", ITEM_CONDITION)
    quoted = calc.trade_in_percent_of_retail(sku["base_price_cents"], submitted_condition)
    trade_in = db.new_entity(
        customer_id=customer_id,
        sku_id=sku_id,
        submitted_condition=submitted_condition,
        inspected_condition=None,
        quoted_value_cents=quoted,
        final_value_cents=0,
        status="SUBMITTED",
    )
    db.trade_ins[trade_in["id"]] = trade_in
    return ok(db.public(trade_in), 201)


@app.route("/trade-ins/<tid>", methods=["GET"])
def get_trade_in(tid):
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    trade_in = must_exist(db.trade_ins, tid, "ERR_TRADE_IN_NOT_FOUND")
    return ok(db.public(trade_in), 200)


@app.route("/trade-ins", methods=["GET"])
def list_trade_ins():
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "customer_id": request.args.get("customer_id"),
        "sku_id": request.args.get("sku_id"),
    }
    return list_response(list(db.trade_ins.values()), filters)


@app.route("/trade-ins/<tid>/accept", methods=["POST"])
def accept_trade_in(tid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    trade_in = must_exist(db.trade_ins, tid, "ERR_TRADE_IN_NOT_FOUND")
    body = get_json_body()
    inspected_condition = opt_enum(body, "inspected_condition", ITEM_CONDITION, None)
    if trade_in["status"] != "SUBMITTED":
        raise ApiError("ERR_TRADE_IN_NOT_SUBMITTED", 409, "Trade-in is not SUBMITTED")
    if inspected_condition is None:
        inspected_condition = trade_in["submitted_condition"]
    sku = db.skus.get(trade_in["sku_id"])
    base = sku["base_price_cents"] if sku else 0
    final_value = calc.trade_in_final(base, inspected_condition)
    trade_in["inspected_condition"] = inspected_condition
    trade_in["final_value_cents"] = final_value
    trade_in["status"] = "ACCEPTED"
    customer = db.customers.get(trade_in["customer_id"])
    if customer is not None:
        customer["store_credit_balance_cents"] += final_value
        db.touch(customer)
    db.touch(trade_in)
    return ok(db.public(trade_in), 200)


@app.route("/trade-ins/<tid>/reject", methods=["POST"])
def reject_trade_in(tid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    trade_in = must_exist(db.trade_ins, tid, "ERR_TRADE_IN_NOT_FOUND")
    if trade_in["status"] != "SUBMITTED":
        raise ApiError("ERR_TRADE_IN_NOT_SUBMITTED", 409, "Trade-in is not SUBMITTED")
    trade_in["status"] = "REJECTED"
    db.touch(trade_in)
    return ok(db.public(trade_in), 200)


# ===========================================================================
# SPECIAL ORDER
# ===========================================================================
@app.route("/special-orders", methods=["POST"])
def create_special_order():
    require_auth(["Customer"])
    body = get_json_body()
    customer_id = req_str(body, "customer_id")
    must_exist(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    sku_id = req_str(body, "sku_id")
    sku = must_exist(db.skus, sku_id, "ERR_SKU_NOT_FOUND")
    store_id = req_str(body, "store_id")
    must_exist(db.stores, store_id, "ERR_STORE_NOT_FOUND")
    qty = opt_int(body, "qty", 1)

    available = sku["on_hand_qty"] - sku["reserved_qty"]
    if available >= qty:
        status = "ALLOCATED"
        sku["reserved_qty"] += qty
        recompute_sku_availability(sku)
        db.touch(sku)
    else:
        status = "WAITLISTED"

    so = db.new_entity(
        customer_id=customer_id,
        sku_id=sku_id,
        store_id=store_id,
        qty=qty,
        status=status,
    )
    db.special_orders[so["id"]] = so
    return ok(db.public(so), 201)


@app.route("/special-orders/<soid>", methods=["GET"])
def get_special_order(soid):
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    so = must_exist(db.special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    return ok(db.public(so), 200)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    filters = {
        "customer_id": request.args.get("customer_id"),
        "sku_id": request.args.get("sku_id"),
        "store_id": request.args.get("store_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(db.special_orders.values()), filters)


@app.route("/special-orders/<soid>/fulfill", methods=["POST"])
def fulfill_special_order(soid):
    require_auth(["StoreStaff", "PlatformAdmin"])
    so = must_exist(db.special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if so["status"] != "ALLOCATED":
        raise ApiError("ERR_SPECIAL_ORDER_NOT_ALLOCATED", 409, "Special order is not ALLOCATED")
    sku = db.skus.get(so["sku_id"])
    if sku is not None:
        sku["on_hand_qty"] -= so["qty"]
        sku["reserved_qty"] -= so["qty"]
        recompute_sku_availability(sku)
        db.touch(sku)
    so["status"] = "FULFILLED"
    db.touch(so)
    return ok(db.public(so), 200)


@app.route("/special-orders/<soid>/cancel", methods=["POST"])
def cancel_special_order(soid):
    role = require_auth(["Customer", "StoreStaff", "PlatformAdmin"])
    so = must_exist(db.special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    require_owner(role, so["customer_id"])
    if so["status"] not in ("REQUESTED", "WAITLISTED", "ALLOCATED"):
        raise ApiError("ERR_SPECIAL_ORDER_NOT_CANCELLABLE", 409, "Special order cannot be cancelled")
    was_allocated = so["status"] == "ALLOCATED"
    so["status"] = "CANCELLED"
    db.touch(so)
    if was_allocated:
        sku = db.skus.get(so["sku_id"])
        if sku is not None:
            sku["reserved_qty"] -= so["qty"]
            recompute_sku_availability(sku)
            db.touch(sku)
            promote_waitlist(sku)
    return ok(db.public(so), 200)


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["PlatformAdmin"])
    body = get_json_body()
    to_iso8601 = req_str(body, "to_iso8601")
    dt = db.parse_iso(to_iso8601)
    if dt is None:
        verr("to_iso8601 is not a valid ISO-8601 datetime")
    db.set_clock(dt)
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
