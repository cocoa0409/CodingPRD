import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml / PRD)
# ---------------------------------------------------------------------------
ROLES = {"Customer", "ShopStaff", "InventoryManager", "WholesaleApprover", "PlatformAdmin"}
ALLERGENS = {"TREE_NUT", "SULFITES"}
PRODUCT_TYPES = {"BULK_OIL", "BULK_VINEGAR", "BOTTLE", "ACCESSORY", "GIFT_SET", "BLEND"}
BULK_TYPES = {"BULK_OIL", "BULK_VINEGAR"}
LINE_TYPES = {"UNIT", "REFILL", "BUNDLE"}

FRESHNESS_MARKDOWN_THRESHOLD = 70
FRESHNESS_MARKDOWN_PCT = Decimal("0.15")
GIFT_SET_DISCOUNT_PCT = Decimal("0.10")
FREE_SHIP_THRESHOLD_CENTS = 7500
FLAT_SHIP_CENTS = 995
OPEN_DECAY_PER_DAY = Decimal("2.5")
POINTS_PER_DOLLAR = 1
BUFFER_MINUTES = 15
TIER_PCT = {"TIER_1": Decimal("0.10"), "TIER_2": Decimal("0.20"), "TIER_3": Decimal("0.30")}

CLOCK = {"now": datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)}

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
members = {}
products = {}
components = {}
fusti = {}
replenishments = {}
wholesale = {}
orders = {}
reservations = {}
subscriptions = {}
stations = {}
sessions = {}

_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# Errors / envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": fmt_dt(now())}


def ok(data, code=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": {"api_request_id": req_id(), "api_request_timestamp": fmt_dt(now())},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Datetime / numeric helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def D(v):
    return Decimal(str(v))


def rhu_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing/invalid auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "body must be an object")
    return b


# ---------------------------------------------------------------------------
# Entity base creation
# ---------------------------------------------------------------------------
def base_full():
    t = now()
    return {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t, "version": 1, "_seq": next_seq()}


def base_light():
    return {"id": str(uuid.uuid4()), "created_at": now(), "_seq": next_seq()}


def touch(e):
    e["updated_at"] = now()
    e["version"] = e.get("version", 0) + 1


def sort_key(e):
    return (e["created_at"], e["_seq"])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_member(m):
    return {
        "id": m["id"], "created_at": fmt_dt(m["created_at"]), "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"], "email": m["email"], "full_name": m["full_name"],
        "member_type": m["member_type"], "allergen_restrictions": list(m["allergen_restrictions"]),
        "wallet_credit_cents": m["wallet_credit_cents"], "loyalty_points": m["loyalty_points"],
    }


def s_product(p):
    return {
        "id": p["id"], "created_at": fmt_dt(p["created_at"]), "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"], "sku": p["sku"], "name": p["name"], "product_type": p["product_type"],
        "unit_price_cents": p["unit_price_cents"], "price_per_ml_cents": p["price_per_ml_cents"],
        "allergens": list(p["allergens"]), "shelf_life_days": p["shelf_life_days"],
    }


def s_component(c):
    return {
        "id": c["id"], "created_at": fmt_dt(c["created_at"]),
        "set_product_id": c["set_product_id"], "component_product_id": c["component_product_id"],
        "quantity": c["quantity"],
    }


def freshness_scores(f):
    p = products[f["product_id"]]
    shelf = p["shelf_life_days"]
    harvest = f["harvest_date"]
    n = now()
    if shelf and shelf > 0:
        elapsed_days = D((n - harvest).total_seconds()) / D(86400)
        label_raw = D(100) * (D(1) - elapsed_days / D(shelf))
        if label_raw < 0:
            label_raw = D(0)
        label = label_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        label = D(0)
    if f["first_draw_at"] is None:
        sensory = label
    else:
        fd = f["first_draw_at"]
        if shelf and shelf > 0:
            elapsed_open = D((fd - harvest).total_seconds()) / D(86400)
            lao_raw = D(100) * (D(1) - elapsed_open / D(shelf))
            if lao_raw < 0:
                lao_raw = D(0)
            label_at_open = lao_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            label_at_open = D(0)
        days_open = D((n - fd).total_seconds()) / D(86400)
        s_raw = label_at_open - OPEN_DECAY_PER_DAY * days_open
        if s_raw < 0:
            s_raw = D(0)
        sensory = s_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return label, sensory


def is_past_best_by(f):
    return now() >= f["best_by_date"]


def available_volume(f):
    return f["current_volume_ml"] - f["reserved_volume_ml"]


def s_fusti(f):
    label, sensory = freshness_scores(f)
    return {
        "id": f["id"], "created_at": fmt_dt(f["created_at"]), "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"], "product_id": f["product_id"], "capacity_ml": f["capacity_ml"],
        "current_volume_ml": f["current_volume_ml"], "reserved_volume_ml": f["reserved_volume_ml"],
        "available_volume_ml": available_volume(f), "reorder_point_ml": f["reorder_point_ml"],
        "harvest_date": fmt_dt(f["harvest_date"]), "best_by_date": fmt_dt(f["best_by_date"]),
        "first_draw_at": fmt_dt(f["first_draw_at"]), "status": f["status"],
        "label_freshness_score": float(label), "sensory_freshness_score": float(sensory),
        "is_past_best_by": is_past_best_by(f),
    }


def s_replenishment(r):
    return {
        "id": r["id"], "created_at": fmt_dt(r["created_at"]), "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"], "fusti_id": r["fusti_id"], "product_id": r["product_id"],
        "requested_volume_ml": r["requested_volume_ml"],
        "received_harvest_date": fmt_dt(r["received_harvest_date"]), "status": r["status"],
    }


def s_wholesale(w):
    return {
        "id": w["id"], "created_at": fmt_dt(w["created_at"]), "updated_at": fmt_dt(w["updated_at"]),
        "version": w["version"], "member_id": w["member_id"], "business_name": w["business_name"],
        "tax_id": w["tax_id"], "status": w["status"], "tier": w["tier"],
        "rejection_reason": w["rejection_reason"],
    }


