"""
Candle, Soap & Bath DTC commerce API — Python + Flask reference implementation.

All state is in-memory (module-level dicts) and wiped on every process boot.
Nothing is seeded at startup; tests build all state through the API surface.

Every behavior traces to a verbatim sentence in workspace/PRD.md.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (wiped every boot). No seeding, ever.
# ---------------------------------------------------------------------------
DB = {
    "products": {},
    "skus": {},
    "batches": {},
    "drops": {},
    "bundles": {},
    "customers": {},
    "orders": {},
    "order_lines": {},
    "returns": {},
    "subscriptions": {},
}

# Logical clock (PRD §2.8): startup default is 2026-07-01T00:00:00Z and never
# falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


ROLES = {"Customer", "MerchOps", "PlatformAdmin"}

# Pricing / loyalty / inventory constants (SCAFFOLD §1.3, PRD §3.7/§2.5).
BULK_TIER1_MIN = 50
BULK_TIER2_MIN = 100
BULK_TIER1_PCT = Decimal("0.10")
BULK_TIER2_PCT = Decimal("0.20")
SILVER_PCT = Decimal("0.05")
GOLD_PCT = Decimal("0.10")
MAX_DISCOUNT_PCT = Decimal("0.25")
FREE_SHIP_THRESHOLD_CENTS = 5000
SHIPPING_FLAT_CENTS = 800
BULK_MIN_QUANTITY = 50
CENTS_PER_POINT = 100
SILVER_MIN = 500
GOLD_MIN = 2000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_SKU_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_DROP_NOT_FOUND": 404,
    "ERR_BUNDLE_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_ORDER_NOT_EDITABLE": 409,
    "ERR_ORDER_NOT_DELIVERED": 409,
    "ERR_SUBSCRIPTION_NOT_DUE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SAFETY_LABEL_REQUIRED": 409,
    "ERR_DROP_NOT_LIVE": 409,
    "ERR_CUSTOMER_SUSPENDED": 409,
    "ERR_DROP_WINDOW_OVERLAP": 409,
    "ERR_BATCH_LINE_CONFLICT": 409,
    "ERR_EMPTY_BUNDLE": 422,
    "ERR_EMPTY_ORDER": 422,
    "ERR_NO_ELIGIBLE_BATCH": 422,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_BULK_MIN_NOT_MET": 422,
    "ERR_VALIDATION": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = _HTTP[error_id]
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        raise ApiError("ERR_VALIDATION", "invalid datetime format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return CLOCK["now"]


def clock_iso():
    return iso_ms(CLOCK["now"])


# ---------------------------------------------------------------------------
# Entity common-field + mutation helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = clock_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """A mutation refreshes updated_at (logical clock) and bumps version by one."""
    entity["updated_at"] = clock_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta_base():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta_base(), "response_type": "object", "data": data}), status


def ok_list(items, pag):
    meta = _meta_base()
    meta.update(pag)
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http


# ---------------------------------------------------------------------------
# Auth / RBAC / ownership
# ---------------------------------------------------------------------------
def get_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid auth headers")
    return role, uid


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this endpoint")


def require_owner(role, uid, owner_customer_id):
    # Ownership applies only to the Customer role acting on their own resources.
    if role == "Customer" and uid != owner_customer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "customer does not own this resource")


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "body must be a JSON object")
    return body


def v_str(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", f"{key} must be a string")
    return val


def v_int(body, key, positive=False, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    if positive and val <= 0:
        raise ApiError("ERR_VALIDATION", f"{key} must be strictly positive")
    return val


def v_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return default
    val = body[key]
    if val not in allowed:
        raise ApiError("ERR_VALIDATION", f"{key} must be one of {sorted(allowed)}")
    return val


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def find(store_key, ident, err_id):
    ent = DB[store_key].get(ident)
    if ent is None:
        raise ApiError(err_id, f"{ident} not found")
    return ent


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def _page_int(raw, default, minimum, maximum):
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "pagination parameter must be an integer")
    if val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val


def list_response(items):
    """items: iterable of raw entities. Sort by created_at ASC (stable insertion
    tie-break) then paginate with limit/offset (PRD §2.3)."""
    limit = _page_int(request.args.get("limit"), 10, 1, 100)
    offset = _page_int(request.args.get("offset"), 0, 0, None)
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


# ---------------------------------------------------------------------------
# Serializers (control exactly which fields are exposed)
# ---------------------------------------------------------------------------
_COMMON = ("id", "created_at", "updated_at", "version")


def _pick(ent, extra):
    out = {k: ent[k] for k in _COMMON}
    for k in extra:
        out[k] = ent[k]
    return out


def ser_product(p):
    return _pick(p, ("product_type", "collection_name", "scent_family", "title"))


def ser_sku(s):
    return _pick(s, ("product_id", "size", "scent", "list_price_cents", "requires_safety_label"))


def ser_batch(b):
    return _pick(b, (
        "sku_id", "quantity_produced", "quantity_reserved", "quantity_shipped",
        "quantity_recalled", "quantity_available", "line_code", "cure_starts_at",
        "cure_ends_at", "is_safety_labeled", "status",
    ))


def drop_status(d):
    now = clock_now()
    if now < d["_starts"]:
        return "SCHEDULED"
    if now < d["_ends"]:
        return "LIVE"
    return "ENDED"


def ser_drop(d):
    out = _pick(d, ("season", "title", "starts_at", "ends_at", "listings"))
    out["status"] = drop_status(d)
    return out


def ser_bundle(b):
    return _pick(b, ("title", "items", "bundle_price_cents", "status"))


def loyalty_tier(balance):
    if balance < SILVER_MIN:
        return "BRONZE"
    if balance < GOLD_MIN:
        return "SILVER"
    return "GOLD"


def ser_customer(c):
    out = _pick(c, ("email", "full_name", "loyalty_points_balance", "status"))
    out["loyalty_tier"] = loyalty_tier(c["loyalty_points_balance"])
    return out


def ser_order(o):
    return _pick(o, (
        "customer_id", "order_type", "gift_message", "recipient_name",
        "payment_status", "fulfillment_status", "total_quantity",
        "provisional_total_cents", "discount_cents", "shipping_fee_cents",
        "final_total_cents", "provisional_points", "awarded_points",
    ))


def ser_order_line(l):
    return _pick(l, (
        "order_id", "sku_id", "batch_id", "quantity", "unit_price_cents",
        "line_subtotal_cents", "status",
    ))


def ser_return(r):
    return _pick(r, ("order_id", "reason", "refund_amount_cents", "revoked_points", "status"))


def ser_subscription(s):
    out = _pick(s, ("customer_id", "sku_id", "quantity", "cadence_days", "renewal_count", "status"))
    out["next_renewal_at"] = iso_ms(s["_next_renewal"])
    return out


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def order_lines_of(order_id):
    return [l for l in DB["order_lines"].values() if l["order_id"] == order_id]


def recompute_order_totals(order):
    lines = [l for l in order_lines_of(order["id"]) if l["status"] in ("RESERVED", "SHIPPED")]
    order["total_quantity"] = sum(l["quantity"] for l in lines)
    order["provisional_total_cents"] = sum(l["line_subtotal_cents"] for l in lines)


def resolve_unit_price(sku):
    """PRD §3.6: LIVE exclusive-drop price overrides, else sku.list_price_cents."""
    for d in DB["drops"].values():
        if drop_status(d) != "LIVE":
            continue
        for listing in d["listings"]:
            if listing["sku_id"] == sku["id"] and listing.get("is_exclusive"):
                return listing["drop_price_cents"]
    return sku["list_price_cents"]


def exclusive_drops_for_sku(sku_id):
    out = []
    for d in DB["drops"].values():
        for listing in d["listings"]:
            if listing["sku_id"] == sku_id and listing.get("is_exclusive"):
                out.append(d)
                break
    return out


def apply_depletion(batch):
    if batch["status"] == "RELEASED" and batch["quantity_available"] == 0:
        batch["status"] = "DEPLETED"


def apply_replenish(batch):
    if batch["status"] == "DEPLETED" and batch["quantity_available"] > 0:
        batch["status"] = "RELEASED"


# ---------------------------------------------------------------------------
# Endpoint: logical clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, uid = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    to_iso = v_str(body, "to_iso8601")
    CLOCK["now"] = parse_dt(to_iso)
    return ok({}, 200)


# ---------------------------------------------------------------------------
# Products & Skus
# ---------------------------------------------------------------------------
@app.route("/products", methods=["POST"])
def create_product():
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    body = get_body()
    product_type = v_enum(body, "product_type", {"CANDLE", "WAX_MELT", "SOAP", "BATH_BOMB"})
    collection_name = v_str(body, "collection_name")
    scent_family = v_str(body, "scent_family")
    title = v_str(body, "title")
    p = new_common()
    p.update({
        "product_type": product_type,
        "collection_name": collection_name,
        "scent_family": scent_family,
        "title": title,
    })
    DB["products"][p["id"]] = p
    return ok(ser_product(p), 201)


@app.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    p = find("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    return ok(ser_product(p), 200)


@app.route("/products/<product_id>/skus", methods=["POST"])
def create_sku(product_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    p = find("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    body = get_body()
    size = v_enum(body, "size", {"SMALL", "MEDIUM", "LARGE"})
    scent = v_str(body, "scent")
    list_price_cents = v_int(body, "list_price_cents", positive=True)
    s = new_common()
    s.update({
        "product_id": product_id,
        "size": size,
        "scent": scent,
        "list_price_cents": list_price_cents,
        # computed from parent product type; any client value ignored (PRD §3.1)
        "requires_safety_label": p["product_type"] in ("CANDLE", "WAX_MELT"),
    })
    DB["skus"][s["id"]] = s
    return ok(ser_sku(s), 201)


@app.route("/skus/<sku_id>", methods=["GET"])
def get_sku(sku_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    s = find("skus", sku_id, "ERR_SKU_NOT_FOUND")
    return ok(ser_sku(s), 200)


@app.route("/skus", methods=["GET"])
def list_skus():
    role, uid = get_auth()
    require_role(role, ROLES)
    product_id = request.args.get("product_id")
    items = DB["skus"].values()
    if product_id is not None:
        items = [s for s in items if s["product_id"] == product_id]
    page, pag = list_response(items)
    return ok_list([ser_sku(s) for s in page], pag)


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------
def _windows_overlap_closed(s1, e1, s2, e2):
    # Closed intervals: touching at an endpoint counts as overlap.
    return s1 <= e2 and s2 <= e1


@app.route("/skus/<sku_id>/batches", methods=["POST"])
def create_batch(sku_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    sku = find("skus", sku_id, "ERR_SKU_NOT_FOUND")
    body = get_body()
    quantity_produced = v_int(body, "quantity_produced", positive=True)
    line_code = v_str(body, "line_code")
    cure_starts_raw = v_str(body, "cure_starts_at")
    cure_ends_raw = v_str(body, "cure_ends_at")
    cs = parse_dt(cure_starts_raw)
    ce = parse_dt(cure_ends_raw)
    if not (ce > cs):
        raise ApiError("ERR_VALIDATION", "cure_ends_at must be strictly after cure_starts_at")
    # Cure-window non-overlap on the same production line (closed interval).
    for other in DB["batches"].values():
        if other["line_code"] == line_code:
            if _windows_overlap_closed(cs, ce, other["_cure_s"], other["_cure_e"]):
                raise ApiError("ERR_BATCH_LINE_CONFLICT", "cure window overlaps another batch on the same line")
    b = new_common()
    b.update({
        "sku_id": sku_id,
        "quantity_produced": quantity_produced,
        "quantity_reserved": 0,
        "quantity_shipped": 0,
        "quantity_recalled": 0,
        "quantity_available": quantity_produced,
        "line_code": line_code,
        "cure_starts_at": cure_starts_raw,
        "cure_ends_at": cure_ends_raw,
        "_cure_s": cs,
        "_cure_e": ce,
        "is_safety_labeled": False,
        "status": "CREATED",
    })
    DB["batches"][b["id"]] = b
    return ok(ser_batch(b), 201)


@app.route("/batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    b = find("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    return ok(ser_batch(b), 200)


@app.route("/batches", methods=["GET"])
def list_batches():
    role, uid = get_auth()
    require_role(role, ROLES)
    sku_id = request.args.get("sku_id")
    items = DB["batches"].values()
    if sku_id is not None:
        items = [b for b in items if b["sku_id"] == sku_id]
    page, pag = list_response(items)
    return ok_list([ser_batch(b) for b in page], pag)


@app.route("/batches/<batch_id>/label", methods=["POST"])
def label_batch(batch_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    b = find("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    if b["status"] != "CREATED":
        raise ApiError("ERR_INVALID_STATE", "batch must be CREATED to label")
    b["is_safety_labeled"] = True
    b["status"] = "LABELED"
    touch(b)
    return ok(ser_batch(b), 200)


@app.route("/batches/<batch_id>/release", methods=["POST"])
def release_batch(batch_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    b = find("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    if b["status"] not in ("CREATED", "LABELED"):
        raise ApiError("ERR_INVALID_STATE", "batch must be CREATED or LABELED to release")
    b["status"] = "RELEASED"
    touch(b)
    return ok(ser_batch(b), 200)


@app.route("/batches/<batch_id>/recall", methods=["POST"])
def recall_batch(batch_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    b = find("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    if b["status"] not in ("RELEASED", "DEPLETED"):
        raise ApiError("ERR_INVALID_STATE", "batch must be RELEASED or DEPLETED to recall")
    do_recall(b)
    return ok(ser_batch(b), 200)


def do_recall(batch):
    affected = {}  # order_id -> list of voided lines
    for line in DB["order_lines"].values():
        if line["batch_id"] != batch["id"]:
            continue
        if line["status"] not in ("RESERVED", "SHIPPED"):
            continue
        order = DB["orders"][line["order_id"]]
        if order["fulfillment_status"] in ("CANCELLED", "RETURNED"):
            continue
        # Void the line and release its held units from the batch.
        if line["status"] == "RESERVED":
            batch["quantity_reserved"] -= line["quantity"]
        else:  # SHIPPED
            batch["quantity_shipped"] -= line["quantity"]
        line["status"] = "VOIDED_RECALL"
        touch(line)
        affected.setdefault(order["id"], []).append(line)

    # Batch becomes terminal RECALLED with all produced units recalled.
    batch["quantity_recalled"] = batch["quantity_produced"]
    batch["quantity_available"] = 0
    batch["status"] = "RECALLED"
    touch(batch)

    for oid, voided in affected.items():
        order = DB["orders"][oid]
        prev_ful = order["fulfillment_status"]
        # Reverse posted loyalty for voided lines if the order had posted points.
        reversed_pts = sum(l["line_subtotal_cents"] // CENTS_PER_POINT for l in voided)
        if prev_ful in ("ALLOCATED", "DELIVERED") and reversed_pts:
            cust = DB["customers"][order["customer_id"]]
            cust["loyalty_points_balance"] -= reversed_pts
            touch(cust)
        # If every line of the order is now voided, cancel (and refund if paid).
        all_lines = order_lines_of(oid)
        if all_lines and all(l["status"] == "VOIDED_RECALL" for l in all_lines):
            order["fulfillment_status"] = "CANCELLED"
            if order["payment_status"] == "PAID":
                order["payment_status"] = "REFUNDED"
        recompute_order_totals(order)
        touch(order)


# ---------------------------------------------------------------------------
# Drops
# ---------------------------------------------------------------------------
@app.route("/drops", methods=["POST"])
def create_drop():
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    body = get_body()
    season = v_str(body, "season")
    title = v_str(body, "title")
    starts_raw = v_str(body, "starts_at")
    ends_raw = v_str(body, "ends_at")
    ss = parse_dt(starts_raw)
    ee = parse_dt(ends_raw)
    if not (ee > ss):
        raise ApiError("ERR_VALIDATION", "ends_at must be strictly after starts_at")
    listings = body.get("listings")
    if listings is None:
        listings = []
    if not isinstance(listings, list):
        raise ApiError("ERR_VALIDATION", "listings must be an array")
    norm_listings = []
    for item in listings:
        if not isinstance(item, dict):
            raise ApiError("ERR_VALIDATION", "each listing must be an object")
        lsku = item.get("sku_id")
        if not isinstance(lsku, str):
            raise ApiError("ERR_VALIDATION", "listing.sku_id must be a string")
        dp = item.get("drop_price_cents")
        if isinstance(dp, bool) or not isinstance(dp, int) or dp <= 0:
            raise ApiError("ERR_VALIDATION", "listing.drop_price_cents must be a positive integer")
        is_excl = item.get("is_exclusive", False)
        if not isinstance(is_excl, bool):
            raise ApiError("ERR_VALIDATION", "listing.is_exclusive must be a boolean")
        # Body FK existence.
        find("skus", lsku, "ERR_SKU_NOT_FOUND")
        norm_listings.append({"sku_id": lsku, "drop_price_cents": dp, "is_exclusive": is_excl})

    # Exclusive-window non-overlap per sku vs other non-ENDED drops (half-open).
    for item in norm_listings:
        if not item["is_exclusive"]:
            continue
        for other in DB["drops"].values():
            if drop_status(other) == "ENDED":
                continue
            for ol in other["listings"]:
                if ol["sku_id"] == item["sku_id"] and ol.get("is_exclusive"):
                    # half-open [start, end): overlap iff ss < other_end and other_start < ee
                    if ss < other["_ends"] and other["_starts"] < ee:
                        raise ApiError("ERR_DROP_WINDOW_OVERLAP",
                                       "exclusive drop window overlaps another for this sku")

    d = new_common()
    d.update({
        "season": season,
        "title": title,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "_starts": ss,
        "_ends": ee,
        "listings": norm_listings,
    })
    DB["drops"][d["id"]] = d
    return ok(ser_drop(d), 201)


@app.route("/drops/<drop_id>", methods=["GET"])
def get_drop(drop_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    d = find("drops", drop_id, "ERR_DROP_NOT_FOUND")
    return ok(ser_drop(d), 200)


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------
@app.route("/bundles", methods=["POST"])
def create_bundle():
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    body = get_body()
    title = v_str(body, "title")
    bundle_price_cents = v_int(body, "bundle_price_cents", positive=True)
    items = body.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ApiError("ERR_VALIDATION", "items must be an array")
    norm_items = []
    for it in items:
        if not isinstance(it, dict):
            raise ApiError("ERR_VALIDATION", "each item must be an object")
        isku = it.get("sku_id")
        if not isinstance(isku, str):
            raise ApiError("ERR_VALIDATION", "item.sku_id must be a string")
        qty = it.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError("ERR_VALIDATION", "item.quantity must be a positive integer")
        find("skus", isku, "ERR_SKU_NOT_FOUND")
        norm_items.append({"sku_id": isku, "quantity": qty})
    b = new_common()
    b.update({
        "title": title,
        "items": norm_items,
        "bundle_price_cents": bundle_price_cents,
        "status": "DRAFT",
    })
    DB["bundles"][b["id"]] = b
    return ok(ser_bundle(b), 201)


@app.route("/bundles/<bundle_id>", methods=["GET"])
def get_bundle(bundle_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    b = find("bundles", bundle_id, "ERR_BUNDLE_NOT_FOUND")
    return ok(ser_bundle(b), 200)


@app.route("/bundles/<bundle_id>/activate", methods=["POST"])
def activate_bundle(bundle_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    b = find("bundles", bundle_id, "ERR_BUNDLE_NOT_FOUND")
    if b["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "bundle must be DRAFT to activate")
    if len(b["items"]) < 1:
        raise ApiError("ERR_EMPTY_BUNDLE", "cannot activate an empty bundle")
    b["status"] = "ACTIVE"
    touch(b)
    return ok(ser_bundle(b), 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/customers", methods=["POST"])
def create_customer():
    role, uid = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    email = v_str(body, "email")
    full_name = v_str(body, "full_name")
    # email is unique (PRD §3.5)
    for c in DB["customers"].values():
        if c["email"] == email:
            raise ApiError("ERR_VALIDATION", "email must be unique")
    c = new_common()
    c.update({
        "email": email,
        "full_name": full_name,
        "loyalty_points_balance": 0,
        "status": "ACTIVE",
    })
    DB["customers"][c["id"]] = c
    return ok(ser_customer(c), 201)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    c = find("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    return ok(ser_customer(c), 200)


@app.route("/customers/<customer_id>/suspend", methods=["POST"])
def suspend_customer(customer_id):
    role, uid = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = find("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "customer must be ACTIVE to suspend")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok(ser_customer(c), 200)


@app.route("/customers/<customer_id>/loyalty-grant", methods=["POST"])
def grant_loyalty(customer_id):
    role, uid = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = find("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    body = get_body()
    points = v_int(body, "points", positive=True)
    c["loyalty_points_balance"] += points
    touch(c)
    return ok(ser_customer(c), 200)


# ---------------------------------------------------------------------------
# Orders & OrderLines
# ---------------------------------------------------------------------------
@app.route("/customers/<customer_id>/orders", methods=["POST"])
def create_order(customer_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    # Ownership on the customer path param (direct compare) precedes existence.
    require_owner(role, uid, customer_id)
    find("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    body = get_body()
    order_type = v_enum(body, "order_type", {"RETAIL", "BULK", "GIFT"}, required=False, default="RETAIL")
    gift_message = v_str(body, "gift_message", required=False)
    recipient_name = v_str(body, "recipient_name", required=False)
    o = new_common()
    o.update({
        "customer_id": customer_id,
        "order_type": order_type,
        "gift_message": gift_message,
        "recipient_name": recipient_name,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "total_quantity": 0,
        "provisional_total_cents": 0,
        "discount_cents": 0,
        "shipping_fee_cents": 0,
        "final_total_cents": 0,
        "provisional_points": 0,
        "awarded_points": 0,
    })
    DB["orders"][o["id"]] = o
    return ok(ser_order(o), 201)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    o = find("orders", order_id, "ERR_ORDER_NOT_FOUND")
    require_owner(role, uid, o["customer_id"])
    return ok(ser_order(o), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    role, uid = get_auth()
    require_role(role, ROLES)
    customer_id = request.args.get("customer_id")
    items = DB["orders"].values()
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    page, pag = list_response(items)
    return ok_list([ser_order(o) for o in page], pag)


@app.route("/orders/<order_id>/lines", methods=["POST"])
def add_line(order_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    order = find("orders", order_id, "ERR_ORDER_NOT_FOUND")
    require_owner(role, uid, order["customer_id"])
    body = get_body()
    sku_id = v_str(body, "sku_id")
    batch_id = v_str(body, "batch_id")
    quantity = v_int(body, "quantity", positive=True)
    # Existence (priority 4) precedes state checks (priority 5).
    sku = find("skus", sku_id, "ERR_SKU_NOT_FOUND")
    batch = find("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    # State: order must be editable (PENDING), then batch must be RELEASED.
    if order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_NOT_EDITABLE", "order is not editable")
    if batch["status"] != "RELEASED":
        raise ApiError("ERR_BATCH_NOT_RELEASED", "batch is not RELEASED")
    # Safety labeling (priority 7).
    if sku["requires_safety_label"] and not batch["is_safety_labeled"]:
        raise ApiError("ERR_SAFETY_LABEL_REQUIRED", "chosen batch is not safety labeled")
    # Drop exclusivity / liveness (priority 8).
    excl = exclusive_drops_for_sku(sku_id)
    if excl:
        live = [d for d in excl if drop_status(d) == "LIVE"]
        if not live:
            raise ApiError("ERR_DROP_NOT_LIVE", "sku's exclusive drop is not LIVE")
    # Inventory sufficiency (priority 11).
    if batch["quantity_available"] < quantity:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", "insufficient batch inventory")

    unit_price = resolve_unit_price(sku)
    line = new_common()
    line.update({
        "order_id": order_id,
        "sku_id": sku_id,
        "batch_id": batch_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_subtotal_cents": unit_price * quantity,
        "status": "RESERVED",
    })
    DB["order_lines"][line["id"]] = line
    # Reserve stock.
    batch["quantity_reserved"] += quantity
    batch["quantity_available"] -= quantity
    apply_depletion(batch)
    touch(batch)
    # Reprice order + bump version (makes concurrent cart edits observable).
    recompute_order_totals(order)
    touch(order)
    return ok(ser_order_line(line), 201)


@app.route("/order-lines/<order_line_id>", methods=["GET"])
def get_order_line(order_line_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    line = find("order_lines", order_line_id, "ERR_ORDER_NOT_FOUND")
    return ok(ser_order_line(line), 200)


@app.route("/order-lines", methods=["GET"])
def list_order_lines():
    role, uid = get_auth()
    require_role(role, ROLES)
    order_id = request.args.get("order_id")
    sku_id = request.args.get("sku_id")
    batch_id = request.args.get("batch_id")
    items = list(DB["order_lines"].values())
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    if sku_id is not None:
        items = [l for l in items if l["sku_id"] == sku_id]
    if batch_id is not None:
        items = [l for l in items if l["batch_id"] == batch_id]
    page, pag = list_response(items)
    return ok_list([ser_order_line(l) for l in page], pag)


@app.route("/orders/<order_id>/checkout", methods=["POST"])
def checkout_order(order_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    order = find("orders", order_id, "ERR_ORDER_NOT_FOUND")
    require_owner(role, uid, order["customer_id"])
    # State (priority 5): PENDING + UNPAID.
    if order["fulfillment_status"] != "PENDING" or order["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE", "order is not in a checkoutable state")
    body = get_body()
    expected = v_int(body, "expected_order_version")
    # OCC (priority 6).
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", "order version has advanced")
    reserved_lines = [l for l in order_lines_of(order_id) if l["status"] == "RESERVED"]
    # Empty order (priority 10).
    if len(reserved_lines) < 1:
        raise ApiError("ERR_EMPTY_ORDER", "order has no reserved lines")
    subtotal = sum(l["line_subtotal_cents"] for l in reserved_lines)
    total_qty = sum(l["quantity"] for l in reserved_lines)
    # Bulk minimum (priority 11).
    if order["order_type"] == "BULK" and total_qty < BULK_MIN_QUANTITY:
        raise ApiError("ERR_BULK_MIN_NOT_MET", "bulk order below minimum quantity")

    customer = DB["customers"][order["customer_id"]]
    # Bulk-quantity discount rate.
    if total_qty < BULK_TIER1_MIN:
        bulk_pct = Decimal("0")
    elif total_qty < BULK_TIER2_MIN:
        bulk_pct = BULK_TIER1_PCT
    else:
        bulk_pct = BULK_TIER2_PCT
    # Loyalty discount rate (BULK forgoes loyalty discount).
    if order["order_type"] == "BULK":
        loyalty_pct = Decimal("0")
    else:
        tier = loyalty_tier(customer["loyalty_points_balance"])
        loyalty_pct = {"BRONZE": Decimal("0"), "SILVER": SILVER_PCT, "GOLD": GOLD_PCT}[tier]
    combined = min(bulk_pct + loyalty_pct, MAX_DISCOUNT_PCT)
    discount = int((Decimal(subtotal) * combined).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    discounted_subtotal = subtotal - discount
    shipping = 0 if discounted_subtotal >= FREE_SHIP_THRESHOLD_CENTS else SHIPPING_FLAT_CENTS
    final_total = discounted_subtotal + shipping
    order["discount_cents"] = discount
    order["shipping_fee_cents"] = shipping
    order["final_total_cents"] = final_total

    # Provisional loyalty: floor-per-line then sum over the reserved lines.
    provisional = sum(l["line_subtotal_cents"] // CENTS_PER_POINT for l in reserved_lines)
    order["provisional_points"] = provisional
    customer["loyalty_points_balance"] += provisional
    touch(customer)

    order["payment_status"] = "PAID"
    order["fulfillment_status"] = "ALLOCATED"
    recompute_order_totals(order)
    touch(order)
    return ok(ser_order(order), 200)


@app.route("/orders/<order_id>/fulfill", methods=["POST"])
def fulfill_order(order_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    order = find("orders", order_id, "ERR_ORDER_NOT_FOUND")
    if order["fulfillment_status"] != "ALLOCATED" or order["payment_status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "order is not ALLOCATED/PAID")
    for line in order_lines_of(order_id):
        if line["status"] != "RESERVED":
            continue
        batch = DB["batches"][line["batch_id"]]
        batch["quantity_reserved"] -= line["quantity"]
        batch["quantity_shipped"] += line["quantity"]
        touch(batch)
        line["status"] = "SHIPPED"
        touch(line)
    awarded = sum(
        l["line_subtotal_cents"] // CENTS_PER_POINT
        for l in order_lines_of(order_id) if l["status"] == "SHIPPED"
    )
    order["awarded_points"] = awarded
    order["fulfillment_status"] = "DELIVERED"
    recompute_order_totals(order)
    touch(order)
    return ok(ser_order(order), 200)


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "MerchOps", "PlatformAdmin"})
    order = find("orders", order_id, "ERR_ORDER_NOT_FOUND")
    require_owner(role, uid, order["customer_id"])
    if order["fulfillment_status"] not in ("PENDING", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE", "order is not cancellable")
    for line in order_lines_of(order_id):
        if line["status"] != "RESERVED":
            continue
        batch = DB["batches"][line["batch_id"]]
        batch["quantity_reserved"] -= line["quantity"]
        batch["quantity_available"] += line["quantity"]
        apply_replenish(batch)
        touch(batch)
        line["status"] = "RELEASED"
        touch(line)
    if order["payment_status"] == "PAID":
        order["payment_status"] = "REFUNDED"
        customer = DB["customers"][order["customer_id"]]
        customer["loyalty_points_balance"] -= order["provisional_points"]
        touch(customer)
    order["fulfillment_status"] = "CANCELLED"
    recompute_order_totals(order)
    touch(order)
    return ok(ser_order(order), 200)


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------
@app.route("/orders/<order_id>/returns", methods=["POST"])
def request_return(order_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    order = find("orders", order_id, "ERR_ORDER_NOT_FOUND")
    require_owner(role, uid, order["customer_id"])
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED", "order is not DELIVERED")
    body = get_body()
    reason = v_str(body, "reason")
    r = new_common()
    r.update({
        "order_id": order_id,
        "reason": reason,
        "refund_amount_cents": 0,
        "revoked_points": 0,
        "status": "REQUESTED",
    })
    DB["returns"][r["id"]] = r
    return ok(ser_return(r), 201)


@app.route("/returns/<return_id>", methods=["GET"])
def get_return(return_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    r = find("returns", return_id, "ERR_RETURN_NOT_FOUND")
    order = DB["orders"][r["order_id"]]
    require_owner(role, uid, order["customer_id"])
    return ok(ser_return(r), 200)


@app.route("/returns", methods=["GET"])
def list_returns():
    role, uid = get_auth()
    require_role(role, ROLES)
    order_id = request.args.get("order_id")
    items = DB["returns"].values()
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    page, pag = list_response(items)
    return ok_list([ser_return(r) for r in page], pag)


@app.route("/returns/<return_id>/approve", methods=["POST"])
def approve_return(return_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    r = find("returns", return_id, "ERR_RETURN_NOT_FOUND")
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "return is not REQUESTED")
    order = DB["orders"][r["order_id"]]
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED", "order is not DELIVERED")
    r["status"] = "APPROVED"
    touch(r)
    return ok(ser_return(r), 200)


@app.route("/returns/<return_id>/reject", methods=["POST"])
def reject_return(return_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    r = find("returns", return_id, "ERR_RETURN_NOT_FOUND")
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "return is not REQUESTED")
    r["status"] = "REJECTED"
    touch(r)
    return ok(ser_return(r), 200)


@app.route("/returns/<return_id>/settle", methods=["POST"])
def settle_return(return_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    r = find("returns", return_id, "ERR_RETURN_NOT_FOUND")
    if r["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "return is not APPROVED")
    order = DB["orders"][r["order_id"]]
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED", "order is not DELIVERED")
    for line in order_lines_of(order["id"]):
        if line["status"] != "SHIPPED":
            continue
        batch = DB["batches"][line["batch_id"]]
        batch["quantity_shipped"] -= line["quantity"]
        batch["quantity_available"] += line["quantity"]
        apply_replenish(batch)
        touch(batch)
        line["status"] = "RETURNED"
        touch(line)
    customer = DB["customers"][order["customer_id"]]
    customer["loyalty_points_balance"] -= order["awarded_points"]
    touch(customer)
    r["refund_amount_cents"] = order["final_total_cents"]
    r["revoked_points"] = order["awarded_points"]
    r["status"] = "REFUNDED"
    touch(r)
    order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "RETURNED"
    recompute_order_totals(order)
    touch(order)
    return ok(ser_return(r), 200)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
@app.route("/customers/<customer_id>/subscriptions", methods=["POST"])
def create_subscription(customer_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    require_owner(role, uid, customer_id)
    find("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    body = get_body()
    sku_id = v_str(body, "sku_id")
    quantity = v_int(body, "quantity", positive=True)
    cadence_days = v_int(body, "cadence_days", positive=True)
    find("skus", sku_id, "ERR_SKU_NOT_FOUND")
    s = new_common()
    s.update({
        "customer_id": customer_id,
        "sku_id": sku_id,
        "quantity": quantity,
        "cadence_days": cadence_days,
        "_next_renewal": clock_now() + timedelta(days=cadence_days),
        "renewal_count": 0,
        "status": "ACTIVE",
    })
    DB["subscriptions"][s["id"]] = s
    return ok(ser_subscription(s), 201)


@app.route("/subscriptions/<subscription_id>", methods=["GET"])
def get_subscription(subscription_id):
    role, uid = get_auth()
    require_role(role, ROLES)
    s = find("subscriptions", subscription_id, "ERR_SUBSCRIPTION_NOT_FOUND")
    require_owner(role, uid, s["customer_id"])
    return ok(ser_subscription(s), 200)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    role, uid = get_auth()
    require_role(role, ROLES)
    customer_id = request.args.get("customer_id")
    sku_id = request.args.get("sku_id")
    items = list(DB["subscriptions"].values())
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if sku_id is not None:
        items = [s for s in items if s["sku_id"] == sku_id]
    page, pag = list_response(items)
    return ok_list([ser_subscription(s) for s in page], pag)


@app.route("/subscriptions/<subscription_id>/pause", methods=["POST"])
def pause_subscription(subscription_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    s = find("subscriptions", subscription_id, "ERR_SUBSCRIPTION_NOT_FOUND")
    require_owner(role, uid, s["customer_id"])
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "subscription is not ACTIVE")
    s["status"] = "PAUSED"
    touch(s)
    return ok(ser_subscription(s), 200)


@app.route("/subscriptions/<subscription_id>/resume", methods=["POST"])
def resume_subscription(subscription_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    s = find("subscriptions", subscription_id, "ERR_SUBSCRIPTION_NOT_FOUND")
    require_owner(role, uid, s["customer_id"])
    if s["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", "subscription is not PAUSED")
    s["status"] = "ACTIVE"
    touch(s)
    return ok(ser_subscription(s), 200)


@app.route("/subscriptions/<subscription_id>/cancel", methods=["POST"])
def cancel_subscription(subscription_id):
    role, uid = get_auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    s = find("subscriptions", subscription_id, "ERR_SUBSCRIPTION_NOT_FOUND")
    require_owner(role, uid, s["customer_id"])
    if s["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", "subscription is not cancellable")
    s["status"] = "CANCELLED"
    touch(s)
    return ok(ser_subscription(s), 200)


@app.route("/subscriptions/<subscription_id>/renew", methods=["POST"])
def renew_subscription(subscription_id):
    role, uid = get_auth()
    require_role(role, {"MerchOps", "PlatformAdmin"})
    s = find("subscriptions", subscription_id, "ERR_SUBSCRIPTION_NOT_FOUND")
    # State (priority 5): subscription must be ACTIVE.
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "subscription is not ACTIVE")
    # Due check (ERR_SUBSCRIPTION_NOT_DUE).
    if clock_now() < s["_next_renewal"]:
        raise ApiError("ERR_SUBSCRIPTION_NOT_DUE", "renewal not yet due")
    # Customer must be ACTIVE (priority 9).
    customer = DB["customers"][s["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", "owning customer is suspended")
    # Batch selector (priority 10 / ERR_NO_ELIGIBLE_BATCH).
    candidates = [
        b for b in DB["batches"].values()
        if b["sku_id"] == s["sku_id"] and b["status"] == "RELEASED"
        and b["quantity_available"] >= s["quantity"]
    ]
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_BATCH", "no eligible batch for renewal")
    # Rank by created_at ASC; created_at is the sole key, id is never used;
    # collisions broken by insertion order (stable).
    candidates.sort(key=lambda b: (b["created_at"], b["_seq"]))
    batch = candidates[0]

    sku = DB["skus"][s["sku_id"]]
    unit_price = resolve_unit_price(sku)
    order = new_common()
    order.update({
        "customer_id": s["customer_id"],
        "order_type": "RETAIL",
        "gift_message": None,
        "recipient_name": None,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "total_quantity": 0,
        "provisional_total_cents": 0,
        "discount_cents": 0,
        "shipping_fee_cents": 0,
        "final_total_cents": 0,
        "provisional_points": 0,
        "awarded_points": 0,
    })
    DB["orders"][order["id"]] = order
    line = new_common()
    line.update({
        "order_id": order["id"],
        "sku_id": s["sku_id"],
        "batch_id": batch["id"],
        "quantity": s["quantity"],
        "unit_price_cents": unit_price,
        "line_subtotal_cents": unit_price * s["quantity"],
        "status": "RESERVED",
    })
    DB["order_lines"][line["id"]] = line
    batch["quantity_reserved"] += s["quantity"]
    batch["quantity_available"] -= s["quantity"]
    apply_depletion(batch)
    touch(batch)
    recompute_order_totals(order)
    touch(order)

    s["_next_renewal"] = s["_next_renewal"] + timedelta(days=s["cadence_days"])
    s["renewal_count"] += 1
    touch(s)
    return ok(ser_subscription(s), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
