"""Farm-Box Aggregator REST API (Python + Flask, in-memory).

Validation precedence, state machines, calculations and error ids all trace to
PRD.md (authoritative) and SCAFFOLD.yaml. The store is process-local dicts; a
fresh process starts empty and nothing is seeded.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

import db
from db import touch, new_entity
from errors import ApiError
from response import success, error_body, serialize

app = Flask(__name__)

# =========================================================================
# Numeric helpers (PRD 2.5 — integer cents, round half up)
# =========================================================================


def cents_round(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =========================================================================
# Auth (PRD 2.1, precedence steps 1-2)
# =========================================================================


def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in db.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return uid, role


# =========================================================================
# Existence helpers (precedence steps 3-4)
# =========================================================================


def get_or_404(table, ident):
    ent = table.get(ident)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND")
    return ent


def body_fk_or_404(table, ident):
    if ident not in table:
        raise ApiError("ERR_NOT_FOUND")
    return table[ident]


# =========================================================================
# Body / field validation helpers (precedence step 6 -> ERR_INVALID_REQUEST)
# =========================================================================


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def bad_request(msg="malformed request body"):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        bad_request("missing or invalid field: %s" % key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        bad_request("invalid enum for %s" % key)
    return v


def req_int(body, key, minimum=None):
    v = body.get(key)
    if not _is_int(v):
        bad_request("field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        bad_request("field %s below minimum" % key)
    return v


def opt_int(body, key, minimum=None):
    v = body.get(key)
    if v is None:
        return None
    if not _is_int(v):
        bad_request("field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        bad_request("field %s below minimum" % key)
    return v


def parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# =========================================================================
# Pagination (PRD 2.3, precedence step 6 -> ERR_INVALID_PAGINATION)
# =========================================================================


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def list_response(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: e["_seq"])   # created_at ASC (PRD 2.3)
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success([serialize(i) for i in page], "array", 200, pagination)


def body():
    return request.get_json(silent=True) or {}


# =========================================================================
# Offering availability accounting (PRD 2.6 / calc offering_availability)
# =========================================================================


def recompute_remaining(off):
    off["remaining_qty"] = off["offered_qty"] - off["reserved_qty"] - off["committed_qty"]


def offering_reserve(off, qty):
    off["reserved_qty"] += qty
    recompute_remaining(off)
    touch(off)


def offering_release(off, qty):
    off["reserved_qty"] -= qty
    recompute_remaining(off)
    touch(off)


def offering_pack_same(off, requested_qty, fulfilled_qty):
    off["reserved_qty"] -= requested_qty
    off["committed_qty"] += fulfilled_qty
    recompute_remaining(off)
    touch(off)


def offering_commit(off, qty):
    off["committed_qty"] += qty
    recompute_remaining(off)
    touch(off)


# =========================================================================
# Pricing (PRD 3.5 / 3.7 / calc line_pricing)
# =========================================================================


def eff_prices(offering, product):
    eff_unit = offering["unit_price_cents"]
    if eff_unit is None:
        eff_unit = product["unit_price_cents"]
    eff_kg = offering["price_per_kg_cents"]
    if eff_kg is None:
        eff_kg = product["price_per_kg_cents"]
    return eff_unit, eff_kg


def estimated_line_price(product, offering, requested_qty):
    eff_unit, eff_kg = eff_prices(offering, product)
    if product["pricing_mode"] == "FIXED":
        return requested_qty * eff_unit
    val = Decimal(requested_qty) * Decimal(str(product["estimated_weight_kg"])) * Decimal(eff_kg)
    return cents_round(val)


def final_line_price(product, offering, fulfilled_qty, actual_weight_kg):
    eff_unit, eff_kg = eff_prices(offering, product)
    if product["pricing_mode"] == "FIXED":
        return fulfilled_qty * eff_unit
    val = Decimal(str(actual_weight_kg)) * Decimal(eff_kg)
    return cents_round(val)


# =========================================================================
# Order line helpers
# =========================================================================


def lines_of(order_id):
    return sorted(
        [l for l in db.order_lines.values() if l["order_id"] == order_id],
        key=lambda l: l["_seq"],
    )


def product_of_offering(offering):
    return db.products[offering["product_id"]]


def farm_of_offering(offering):
    return product_of_offering(offering)["farm_id"]


# =========================================================================
# Refund waterfall (PRD 3.8 / calc refund_allocation)
# =========================================================================


def partial_refund(order, line, credit, customer, mark_partial):
    """Allocate `credit` cents across SNAP -> Double-Up -> wallet (pinned)."""
    if credit <= 0:
        return
    if line["snap_eligible"]:
        remaining_snap = order["snap_applied_cents"] - order["refunded_snap_cents"]
        remaining_du = order["doubleup_match_cents"] - order["_du_reversed"]
        to_snap = min(credit, max(0, remaining_snap))
        to_du = min(credit - to_snap, max(0, remaining_du))
        to_wallet = credit - to_snap - to_du
    else:
        to_snap = 0
        to_du = 0
        to_wallet = credit
    customer["snap_balance_cents"] += to_snap
    customer["doubleup_used_cents"] -= to_du
    customer["wallet_credit_cents"] += to_wallet
    order["refunded_snap_cents"] += to_snap
    order["refunded_wallet_cents"] += to_wallet
    order["_du_reversed"] += to_du
    if mark_partial:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    touch(customer)


# =========================================================================
# Error handlers
# =========================================================================


@app.errorhandler(ApiError)
def handle_api_error(e):
    b = error_body(e.error_id, e.message)
    return b, e.http_status


@app.errorhandler(404)
def handle_404(e):
    b = error_body("ERR_NOT_FOUND", "resource not found")
    return b, 404


@app.errorhandler(405)
def handle_405(e):
    b = error_body("ERR_NOT_FOUND", "method not allowed")
    return b, 404


# =========================================================================
# FARM
# =========================================================================


@app.post("/farms")
def create_farm():
    authenticate({"PlatformAdmin"})
    b = body()
    name = req_str(b, "name")
    region_code = req_str(b, "region_code")
    commission_pct = b.get("commission_pct")
    if not _is_num(commission_pct) or commission_pct < 0 or commission_pct > 1:
        bad_request("commission_pct must be a number in [0,1]")
    snap_authorized = b.get("snap_authorized", False)
    if not isinstance(snap_authorized, bool):
        bad_request("snap_authorized must be boolean")
    farm = new_entity(
        "Farm", name=name, region_code=region_code, commission_pct=commission_pct,
        snap_authorized=snap_authorized, payout_balance_cents=0, settled_cycle_count=0,
    )
    db.farms[farm["id"]] = farm
    return success(serialize(farm), "object", 201)


@app.get("/farms/<fid>")
def get_farm(fid):
    authenticate({"PlatformAdmin", "Farm", "Customer"})
    farm = get_or_404(db.farms, fid)
    return success(serialize(farm), "object", 200)


@app.get("/farms/<fid>/products")
def list_farm_products(fid):
    authenticate({"PlatformAdmin", "Farm", "Customer"})
    get_or_404(db.farms, fid)
    items = [p for p in db.products.values() if p["farm_id"] == fid]
    return list_response(items)


# =========================================================================
# PRODUCT
# =========================================================================


@app.post("/farms/<fid>/products")
def create_product(fid):
    uid, role = authenticate({"PlatformAdmin", "Farm"})
    farm = get_or_404(db.farms, fid)
    # ownership (step 5): a Farm may only write its own catalog
    if role == "Farm" and uid != fid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    b = body()
    name = req_str(b, "name")
    category = req_enum(b, "category", {"PRODUCE", "DAIRY", "MEAT", "PANTRY", "OTHER"})
    pricing_mode = req_enum(b, "pricing_mode", {"FIXED", "WEIGHT"})
    unit_price_cents = opt_int(b, "unit_price_cents", 0)
    price_per_kg_cents = opt_int(b, "price_per_kg_cents", 0)
    estimated_weight_kg = b.get("estimated_weight_kg")
    if estimated_weight_kg is not None and (not _is_num(estimated_weight_kg) or estimated_weight_kg <= 0):
        bad_request("estimated_weight_kg must be a positive number")
    snap_eligible = b.get("snap_eligible", False)
    if not isinstance(snap_eligible, bool):
        bad_request("snap_eligible must be boolean")
    if pricing_mode == "FIXED":
        if unit_price_cents is None:
            bad_request("FIXED product requires unit_price_cents")
        price_per_kg_cents = None
        estimated_weight_kg = None
    else:  # WEIGHT
        if price_per_kg_cents is None or estimated_weight_kg is None:
            bad_request("WEIGHT product requires price_per_kg_cents and estimated_weight_kg")
        unit_price_cents = None
    # SNAP authorization (step 11)
    if snap_eligible and not farm["snap_authorized"]:
        raise ApiError("ERR_FARM_NOT_SNAP_AUTHORIZED")
    product = new_entity(
        "Product", farm_id=fid, name=name, category=category, pricing_mode=pricing_mode,
        unit_price_cents=unit_price_cents, price_per_kg_cents=price_per_kg_cents,
        estimated_weight_kg=estimated_weight_kg, snap_eligible=snap_eligible,
    )
    db.products[product["id"]] = product
    return success(serialize(product), "object", 201)


# =========================================================================
# MARKET CYCLE
# =========================================================================


@app.post("/market-cycles")
def create_cycle():
    authenticate({"PlatformAdmin"})
    b = body()
    cycle_code = req_str(b, "cycle_code")
    region_code = req_str(b, "region_code")
    open_s = b.get("order_open_at")
    cutoff_s = b.get("order_cutoff_at")
    fulfill_s = b.get("fulfillment_date")
    d_open = parse_dt(open_s)
    d_cutoff = parse_dt(cutoff_s)
    d_fulfill = parse_dt(fulfill_s)
    if d_open is None or d_cutoff is None or d_fulfill is None:
        bad_request("order_open_at/order_cutoff_at/fulfillment_date required (ISO 8601)")
    if not (d_cutoff > d_open and d_fulfill > d_cutoff):
        bad_request("instants must strictly increase")
    # cycle window conflict (step 12)
    for c in db.market_cycles.values():
        if c["region_code"] != region_code:
            continue
        a_open = parse_dt(c["order_open_at"])
        a_fulfill = parse_dt(c["fulfillment_date"])
        gap = max(d_open - a_fulfill, a_open - d_fulfill)
        if gap < db.CYCLE_BUFFER:
            raise ApiError("ERR_CYCLE_WINDOW_CONFLICT")
    cycle = new_entity(
        "MarketCycle", cycle_code=cycle_code, region_code=region_code,
        order_open_at=open_s, order_cutoff_at=cutoff_s, fulfillment_date=fulfill_s,
        status="SCHEDULED",
    )
    db.market_cycles[cycle["id"]] = cycle
    return success(serialize(cycle), "object", 201)


@app.get("/market-cycles/<cid>")
def get_cycle(cid):
    authenticate({"PlatformAdmin", "Farm", "Customer"})
    cycle = get_or_404(db.market_cycles, cid)
    return success(serialize(cycle), "object", 200)


@app.post("/market-cycles/<cid>/open")
def open_cycle(cid):
    authenticate({"PlatformAdmin"})
    cycle = get_or_404(db.market_cycles, cid)
    if cycle["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    cycle["status"] = "OPEN"
    touch(cycle)
    # generate subscription box orders (PRD 3.2 / 3.4)
    subs = [s for s in db.subscriptions.values() if s["status"] == "ACTIVE"]
    subs.sort(key=lambda s: s["_seq"])
    for sub in subs:
        hub = db.pickup_hubs.get(sub["pickup_hub_id"])
        if hub is None or hub["region_code"] != cycle["region_code"]:
            continue
        build_subscription_box(sub, cycle)
    return success(serialize(cycle), "object", 200)


def build_subscription_box(sub, cycle):
    order = new_entity(
        "Order", customer_id=sub["customer_id"], market_cycle_id=cycle["id"],
        pickup_hub_id=sub["pickup_hub_id"], subscription_id=sub["id"],
        fulfillment_type="PICKUP", delivery_slot_start=None, delivery_slot_end=None,
        subtotal_cents=0, eligible_subtotal_cents=0, snap_applied_cents=0,
        doubleup_match_cents=0, customer_owed_cents=0, final_total_cents=None,
        refunded_snap_cents=0, refunded_wallet_cents=0, order_status="CART",
        payment_status="UNPAID", _du_reversed=0,
    )
    db.orders[order["id"]] = order
    target = min(db.BOX_TARGET_CENTS[sub["box_size"]], sub["price_cap_cents"])
    # PRODUCE offerings in this cycle, ascending created_at (sole ordering key)
    candidates = [
        o for o in db.offerings.values()
        if o["market_cycle_id"] == cycle["id"]
        and product_of_offering(o)["category"] == "PRODUCE"
    ]
    candidates.sort(key=lambda o: o["_seq"])
    running = 0
    for off in candidates:
        product = product_of_offering(off)
        unit_est = estimated_line_price(product, off, 1)
        if running + unit_est > target:
            break
        add_order_line(order, off, product, 1)
        running += unit_est


@app.post("/market-cycles/<cid>/cutoff")
def cutoff_cycle(cid):
    authenticate({"PlatformAdmin"})
    cycle = get_or_404(db.market_cycles, cid)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    cycle["status"] = "CUTOFF"
    touch(cycle)
    # PLACED orders -> ALLOCATED; their REQUESTED lines -> ALLOCATED
    for order in db.orders.values():
        if order["market_cycle_id"] != cid or order["order_status"] != "PLACED":
            continue
        order["order_status"] = "ALLOCATED"
        touch(order)
        for line in lines_of(order["id"]):
            if line["line_status"] == "REQUESTED":
                line["allocated_qty"] = line["requested_qty"]
                line["line_status"] = "ALLOCATED"
                touch(line)
    return success(serialize(cycle), "object", 200)


@app.post("/market-cycles/<cid>/settle")
def settle_cycle(cid):
    authenticate({"PlatformAdmin"})
    cycle = get_or_404(db.market_cycles, cid)
    if cycle["status"] != "CUTOFF":
        raise ApiError("ERR_INVALID_STATE")
    for order in db.orders.values():
        if order["market_cycle_id"] != cid:
            continue
        if order["order_status"] not in ("FULFILLED", "CANCELLED"):
            raise ApiError("ERR_CYCLE_HAS_OPEN_ORDERS")
    cycle["status"] = "SETTLED"
    touch(cycle)
    return success(serialize(cycle), "object", 200)


# =========================================================================
# OFFERING
# =========================================================================


@app.post("/market-cycles/<cid>/offerings")
def create_offering(cid):
    uid, role = authenticate({"PlatformAdmin", "Farm"})
    cycle = get_or_404(db.market_cycles, cid)
    b = body()
    product_id = b.get("product_id")
    if not isinstance(product_id, str):
        bad_request("product_id required")
    product = body_fk_or_404(db.products, product_id)
    offered_qty = req_int(b, "offered_qty", 1)
    unit_price_cents = opt_int(b, "unit_price_cents", 0)
    price_per_kg_cents = opt_int(b, "price_per_kg_cents", 0)
    farm = db.farms[product["farm_id"]]
    # business-referential (step 10): farm actor may only offer its own product
    if role == "Farm" and product["farm_id"] != uid:
        raise ApiError("ERR_PRODUCT_FARM_MISMATCH")
    # SNAP authorization (step 11)
    if product["snap_eligible"] and not farm["snap_authorized"]:
        raise ApiError("ERR_FARM_NOT_SNAP_AUTHORIZED")
    offering = new_entity(
        "Offering", product_id=product_id, market_cycle_id=cid, offered_qty=offered_qty,
        unit_price_cents=unit_price_cents, price_per_kg_cents=price_per_kg_cents,
        reserved_qty=0, committed_qty=0, remaining_qty=offered_qty,
    )
    db.offerings[offering["id"]] = offering
    return success(serialize(offering), "object", 201)


@app.get("/offerings/<oid>")
def get_offering(oid):
    authenticate({"PlatformAdmin", "Farm", "Customer"})
    off = get_or_404(db.offerings, oid)
    return success(serialize(off), "object", 200)


@app.get("/offerings")
def list_offerings():
    authenticate({"PlatformAdmin", "Farm", "Customer"})
    product_id = request.args.get("product_id")
    market_cycle_id = request.args.get("market_cycle_id")
    farm_id = request.args.get("farm_id")
    items = []
    for o in db.offerings.values():
        if product_id is not None and o["product_id"] != product_id:
            continue
        if market_cycle_id is not None and o["market_cycle_id"] != market_cycle_id:
            continue
        if farm_id is not None and farm_of_offering(o) != farm_id:
            continue
        items.append(o)
    return list_response(items)


# =========================================================================
# PICKUP HUB
# =========================================================================


@app.post("/pickup-hubs")
def create_hub():
    authenticate({"PlatformAdmin"})
    b = body()
    name = req_str(b, "name")
    hub_type = req_enum(b, "hub_type", {"PICKUP", "DELIVERY"})
    slot_capacity = req_int(b, "slot_capacity", 1)
    region_code = req_str(b, "region_code")
    hub = new_entity(
        "PickupHub", name=name, hub_type=hub_type, slot_capacity=slot_capacity,
        region_code=region_code,
    )
    db.pickup_hubs[hub["id"]] = hub
    return success(serialize(hub), "object", 201)


@app.get("/pickup-hubs/<hid>")
def get_hub(hid):
    authenticate({"PlatformAdmin", "Farm", "Customer"})
    hub = get_or_404(db.pickup_hubs, hid)
    return success(serialize(hub), "object", 200)


# =========================================================================
# CUSTOMER
# =========================================================================


@app.post("/customers")
def create_customer():
    authenticate({"PlatformAdmin"})
    b = body()
    name = req_str(b, "name")
    snap_balance_cents = b.get("snap_balance_cents", 0)
    if not _is_int(snap_balance_cents) or snap_balance_cents < 0:
        bad_request("snap_balance_cents must be a non-negative integer")
    cust = new_entity(
        "Customer", name=name, snap_balance_cents=snap_balance_cents,
        wallet_credit_cents=0, doubleup_used_cents=0,
    )
    db.customers[cust["id"]] = cust
    return success(serialize(cust), "object", 201)


@app.get("/customers/<cid>")
def get_customer(cid):
    uid, role = authenticate({"PlatformAdmin", "Customer"})
    cust = get_or_404(db.customers, cid)
    # own record readable by that customer only (PRD 3.4)
    if role == "Customer" and uid != cid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return success(serialize(cust), "object", 200)


# =========================================================================
# SUBSCRIPTION
# =========================================================================


@app.post("/customers/<cid>/subscriptions")
def create_subscription(cid):
    uid, role = authenticate({"PlatformAdmin", "Customer"})
    get_or_404(db.customers, cid)
    b = body()
    pickup_hub_id = b.get("pickup_hub_id")
    if not isinstance(pickup_hub_id, str):
        bad_request("pickup_hub_id required")
    body_fk_or_404(db.pickup_hubs, pickup_hub_id)
    # ownership (step 5): a customer may only create under their own path
    if role == "Customer" and uid != cid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    box_size = req_enum(b, "box_size", {"SMALL", "MEDIUM", "LARGE"})
    cadence = req_enum(b, "cadence", {"WEEKLY", "BIWEEKLY"})
    price_cap_cents = req_int(b, "price_cap_cents", 1)
    sub = new_entity(
        "Subscription", customer_id=cid, pickup_hub_id=pickup_hub_id, box_size=box_size,
        cadence=cadence, price_cap_cents=price_cap_cents, status="ACTIVE",
    )
    db.subscriptions[sub["id"]] = sub
    return success(serialize(sub), "object", 201)


@app.get("/subscriptions/<sid>")
def get_subscription(sid):
    uid, role = authenticate({"PlatformAdmin", "Customer"})
    sub = get_or_404(db.subscriptions, sid)
    return success(serialize(sub), "object", 200)


@app.get("/subscriptions")
def list_subscriptions():
    authenticate({"PlatformAdmin", "Customer"})
    customer_id = request.args.get("customer_id")
    pickup_hub_id = request.args.get("pickup_hub_id")
    items = []
    for s in db.subscriptions.values():
        if customer_id is not None and s["customer_id"] != customer_id:
            continue
        if pickup_hub_id is not None and s["pickup_hub_id"] != pickup_hub_id:
            continue
        items.append(s)
    return list_response(items)


def _sub_transition(sid, from_state, to_state):
    uid, role = authenticate({"PlatformAdmin", "Customer"})
    sub = get_or_404(db.subscriptions, sid)
    if role == "Customer" and uid != sub["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if sub["status"] != from_state:
        raise ApiError("ERR_INVALID_STATE")
    sub["status"] = to_state
    touch(sub)
    return success(serialize(sub), "object", 200)


@app.post("/subscriptions/<sid>/pause")
def pause_subscription(sid):
    return _sub_transition(sid, "ACTIVE", "PAUSED")


@app.post("/subscriptions/<sid>/resume")
def resume_subscription(sid):
    return _sub_transition(sid, "PAUSED", "ACTIVE")


@app.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    uid, role = authenticate({"PlatformAdmin", "Customer"})
    sub = get_or_404(db.subscriptions, sid)
    if role == "Customer" and uid != sub["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE")
    sub["status"] = "CANCELLED"
    touch(sub)
    return success(serialize(sub), "object", 200)


# =========================================================================
# ORDER
# =========================================================================


@app.post("/orders")
def create_order():
    uid, role = authenticate({"Customer"})
    b = body()
    market_cycle_id = b.get("market_cycle_id")
    pickup_hub_id = b.get("pickup_hub_id")
    if not isinstance(market_cycle_id, str) or not isinstance(pickup_hub_id, str):
        bad_request("market_cycle_id and pickup_hub_id required")
    cycle = body_fk_or_404(db.market_cycles, market_cycle_id)
    body_fk_or_404(db.pickup_hubs, pickup_hub_id)
    fulfillment_type = req_enum(b, "fulfillment_type", {"PICKUP", "DELIVERY"})
    slot_start = b.get("delivery_slot_start")
    slot_end = b.get("delivery_slot_end")
    if fulfillment_type == "DELIVERY":
        ds = parse_dt(slot_start)
        de = parse_dt(slot_end)
        if ds is None or de is None or not (de > ds):
            bad_request("DELIVERY requires delivery_slot_start/end with end>start")
    else:
        slot_start = None
        slot_end = None
    # cycle-open posture (step 8)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    order = new_entity(
        "Order", customer_id=uid, market_cycle_id=market_cycle_id,
        pickup_hub_id=pickup_hub_id, subscription_id=None,
        fulfillment_type=fulfillment_type, delivery_slot_start=slot_start,
        delivery_slot_end=slot_end, subtotal_cents=0, eligible_subtotal_cents=0,
        snap_applied_cents=0, doubleup_match_cents=0, customer_owed_cents=0,
        final_total_cents=None, refunded_snap_cents=0, refunded_wallet_cents=0,
        order_status="CART", payment_status="UNPAID", _du_reversed=0,
    )
    db.orders[order["id"]] = order
    return success(serialize(order), "object", 201)


@app.get("/orders/<oid>")
def get_order(oid):
    authenticate({"PlatformAdmin", "Customer"})
    order = get_or_404(db.orders, oid)
    return success(serialize(order), "object", 200)


@app.get("/orders")
def list_orders():
    authenticate({"PlatformAdmin", "Customer"})
    f_customer = request.args.get("customer_id")
    f_cycle = request.args.get("market_cycle_id")
    f_hub = request.args.get("pickup_hub_id")
    f_sub = request.args.get("subscription_id")
    f_status = request.args.get("order_status")
    items = []
    for o in db.orders.values():
        if f_customer is not None and o["customer_id"] != f_customer:
            continue
        if f_cycle is not None and o["market_cycle_id"] != f_cycle:
            continue
        if f_hub is not None and o["pickup_hub_id"] != f_hub:
            continue
        if f_sub is not None and o["subscription_id"] != f_sub:
            continue
        if f_status is not None and o["order_status"] != f_status:
            continue
        items.append(o)
    return list_response(items)


def add_order_line(order, offering, product, requested_qty):
    """Create a REQUESTED line, reserve offering qty, price it (estimated)."""
    est = estimated_line_price(product, offering, requested_qty)
    line = new_entity(
        "OrderLine", order_id=order["id"], offering_id=offering["id"],
        requested_qty=requested_qty, allocated_qty=None, fulfilled_qty=None,
        actual_weight_kg=None, snap_eligible=product["snap_eligible"],
        estimated_line_cents=est, final_line_cents=None, substitute_offering_id=None,
        price_delta_cents=0, line_status="REQUESTED",
    )
    db.order_lines[line["id"]] = line
    offering_reserve(offering, requested_qty)
    return line


@app.post("/orders/<oid>/lines")
def create_order_line(oid):
    uid, role = authenticate({"Customer"})
    order = get_or_404(db.orders, oid)
    b = body()
    offering_id = b.get("offering_id")
    if not isinstance(offering_id, str):
        bad_request("offering_id required")
    offering = body_fk_or_404(db.offerings, offering_id)
    # ownership (step 5)
    if uid != order["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    requested_qty = req_int(b, "requested_qty", 1)
    # cycle-open posture (step 8)
    cycle = db.market_cycles[order["market_cycle_id"]]
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    # target state (step 9): order must be CART
    if order["order_status"] != "CART":
        raise ApiError("ERR_INVALID_STATE")
    # availability (step 14)
    if requested_qty > offering["remaining_qty"]:
        raise ApiError("ERR_INSUFFICIENT_AVAILABILITY")
    product = product_of_offering(offering)
    line = add_order_line(order, offering, product, requested_qty)
    return success(serialize(line), "object", 201)


@app.post("/orders/<oid>/checkout")
def checkout_order(oid):
    uid, role = authenticate({"Customer"})
    order = get_or_404(db.orders, oid)
    if uid != order["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # cycle-open posture (step 8)
    cycle = db.market_cycles[order["market_cycle_id"]]
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    # target state (step 9)
    if order["order_status"] != "CART":
        raise ApiError("ERR_INVALID_STATE")
    order_lines_list = [l for l in lines_of(order["id"]) if l["line_status"] != "CANCELLED"]
    if len(order_lines_list) == 0:
        raise ApiError("ERR_EMPTY_ORDER")
    # delivery slot capacity (step 13)
    if order["fulfillment_type"] == "DELIVERY":
        check_slot_capacity(order)
    # benefit application (estimated variant), evaluation order fixed
    customer = db.customers[order["customer_id"]]
    subtotal = sum(l["estimated_line_cents"] for l in order_lines_list)
    eligible = sum(l["estimated_line_cents"] for l in order_lines_list if l["snap_eligible"])
    snap = min(customer["snap_balance_cents"], eligible)
    headroom = max(0, db.DOUBLEUP_CAP_CENTS - customer["doubleup_used_cents"])
    du = min(snap, headroom)
    owed = max(0, subtotal - snap - du)
    order["subtotal_cents"] = subtotal
    order["eligible_subtotal_cents"] = eligible
    order["snap_applied_cents"] = snap
    order["doubleup_match_cents"] = du
    order["customer_owed_cents"] = owed
    customer["snap_balance_cents"] -= snap
    customer["doubleup_used_cents"] += du
    touch(customer)
    order["order_status"] = "PLACED"
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success(serialize(order), "object", 200)


def check_slot_capacity(order):
    hub = db.pickup_hubs[order["pickup_hub_id"]]
    cap = hub["slot_capacity"]
    intervals = []
    for o in db.orders.values():
        if o["pickup_hub_id"] != hub["id"] or o["fulfillment_type"] != "DELIVERY":
            continue
        if o["id"] == order["id"]:
            continue
        if o["order_status"] not in ("PLACED", "ALLOCATED", "FULFILLED"):
            continue
        s = parse_dt(o["delivery_slot_start"])
        e = parse_dt(o["delivery_slot_end"])
        if s is None or e is None:
            continue
        intervals.append((s, e))
    intervals.append((parse_dt(order["delivery_slot_start"]), parse_dt(order["delivery_slot_end"])))
    events = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    events.sort(key=lambda x: (x[0], x[1]))  # end (-1) before start (+1): half-open
    cur = 0
    mx = 0
    for _, d in events:
        cur += d
        if cur > mx:
            mx = cur
    if mx > cap:
        raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED")


@app.post("/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = authenticate({"Customer", "PlatformAdmin"})
    order = get_or_404(db.orders, oid)
    if role == "Customer" and uid != order["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    status = order["order_status"]
    if status not in ("CART", "PLACED", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE")
    if status == "ALLOCATED":
        for line in lines_of(order["id"]):
            if line["line_status"] in ("PACKED", "SUBSTITUTED", "SHORTED", "FULFILLED"):
                raise ApiError("ERR_ORDER_IN_PACKOUT")
    # cascade L1/L2: cancel non-terminal lines, release reserved units
    for line in lines_of(order["id"]):
        if line["line_status"] in ("REQUESTED", "ALLOCATED"):
            offering = db.offerings[line["offering_id"]]
            offering_release(offering, line["requested_qty"])
            line["line_status"] = "CANCELLED"
            touch(line)
    # full refund only for orders that applied benefits (PLACED / ALLOCATED)
    if status in ("PLACED", "ALLOCATED"):
        customer = db.customers[order["customer_id"]]
        snap = order["snap_applied_cents"]
        du = order["doubleup_match_cents"]
        owed = order["customer_owed_cents"]
        customer["snap_balance_cents"] += snap
        customer["doubleup_used_cents"] -= du
        customer["wallet_credit_cents"] += owed
        order["refunded_snap_cents"] += snap
        order["refunded_wallet_cents"] += owed
        order["_du_reversed"] += du
        order["payment_status"] = "REFUNDED"
        touch(customer)
    order["order_status"] = "CANCELLED"
    touch(order)
    return success(serialize(order), "object", 200)


@app.post("/orders/<oid>/fulfill")
def fulfill_order(oid):
    authenticate({"PlatformAdmin", "Farm"})
    order = get_or_404(db.orders, oid)
    if order["order_status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE")
    order_line_list = lines_of(order["id"])
    for line in order_line_list:
        if line["line_status"] not in ("PACKED", "SUBSTITUTED", "SHORTED"):
            raise ApiError("ERR_LINES_NOT_PACKED")
    for line in order_line_list:
        line["line_status"] = "FULFILLED"
        touch(line)
    final_total = sum(l["final_line_cents"] for l in order_line_list)
    order["final_total_cents"] = final_total
    order["customer_owed_cents"] = max(
        0, final_total - order["snap_applied_cents"] - order["doubleup_match_cents"]
    )
    order["order_status"] = "FULFILLED"
    order["payment_status"] = "CAPTURED"
    touch(order)
    return success(serialize(order), "object", 200)


# =========================================================================
# ORDER LINE
# =========================================================================


@app.get("/order-lines/<lid>")
def get_order_line(lid):
    authenticate({"PlatformAdmin", "Customer", "Farm"})
    line = get_or_404(db.order_lines, lid)
    return success(serialize(line), "object", 200)


@app.get("/order-lines")
def list_order_lines():
    authenticate({"PlatformAdmin", "Customer", "Farm"})
    f_order = request.args.get("order_id")
    f_offering = request.args.get("offering_id")
    f_sub = request.args.get("substitute_offering_id")
    f_status = request.args.get("line_status")
    items = []
    for l in db.order_lines.values():
        if f_order is not None and l["order_id"] != f_order:
            continue
        if f_offering is not None and l["offering_id"] != f_offering:
            continue
        if f_sub is not None and l["substitute_offering_id"] != f_sub:
            continue
        if f_status is not None and l["line_status"] != f_status:
            continue
        items.append(l)
    return list_response(items)


@app.post("/order-lines/<lid>/pack")
def pack_order_line(lid):
    uid, role = authenticate({"Farm", "PlatformAdmin"})
    line = get_or_404(db.order_lines, lid)
    b = body()
    sub_off_id = b.get("substitute_offering_id")
    is_sub = sub_off_id is not None
    # body-referenced FK existence (step 4)
    sub_off = None
    if is_sub:
        sub_off = body_fk_or_404(db.offerings, sub_off_id)
    # body well-formedness (step 6)
    if is_sub:
        substitute_qty = req_int(b, "substitute_qty", 1)
        fulfilled_qty = None
    else:
        fulfilled_qty = req_int(b, "fulfilled_qty", 0)
        substitute_qty = None
    actual_weight_kg = b.get("actual_weight_kg")
    if actual_weight_kg is not None and not _is_num(actual_weight_kg):
        bad_request("actual_weight_kg must be a number")

    order = db.orders[line["order_id"]]
    offering = db.offerings[line["offering_id"]]
    product = product_of_offering(offering)

    # parent-order posture (step 7): checked before the line's own state
    if order["order_status"] != "ALLOCATED":
        raise ApiError("ERR_ORDER_NOT_ALLOCATED")
    # target state (step 9)
    if line["line_status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE")
    # business-referential ownership (step 10)
    if role == "Farm":
        if farm_of_offering(offering) != uid:
            raise ApiError("ERR_NOT_LINE_OWNER")
        if is_sub and farm_of_offering(sub_off) != uid:
            raise ApiError("ERR_NOT_LINE_OWNER")
    # offering-cycle match (step 10)
    if is_sub and sub_off["market_cycle_id"] != offering["market_cycle_id"]:
        raise ApiError("ERR_OFFERING_CYCLE_MISMATCH")

    customer = db.customers[order["customer_id"]]

    if is_sub:
        sub_product = product_of_offering(sub_off)
        # measurement (step 13)
        if sub_product["pricing_mode"] == "WEIGHT" and substitute_qty >= 1:
            if actual_weight_kg is None or actual_weight_kg <= 0:
                raise ApiError("ERR_INVALID_WEIGHT")
        # availability (step 14)
        if substitute_qty > sub_off["remaining_qty"]:
            raise ApiError("ERR_INSUFFICIENT_AVAILABILITY")
        final_cents = final_line_price(sub_product, sub_off, substitute_qty, actual_weight_kg)
        line["substitute_offering_id"] = sub_off_id
        line["fulfilled_qty"] = substitute_qty
        line["actual_weight_kg"] = actual_weight_kg
        line["final_line_cents"] = final_cents
        line["price_delta_cents"] = final_cents - line["estimated_line_cents"]
        line["line_status"] = "SUBSTITUTED"
        # original offering releases reserved; substitute offering commits
        offering_release(offering, line["requested_qty"])
        offering_commit(sub_off, substitute_qty)
        touch(line)
        if line["price_delta_cents"] < 0:
            partial_refund(order, line, -line["price_delta_cents"], customer, True)
            touch(order)
        return success(serialize(line), "object", 200)

    # non-substitution pack: over-pack (step 13)
    allocated = line["allocated_qty"]
    if fulfilled_qty > allocated:
        raise ApiError("ERR_OVER_PACK")
    # measurement (step 13): WEIGHT line with fulfilled_qty >= 1 needs weight > 0
    if product["pricing_mode"] == "WEIGHT" and fulfilled_qty >= 1:
        if actual_weight_kg is None or actual_weight_kg <= 0:
            raise ApiError("ERR_INVALID_WEIGHT")

    if fulfilled_qty == 0:
        final_cents = 0
    else:
        final_cents = final_line_price(product, offering, fulfilled_qty, actual_weight_kg)
    line["fulfilled_qty"] = fulfilled_qty
    line["actual_weight_kg"] = actual_weight_kg
    line["final_line_cents"] = final_cents
    line["price_delta_cents"] = final_cents - line["estimated_line_cents"]
    offering_pack_same(offering, line["requested_qty"], fulfilled_qty)

    if fulfilled_qty == allocated:
        line["line_status"] = "PACKED"
        touch(line)
        # cheaper full pack: partial refund, but PRD marks PARTIALLY_REFUNDED
        # only for short/substitution -> mark_partial=False here.
        if line["price_delta_cents"] < 0:
            partial_refund(order, line, -line["price_delta_cents"], customer, False)
            touch(order)
    else:  # SHORTED
        line["line_status"] = "SHORTED"
        touch(line)
        credit = line["estimated_line_cents"] - final_cents  # >= 0
        partial_refund(order, line, credit, customer, True)
        touch(order)
    return success(serialize(line), "object", 200)


# =========================================================================
# VENDOR SETTLEMENT (PRD 3.9 / calc vendor_settlement_payout)
# =========================================================================


def snap_du_attribution(order):
    """Per FULFILLED snap_eligible line, cents of gross funded by SNAP+DoubleUp.

    The order-level net SNAP+Double-Up pool (after refunds) is allocated across
    its FULFILLED snap_eligible lines in creation order, each capped at that
    line's final_line_cents (SNAP/DU cannot fund more than the line's gross).
    """
    net_snap = order["snap_applied_cents"] - order["refunded_snap_cents"]
    net_du = order["doubleup_match_cents"] - order["_du_reversed"]
    pool = max(0, net_snap) + max(0, net_du)
    result = {}
    elig = [
        l for l in lines_of(order["id"])
        if l["line_status"] == "FULFILLED" and l["snap_eligible"]
    ]
    for line in elig:
        take = min(pool, line["final_line_cents"])
        result[line["id"]] = take
        pool -= take
    return result


@app.post("/farms/<fid>/settlements")
def create_settlement(fid):
    authenticate({"PlatformAdmin"})
    farm = get_or_404(db.farms, fid)
    b = body()
    market_cycle_id = b.get("market_cycle_id")
    if not isinstance(market_cycle_id, str):
        bad_request("market_cycle_id required")
    cycle = body_fk_or_404(db.market_cycles, market_cycle_id)
    expected_farm_version = b.get("expected_farm_version")
    if not _is_int(expected_farm_version):
        bad_request("expected_farm_version required (integer)")
    # target state (step 9): cycle must be SETTLED
    if cycle["status"] != "SETTLED":
        raise ApiError("ERR_INVALID_STATE")
    # OCC (step 14)
    if expected_farm_version != farm["version"]:
        raise ApiError("ERR_STALE_FARM_VERSION")

    commission_pct = Decimal(str(farm["commission_pct"]))
    gross = 0
    commission = 0
    snap_reimb = 0
    line_count = 0
    swept = []
    # precompute per-order attribution once
    attribution_cache = {}
    for line in db.order_lines.values():
        if line["line_status"] != "FULFILLED":
            continue
        if line.get("_settled"):
            continue
        offering = db.offerings[line["offering_id"]]
        if farm_of_offering(offering) != fid:
            continue
        order = db.orders[line["order_id"]]
        if order["market_cycle_id"] != market_cycle_id:
            continue
        gross += line["final_line_cents"]
        commission += cents_round(Decimal(line["final_line_cents"]) * commission_pct)
        line_count += 1
        swept.append(line)
        if line["snap_eligible"]:
            oid = order["id"]
            if oid not in attribution_cache:
                attribution_cache[oid] = snap_du_attribution(order)
            snap_reimb += attribution_cache[oid].get(line["id"], 0)

    net_payout = gross - commission
    settlement = new_entity(
        "VendorSettlement", common=False, farm_id=fid, market_cycle_id=market_cycle_id,
        gross_sales_cents=gross, commission_cents=commission,
        snap_reimbursable_cents=snap_reimb, net_payout_cents=net_payout,
        line_count=line_count,
    )
    db.settlements[settlement["id"]] = settlement
    for line in swept:
        line["_settled"] = True
    # post payout onto the farm (single mutation -> version += 1)
    farm["payout_balance_cents"] += net_payout
    farm["settled_cycle_count"] += 1
    touch(farm)
    return success(serialize(settlement), "object", 201)


@app.get("/settlements/<sid>")
def get_settlement(sid):
    authenticate({"PlatformAdmin", "Farm"})
    s = get_or_404(db.settlements, sid)
    return success(serialize(s), "object", 200)


@app.get("/settlements")
def list_settlements():
    authenticate({"PlatformAdmin", "Farm"})
    f_farm = request.args.get("farm_id")
    f_cycle = request.args.get("market_cycle_id")
    items = []
    for s in db.settlements.values():
        if f_farm is not None and s["farm_id"] != f_farm:
            continue
        if f_cycle is not None and s["market_cycle_id"] != f_cycle:
            continue
        items.append(s)
    return list_response(items)


# =========================================================================
# LOGICAL CLOCK (test-driving, PRD 2.10)
# =========================================================================


@app.post("/_clock/set_current_utc")
def set_clock():
    authenticate({"PlatformAdmin"})
    b = body()
    to_iso = b.get("to_iso8601")
    if parse_dt(to_iso) is None:
        bad_request("to_iso8601 required (ISO 8601)")
    db.logical_clock["value"] = to_iso
    return success(None, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