def s_order(o):
    return {
        "id": o["id"], "created_at": fmt_dt(o["created_at"]), "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"], "member_id": o["member_id"],
        "wholesale_account_id": o["wholesale_account_id"], "lines": o["lines"],
        "payment_status": o["payment_status"], "fulfillment_status": o["fulfillment_status"],
        "provisional_subtotal_cents": o["provisional_subtotal_cents"],
        "provisional_total_cents": o["provisional_total_cents"],
        "final_subtotal_cents": o["final_subtotal_cents"],
        "final_total_cents": o["final_total_cents"], "discount_cents": o["discount_cents"],
        "shipping_fee_cents": o["shipping_fee_cents"],
        "wallet_credit_applied_cents": o["wallet_credit_applied_cents"],
        "amount_charged_cents": o["amount_charged_cents"],
        "amount_refunded_cents": o["amount_refunded_cents"],
        "use_wallet_credit": o["use_wallet_credit"],
    }


def s_reservation(r):
    return {
        "id": r["id"], "created_at": fmt_dt(r["created_at"]), "order_id": r["order_id"],
        "fusti_id": r["fusti_id"], "volume_ml": r["volume_ml"], "status": r["status"],
    }


def s_subscription(sub):
    return {
        "id": sub["id"], "created_at": fmt_dt(sub["created_at"]), "updated_at": fmt_dt(sub["updated_at"]),
        "version": sub["version"], "member_id": sub["member_id"], "product_id": sub["product_id"],
        "quantity": sub["quantity"], "volume_ml": sub["volume_ml"], "cadence_days": sub["cadence_days"],
        "status": sub["status"], "next_renewal_date": fmt_dt(sub["next_renewal_date"]),
        "renewals_count": sub["renewals_count"], "last_order_id": sub["last_order_id"],
    }


def s_station(st):
    return {
        "id": st["id"], "created_at": fmt_dt(st["created_at"]), "updated_at": fmt_dt(st["updated_at"]),
        "version": st["version"], "name": st["name"],
    }


def s_session(se):
    return {
        "id": se["id"], "created_at": fmt_dt(se["created_at"]), "updated_at": fmt_dt(se["updated_at"]),
        "version": se["version"], "station_id": se["station_id"], "member_id": se["member_id"],
        "start_at": fmt_dt(se["start_at"]), "end_at": fmt_dt(se["end_at"]),
        "party_size": se["party_size"], "status": se["status"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> 404)
# ---------------------------------------------------------------------------
def get_or_404(store, key, err):
    e = store.get(key)
    if e is None:
        raise ApiError(err, 404, "not found")
    return e


def get_member(mid):
    return get_or_404(members, mid, "ERR_MEMBER_NOT_FOUND")


def get_product(pid):
    return get_or_404(products, pid, "ERR_PRODUCT_NOT_FOUND")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require_str(b, key):
    v = b.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{key} required")
    return v


def validate_allergen_list(v):
    if v is None:
        return []
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", 422, "allergens must be a list")
    for a in v:
        if a not in ALLERGENS:
            raise ApiError("ERR_VALIDATION", 422, "invalid allergen")
    return list(v)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def bundle_price(set_product):
    total = 0
    for c in components.values():
        if c["set_product_id"] == set_product["id"]:
            comp = products.get(c["component_product_id"])
            if comp is None:
                continue
            total += rhu_cents(D(comp["unit_price_cents"]) * D(c["quantity"]) * (D(1) - GIFT_SET_DISCOUNT_PCT))
    return total


def line_price_provisional(line):
    p = products[line["product_id"]]
    lt = line["line_type"]
    if lt == "UNIT":
        return p["unit_price_cents"] * line["quantity"]
    if lt == "REFILL":
        return rhu_cents(D(p["price_per_ml_cents"]) * D(line["volume_ml"]))
    return bundle_price(p)


def tier_pct_for(order):
    wid = order.get("wholesale_account_id")
    if not wid:
        return Decimal("0")
    acct = wholesale.get(wid)
    if acct is None or acct["status"] != "APPROVED":
        return Decimal("0")
    return TIER_PCT.get(acct["tier"], Decimal("0"))


def settle(subtotal, tier_pct):
    discount = rhu_cents(D(subtotal) * tier_pct)
    discounted = subtotal - discount
    shipping = 0 if discounted >= FREE_SHIP_THRESHOLD_CENTS else FLAT_SHIP_CENTS
    total = discounted + shipping
    return discount, discounted, shipping, total


# ---------------------------------------------------------------------------
# Order creation (shared by POST /orders and subscription renew)
# ---------------------------------------------------------------------------
def create_order_record(member_id, lines, wholesale_account_id, use_wallet_credit):
    subtotal = sum(line_price_provisional(l) for l in lines)
    o = base_full()
    o.update({
        "member_id": member_id, "wholesale_account_id": wholesale_account_id, "lines": lines,
        "payment_status": "UNPAID", "fulfillment_status": "PENDING",
        "provisional_subtotal_cents": subtotal, "final_subtotal_cents": None,
        "final_total_cents": None, "wallet_credit_applied_cents": 0, "amount_charged_cents": 0,
        "amount_refunded_cents": 0, "use_wallet_credit": bool(use_wallet_credit),
        "line_reservations": {},
    })
    tier_pct = tier_pct_for(o)
    discount, discounted, shipping, total = settle(subtotal, tier_pct)
    o["discount_cents"] = discount
    o["shipping_fee_cents"] = shipping
    o["provisional_total_cents"] = total
    orders[o["id"]] = o
    return o


# ===========================================================================
# Endpoints
# ===========================================================================

@app.post("/api/_clock/set_current_utc")
def clock_set():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    b = body()
    target = require_str(b, "to_iso8601")
    CLOCK["now"] = parse_dt(target)
    return ok({"current_utc": fmt_dt(CLOCK["now"])}, 200)


# ---- Members ----
@app.post("/api/members")
def create_member():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    b = body()
    email = require_str(b, "email")
    full_name = require_str(b, "full_name")
    allergen = validate_allergen_list(b.get("allergen_restrictions"))
    m = base_full()
    m.update({
        "email": email, "full_name": full_name, "member_type": "RETAIL",
        "allergen_restrictions": allergen, "wallet_credit_cents": 0, "loyalty_points": 0,
    })
    members[m["id"]] = m
    return ok(s_member(m), 201)


@app.get("/api/members/<mid>")
def get_member_ep(mid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "InventoryManager", "WholesaleApprover", "PlatformAdmin"})
    m = get_member(mid)
    if role == "Customer" and mid != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    return ok(s_member(m), 200)


