"""Luxury Resale & Consignment Authentication API (Python + Flask).

Every endpoint, field, side effect and ordering traces to a verbatim sentence in
workspace/PRD.md. Storage is in-memory only (see store.py); the store starts empty
on every boot and nothing is ever seeded.
"""

import os
import random
import string
import threading
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Flask, request, jsonify

from store import (
    db, new_id, format_iso, parse_iso,
    rhu_cents, to_decimal_rate, mul_round,
    tier_for, locked_commission_rate, is_listable,
    SALES_TAX_PCT, RESTOCKING_PCT, PAYOUT_HOLD_DAYS, OFFER_TTL_HOURS,
    TRAVEL_BUFFER_MINUTES,
)

app = Flask(__name__)

VALID_ROLES = {"OpsAdmin", "Seller", "Buyer", "Authenticator", "ConciergeAgent"}
CATEGORIES = {"HANDBAGS", "WATCHES", "JEWELRY", "APPAREL", "SHOES"}
GRADES = {"A", "B", "C", "D"}
VERDICTS = {"AUTHENTIC", "COUNTERFEIT", "INCONCLUSIVE"}
INTAKE_CHANNELS = {"DROP_OFF", "PICKUP"}
DISPUTE_TYPES = {"AUTHENTICITY", "CONDITION", "CHANGE_OF_MIND"}
OUTCOMES = {"BUYER", "SELLER"}

# Serialize all request handling so cascades apply atomically.
_LOCK = threading.RLock()


# ===========================================================================
# Errors + response envelope
# ===========================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": format_iso(db.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), code