# ---- Products ----
@app.post("/api/products")
def create_product():
    uid, role = require_auth()
    require_role(role, {"InventoryManager"})
    b = body()
    sku = require_str(b, "sku")
    name = require_str(b, "name")
    ptype = b.get("product_type")
    if ptype not in PRODUCT_TYPES:
        raise ApiError("ERR_VALIDATION", 422, "invalid product_type")
    unit_price = b.get("unit_price_cents", 0)
    ppm = b.get("price_per_ml_cents", 0)
    allergens = validate_allergen_list(b.get("allergens"))
    shelf = b.get("shelf_life_days", 0)
    if not isinstance(unit_price, int) or isinstance(unit_price, bool) or unit_price < 0:
        raise ApiError("ERR_VALIDATION", 422, "invalid unit_price_cents")
    if isinstance(ppm, bool) or not isinstance(ppm, (int, float)) or ppm < 0:
        raise ApiError("ERR_VALIDATION", 422, "invalid price_per_ml_cents")
    if not isinstance(shelf, int) or isinstance(shelf, bool) or shelf < 0:
        raise ApiError("ERR_VALIDATION", 422, "invalid shelf_life_days")
    for p in products.values():
        if p["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU", 409, "sku exists")
    p = base_full()
    p.update({
        "sku": sku, "name": name, "product_type": ptype, "unit_price_cents": unit_price,
        "price_per_ml_cents": ppm, "allergens": allergens, "shelf_life_days": shelf,
    })
    products[p["id"]] = p
    return ok(s_product(p), 201)


@app.get("/api/products/<pid>")
def get_product_ep(pid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "InventoryManager", "WholesaleApprover", "PlatformAdmin"})
    p = get_product(pid)
    return ok(s_product(p), 200)


@app.post("/api/products/<pid>/components")
def add_component(pid):
    uid, role = require_auth()
    require_role(role, {"InventoryManager"})
    p = get_product(pid)
    b = body()
    cpid = b.get("component_product_id")
    if not isinstance(cpid, str) or not cpid:
        raise ApiError("ERR_VALIDATION", 422, "component_product_id required")
    comp = get_or_404(products, cpid, "ERR_PRODUCT_NOT_FOUND")
    qty = b.get("quantity")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
        raise ApiError("ERR_VALIDATION", 422, "quantity must be >= 1")
    if p["product_type"] not in {"GIFT_SET", "BLEND"} or comp["product_type"] in {"GIFT_SET", "BLEND"}:
        raise ApiError("ERR_INVALID_COMPONENT", 422, "invalid component")
    c = base_light()
    c.update({"set_product_id": pid, "component_product_id": cpid, "quantity": qty})
    components[c["id"]] = c
    return ok(s_component(c), 201)


@app.get("/api/products/<pid>/components")
def list_components(pid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "InventoryManager", "WholesaleApprover", "PlatformAdmin"})
    get_product(pid)
    items = [c for c in components.values() if c["set_product_id"] == pid]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_component(c) for c in page], limit, offset, total)


# ---- Fusti ----
@app.post("/api/fusti")
def create_fusti():
    uid, role = require_auth()
    require_role(role, {"InventoryManager"})
    b = body()
    pid = b.get("product_id")
    if not isinstance(pid, str) or not pid:
        raise ApiError("ERR_VALIDATION", 422, "product_id required")
    p = get_product(pid)
    capacity = b.get("capacity_ml")
    initial = b.get("initial_volume_ml")
    reorder = b.get("reorder_point_ml")
    harvest = b.get("harvest_date")
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise ApiError("ERR_VALIDATION", 422, "capacity_ml must be >= 1")
    if not isinstance(initial, int) or isinstance(initial, bool) or initial < 0:
        raise ApiError("ERR_VALIDATION", 422, "invalid initial_volume_ml")
    if not isinstance(reorder, int) or isinstance(reorder, bool) or reorder < 0:
        raise ApiError("ERR_VALIDATION", 422, "invalid reorder_point_ml")
    harvest_dt = parse_dt(harvest)
    f = base_full()
    best_by = harvest_dt + timedelta(days=p["shelf_life_days"])
    status = "LOW" if initial <= reorder else "IN_SERVICE"
    f.update({
        "product_id": pid, "capacity_ml": capacity, "current_volume_ml": initial,
        "reserved_volume_ml": 0, "reorder_point_ml": reorder, "harvest_date": harvest_dt,
        "best_by_date": best_by, "first_draw_at": None, "status": status,
    })
    fusti[f["id"]] = f
    return ok(s_fusti(f), 201)


@app.get("/api/fusti/<fid>")
def get_fusti_ep(fid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "InventoryManager", "WholesaleApprover", "PlatformAdmin"})
    f = get_or_404(fusti, fid, "ERR_FUSTI_NOT_FOUND")
    return ok(s_fusti(f), 200)


@app.get("/api/fusti")
def list_fusti():
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "InventoryManager", "WholesaleApprover", "PlatformAdmin"})
    items = list(fusti.values())
    pf = request.args.get("product_id")
    st = request.args.get("status")
    if pf:
        items = [f for f in items if f["product_id"] == pf]
    if st:
        items = [f for f in items if f["status"] == st]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_fusti(f) for f in page], limit, offset, total)


@app.post("/api/fusti/<fid>/transition")
def fusti_transition(fid):
    uid, role = require_auth()
    require_role(role, {"InventoryManager"})
    f = get_or_404(fusti, fid, "ERR_FUSTI_NOT_FOUND")
    b = body()
    action = b.get("action")
    if action not in {"QUARANTINE", "RELEASE", "RETIRE"}:
        raise ApiError("ERR_VALIDATION", 422, "invalid action")
    st = f["status"]
    if action == "QUARANTINE":
        if st not in {"IN_SERVICE", "LOW"}:
            raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
        f["status"] = "QUARANTINED"
    elif action == "RELEASE":
        if st != "QUARANTINED":
            raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
        f["status"] = "IN_SERVICE" if f["current_volume_ml"] > f["reorder_point_ml"] else "LOW"
    else:  # RETIRE
        if st != "QUARANTINED":
            raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
        f["status"] = "RETIRED"
    touch(f)
    return ok(s_fusti(f), 200)


# ---- Reservations ----
@app.get("/api/reservations/<rid>")
def get_reservation(rid):
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "InventoryManager", "PlatformAdmin"})
    r = get_or_404(reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    return ok(s_reservation(r), 200)


@app.get("/api/reservations")
def list_reservations():
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "InventoryManager", "PlatformAdmin"})
    items = list(reservations.values())
    oid = request.args.get("order_id")
    fid = request.args.get("fusti_id")
    st = request.args.get("status")
    if oid:
        items = [r for r in items if r["order_id"] == oid]
    if fid:
        items = [r for r in items if r["fusti_id"] == fid]
    if st:
        items = [r for r in items if r["status"] == st]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_reservation(r) for r in page], limit, offset, total)


# ---- Replenishment orders ----
@app.get("/api/replenishment-orders/<rid>")
def get_replenishment(rid):
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "InventoryManager", "PlatformAdmin"})
    r = get_or_404(replenishments, rid, "ERR_REPLENISHMENT_NOT_FOUND")
    return ok(s_replenishment(r), 200)


@app.get("/api/replenishment-orders")
def list_replenishments():
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "InventoryManager", "PlatformAdmin"})
    items = list(replenishments.values())
    fid = request.args.get("fusti_id")
    pid = request.args.get("product_id")
    st = request.args.get("status")
    if fid:
        items = [r for r in items if r["fusti_id"] == fid]
    if pid:
        items = [r for r in items if r["product_id"] == pid]
    if st:
        items = [r for r in items if r["status"] == st]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_replenishment(r) for r in page], limit, offset, total)


@app.post("/api/replenishment-orders/<rid>/receive")
def receive_replenishment(rid):
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "InventoryManager"})
    r = get_or_404(replenishments, rid, "ERR_REPLENISHMENT_NOT_FOUND")
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    b = body()
    rhd = parse_dt(b.get("received_harvest_date"))
    f = fusti.get(r["fusti_id"])
    if f is not None:
        p = products[f["product_id"]]
        f["current_volume_ml"] = f["capacity_ml"]
        f["harvest_date"] = rhd
        f["best_by_date"] = rhd + timedelta(days=p["shelf_life_days"])
        f["first_draw_at"] = None
        f["status"] = "IN_SERVICE"
        touch(f)
    r["received_harvest_date"] = rhd
    r["status"] = "RECEIVED"
    touch(r)
    return ok(s_replenishment(r), 200)


# ---- Wholesale accounts ----
@app.post("/api/wholesale-accounts")
def create_wholesale():
    uid, role = require_auth()
    require_role(role, {"Customer"})
    get_member(uid)
    b = body()
    business = require_str(b, "business_name")
    tax = require_str(b, "tax_id")
    w = base_full()
    w.update({
        "member_id": uid, "business_name": business, "tax_id": tax, "status": "DRAFT",
        "tier": "NONE", "rejection_reason": None,
    })
    wholesale[w["id"]] = w
    return ok(s_wholesale(w), 201)


@app.get("/api/wholesale-accounts/<wid>")
def get_wholesale(wid):
    uid, role = require_auth()
    require_role(role, {"Customer", "WholesaleApprover", "PlatformAdmin"})
    w = get_or_404(wholesale, wid, "ERR_WHOLESALE_ACCOUNT_NOT_FOUND")
    if role == "Customer" and w["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    return ok(s_wholesale(w), 200)


@app.get("/api/wholesale-accounts")
def list_wholesale():
    uid, role = require_auth()
    require_role(role, {"WholesaleApprover", "PlatformAdmin"})
    items = list(wholesale.values())
    mid = request.args.get("member_id")
    st = request.args.get("status")
    if mid:
        items = [w for w in items if w["member_id"] == mid]
    if st:
        items = [w for w in items if w["status"] == st]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_wholesale(w) for w in page], limit, offset, total)