def ok_list(records, total, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return ok([serialize(r) for r in records], 200, "array", pagination)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        _LOCK.release()
    except RuntimeError:
        pass


# ===========================================================================
# Auth (PRD §2.1)
# ===========================================================================
class Ctx:
    __slots__ = ("uid", "role")

    def __init__(self, uid, role):
        self.uid = uid
        self.role = role


def require_auth(roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", 400,
                       "X-User-ID and X-User-Role headers must be present and well-formed")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role is not permitted for this operation")
    return Ctx(uid, role)


def endpoint(path, methods, roles):
    """Register a route that first enforces auth-context then role permission."""
    def deco(fn):
        def wrapper(**kwargs):
            ctx = require_auth(roles)
            return fn(ctx, **kwargs)
        wrapper.__name__ = fn.__name__
        app.add_url_rule(path, fn.__name__, wrapper, methods=methods)
        return fn
    return deco


# ===========================================================================
# Body validation (PRD §2.1 / §2.5 -> ERR_VALIDATION)
# ===========================================================================
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def _bad(field):
    raise ApiError("ERR_VALIDATION", 400, "Invalid or missing field: %s" % field)


def validate(body, spec):
    """spec entries: (name, kind, optional, enum_set). Returns cleaned dict."""
    out = {}
    for name, kind, optional, enum_set in spec:
        present = name in body and body[name] is not None
        if not present:
            if optional:
                out[name] = None
                continue
            _bad(name)
        v = body[name]
        if kind == "str":
            if not isinstance(v, str):
                _bad(name)
        elif kind == "cents":
            if isinstance(v, bool) or not isinstance(v, int):
                _bad(name)
        elif kind == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                _bad(name)
        elif kind == "enum":
            if v not in enum_set:
                _bad(name)
        elif kind == "datetime":
            try:
                parse_iso(v)
            except Exception:
                _bad(name)
        out[name] = v
    return out


# ===========================================================================
# Record lifecycle helpers (PRD §2.4)
# ===========================================================================
def stamp_new(record):
    t = db.now()
    record["id"] = new_id()
    record["created_at"] = t
    record["updated_at"] = t
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def bump(record):
    record["version"] += 1
    record["updated_at"] = db.now()


def serialize(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = format_iso(v)
        else:
            out[k] = v
    return out


def get_or_404(coll, id_, err):
    rec = coll.get(id_)
    if rec is None:
        raise ApiError(err, 404, "Resource not found")
    return rec


def policy_for_category(category):
    for p in db.category_policies.values():
        if p["category"] == category:
            return p
    return None


def recompute_balance(seller):
    seller["payout_balance_cents"] = (
        seller["pending_payout_cents"] + seller["released_payout_cents"]
    )


# ===========================================================================
# Pagination + list helpers (PRD §2.3)
# ===========================================================================
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args["limit"] != "":
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args["offset"] != "":
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sort_and_page(records, limit, offset):
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


def matches(record, filters):
    for key, val in filters.items():
        if val is None:
            continue
        if str(record.get(key)) != str(val):
            return False
    return True


# ===========================================================================
# Offer lazy expiry (PRD §2.10 / §3.5)
# ===========================================================================
def maybe_expire(offer):
    if offer["status"] in ("PENDING", "COUNTERED") and db.now() > offer["expires_at"]:
        offer["status"] = "EXPIRED"
        bump(offer)


# ===========================================================================
# Sellers  (PRD §3.1)
# ===========================================================================
@endpoint("/consignment/sellers", ["POST"], {"OpsAdmin"})
def create_seller(ctx):
    body = validate(get_body(), [("display_name", "str", False, None), ("email", "str", False, None)])
    rec = {
        "display_name": body["display_name"],
        "email": body["email"],
        "status": "ACTIVE",
        "tier": "STANDARD",
        "lifetime_net_sales_cents": 0,
        "pending_payout_cents": 0,
        "released_payout_cents": 0,
        "reversed_payout_cents": 0,
        "payout_balance_cents": 0,
    }
    stamp_new(rec)
    db.sellers[rec["id"]] = rec
    return ok(serialize(rec), 201)


@endpoint("/consignment/sellers/<sid>", ["GET"], {"OpsAdmin", "Seller"})
def get_seller(ctx, sid):
    rec = get_or_404(db.sellers, sid, "ERR_SELLER_NOT_FOUND")
    return ok(serialize(rec), 200)


# ===========================================================================
# Buyers  (PRD §3.1)
# ===========================================================================
@endpoint("/consignment/buyers", ["POST"], {"OpsAdmin"})
def create_buyer(ctx):
    body = validate(get_body(), [("display_name", "str", False, None), ("email", "str", False, None)])
    rec = {
        "display_name": body["display_name"],
        "email": body["email"],
        "status": "ACTIVE",
        "lifetime_purchases_cents": 0,
    }
    stamp_new(rec)
    db.buyers[rec["id"]] = rec
    return ok(serialize(rec), 201)


@endpoint("/consignment/buyers/<bid>", ["GET"], {"OpsAdmin", "Buyer"})
def get_buyer(ctx, bid):
    rec = get_or_404(db.buyers, bid, "ERR_BUYER_NOT_FOUND")
    return ok(serialize(rec), 200)


# ===========================================================================
# Category policies  (PRD §3.1)
# ===========================================================================
@endpoint("/consignment/category-policies", ["POST"], {"OpsAdmin"})
def create_category_policy(ctx):
    body = validate(get_body(), [
        ("category", "enum", False, CATEGORIES),
        ("base_commission_pct", "number", False, None),
        ("buyer_fee_pct", "number", False, None),
        ("buyer_fee_flat_cents", "cents", False, None),
        ("return_window_days", "cents", False, None),
        ("min_offer_pct", "number", False, None),
        ("listable_min_condition_grade", "enum", False, GRADES),
        ("pickup_insurance_cap_cents", "cents", False, None),
    ])
    if policy_for_category(body["category"]) is not None:
        raise ApiError("ERR_VALIDATION", 400, "A policy already exists for this category")
    rec = {
        "category": body["category"],
        "base_commission_pct": body["base_commission_pct"],
        "buyer_fee_pct": body["buyer_fee_pct"],
        "buyer_fee_flat_cents": body["buyer_fee_flat_cents"],
        "return_window_days": body["return_window_days"],
        "min_offer_pct": body["min_offer_pct"],
        "listable_min_condition_grade": body["listable_min_condition_grade"],
        "pickup_insurance_cap_cents": body["pickup_insurance_cap_cents"],
    }
    stamp_new(rec)
    db.category_policies[rec["id"]] = rec
    return ok(serialize(rec), 201)


@endpoint("/consignment/category-policies/<pid>", ["GET"],
          {"OpsAdmin", "Seller", "Buyer", "Authenticator"})
def get_category_policy(ctx, pid):
    rec = get_or_404(db.category_policies, pid, "ERR_CATEGORY_POLICY_NOT_FOUND")
    return ok(serialize(rec), 200)


# ===========================================================================
# Consignment items  (PRD §3.2 / §3.3)
# ===========================================================================
@endpoint("/consignment/items", ["POST"], {"Seller", "OpsAdmin"})
def create_item(ctx):
    body = validate(get_body(), [
        ("seller_id", "str", False, None),
        ("category", "enum", False, CATEGORIES),
        ("brand", "str", False, None),
        ("title", "str", False, None),
        ("declared_value_cents", "cents", False, None),
        ("intake_channel", "enum", False, INTAKE_CHANNELS),
    ])
    get_or_404(db.sellers, body["seller_id"], "ERR_SELLER_NOT_FOUND")
    if ctx.role == "Seller" and body["seller_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Seller does not own this consignment")
    status = "RECEIVED" if body["intake_channel"] == "DROP_OFF" else "INTAKE_REQUESTED"
    rec = {
        "seller_id": body["seller_id"],
        "category": body["category"],
        "brand": body["brand"],
        "title": body["title"],
        "declared_value_cents": body["declared_value_cents"],
        "intake_channel": body["intake_channel"],
        "status": status,
        "authenticity_verdict": None,
        "condition_grade": None,
        "authenticator_id": None,
        "authenticated_at": None,
        "listable": False,
    }
    stamp_new(rec)
    db.items[rec["id"]] = rec
    return ok(serialize(rec), 201)


@endpoint("/consignment/items", ["GET"], {"OpsAdmin", "Seller"})
def list_items(ctx):
    limit, offset = parse_pagination()
    filters = {
        "seller_id": request.args.get("seller_id"),
        "category": request.args.get("category"),
        "status": request.args.get("status"),
    }
    recs = [r for r in db.items.values() if matches(r, filters)]
    page, total = sort_and_page(recs, limit, offset)
    return ok_list(page, total, limit, offset)


@endpoint("/consignment/items/<iid>", ["GET"], {"OpsAdmin", "Seller", "Authenticator"})
def get_item(ctx, iid):
    rec = get_or_404(db.items, iid, "ERR_ITEM_NOT_FOUND")
    return ok(serialize(rec), 200)


@endpoint("/consignment/items/<iid>/authenticate", ["POST"], {"Authenticator"})
def authenticate_item(ctx, iid):
    body = validate(get_body(), [
        ("verdict", "enum", False, VERDICTS),
        ("condition_grade", "enum", False, GRADES),
        ("notes", "str", True, None),
    ])
    item = get_or_404(db.items, iid, "ERR_ITEM_NOT_FOUND")
    # authenticate is exempt from ownership (Authenticator never owns the item)
    if item["status"] != "RECEIVED":
        raise ApiError("ERR_ITEM_INVALID_STATE", 409, "Item must be RECEIVED to authenticate")
    item["authenticity_verdict"] = body["verdict"]
    item["condition_grade"] = body["condition_grade"]
    item["authenticator_id"] = ctx.uid
    item["authenticated_at"] = db.now()
    policy = policy_for_category(item["category"])
    min_grade = policy["listable_min_condition_grade"] if policy else None
    item["listable"] = is_listable(body["verdict"], body["condition_grade"], min_grade)
    if body["verdict"] == "AUTHENTIC":
        item["status"] = "AUTHENTICATED"
    else:
        item["status"] = "REJECTED"
    bump(item)
    return ok(serialize(item), 200)


# ===========================================================================
# Listings  (PRD §3.4)
# ===========================================================================
@endpoint("/consignment/listings", ["POST"], {"Seller", "OpsAdmin"})
def create_listing(ctx):
    body = validate(get_body(), [
        ("item_id", "str", False, None),
        ("list_price_cents", "cents", False, None),
    ])
    item = get_or_404(db.items, body["item_id"], "ERR_ITEM_NOT_FOUND")
    if ctx.role == "Seller" and item["seller_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Seller does not own this item")
    rec = {
        "item_id": item["id"],
        "seller_id": item["seller_id"],
        "category": item["category"],
        "list_price_cents": body["list_price_cents"],
        "status": "DRAFT",
        "commission_tier_locked": None,
        "commission_rate_locked_pct": None,
        "provisional_payout_cents": None,
        "min_offer_cents": None,
    }
    stamp_new(rec)
    db.listings[rec["id"]] = rec
    return ok(serialize(rec), 201)


@endpoint("/consignment/listings", ["GET"], {"OpsAdmin", "Seller", "Buyer"})
def list_listings(ctx):
    limit, offset = parse_pagination()
    filters = {
        "item_id": request.args.get("item_id"),
        "seller_id": request.args.get("seller_id"),
        "status": request.args.get("status"),
    }
    recs = [r for r in db.listings.values() if matches(r, filters)]
    page, total = sort_and_page(recs, limit, offset)
    return ok_list(page, total, limit, offset)


@endpoint("/consignment/listings/<lid>", ["GET"], {"OpsAdmin", "Seller", "Buyer", "Authenticator"})
def get_listing(ctx, lid):
    rec = get_or_404(db.listings, lid, "ERR_LISTING_NOT_FOUND")
    return ok(serialize(rec), 200)


@endpoint("/consignment/listings/<lid>/publish", ["POST"], {"Seller", "OpsAdmin"})
def publish_listing(ctx, lid):
    listing = get_or_404(db.listings, lid, "ERR_LISTING_NOT_FOUND")
    item = get_or_404(db.items, listing["item_id"], "ERR_ITEM_NOT_FOUND")
    policy = policy_for_category(item["category"])
    if policy is None:
        raise ApiError("ERR_CATEGORY_POLICY_NOT_FOUND", 404, "No policy for this category")
    if ctx.role == "Seller" and listing["seller_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Seller does not own this listing")
    # (5) target state
    if listing["status"] != "DRAFT":
        raise ApiError("ERR_LISTING_INVALID_STATE", 409, "Listing must be DRAFT to publish")
    # (7) cross-entity state
    if item["status"] != "AUTHENTICATED":
        raise ApiError("ERR_ITEM_NOT_AUTHENTICATED", 409, "Item must be AUTHENTICATED")
    # (8) business: item must be listable
    if not is_listable(item["authenticity_verdict"], item["condition_grade"],
                       policy["listable_min_condition_grade"]):
        raise ApiError("ERR_ITEM_GRADE_NOT_LISTABLE", 422, "Item grade is below the listable minimum")

    seller = db.sellers[listing["seller_id"]]
    tier = seller["tier"]
    rate = locked_commission_rate(policy["base_commission_pct"], tier)
    list_price = listing["list_price_cents"]
    listing["commission_tier_locked"] = tier
    listing["commission_rate_locked_pct"] = float(rate)
    listing["provisional_payout_cents"] = list_price - rhu_cents(Decimal(list_price) * rate)
    listing["min_offer_cents"] = mul_round(list_price, policy["min_offer_pct"])
    listing["status"] = "ACTIVE"
    bump(listing)
    # cascade: item AUTHENTICATED -> LISTED
    item["status"] = "LISTED"
    bump(item)
    return ok(serialize(listing), 200)


# ===========================================================================
# Sale creation cascade (shared by direct-buy and offer-accept)
# ===========================================================================
def decline_siblings(listing_id, exclude_offer_id=None):
    for o in db.offers.values():
        if (o["listing_id"] == listing_id and o["id"] != exclude_offer_id
                and o["status"] in ("PENDING", "COUNTERED")):
            o["status"] = "DECLINED"
            bump(o)


def create_sale(listing, buyer_id, sale_channel, sale_price, offer_id=None):
    policy = policy_for_category(listing["category"])
    rate_float = listing["commission_rate_locked_pct"]
    commission = mul_round(sale_price, rate_float)
    net = sale_price - commission
    buyer_fee = policy["buyer_fee_flat_cents"] + mul_round(sale_price, policy["buyer_fee_pct"])
    tax = rhu_cents(Decimal(sale_price + buyer_fee) * SALES_TAX_PCT)
    order_total = sale_price + buyer_fee + tax
    sale = {
        "listing_id": listing["id"],
        "buyer_id": buyer_id,
        "seller_id": listing["seller_id"],
        "offer_id": offer_id,
        "sale_channel": sale_channel,
        "sale_price_cents": sale_price,
        "commission_rate_pct": rate_float,
        "commission_cents": commission,
        "seller_net_payout_cents": net,
        "buyer_fee_cents": buyer_fee,
        "tax_cents": tax,
        "order_total_cents": order_total,
        "payment_status": "PENDING",
        "fulfillment_status": "AWAITING_SHIPMENT",
        "delivered_at": None,
        "return_window_ends_at": None,
    }
    stamp_new(sale)
    db.sales[sale["id"]] = sale
    # cascade: listing ACTIVE -> SOLD, item LISTED -> SOLD, sibling offers DECLINED
    listing["status"] = "SOLD"
    bump(listing)
    item = db.items[listing["item_id"]]
    item["status"] = "SOLD"
    bump(item)
    decline_siblings(listing["id"], exclude_offer_id=offer_id)
    return sale


# ===========================================================================
# Offers  (PRD §3.5)
# ===========================================================================
@endpoint("/consignment/offers", ["POST"], {"Buyer"})
def create_offer(ctx):
    body = validate(get_body(), [
        ("listing_id", "str", False, None),
        ("buyer_id", "str", False, None),
        ("amount_cents", "cents", False, None),
        ("expected_listing_version", "cents", False, None),
    ])
    listing = get_or_404(db.listings, body["listing_id"], "ERR_LISTING_NOT_FOUND")
    get_or_404(db.buyers, body["buyer_id"], "ERR_BUYER_NOT_FOUND")
    if body["buyer_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Buyer does not match the acting principal")
    # (6) optimistic concurrency
    if body["expected_listing_version"] != listing["version"]:
        raise ApiError("ERR_STALE_LISTING_VERSION", 412, "Listing version is stale")
    # (7) cross-entity state
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE")
    # (10) business fiscal floor
    if body["amount_cents"] < listing["min_offer_cents"]:
        raise ApiError("ERR_OFFER_BELOW_FLOOR", 422, "Offer is below the minimum offer floor")
    now = db.now()
    rec = {
        "listing_id": listing["id"],
        "buyer_id": body["buyer_id"],
        "amount_cents": body["amount_cents"],
        "status": "PENDING",
        "counter_amount_cents": None,
        "round_number": 1,
        "agreed_price_cents": None,
        "expires_at": now + timedelta(hours=OFFER_TTL_HOURS),
    }
    stamp_new(rec)
    db.offers[rec["id"]] = rec
    # side effect: increments Listing.version by 1
    bump(listing)
    return ok(serialize(rec), 201)


@endpoint("/consignment/offers", ["GET"], {"OpsAdmin", "Seller", "Buyer"})
def list_offers(ctx):
    limit, offset = parse_pagination()
    for o in db.offers.values():
        maybe_expire(o)
    filters = {
        "listing_id": request.args.get("listing_id"),
        "buyer_id": request.args.get("buyer_id"),
        "status": request.args.get("status"),
    }
    recs = [r for r in db.offers.values() if matches(r, filters)]
    page, total = sort_and_page(recs, limit, offset)
    return ok_list(page, total, limit, offset)


@endpoint("/consignment/offers/<oid>", ["GET"], {"OpsAdmin", "Seller", "Buyer"})
def get_offer(ctx, oid):
    rec = get_or_404(db.offers, oid, "ERR_OFFER_NOT_FOUND")
    maybe_expire(rec)
    return ok(serialize(rec), 200)


@endpoint("/consignment/offers/<oid>/counter", ["POST"], {"Seller", "Buyer"})
def counter_offer(ctx, oid):
    body = validate(get_body(), [("counter_amount_cents", "cents", False, None)])
    offer = get_or_404(db.offers, oid, "ERR_OFFER_NOT_FOUND")
    listing = db.listings[offer["listing_id"]]
    maybe_expire(offer)
    target = body["counter_amount_cents"]
    if ctx.role == "Seller":
        # ownership: seller owns the listing
        if listing["seller_id"] != ctx.uid:
            raise ApiError("ERR_NOT_OWNER", 403, "Seller does not own this listing")
        if offer["status"] != "PENDING":
            raise ApiError("ERR_OFFER_INVALID_STATE", 409, "Offer must be PENDING for a seller counter")
        if listing["status"] != "ACTIVE":
            raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE")
        if target < listing["min_offer_cents"]:
            raise ApiError("ERR_OFFER_BELOW_FLOOR", 422, "Counter is below the minimum offer floor")
        offer["counter_amount_cents"] = target
        offer["status"] = "COUNTERED"
        bump(offer)
    else:  # Buyer counters back
        if offer["buyer_id"] != ctx.uid:
            raise ApiError("ERR_NOT_OWNER", 403, "Buyer does not own this offer")
        if offer["status"] != "COUNTERED":
            raise ApiError("ERR_OFFER_INVALID_STATE", 409, "Offer must be COUNTERED for a buyer counter-back")
        if listing["status"] != "ACTIVE":
            raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE")
        if target < listing["min_offer_cents"]:
            raise ApiError("ERR_OFFER_BELOW_FLOOR", 422, "Counter is below the minimum offer floor")
        offer["amount_cents"] = target
        offer["counter_amount_cents"] = None
        offer["round_number"] += 1
        offer["status"] = "PENDING"
        bump(offer)
    return ok(serialize(offer), 200)


@endpoint("/consignment/offers/<oid>/accept", ["POST"], {"Seller", "Buyer"})
def accept_offer(ctx, oid):
    offer = get_or_404(db.offers, oid, "ERR_OFFER_NOT_FOUND")
    listing = db.listings[offer["listing_id"]]
    maybe_expire(offer)
    if ctx.role == "Seller":
        if listing["seller_id"] != ctx.uid:
            raise ApiError("ERR_NOT_OWNER", 403, "Seller does not own this listing")
        if offer["status"] != "PENDING":
            raise ApiError("ERR_OFFER_INVALID_STATE", 409, "Seller may only accept a PENDING offer")
        if listing["status"] != "ACTIVE":
            raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE")
        agreed = offer["amount_cents"]
    else:  # Buyer accepts a seller counter
        if offer["buyer_id"] != ctx.uid:
            raise ApiError("ERR_NOT_OWNER", 403, "Buyer does not own this offer")
        if offer["status"] != "COUNTERED":
            raise ApiError("ERR_OFFER_INVALID_STATE", 409, "Buyer may only accept a COUNTERED offer")
        if listing["status"] != "ACTIVE":
            raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE")
        agreed = offer["counter_amount_cents"]
    offer["agreed_price_cents"] = agreed
    offer["status"] = "ACCEPTED"
    bump(offer)
    create_sale(listing, offer["buyer_id"], "OFFER", agreed, offer_id=offer["id"])
    return ok(serialize(offer), 200)


# ===========================================================================
# Sales  (PRD §3.5 / §3.6)
# ===========================================================================
@endpoint("/consignment/sales", ["POST"], {"Buyer", "OpsAdmin"})
def create_sale_direct(ctx):
    body = validate(get_body(), [
        ("listing_id", "str", False, None),
        ("buyer_id", "str", False, None),
    ])
    listing = get_or_404(db.listings, body["listing_id"], "ERR_LISTING_NOT_FOUND")
    get_or_404(db.buyers, body["buyer_id"], "ERR_BUYER_NOT_FOUND")
    if ctx.role == "Buyer" and body["buyer_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Buyer does not match the acting principal")
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Listing is not ACTIVE")
    sale = create_sale(listing, body["buyer_id"], "DIRECT", listing["list_price_cents"], offer_id=None)
    return ok(serialize(sale), 201)


@endpoint("/consignment/sales", ["GET"], {"OpsAdmin", "Seller", "Buyer"})
def list_sales(ctx):
    limit, offset = parse_pagination()
    filters = {
        "listing_id": request.args.get("listing_id"),
        "buyer_id": request.args.get("buyer_id"),
        "seller_id": request.args.get("seller_id"),
        "status": request.args.get("status"),
    }
    # 'status' has no single canonical axis; support both payment and fulfillment.
    status = filters.pop("status")
    recs = []
    for r in db.sales.values():
        if not matches(r, filters):
            continue
        if status is not None and status not in (r["payment_status"], r["fulfillment_status"]):
            continue
        recs.append(r)
    page, total = sort_and_page(recs, limit, offset)
    return ok_list(page, total, limit, offset)


@endpoint("/consignment/sales/<sid>", ["GET"], {"OpsAdmin", "Seller", "Buyer"})
def get_sale(ctx, sid):
    rec = get_or_404(db.sales, sid, "ERR_SALE_NOT_FOUND")
    return ok(serialize(rec), 200)


@endpoint("/consignment/sales/<sid>/capture-payment", ["POST"], {"Buyer", "OpsAdmin"})
def capture_payment(ctx, sid):
    sale = get_or_404(db.sales, sid, "ERR_SALE_NOT_FOUND")
    if ctx.role == "Buyer" and sale["buyer_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Buyer does not own this sale")
    if sale["payment_status"] != "PENDING":
        raise ApiError("ERR_SALE_PAYMENT_INVALID_STATE", 409, "Payment is not in PENDING state")
    sale["payment_status"] = "CAPTURED"
    bump(sale)
    return ok(serialize(sale), 200)


@endpoint("/consignment/sales/<sid>/ship", ["POST"], {"Seller", "OpsAdmin"})
def ship_sale(ctx, sid):
    sale = get_or_404(db.sales, sid, "ERR_SALE_NOT_FOUND")
    if ctx.role == "Seller" and sale["seller_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Seller does not own this sale")
    if sale["fulfillment_status"] != "AWAITING_SHIPMENT" or sale["payment_status"] != "CAPTURED":
        raise ApiError("ERR_SALE_FULFILLMENT_INVALID_STATE", 409,
                       "Sale must be AWAITING_SHIPMENT with payment CAPTURED to ship")
    sale["fulfillment_status"] = "SHIPPED"
    bump(sale)
    return ok(serialize(sale), 200)


@endpoint("/consignment/sales/<sid>/confirm-delivery", ["POST"], {"Buyer", "OpsAdmin"})
def confirm_delivery(ctx, sid):
    sale = get_or_404(db.sales, sid, "ERR_SALE_NOT_FOUND")
    if ctx.role == "Buyer" and sale["buyer_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Buyer does not own this sale")
    if sale["fulfillment_status"] != "SHIPPED":
        raise ApiError("ERR_SALE_FULFILLMENT_INVALID_STATE", 409, "Sale must be SHIPPED to confirm delivery")
    listing = db.listings[sale["listing_id"]]
    policy = policy_for_category(listing["category"])
    now = db.now()
    sale["fulfillment_status"] = "DELIVERED"
    sale["delivered_at"] = now
    sale["return_window_ends_at"] = now + timedelta(days=policy["return_window_days"])
    bump(sale)
    # cascade: create Payout SCHEDULED
    payout = {
        "sale_id": sale["id"],
        "seller_id": sale["seller_id"],
        "amount_cents": sale["seller_net_payout_cents"],
        "status": "SCHEDULED",
        "scheduled_release_at": sale["return_window_ends_at"] + timedelta(days=PAYOUT_HOLD_DAYS),
        "released_at": None,
    }
    stamp_new(payout)
    db.payouts[payout["id"]] = payout
    # cascade: seller pending ledger + buyer purchase ledger
    seller = db.sellers[sale["seller_id"]]
    seller["pending_payout_cents"] += sale["seller_net_payout_cents"]
    recompute_balance(seller)
    bump(seller)
    buyer = db.buyers[sale["buyer_id"]]
    buyer["lifetime_purchases_cents"] += sale["order_total_cents"]
    bump(buyer)
    return ok(serialize(sale), 200)


@endpoint("/consignment/sales/<sid>/payouts", ["GET"], {"OpsAdmin", "Seller"})
def list_sale_payouts(ctx, sid):
    get_or_404(db.sales, sid, "ERR_SALE_NOT_FOUND")
    limit, offset = parse_pagination()
    recs = [p for p in db.payouts.values() if p["sale_id"] == sid]
    page, total = sort_and_page(recs, limit, offset)
    return ok_list(page, total, limit, offset)


@endpoint("/consignment/sales/<sid>/disputes", ["GET"], {"OpsAdmin", "Seller", "Buyer"})
def list_sale_disputes(ctx, sid):
    get_or_404(db.sales, sid, "ERR_SALE_NOT_FOUND")
    limit, offset = parse_pagination()
    recs = [d for d in db.disputes.values() if d["sale_id"] == sid]
    page, total = sort_and_page(recs, limit, offset)
    return ok_list(page, total, limit, offset)


# ===========================================================================
# Payouts  (PRD §3.7)
# ===========================================================================
@endpoint("/consignment/payouts/<pid>/release", ["POST"], {"OpsAdmin"})
def release_payout(ctx, pid):
    payout = get_or_404(db.payouts, pid, "ERR_PAYOUT_NOT_FOUND")
    # (5) state
    if payout["status"] != "SCHEDULED":
        raise ApiError("ERR_PAYOUT_NOT_RELEASABLE", 409, "Payout is not in SCHEDULED state")
    # (13) temporal
    if db.now() < payout["scheduled_release_at"]:
        raise ApiError("ERR_PAYOUT_HOLD_ACTIVE", 409, "Payout hold is still active")
    payout["status"] = "RELEASED"
    payout["released_at"] = db.now()
    bump(payout)
    seller = db.sellers[payout["seller_id"]]
    amt = payout["amount_cents"]
    seller["pending_payout_cents"] -= amt
    seller["released_payout_cents"] += amt
    seller["lifetime_net_sales_cents"] += amt
    seller["tier"] = tier_for(seller["lifetime_net_sales_cents"])
    recompute_balance(seller)
    bump(seller)
    return ok(serialize(payout), 200)


# ===========================================================================
# Disputes  (PRD §3.8)
# ===========================================================================
@endpoint("/consignment/disputes", ["POST"], {"Buyer", "OpsAdmin"})
def file_dispute(ctx):
    body = validate(get_body(), [
        ("sale_id", "str", False, None),
        ("type", "enum", False, DISPUTE_TYPES),
        ("reason", "str", False, None),
    ])
    sale = get_or_404(db.sales, body["sale_id"], "ERR_SALE_NOT_FOUND")
    if ctx.role == "Buyer" and sale["buyer_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Buyer does not own this sale")
    # (5) state: disputable
    if sale["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_SALE_NOT_DISPUTABLE", 409, "Sale is not disputable")
    # (9) at most one open dispute
    for d in db.disputes.values():
        if d["sale_id"] == sale["id"] and d["status"] == "FILED":
            raise ApiError("ERR_DISPUTE_ALREADY_EXISTS", 409, "An open dispute already exists")
    # (12) temporal: within the return window (inclusive)
    if db.now() > sale["return_window_ends_at"]:
        raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED", 409, "The return window has expired")
    rec = {
        "sale_id": sale["id"],
        "buyer_id": sale["buyer_id"],
        "type": body["type"],
        "reason": body["reason"],
        "status": "FILED",
        "outcome": None,
        "refund_amount_cents": None,
        "restocking_fee_cents": None,
        "resolved_at": None,
    }
    stamp_new(rec)
    db.disputes[rec["id"]] = rec
    # cascade: the sale's SCHEDULED payout -> HELD
    for p in db.payouts.values():
        if p["sale_id"] == sale["id"] and p["status"] == "SCHEDULED":
            p["status"] = "HELD"
            bump(p)
    return ok(serialize(rec), 201)


@endpoint("/consignment/disputes/<did>/resolve", ["POST"], {"OpsAdmin"})
def resolve_dispute(ctx, did):
    body = validate(get_body(), [("outcome", "enum", False, OUTCOMES)])
    dispute = get_or_404(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    if dispute["status"] != "FILED":
        raise ApiError("ERR_DISPUTE_INVALID_STATE", 409, "Dispute is not in FILED state")
    sale = db.sales[dispute["sale_id"]]
    dispute["outcome"] = body["outcome"]
    dispute["resolved_at"] = db.now()
    if body["outcome"] == "SELLER":
        _resolve_seller(dispute, sale)
    else:
        _resolve_buyer(dispute, sale)
    return ok(serialize(dispute), 200)


def _resolve_seller(dispute, sale):
    dispute["refund_amount_cents"] = 0
    dispute["restocking_fee_cents"] = 0
    dispute["status"] = "RESOLVED_SELLER"
    bump(dispute)
    # cascade: the sale's HELD payout -> SCHEDULED (sale otherwise untouched)
    for p in db.payouts.values():
        if p["sale_id"] == sale["id"] and p["status"] == "HELD":
            p["status"] = "SCHEDULED"
            bump(p)


def _resolve_buyer(dispute, sale):
    listing = db.listings[sale["listing_id"]]
    dtype = dispute["type"]
    if dtype in ("AUTHENTICITY", "CONDITION"):
        restocking = 0
        refund = sale["order_total_cents"]
    else:  # CHANGE_OF_MIND
        restocking = mul_round(sale["sale_price_cents"], RESTOCKING_PCT)
        refund = sale["sale_price_cents"] + sale["tax_cents"] - restocking
    dispute["restocking_fee_cents"] = restocking
    dispute["refund_amount_cents"] = refund
    dispute["status"] = "RESOLVED_BUYER"
    bump(dispute)
    # Sale: payment CAPTURED -> REFUNDED, fulfillment DELIVERED -> RETURNED
    sale["payment_status"] = "REFUNDED"
    sale["fulfillment_status"] = "RETURNED"
    bump(sale)
    # Buyer ledger: exact reversal of the delivery credit
    buyer = db.buyers[sale["buyer_id"]]
    buyer["lifetime_purchases_cents"] -= sale["order_total_cents"]
    bump(buyer)
    # Payout SCHEDULED/HELD -> REVERSED, seller ledger adjusted
    seller = db.sellers[sale["seller_id"]]
    for p in db.payouts.values():
        if p["sale_id"] == sale["id"] and p["status"] in ("SCHEDULED", "HELD"):
            seller["pending_payout_cents"] -= p["amount_cents"]
            seller["reversed_payout_cents"] += p["amount_cents"]
            p["status"] = "REVERSED"
            bump(p)
    recompute_balance(seller)
    bump(seller)
    # Item fate depends on dispute type
    item = db.items[listing["item_id"]]
    if dtype in ("AUTHENTICITY", "CONDITION"):
        item["status"] = "DISPOSED"
        bump(item)
    else:  # CHANGE_OF_MIND: relist
        item["status"] = "LISTED"
        bump(item)
        listing["status"] = "ACTIVE"
        bump(listing)


# ===========================================================================
# White-glove pickup: concierges, vehicles, appointments  (PRD §3.2)
# ===========================================================================
@endpoint("/consignment/concierges", ["POST"], {"OpsAdmin"})
def create_concierge(ctx):
    body = validate(get_body(), [("name", "str", False, None), ("region", "str", False, None)])
    rec = {"name": body["name"], "region": body["region"], "status": "ACTIVE"}
    stamp_new(rec)
    db.concierges[rec["id"]] = rec
    return ok(serialize(rec), 201)


@endpoint("/consignment/vehicles", ["POST"], {"OpsAdmin"})
def create_vehicle(ctx):
    body = validate(get_body(), [("plate", "str", False, None)])
    rec = {"plate": body["plate"], "status": "ACTIVE"}
    stamp_new(rec)
    db.vehicles[rec["id"]] = rec
    return ok(serialize(rec), 201)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Strict half-open overlap: [a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@endpoint("/consignment/pickups", ["POST"], {"Seller", "OpsAdmin"})
def create_pickup(ctx):
    body = validate(get_body(), [
        ("item_id", "str", False, None),
        ("concierge_id", "str", False, None),
        ("vehicle_id", "str", False, None),
        ("window_start", "datetime", False, None),
        ("window_end", "datetime", False, None),
    ])
    # existence, left-to-right
    item = get_or_404(db.items, body["item_id"], "ERR_ITEM_NOT_FOUND")
    get_or_404(db.concierges, body["concierge_id"], "ERR_CONCIERGE_NOT_FOUND")
    get_or_404(db.vehicles, body["vehicle_id"], "ERR_VEHICLE_NOT_FOUND")
    policy = policy_for_category(item["category"])
    if policy is None:
        raise ApiError("ERR_CATEGORY_POLICY_NOT_FOUND", 404, "No policy for this category")
    # ownership
    if ctx.role == "Seller" and item["seller_id"] != ctx.uid:
        raise ApiError("ERR_NOT_OWNER", 403, "Seller does not own this item")

    win_start = parse_iso(body["window_start"])
    win_end = parse_iso(body["window_end"])

    # (11) fiscal: declared value within insurance cap
    if item["declared_value_cents"] > policy["pickup_insurance_cap_cents"]:
        raise ApiError("ERR_PICKUP_VALUE_EXCEEDS_INSURANCE", 422,
                       "Declared value exceeds the pickup insurance cap")
    # (14) concierge availability with 60-minute travel buffer on both ends
    buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    padded_start = win_start - buffer
    padded_end = win_end + buffer
    for pk in db.pickups.values():
        if pk["status"] != "SCHEDULED" or pk["concierge_id"] != body["concierge_id"]:
            continue
        o_start = parse_iso(pk["window_start"])
        o_end = parse_iso(pk["window_end"])
        if _intervals_overlap(padded_start, padded_end, o_start, o_end):
            raise ApiError("ERR_CONCIERGE_UNAVAILABLE", 409, "Concierge is unavailable")
    # (15) vehicle availability: strict half-open, no buffer (adjacency allowed)
    for pk in db.pickups.values():
        if pk["status"] != "SCHEDULED" or pk["vehicle_id"] != body["vehicle_id"]:
            continue
        o_start = parse_iso(pk["window_start"])
        o_end = parse_iso(pk["window_end"])
        if _intervals_overlap(win_start, win_end, o_start, o_end):
            raise ApiError("ERR_VEHICLE_UNAVAILABLE", 409, "Vehicle is unavailable")

    rec = {
        "item_id": item["id"],
        "concierge_id": body["concierge_id"],
        "vehicle_id": body["vehicle_id"],
        "seller_id": item["seller_id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "SCHEDULED",
        "declared_value_cents": item["declared_value_cents"],
    }
    stamp_new(rec)
    db.pickups[rec["id"]] = rec
    return ok(serialize(rec), 201)


@endpoint("/consignment/pickups", ["GET"], {"OpsAdmin", "Seller"})
def list_pickups(ctx):
    limit, offset = parse_pagination()
    filters = {
        "concierge_id": request.args.get("concierge_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "item_id": request.args.get("item_id"),
        "seller_id": request.args.get("seller_id"),
        "status": request.args.get("status"),
    }
    recs = [r for r in db.pickups.values() if matches(r, filters)]
    page, total = sort_and_page(recs, limit, offset)
    return ok_list(page, total, limit, offset)


@endpoint("/consignment/pickups/<pid>", ["GET"], {"OpsAdmin", "Seller"})
def get_pickup(ctx, pid):
    rec = get_or_404(db.pickups, pid, "ERR_PICKUP_NOT_FOUND")
    return ok(serialize(rec), 200)


@endpoint("/consignment/pickups/<pid>/complete", ["POST"], {"ConciergeAgent", "OpsAdmin"})
def complete_pickup(ctx, pid):
    pickup = get_or_404(db.pickups, pid, "ERR_PICKUP_NOT_FOUND")
    if pickup["status"] != "SCHEDULED":
        raise ApiError("ERR_PICKUP_INVALID_STATE", 409, "Pickup must be SCHEDULED to complete")
    pickup["status"] = "COMPLETED"
    bump(pickup)
    # cascade: item INTAKE_REQUESTED -> RECEIVED
    item = db.items.get(pickup["item_id"])
    if item is not None and item["status"] == "INTAKE_REQUESTED":
        item["status"] = "RECEIVED"
        bump(item)
    return ok(serialize(pickup), 200)


# ===========================================================================
# Logical clock control  (PRD §2.10)
# ===========================================================================
@endpoint("/_clock/set_current_utc", ["POST"], {"OpsAdmin"})
def set_clock(ctx):
    body = validate(get_body(), [("to_iso8601", "datetime", False, None)])
    db.clock = parse_iso(body["to_iso8601"])
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