@app.post("/api/wholesale-accounts/<wid>/submit")
def submit_wholesale(wid):
    uid, role = require_auth()
    require_role(role, {"Customer"})
    w = get_or_404(wholesale, wid, "ERR_WHOLESALE_ACCOUNT_NOT_FOUND")
    if w["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    if w["status"] not in {"DRAFT", "CHANGES_REQUESTED"}:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    if w["status"] == "CHANGES_REQUESTED":
        w["rejection_reason"] = None
    w["status"] = "SUBMITTED"
    touch(w)
    return ok(s_wholesale(w), 200)


def recompute_member_type(member_id):
    m = members.get(member_id)
    if m is None:
        return
    has_approved = any(
        w["member_id"] == member_id and w["status"] == "APPROVED" for w in wholesale.values()
    )
    new_type = "WHOLESALE" if has_approved else "RETAIL"
    if m["member_type"] != new_type:
        m["member_type"] = new_type
        touch(m)


@app.post("/api/wholesale-accounts/<wid>/decision")
def decide_wholesale(wid):
    uid, role = require_auth()
    require_role(role, {"WholesaleApprover"})
    w = get_or_404(wholesale, wid, "ERR_WHOLESALE_ACCOUNT_NOT_FOUND")
    b = body()
    decision = b.get("decision")
    if decision not in {"APPROVE", "REQUEST_CHANGES", "REJECT", "SUSPEND", "REINSTATE"}:
        raise ApiError("ERR_VALIDATION", 422, "invalid decision")
    required_from = {
        "APPROVE": "SUBMITTED", "REQUEST_CHANGES": "SUBMITTED", "REJECT": "SUBMITTED",
        "SUSPEND": "APPROVED", "REINSTATE": "SUSPENDED",
    }
    if w["status"] != required_from[decision]:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    ev = b.get("expected_wholesale_account_version")
    if ev is None:
        raise ApiError("ERR_VALIDATION", 422, "expected_wholesale_account_version required")
    if ev != w["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale version")

    if decision == "APPROVE":
        tier = b.get("tier")
        if tier not in TIER_PCT:
            raise ApiError("ERR_VALIDATION", 422, "invalid tier")
        w["tier"] = tier
        w["status"] = "APPROVED"
        touch(w)
        recompute_member_type(w["member_id"])
    elif decision == "REQUEST_CHANGES":
        w["rejection_reason"] = b.get("rejection_reason")
        w["status"] = "CHANGES_REQUESTED"
        touch(w)
    elif decision == "REJECT":
        w["rejection_reason"] = b.get("rejection_reason")
        w["status"] = "REJECTED"
        touch(w)
    elif decision == "SUSPEND":
        w["status"] = "SUSPENDED"
        touch(w)
        recompute_member_type(w["member_id"])
    else:  # REINSTATE
        w["status"] = "APPROVED"
        touch(w)
        recompute_member_type(w["member_id"])
    return ok(s_wholesale(w), 200)


# ---- Orders ----
def validate_order_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError("ERR_VALIDATION", 422, "lines must be non-empty")
    # Body FK existence (priority 4)
    for l in lines:
        if not isinstance(l, dict):
            raise ApiError("ERR_VALIDATION", 422, "invalid line")
        pid = l.get("product_id")
        if isinstance(pid, str) and pid:
            get_product(pid)
    # Structural validation (priority 8)
    norm = []
    for l in lines:
        lt = l.get("line_type")
        if lt not in LINE_TYPES:
            raise ApiError("ERR_VALIDATION", 422, "invalid line_type")
        pid = l.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise ApiError("ERR_VALIDATION", 422, "product_id required")
        p = products[pid]
        qty = l.get("quantity", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ApiError("ERR_VALIDATION", 422, "quantity must be >= 1")
        vol = l.get("volume_ml")
        if lt == "UNIT":
            if p["product_type"] not in {"BOTTLE", "ACCESSORY"}:
                raise ApiError("ERR_VALIDATION", 422, "UNIT requires BOTTLE/ACCESSORY")
            vol = None
        elif lt == "REFILL":
            if p["product_type"] not in BULK_TYPES:
                raise ApiError("ERR_VALIDATION", 422, "REFILL requires BULK product")
            if vol is None:
                raise ApiError("ERR_VALIDATION", 422, "volume_ml required for REFILL")
            if not isinstance(vol, int) or isinstance(vol, bool):
                raise ApiError("ERR_VALIDATION", 422, "volume_ml must be integer")
        else:  # BUNDLE
            if p["product_type"] not in {"GIFT_SET", "BLEND"}:
                raise ApiError("ERR_VALIDATION", 422, "BUNDLE requires GIFT_SET/BLEND")
            vol = None
        norm.append({"line_type": lt, "product_id": pid, "quantity": qty, "volume_ml": vol})
    # Zero-volume refill guard (priority 9)
    for l in norm:
        if l["line_type"] == "REFILL" and l["volume_ml"] <= 0:
            raise ApiError("ERR_INVALID_QUANTITY", 422, "refill volume must be > 0")
    # Component legality (priority 10): a BUNDLE set must have >= 1 component
    for l in norm:
        if l["line_type"] == "BUNDLE":
            cnt = sum(1 for c in components.values() if c["set_product_id"] == l["product_id"])
            if cnt < 1:
                raise ApiError("ERR_INVALID_COMPONENT", 422, "set has no components")
    return norm


@app.post("/api/orders")
def create_order():
    uid, role = require_auth()
    require_role(role, {"Customer"})
    get_member(uid)
    b = body()
    lines = b.get("lines")
    wid = b.get("wholesale_account_id")
    if wid is not None:
        get_or_404(wholesale, wid, "ERR_WHOLESALE_ACCOUNT_NOT_FOUND")
    norm = validate_order_lines(lines)
    # PRD §3.3: order creation is permitted with a non-APPROVED wholesale account
    # (the discount rate simply becomes zero); the APPROVED requirement is enforced
    # only at payment (§3.4). Do NOT reject at create time.
    o = create_order_record(uid, norm, wid, bool(b.get("use_wallet_credit", False)))
    return ok(s_order(o), 201)


@app.get("/api/orders/<oid>")
def get_order(oid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "PlatformAdmin"})
    o = get_or_404(orders, oid, "ERR_ORDER_NOT_FOUND")
    if role == "Customer" and o["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    return ok(s_order(o), 200)


@app.get("/api/orders")
def list_orders():
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "PlatformAdmin"})
    items = list(orders.values())
    mid = request.args.get("member_id")
    wid = request.args.get("wholesale_account_id")
    ps = request.args.get("payment_status")
    fs = request.args.get("fulfillment_status")
    if mid:
        items = [o for o in items if o["member_id"] == mid]
    if wid:
        items = [o for o in items if o["wholesale_account_id"] == wid]
    if ps:
        items = [o for o in items if o["payment_status"] == ps]
    if fs:
        items = [o for o in items if o["fulfillment_status"] == fs]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_order(o) for o in page], limit, offset, total)


def check_order_version(o, b):
    ev = b.get("expected_order_version")
    if ev is None:
        raise ApiError("ERR_VALIDATION", 422, "expected_order_version required")
    if ev != o["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale version")


@app.post("/api/orders/<oid>/pay")
def pay_order(oid):
    uid, role = require_auth()
    require_role(role, {"Customer"})
    o = get_or_404(orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    if o["payment_status"] != "UNPAID" or o["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    b = body()
    check_order_version(o, b)
    # zero-volume refill guard (priority 9)
    for l in o["lines"]:
        if l["line_type"] == "REFILL" and l["volume_ml"] <= 0:
            raise ApiError("ERR_INVALID_QUANTITY", 422, "refill volume must be > 0")
    member = members[o["member_id"]]
    # allergen safety (priority 11)
    restricted = set(member["allergen_restrictions"])
    for l in o["lines"]:
        p = products[l["product_id"]]
        if restricted.intersection(p["allergens"]):
            raise ApiError("ERR_ALLERGEN_CONFLICT", 422, "allergen conflict")
    # wholesale approval (priority 17)
    if o["wholesale_account_id"]:
        acct = wholesale.get(o["wholesale_account_id"])
        if acct is None or acct["status"] != "APPROVED":
            raise ApiError("ERR_WHOLESALE_NOT_APPROVED", 409, "wholesale account not approved")
    # bulk-volume availability + FEFO selection (priority 18)
    pending = {}
    plan = []  # (line_index, fusti, volume)
    for idx, l in enumerate(o["lines"]):
        if l["line_type"] != "REFILL":
            continue
        vol = l["volume_ml"]
        candidates = []
        for f in fusti.values():
            if f["product_id"] != l["product_id"]:
                continue
            if f["status"] not in {"IN_SERVICE", "LOW"}:
                continue
            if is_past_best_by(f):
                continue
            avail = f["current_volume_ml"] - f["reserved_volume_ml"] - pending.get(f["id"], 0)
            if avail >= vol:
                candidates.append(f)
        if not candidates:
            raise ApiError("ERR_INSUFFICIENT_VOLUME", 409, "insufficient volume")
        candidates.sort(key=lambda f: (f["best_by_date"], f["created_at"], f["_seq"]))
        chosen = candidates[0]
        pending[chosen["id"]] = pending.get(chosen["id"], 0) + vol
        plan.append((idx, chosen, vol))
    # commit
    applied = 0
    if o["use_wallet_credit"]:
        applied = min(member["wallet_credit_cents"], o["provisional_total_cents"])
    member["wallet_credit_cents"] -= applied
    if applied:
        touch(member)
    o["wallet_credit_applied_cents"] = applied
    o["amount_charged_cents"] = o["provisional_total_cents"] - applied
    touched_fusti = set()
    for idx, chosen, vol in plan:
        r = base_light()
        r.update({"order_id": o["id"], "fusti_id": chosen["id"], "volume_ml": vol, "status": "HELD"})
        reservations[r["id"]] = r
        o["line_reservations"][idx] = r["id"]
        chosen["reserved_volume_ml"] += vol
        touched_fusti.add(chosen["id"])
    for fid in touched_fusti:
        touch(fusti[fid])
    o["payment_status"] = "PAID"
    o["fulfillment_status"] = "RESERVED"
    touch(o)
    return ok(s_order(o), 200)


def compute_final_subtotal(o):
    subtotal = 0
    for idx, l in enumerate(o["lines"]):
        lt = l["line_type"]
        p = products[l["product_id"]]
        if lt == "UNIT":
            subtotal += p["unit_price_cents"] * l["quantity"]
        elif lt == "BUNDLE":
            subtotal += bundle_price(p)
        else:  # REFILL
            res_id = o["line_reservations"].get(idx)
            marked_down = False
            if res_id is not None:
                res = reservations.get(res_id)
                if res is not None:
                    f = fusti.get(res["fusti_id"])
                    if f is not None:
                        _, sensory = freshness_scores(f)
                        if sensory < FRESHNESS_MARKDOWN_THRESHOLD:
                            marked_down = True
            base = D(p["price_per_ml_cents"]) * D(l["volume_ml"])
            if marked_down:
                base = base * (D(1) - FRESHNESS_MARKDOWN_PCT)
            subtotal += rhu_cents(base)
    return subtotal


@app.post("/api/orders/<oid>/fulfill")
def fulfill_order(oid):
    uid, role = require_auth()
    require_role(role, {"ShopStaff"})
    o = get_or_404(orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    b = body()
    check_order_version(o, b)
    # gather reservation fusti
    res_list = []
    for idx, l in enumerate(o["lines"]):
        if l["line_type"] == "REFILL":
            res_id = o["line_reservations"].get(idx)
            res = reservations.get(res_id) if res_id else None
            if res is not None:
                res_list.append(res)
    # past-best-by guard (priority 12)
    for res in res_list:
        f = fusti.get(res["fusti_id"])
        if f is not None and is_past_best_by(f):
            raise ApiError("ERR_FUSTI_EXPIRED", 422, "fusti past best by")
    # vessel-posture guard (priority 13)
    for res in res_list:
        f = fusti.get(res["fusti_id"])
        if f is None or f["status"] not in {"IN_SERVICE", "LOW"}:
            raise ApiError("ERR_FUSTI_QUARANTINED", 409, "fusti not available")

    member = members[o["member_id"]]
    # final pricing (uses pre-commit sensory scores)
    final_subtotal = compute_final_subtotal(o)
    tier_pct = tier_pct_for(o)
    _, _, _, final_total = settle(final_subtotal, tier_pct)
    o["final_subtotal_cents"] = final_subtotal
    o["final_total_cents"] = final_total
    # reconcile wallet
    if o["provisional_total_cents"] > final_total:
        delta = o["provisional_total_cents"] - final_total
        member["wallet_credit_cents"] += delta
        o["amount_refunded_cents"] += delta
        touch(member)
    # commit reservations / draw volume
    before_status = {}
    touched_fusti = []
    for res in res_list:
        f = fusti.get(res["fusti_id"])
        if f is None:
            continue
        if f["id"] not in before_status:
            before_status[f["id"]] = f["status"]
            touched_fusti.append(f["id"])
        res["status"] = "COMMITTED"
        f["current_volume_ml"] -= res["volume_ml"]
        f["reserved_volume_ml"] -= res["volume_ml"]
        if f["first_draw_at"] is None:
            f["first_draw_at"] = now()
    # reorder cascade per affected fusti
    for fid in touched_fusti:
        f = fusti[fid]
        before = before_status[fid]
        cur = f["current_volume_ml"]
        new = before
        if cur == 0 and before in {"IN_SERVICE", "LOW"}:
            new = "EMPTY"
        elif 0 < cur <= f["reorder_point_ml"] and before == "IN_SERVICE":
            new = "LOW"
        if new != before:
            f["status"] = new
            if new in {"LOW", "EMPTY"}:
                ro = base_full()
                ro.update({
                    "fusti_id": f["id"], "product_id": f["product_id"],
                    "requested_volume_ml": f["capacity_ml"] - f["current_volume_ml"],
                    "received_harvest_date": None, "status": "REQUESTED",
                })
                replenishments[ro["id"]] = ro
        touch(f)
    # loyalty accrual
    points = (final_total // 100) * POINTS_PER_DOLLAR
    member["loyalty_points"] += points
    touch(member)
    o["fulfillment_status"] = "FULFILLED"
    touch(o)
    return ok(s_order(o), 200)


@app.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff"})
    o = get_or_404(orders, oid, "ERR_ORDER_NOT_FOUND")
    if role == "Customer" and o["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    ps, fs = o["payment_status"], o["fulfillment_status"]
    # resolve transition by current state
    if fs == "PENDING" and ps == "UNPAID":
        actor = "Customer"
        variant = "pending"
    elif fs == "RESERVED" and ps == "PAID":
        actor = "Customer"
        variant = "reserved"
    elif fs == "FULFILLED" and ps == "PAID":
        actor = "ShopStaff"
        variant = "return"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    if role != actor:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this cancellation")
    b = body()
    check_order_version(o, b)
    member = members[o["member_id"]]
    if variant == "pending":
        o["fulfillment_status"] = "CANCELLED"
    elif variant == "reserved":
        touched = set()
        for r in reservations.values():
            if r["order_id"] == o["id"] and r["status"] == "HELD":
                r["status"] = "RELEASED"
                f = fusti.get(r["fusti_id"])
                if f is not None:
                    f["reserved_volume_ml"] -= r["volume_ml"]
                    touched.add(f["id"])
        for fid in touched:
            touch(fusti[fid])
        member["wallet_credit_cents"] += o["wallet_credit_applied_cents"]
        if o["wallet_credit_applied_cents"]:
            touch(member)
        o["amount_refunded_cents"] = o["provisional_total_cents"]
        o["payment_status"] = "REFUNDED"
        o["fulfillment_status"] = "CANCELLED"
    else:  # return
        touched = set()
        for r in reservations.values():
            if r["order_id"] == o["id"] and r["status"] == "COMMITTED":
                f = fusti.get(r["fusti_id"])
                if f is not None:
                    f["current_volume_ml"] += r["volume_ml"]
                    touched.add(f["id"])
        for fid in touched:
            touch(fusti[fid])
        member["wallet_credit_cents"] += o["final_total_cents"]
        points = (o["final_total_cents"] // 100) * POINTS_PER_DOLLAR
        member["loyalty_points"] = max(0, member["loyalty_points"] - points)
        touch(member)
        o["amount_refunded_cents"] = o["final_total_cents"]
        o["payment_status"] = "REFUNDED"
        o["fulfillment_status"] = "CANCELLED"
    touch(o)
    return ok(s_order(o), 200)


# ---- Subscriptions ----
@app.post("/api/subscriptions")
def create_subscription():
    uid, role = require_auth()
    require_role(role, {"Customer"})
    member = get_member(uid)
    b = body()
    pid = b.get("product_id")
    if not isinstance(pid, str) or not pid:
        raise ApiError("ERR_VALIDATION", 422, "product_id required")
    p = get_product(pid)
    # OCC on member version (priority 7)
    ev = b.get("expected_member_version")
    if ev is None:
        raise ApiError("ERR_VALIDATION", 422, "expected_member_version required")
    if ev != member["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale version")
    cadence = b.get("cadence_days")
    if not isinstance(cadence, int) or isinstance(cadence, bool) or cadence < 1:
        raise ApiError("ERR_VALIDATION", 422, "cadence_days must be >= 1")
    qty = b.get("quantity", 1)
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
        raise ApiError("ERR_VALIDATION", 422, "quantity must be >= 1")
    vol = b.get("volume_ml")
    if vol is not None and (not isinstance(vol, int) or isinstance(vol, bool) or vol < 1):
        raise ApiError("ERR_VALIDATION", 422, "volume_ml must be >= 1")
    # supersede prior ACTIVE subscription for same product
    for sub in subscriptions.values():
        if sub["member_id"] == uid and sub["product_id"] == pid and sub["status"] == "ACTIVE":
            sub["status"] = "CANCELLED"
            touch(sub)
    sub = base_full()
    sub.update({
        "member_id": uid, "product_id": pid, "quantity": qty, "volume_ml": vol,
        "cadence_days": cadence, "status": "ACTIVE",
        "next_renewal_date": now() + timedelta(days=cadence), "renewals_count": 0,
        "last_order_id": None,
    })
    subscriptions[sub["id"]] = sub
    touch(member)
    return ok(s_subscription(sub), 201)


@app.get("/api/subscriptions/<sid>")
def get_subscription(sid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "PlatformAdmin"})
    sub = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if role == "Customer" and sub["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    return ok(s_subscription(sub), 200)


@app.get("/api/subscriptions")
def list_subscriptions():
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "PlatformAdmin"})
    items = list(subscriptions.values())
    mid = request.args.get("member_id")
    pid = request.args.get("product_id")
    loid = request.args.get("last_order_id")
    st = request.args.get("status")
    if mid:
        items = [s for s in items if s["member_id"] == mid]
    if pid:
        items = [s for s in items if s["product_id"] == pid]
    if loid:
        items = [s for s in items if s["last_order_id"] == loid]
    if st:
        items = [s for s in items if s["status"] == st]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_subscription(s) for s in page], limit, offset, total)


def sub_line(sub):
    p = products[sub["product_id"]]
    pt = p["product_type"]
    if pt in BULK_TYPES:
        return {"line_type": "REFILL", "product_id": sub["product_id"],
                "quantity": sub["quantity"], "volume_ml": sub["volume_ml"]}
    if pt in {"GIFT_SET", "BLEND"}:
        return {"line_type": "BUNDLE", "product_id": sub["product_id"],
                "quantity": sub["quantity"], "volume_ml": None}
    return {"line_type": "UNIT", "product_id": sub["product_id"],
            "quantity": sub["quantity"], "volume_ml": None}


@app.post("/api/subscriptions/<sid>/transition")
def transition_subscription(sid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff"})
    sub = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    b = body()
    action = b.get("action")
    if action not in {"PAUSE", "RESUME", "CANCEL", "RENEW"}:
        raise ApiError("ERR_VALIDATION", 422, "invalid action")
    if action in {"PAUSE", "RESUME", "CANCEL"}:
        if role != "Customer":
            raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")
        if sub["member_id"] != uid:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
        if action == "PAUSE":
            if sub["status"] != "ACTIVE":
                raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
            sub["status"] = "PAUSED"
        elif action == "RESUME":
            if sub["status"] != "PAUSED":
                raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
            sub["status"] = "ACTIVE"
        else:  # CANCEL
            if sub["status"] not in {"ACTIVE", "PAUSED"}:
                raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
            sub["status"] = "CANCELLED"
        touch(sub)
    else:  # RENEW
        if role != "ShopStaff":
            raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")
        if sub["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
        if now() < sub["next_renewal_date"]:
            raise ApiError("ERR_INVALID_STATE", 409, "renewal not yet due")
        line = sub_line(sub)
        o = create_order_record(sub["member_id"], [line], None, False)
        sub["last_order_id"] = o["id"]
        sub["next_renewal_date"] = sub["next_renewal_date"] + timedelta(days=sub["cadence_days"])
        sub["renewals_count"] += 1
        touch(sub)
    return ok(s_subscription(sub), 200)


# ---- Tasting bar ----
@app.post("/api/tasting-stations")
def create_station():
    uid, role = require_auth()
    require_role(role, {"InventoryManager", "PlatformAdmin"})
    b = body()
    name = require_str(b, "name")
    st = base_full()
    st.update({"name": name})
    stations[st["id"]] = st
    return ok(s_station(st), 201)


@app.post("/api/tasting-sessions")
def book_session():
    uid, role = require_auth()
    require_role(role, {"Customer"})
    b = body()
    sid = b.get("station_id")
    if not isinstance(sid, str) or not sid:
        raise ApiError("ERR_VALIDATION", 422, "station_id required")
    station = get_or_404(stations, sid, "ERR_STATION_NOT_FOUND")
    get_member(uid)
    # structural validation (priority 8)
    start_at = parse_dt(b.get("start_at"))
    end_at = parse_dt(b.get("end_at"))
    if end_at <= start_at:
        raise ApiError("ERR_VALIDATION", 422, "end_at must be after start_at")
    party = b.get("party_size", 1)
    if not isinstance(party, int) or isinstance(party, bool) or party < 1:
        raise ApiError("ERR_VALIDATION", 422, "party_size must be >= 1")
    # station buffer (priority 14): gap strictly < 15 min
    buffer_delta = timedelta(minutes=BUFFER_MINUTES)
    for se in sessions.values():
        if se["station_id"] != sid or se["status"] == "CANCELLED":
            continue
        if start_at < se["end_at"] and se["start_at"] < end_at:
            gap = timedelta(0)  # overlap
        elif start_at >= se["end_at"]:
            gap = start_at - se["end_at"]
        else:
            gap = se["start_at"] - end_at
        if gap < buffer_delta:
            raise ApiError("ERR_STATION_UNAVAILABLE", 409, "station unavailable")
    # member double-book (priority 15): half-open overlap same member any station
    for se in sessions.values():
        if se["member_id"] != uid or se["status"] == "CANCELLED":
            continue
        if start_at < se["end_at"] and se["start_at"] < end_at:
            raise ApiError("ERR_MEMBER_DOUBLE_BOOKED", 409, "member double booked")
    # future-start guard (priority 16)
    if start_at <= now():
        raise ApiError("ERR_SESSION_IN_PAST", 422, "session must start in the future")
    se = base_full()
    se.update({
        "station_id": sid, "member_id": uid, "start_at": start_at, "end_at": end_at,
        "party_size": party, "status": "BOOKED",
    })
    sessions[se["id"]] = se
    return ok(s_session(se), 201)


@app.get("/api/tasting-sessions/<seid>")
def get_session(seid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff", "PlatformAdmin"})
    se = get_or_404(sessions, seid, "ERR_SESSION_NOT_FOUND")
    if role == "Customer" and se["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
    return ok(s_session(se), 200)


@app.get("/api/tasting-sessions")
def list_sessions():
    uid, role = require_auth()
    require_role(role, {"ShopStaff", "PlatformAdmin"})
    items = list(sessions.values())
    sf = request.args.get("station_id")
    mf = request.args.get("member_id")
    st = request.args.get("status")
    if sf:
        items = [s for s in items if s["station_id"] == sf]
    if mf:
        items = [s for s in items if s["member_id"] == mf]
    if st:
        items = [s for s in items if s["status"] == st]
    items.sort(key=sort_key)
    page, limit, offset, total = paginate(items)
    return ok_list([s_session(s) for s in page], limit, offset, total)


@app.post("/api/tasting-sessions/<seid>/transition")
def transition_session(seid):
    uid, role = require_auth()
    require_role(role, {"Customer", "ShopStaff"})
    se = get_or_404(sessions, seid, "ERR_SESSION_NOT_FOUND")
    b = body()
    action = b.get("action")
    if action not in {"CHECK_IN", "COMPLETE", "CANCEL", "NO_SHOW"}:
        raise ApiError("ERR_VALIDATION", 422, "invalid action")
    if action == "CANCEL":
        if role != "Customer":
            raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")
        if se["member_id"] != uid:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "not owner")
        if se["status"] != "BOOKED":
            raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
        se["status"] = "CANCELLED"
    else:
        if role != "ShopStaff":
            raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")
        if action == "CHECK_IN":
            if se["status"] != "BOOKED":
                raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
            se["status"] = "CHECKED_IN"
        elif action == "COMPLETE":
            if se["status"] != "CHECKED_IN":
                raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
            se["status"] = "COMPLETED"
        else:  # NO_SHOW
            if se["status"] != "BOOKED":
                raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
            if now() < se["start_at"]:
                raise ApiError("ERR_INVALID_STATE", 409, "not yet started")
            se["status"] = "NO_SHOW"
    touch(se)
    return ok(s_session(se), 200)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    limit = parse_int(request.args.get("limit"), 10)
    offset = parse_int(request.args.get("offset"), 0)
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
