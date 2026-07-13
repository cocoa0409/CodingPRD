"""
Estate-Liquidation Online Auction API — Python + Flask reference implementation.

In-memory only. The store starts empty on every process boot (no seeding).
All structural names (headers, envelope fields, pagination params, error ids,
OCC field) are taken directly from SCAFFOLD.yaml / PRD.md.
"""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_ROLES = {"Operator", "Buyer", "Anonymous"}
SALES_TAX_BPS = 800
SUSPEND_STRIKE_THRESHOLD = 3
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

LOT_STATUSES = {"DRAFT", "CATALOGED", "LISTED", "SELLING", "SOLD", "PASSED",
                "DONATED", "WITHDRAWN"}
DISPUTE_STATUSES = {"OPEN", "UNDER_REVIEW", "NEEDS_INFO", "RESOLVED", "REJECTED"}
CONDITION_GRADES = {"A", "B", "C", "D"}

# ---------------------------------------------------------------------------
# In-memory store (empty at boot)
# ---------------------------------------------------------------------------
estates = {}
lots = {}
photos = {}
buyers = {}
bids = {}
orders = {}
payments = {}
pickup_windows = {}
disputes = {}
donations = {}

_seq_counter = 0
CLOCK = None  # datetime (aware, UTC)


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


def err(error_id, status, message=""):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "." + f"{dt.microsecond // 1000:03d}" + "Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "." + f"{dt.microsecond // 1000:03d}" + "Z"


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def bps(amount_cents, rate_bps):
    """Apply a basis-point rate to a cent amount, round half up to whole cents."""
    val = (Decimal(int(amount_cents)) * Decimal(int(rate_bps)) / Decimal(10000))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def resp_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def resp_array(items, limit, offset, total, has_more):
    m = meta_base()
    m.update({"limit": limit, "offset": offset, "total_count": total, "has_more": has_more})
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.status


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def check_auth(allowed_roles, require_auth=True):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")

    if require_auth:
        if role not in VALID_ROLES:
            err("ERR_UNAUTHENTICATED", 401, "Missing or malformed authentication headers")
        if role == "Buyer" and (uid is None or uid == ""):
            err("ERR_UNAUTHENTICATED", 401, "Buyer identity header missing")

    if role in VALID_ROLES:
        eff = role
    elif role is None or role == "":
        eff = "Anonymous"
    else:
        eff = None  # malformed role value on a no-auth-required endpoint

    if eff is None or eff not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")

    return role, uid


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def get_body():
    return request.get_json(silent=True) or {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", 400, f"Missing field: {field}")
    if not isinstance(body[field], str) or body[field] == "":
        err("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string")
    return body[field]


def opt_str(body, field):
    if field not in body or body[field] is None:
        return None
    if not isinstance(body[field], str):
        err("ERR_VALIDATION", 400, f"Field {field} must be a string")
    return body[field]


def req_int(body, field, minv=None, maxv=None):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", 400, f"Missing field: {field}")
    if not is_int(body[field]):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    v = body[field]
    if minv is not None and v < minv:
        err("ERR_VALIDATION", 400, f"Field {field} must be >= {minv}")
    if maxv is not None and v > maxv:
        err("ERR_VALIDATION", 400, f"Field {field} must be <= {maxv}")
    return v


def opt_int(body, field, minv=None, maxv=None, default=None):
    if field not in body or body[field] is None:
        return default
    if not is_int(body[field]):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    v = body[field]
    if minv is not None and v < minv:
        err("ERR_VALIDATION", 400, f"Field {field} must be >= {minv}")
    if maxv is not None and v > maxv:
        err("ERR_VALIDATION", 400, f"Field {field} must be <= {maxv}")
    return v


def req_datetime(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", 400, f"Missing field: {field}")
    try:
        return parse_dt(body[field])
    except Exception:
        err("ERR_VALIDATION", 400, f"Field {field} must be an ISO 8601 datetime")


def get_pagination():
    limit = 10
    offset = 0
    ls = request.args.get("limit")
    os_ = request.args.get("offset")
    if ls is not None:
        try:
            limit = int(ls)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if os_ is not None:
        try:
            offset = int(os_)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: list already sorted. Returns (page, total, has_more, limit, offset)."""
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, total, has_more, limit, offset


def sorted_by_creation(items):
    return sorted(items, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Entity mutation helpers
# ---------------------------------------------------------------------------
def touch(entity):
    """Bump version + updated_at for a versioned entity."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()


def new_common():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_appendonly():
    return {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def order_charges(order):
    subtotal = sum(int(lots[lid]["hammer_price_cents"] or 0) for lid in order["lot_ids"])
    estate = estates[order["estate_id"]]
    premium = bps(subtotal, estate["buyer_premium_bps"])
    tax = bps(subtotal + premium, SALES_TAX_BPS)
    total = subtotal + premium + tax
    order["subtotal_cents"] = subtotal
    order["buyer_premium_cents"] = premium
    order["sales_tax_cents"] = tax
    order["total_cents"] = total
    charges = sum(int(p["amount_cents"]) for p in payments.values()
                  if p["order_id"] == order["id"] and p["kind"] == "CHARGE")
    refunds = sum(int(p["amount_cents"]) for p in payments.values()
                  if p["order_id"] == order["id"] and p["kind"] == "REFUND")
    order["amount_paid_cents"] = charges - refunds


def recompute_buyer(buyer_id):
    buyer = buyers.get(buyer_id)
    if buyer is None:
        return
    my_orders = [o for o in orders.values() if o["buyer_id"] == buyer_id]
    gross = sum(int(o["total_cents"]) for o in my_orders)
    net = sum(int(o["total_cents"]) for o in my_orders if o["payment_status"] == "UNPAID")
    if buyer["gross_owed_cents"] != gross or buyer["net_owed_cents"] != net:
        buyer["gross_owed_cents"] = gross
        buyer["net_owed_cents"] = net
        touch(buyer)


def estate_lot_count(estate_id):
    return sum(1 for l in lots.values() if l["estate_id"] == estate_id)


def settle_amounts(estate):
    gross = 0
    for lot in lots.values():
        if lot["estate_id"] == estate["id"] and lot["status"] == "SOLD":
            order = orders.get(lot["winning_order_id"])
            if order is not None and order["payment_status"] == "PAID":
                gross += int(lot["hammer_price_cents"] or 0)
    commission = bps(gross, estate["commission_bps"])
    estate["gross_sales_cents"] = gross
    estate["commission_cents"] = commission
    estate["seller_payout_cents"] = gross - commission


def high_bid_of_lot(lot_id):
    for b in bids.values():
        if b["lot_id"] == lot_id and b["is_winning"]:
            return b
    return None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    check_auth(["Operator"], True)
    body = get_body()
    global CLOCK
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        err("ERR_VALIDATION", 400, "Missing field: to_iso8601")
    try:
        CLOCK = parse_dt(body["to_iso8601"])
    except Exception:
        err("ERR_VALIDATION", 400, "to_iso8601 must be an ISO 8601 datetime")
    return resp_object({}, 200)


def clock_now():
    return CLOCK if CLOCK is not None else parse_dt(CLOCK_DEFAULT)


# ===========================================================================
# ESTATE
# ===========================================================================
@app.route("/estates", methods=["POST"])
def create_estate():
    check_auth(["Operator"], True)
    body = get_body()
    seller_name = req_str(body, "seller_name")
    seller_email = req_str(body, "seller_email")
    starts = req_datetime(body, "auction_starts_at")
    ends = req_datetime(body, "auction_ends_at")
    if not (ends > starts):
        err("ERR_VALIDATION", 400, "auction_ends_at must be strictly after auction_starts_at")
    commission_bps = opt_int(body, "commission_bps", 0, 10000, 3500)
    buyer_premium_bps = opt_int(body, "buyer_premium_bps", 0, 10000, 1750)
    soft_close_seconds = opt_int(body, "soft_close_seconds", 0, None, 300)

    e = new_common()
    e.update({
        "seller_name": seller_name,
        "seller_email": seller_email,
        "commission_bps": commission_bps,
        "buyer_premium_bps": buyer_premium_bps,
        "auction_starts_at": body["auction_starts_at"],
        "auction_ends_at": body["auction_ends_at"],
        "soft_close_seconds": soft_close_seconds,
        "extended_count": 0,
        "status": "CATALOGING",
        "lot_count": 0,
        "provisional_gross_cents": 0,
        "gross_sales_cents": 0,
        "commission_cents": 0,
        "seller_payout_cents": 0,
    })
    estates[e["id"]] = e
    return resp_object(serialize(e), 201)


@app.route("/estates/<eid>", methods=["GET"])
def get_estate(eid):
    check_auth(["Operator", "Buyer", "Anonymous"], require_auth=False)
    e = estates.get(eid)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Estate not found")
    return resp_object(serialize(e), 200)


@app.route("/estates/<eid>/lots", methods=["GET"])
def list_estate_lots(eid):
    check_auth(["Operator", "Buyer", "Anonymous"], require_auth=False)
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in LOT_STATUSES:
        err("ERR_VALIDATION", 400, "Invalid status filter")
    limit, offset = get_pagination()
    if estates.get(eid) is None:
        err("ERR_NOT_FOUND", 404, "Estate not found")
    items = [l for l in lots.values() if l["estate_id"] == eid]
    if status_filter is not None:
        items = [l for l in items if l["status"] == status_filter]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(l) for l in page], limit, offset, total, has_more)


@app.route("/estates/<eid>/pickup-windows", methods=["GET"])
def list_estate_windows(eid):
    check_auth(["Operator", "Buyer", "Anonymous"], require_auth=False)
    limit, offset = get_pagination()
    if estates.get(eid) is None:
        err("ERR_NOT_FOUND", 404, "Estate not found")
    items = sorted_by_creation([w for w in pickup_windows.values() if w["estate_id"] == eid])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(w) for w in page], limit, offset, total, has_more)


def _get_estate_or_404(eid):
    e = estates.get(eid)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Estate not found")
    return e


@app.route("/estates/<eid>/open", methods=["POST"])
def estate_open(eid):
    check_auth(["Operator"], True)
    e = _get_estate_or_404(eid)
    if e["status"] != "CATALOGING":
        err("ERR_ESTATE_NOT_CATALOGING", 409, "Estate is not in CATALOGING")
    listed = [l for l in lots.values() if l["estate_id"] == eid and l["status"] == "LISTED"]
    if not listed:
        err("ERR_INVALID_STATE", 409, "Estate has no LISTED lots to open")
    for l in sorted_by_creation(listed):
        l["status"] = "SELLING"
        l["current_bid_cents"] = 0
        touch(l)
    e["status"] = "LIVE"
    touch(e)
    return resp_object(serialize(e), 200)


@app.route("/estates/<eid>/close", methods=["POST"])
def estate_close(eid):
    check_auth(["Operator"], True)
    e = _get_estate_or_404(eid)
    if e["status"] != "LIVE":
        err("ERR_ESTATE_NOT_LIVE", 409, "Estate is not LIVE")

    selling = sorted_by_creation(
        [l for l in lots.values() if l["estate_id"] == eid and l["status"] == "SELLING"])

    provisional = 0
    sold_lots = []
    for lot in selling:
        high = int(lot["current_bid_cents"] or 0)
        if lot["bid_count"] >= 1:
            provisional += high
        reserve_met = (lot["reserve_cents"] is None) or (high >= int(lot["reserve_cents"]))
        if lot["bid_count"] >= 1 and reserve_met:
            lot["status"] = "SOLD"
            lot["hammer_price_cents"] = high
            sold_lots.append(lot)
        else:
            lot["status"] = "PASSED"
        touch(lot)

    # Assemble buyer orders (one per winning buyer for this estate)
    by_buyer = {}
    for lot in sold_lots:
        by_buyer.setdefault(lot["high_bidder_id"], []).append(lot)

    for buyer_id, blots in by_buyer.items():
        order = _find_estate_order(eid, buyer_id)
        created = False
        if order is None:
            order = new_common()
            order.update({
                "estate_id": eid,
                "buyer_id": buyer_id,
                "lot_ids": [],
                "subtotal_cents": 0,
                "buyer_premium_cents": 0,
                "sales_tax_cents": 0,
                "total_cents": 0,
                "amount_paid_cents": 0,
                "payment_status": "UNPAID",
                "pickup_status": "PENDING",
                "pickup_window_id": None,
            })
            orders[order["id"]] = order
            created = True
        for lot in blots:
            order["lot_ids"].append(lot["id"])
            lot["winning_order_id"] = order["id"]
        order_charges(order)
        if not created:
            touch(order)
        recompute_buyer(buyer_id)

    e["provisional_gross_cents"] = provisional
    e["status"] = "CLOSED"
    touch(e)
    return resp_object(serialize(e), 200)


def _find_estate_order(estate_id, buyer_id):
    for o in orders.values():
        if o["estate_id"] == estate_id and o["buyer_id"] == buyer_id:
            return o
    return None


@app.route("/estates/<eid>/settle", methods=["POST"])
def estate_settle(eid):
    check_auth(["Operator"], True)
    e = _get_estate_or_404(eid)
    if e["status"] != "CLOSED":
        err("ERR_ESTATE_NOT_CLOSED", 409, "Estate is not CLOSED")
    settle_amounts(e)
    e["status"] = "SETTLED"
    touch(e)
    return resp_object(serialize(e), 200)


@app.route("/estates/<eid>/cleanout", methods=["POST"])
def estate_cleanout(eid):
    check_auth(["Operator"], True)
    e = _get_estate_or_404(eid)
    if e["status"] != "SETTLED":
        err("ERR_ESTATE_NOT_SETTLED", 409, "Estate is not SETTLED")
    passed = sorted_by_creation(
        [l for l in lots.values() if l["estate_id"] == eid and l["status"] == "PASSED"])
    for lot in passed:
        disposition = "RECYCLED" if lot["condition_grade"] == "D" else "DONATED"
        d = new_appendonly()
        d.update({
            "lot_id": lot["id"],
            "estate_id": eid,
            "recipient": "LOCAL_CHARITY",
            "disposition": disposition,
        })
        donations[d["id"]] = d
        lot["status"] = "DONATED"
        touch(lot)
    e["status"] = "CLEANED_OUT"
    touch(e)
    return resp_object(serialize(e), 200)


# ===========================================================================
# LOT
# ===========================================================================
@app.route("/lots", methods=["POST"])
def create_lot():
    check_auth(["Operator"], True)
    body = get_body()
    estate_id = req_str(body, "estate_id")
    title = req_str(body, "title")
    description = req_str(body, "description")
    category = req_str(body, "category")
    if "condition_grade" not in body or body["condition_grade"] is None:
        err("ERR_VALIDATION", 400, "Missing field: condition_grade")
    condition_grade = body["condition_grade"]
    if condition_grade not in CONDITION_GRADES:
        err("ERR_VALIDATION", 400, "condition_grade must be one of A,B,C,D")
    starting_bid_cents = req_int(body, "starting_bid_cents", minv=1)
    reserve_cents = opt_int(body, "reserve_cents", minv=1, default=None)

    estate = estates.get(estate_id)
    if estate is None:
        err("ERR_NOT_FOUND", 404, "Estate not found")
    if estate["status"] != "CATALOGING":
        err("ERR_ESTATE_NOT_CATALOGING", 409, "Estate is not in CATALOGING")

    l = new_common()
    l.update({
        "estate_id": estate_id,
        "title": title,
        "description": description,
        "category": category,
        "condition_grade": condition_grade,
        "starting_bid_cents": starting_bid_cents,
        "reserve_cents": reserve_cents,
        "current_bid_cents": 0,
        "high_bidder_id": None,
        "bid_count": 0,
        "photo_count": 0,
        "hammer_price_cents": None,
        "winning_order_id": None,
        "status": "DRAFT",
    })
    lots[l["id"]] = l
    estate["lot_count"] = estate_lot_count(estate_id)
    touch(estate)
    return resp_object(serialize(l), 201)


@app.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    check_auth(["Operator", "Buyer", "Anonymous"], require_auth=False)
    l = lots.get(lid)
    if l is None:
        err("ERR_NOT_FOUND", 404, "Lot not found")
    return resp_object(serialize(l), 200)


@app.route("/lots/<lid>/photos", methods=["GET"])
def list_lot_photos(lid):
    check_auth(["Operator", "Buyer", "Anonymous"], require_auth=False)
    limit, offset = get_pagination()
    if lots.get(lid) is None:
        err("ERR_NOT_FOUND", 404, "Lot not found")
    items = sorted_by_creation([p for p in photos.values() if p["lot_id"] == lid])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(p) for p in page], limit, offset, total, has_more)


@app.route("/lots/<lid>", methods=["PATCH"])
def patch_lot(lid):
    check_auth(["Operator"], True)
    body = get_body()

    # body validation (structural)
    if "status" in body and body["status"] is not None:
        if body["status"] not in LOT_STATUSES:
            err("ERR_VALIDATION", 400, "Invalid lot status")
    if "condition_grade" in body and body["condition_grade"] is not None:
        if body["condition_grade"] not in CONDITION_GRADES:
            err("ERR_VALIDATION", 400, "condition_grade must be one of A,B,C,D")
    if "starting_bid_cents" in body and body["starting_bid_cents"] is not None:
        if not is_int(body["starting_bid_cents"]) or body["starting_bid_cents"] < 1:
            err("ERR_VALIDATION", 400, "starting_bid_cents must be an integer >= 1")
    if "reserve_cents" in body and body["reserve_cents"] is not None:
        if not is_int(body["reserve_cents"]) or body["reserve_cents"] < 1:
            err("ERR_VALIDATION", 400, "reserve_cents must be an integer >= 1")
    for f in ("title", "description", "category"):
        if f in body and body[f] is not None and not isinstance(body[f], str):
            err("ERR_VALIDATION", 400, f"{f} must be a string")

    l = lots.get(lid)
    if l is None:
        err("ERR_NOT_FOUND", 404, "Lot not found")
    estate = estates.get(l["estate_id"])

    # Status transition path
    if "status" in body and body["status"] is not None:
        target = body["status"]
        cur = l["status"]
        if (cur, target) == ("DRAFT", "CATALOGED"):
            if estate["status"] != "CATALOGING":
                err("ERR_ESTATE_NOT_CATALOGING", 409, "Estate is not in CATALOGING")
            if l["photo_count"] < 1:
                err("ERR_INVALID_STATE", 409, "Lot needs at least one photo to be cataloged")
            l["status"] = "CATALOGED"
            touch(l)
        elif (cur, target) == ("CATALOGED", "LISTED"):
            if estate["status"] != "CATALOGING":
                err("ERR_ESTATE_NOT_CATALOGING", 409, "Estate is not in CATALOGING")
            l["status"] = "LISTED"
            touch(l)
        elif (cur, target) == ("PASSED", "WITHDRAWN"):
            l["status"] = "WITHDRAWN"
            touch(l)
        elif cur == target:
            # no-op transition to same status is not a legal move
            err("ERR_INVALID_STATE", 409, "Illegal lot status transition")
        else:
            err("ERR_INVALID_STATE", 409, "Illegal lot status transition")
        return resp_object(serialize(l), 200)

    # Field edit path (only while DRAFT)
    editable = ("title", "description", "category", "condition_grade",
                "starting_bid_cents", "reserve_cents")
    provided = [f for f in editable if f in body]
    if provided:
        if l["status"] != "DRAFT":
            err("ERR_INVALID_STATE", 409, "Lot fields can only be edited while DRAFT")
        for f in provided:
            l[f] = body[f]
        touch(l)
    return resp_object(serialize(l), 200)


# ===========================================================================
# PHOTO
# ===========================================================================
@app.route("/photos", methods=["POST"])
def create_photo():
    check_auth(["Operator"], True)
    body = get_body()
    lot_id = req_str(body, "lot_id")
    image_url = req_str(body, "image_url")
    caption = opt_str(body, "caption")
    condition_note = opt_str(body, "condition_note")
    is_primary = body.get("is_primary", False)
    if is_primary is None:
        is_primary = False
    if not isinstance(is_primary, bool):
        err("ERR_VALIDATION", 400, "is_primary must be a boolean")

    lot = lots.get(lot_id)
    if lot is None:
        err("ERR_NOT_FOUND", 404, "Lot not found")
    estate = estates.get(lot["estate_id"])
    if estate["status"] != "CATALOGING":
        err("ERR_ESTATE_NOT_CATALOGING", 409, "Estate is not in CATALOGING")
    if lot["status"] not in ("DRAFT", "CATALOGED"):
        err("ERR_INVALID_STATE", 409, "Lot must be DRAFT or CATALOGED to attach a photo")

    p = new_appendonly()
    p.update({
        "lot_id": lot_id,
        "image_url": image_url,
        "caption": caption,
        "condition_note": condition_note,
        "is_primary": is_primary,
    })
    photos[p["id"]] = p
    lot["photo_count"] = lot["photo_count"] + 1
    touch(lot)
    return resp_object(serialize(p), 201)


# ===========================================================================
# BUYER
# ===========================================================================
@app.route("/buyers", methods=["POST"])
def create_buyer():
    check_auth(["Anonymous"], require_auth=False)
    body = get_body()
    display_name = req_str(body, "display_name")
    email = req_str(body, "email")
    b = new_common()
    b.update({
        "display_name": display_name,
        "email": email,
        "status": "REGISTERED",
        "no_show_strikes": 0,
        "gross_owed_cents": 0,
        "net_owed_cents": 0,
    })
    buyers[b["id"]] = b
    return resp_object(serialize(b), 201)


@app.route("/buyers/<bid>", methods=["GET"])
def get_buyer(bid):
    check_auth(["Operator", "Buyer"], True)
    b = buyers.get(bid)
    if b is None:
        err("ERR_NOT_FOUND", 404, "Buyer not found")
    return resp_object(serialize(b), 200)


@app.route("/buyers/<bid>/verify", methods=["POST"])
def verify_buyer(bid):
    check_auth(["Operator"], True)
    b = buyers.get(bid)
    if b is None:
        err("ERR_NOT_FOUND", 404, "Buyer not found")
    if b["status"] != "REGISTERED":
        err("ERR_INVALID_STATE", 409, "Buyer is not in REGISTERED")
    b["status"] = "VERIFIED"
    touch(b)
    return resp_object(serialize(b), 200)


# ===========================================================================
# BID
# ===========================================================================
def min_next_bid(lot):
    if int(lot["current_bid_cents"] or 0) == 0:
        return int(lot["starting_bid_cents"])
    c = int(lot["current_bid_cents"])
    if c < 2500:
        step = 100
    elif c < 10000:
        step = 250
    elif c < 50000:
        step = 1000
    else:
        step = 2500
    return c + step


@app.route("/bids", methods=["POST"])
def create_bid():
    role, uid = check_auth(["Buyer"], True)
    body = get_body()
    lot_id = req_str(body, "lot_id")
    buyer_id = req_str(body, "buyer_id")
    amount_cents = req_int(body, "amount_cents", minv=1)
    expected_lot_version = req_int(body, "expected_lot_version", minv=0)

    # existence (left to right: lot then buyer)
    lot = lots.get(lot_id)
    if lot is None:
        err("ERR_NOT_FOUND", 404, "Lot not found")
    buyer = buyers.get(buyer_id)
    if buyer is None:
        err("ERR_NOT_FOUND", 404, "Buyer not found")

    # cross-owner
    if buyer_id != uid:
        err("ERR_CROSS_OWNER", 403, "Bidding buyer must match X-User-ID")

    # lot state
    if lot["status"] != "SELLING":
        err("ERR_LOT_NOT_SELLING", 409, "Lot is not SELLING")

    # buyer verification / suspension
    if buyer["status"] == "REGISTERED":
        err("ERR_BUYER_NOT_VERIFIED", 409, "Buyer is not VERIFIED")
    if buyer["status"] == "SUSPENDED":
        err("ERR_BUYER_SUSPENDED", 409, "Buyer is SUSPENDED")

    # min increment
    if amount_cents < min_next_bid(lot):
        err("ERR_BID_TOO_LOW", 409, "Bid below the minimum next amount")

    # OCC
    if expected_lot_version != lot["version"]:
        err("ERR_STALE_VERSION", 412, "expected_lot_version does not match current lot version")

    # Accept the bid
    prev = high_bid_of_lot(lot_id)
    if prev is not None:
        prev["status"] = "OUTBID"
        prev["is_winning"] = False

    b = new_appendonly()
    b.update({
        "lot_id": lot_id,
        "buyer_id": buyer_id,
        "amount_cents": amount_cents,
        "expected_lot_version": expected_lot_version,
        "status": "ACCEPTED",
        "is_winning": True,
    })
    bids[b["id"]] = b

    lot["current_bid_cents"] = amount_cents
    lot["high_bidder_id"] = buyer_id
    lot["bid_count"] = lot["bid_count"] + 1
    touch(lot)

    # Soft-close extension
    estate = estates.get(lot["estate_id"])
    try:
        ends = parse_dt(estate["auction_ends_at"])
        now = clock_now()
        soft = int(estate["soft_close_seconds"])
        if (ends - timedelta(seconds=soft)) <= now < ends:
            estate["auction_ends_at"] = normalize_dt(ends + timedelta(seconds=soft))
            estate["extended_count"] = estate["extended_count"] + 1
            touch(estate)
    except Exception:
        pass

    return resp_object(serialize(b), 201)


@app.route("/bids/<bid>", methods=["GET"])
def get_bid(bid):
    check_auth(["Operator", "Buyer"], True)
    b = bids.get(bid)
    if b is None:
        err("ERR_NOT_FOUND", 404, "Bid not found")
    return resp_object(serialize(b), 200)


@app.route("/bids", methods=["GET"])
def list_bids():
    check_auth(["Operator", "Buyer"], True)
    limit, offset = get_pagination()
    lot_id = request.args.get("lot_id")
    buyer_id = request.args.get("buyer_id")
    items = list(bids.values())
    if lot_id is not None:
        items = [b for b in items if b["lot_id"] == lot_id]
    if buyer_id is not None:
        items = [b for b in items if b["buyer_id"] == buyer_id]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(b) for b in page], limit, offset, total, has_more)


# ===========================================================================
# ORDER
# ===========================================================================
@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    check_auth(["Operator", "Buyer"], True)
    o = orders.get(oid)
    if o is None:
        err("ERR_NOT_FOUND", 404, "Order not found")
    return resp_object(serialize(o), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    check_auth(["Operator", "Buyer"], True)
    limit, offset = get_pagination()
    estate_id = request.args.get("estate_id")
    buyer_id = request.args.get("buyer_id")
    pickup_window_id = request.args.get("pickup_window_id")
    items = list(orders.values())
    if estate_id is not None:
        items = [o for o in items if o["estate_id"] == estate_id]
    if buyer_id is not None:
        items = [o for o in items if o["buyer_id"] == buyer_id]
    if pickup_window_id is not None:
        items = [o for o in items if o["pickup_window_id"] == pickup_window_id]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(o) for o in page], limit, offset, total, has_more)


@app.route("/orders/<oid>/payments", methods=["GET"])
def list_order_payments(oid):
    check_auth(["Operator", "Buyer"], True)
    limit, offset = get_pagination()
    if orders.get(oid) is None:
        err("ERR_NOT_FOUND", 404, "Order not found")
    items = sorted_by_creation([p for p in payments.values() if p["order_id"] == oid])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(p) for p in page], limit, offset, total, has_more)


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    role, uid = check_auth(["Buyer"], True)
    body = get_body()
    amount_cents = req_int(body, "amount_cents", minv=1)

    o = orders.get(oid)
    if o is None:
        err("ERR_NOT_FOUND", 404, "Order not found")
    if o["buyer_id"] != uid:
        err("ERR_CROSS_OWNER", 403, "Order does not belong to acting buyer")
    if o["payment_status"] != "UNPAID":
        err("ERR_ORDER_ALREADY_PAID", 409, "Order is not UNPAID")
    buyer = buyers.get(o["buyer_id"])
    if buyer is not None and buyer["status"] == "SUSPENDED":
        err("ERR_BUYER_SUSPENDED", 409, "Buyer is SUSPENDED")
    if amount_cents < o["total_cents"]:
        err("ERR_INSUFFICIENT_PAYMENT", 402, "Payment does not cover the order total")

    p = new_appendonly()
    p.update({
        "order_id": oid,
        "kind": "CHARGE",
        "amount_cents": amount_cents,
        "note": opt_str(body, "note"),
    })
    payments[p["id"]] = p
    order_charges(o)
    if o["amount_paid_cents"] >= o["total_cents"]:
        o["payment_status"] = "PAID"
    touch(o)
    recompute_buyer(o["buyer_id"])
    return resp_object(serialize(o), 200)


@app.route("/orders/<oid>/schedule-pickup", methods=["POST"])
def schedule_pickup(oid):
    role, uid = check_auth(["Buyer"], True)
    body = get_body()
    window_id = req_str(body, "pickup_window_id")

    o = orders.get(oid)
    if o is None:
        err("ERR_NOT_FOUND", 404, "Order not found")
    window = pickup_windows.get(window_id)
    if window is None:
        err("ERR_NOT_FOUND", 404, "Pickup window not found")
    if o["buyer_id"] != uid:
        err("ERR_CROSS_OWNER", 403, "Order does not belong to acting buyer")

    if o["payment_status"] != "PAID":
        err("ERR_ORDER_NOT_PAID", 409, "Order is not PAID")
    if o["pickup_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Order pickup is not PENDING")

    if window["estate_id"] != o["estate_id"]:
        err("ERR_WINDOW_ESTATE_MISMATCH", 409, "Window belongs to a different estate")

    # buyer pickup non-overlap (closed interval) vs buyer's other held windows
    chosen_s = parse_dt(window["starts_at"])
    chosen_e = parse_dt(window["ends_at"])
    for other in orders.values():
        if other["id"] == oid:
            continue
        if other["buyer_id"] != o["buyer_id"]:
            continue
        if other["pickup_status"] not in ("SCHEDULED", "PICKED_UP"):
            continue
        if other["pickup_window_id"] is None:
            continue
        ow = pickup_windows.get(other["pickup_window_id"])
        if ow is None:
            continue
        os_ = parse_dt(ow["starts_at"])
        oe = parse_dt(ow["ends_at"])
        if chosen_s <= oe and os_ <= chosen_e:
            err("ERR_PICKUP_OVERLAP", 409, "Chosen window collides with another the buyer holds")

    if window["booked_count"] >= window["capacity"]:
        err("ERR_WINDOW_FULL", 409, "Pickup window is full")

    o["pickup_window_id"] = window_id
    o["pickup_status"] = "SCHEDULED"
    touch(o)
    window["booked_count"] = window["booked_count"] + 1
    touch(window)
    return resp_object(serialize(o), 200)


@app.route("/orders/<oid>/cancel-pickup", methods=["POST"])
def cancel_pickup(oid):
    role, uid = check_auth(["Buyer"], True)
    o = orders.get(oid)
    if o is None:
        err("ERR_NOT_FOUND", 404, "Order not found")
    if o["buyer_id"] != uid:
        err("ERR_CROSS_OWNER", 403, "Order does not belong to acting buyer")
    if o["pickup_status"] != "SCHEDULED":
        err("ERR_PICKUP_NOT_SCHEDULED", 409, "Order pickup is not SCHEDULED")

    window = pickup_windows.get(o["pickup_window_id"])
    if window is not None:
        window["booked_count"] = max(0, window["booked_count"] - 1)
        touch(window)
    o["pickup_window_id"] = None
    o["pickup_status"] = "PENDING"
    touch(o)
    return resp_object(serialize(o), 200)


@app.route("/orders/<oid>/complete-pickup", methods=["POST"])
def complete_pickup(oid):
    check_auth(["Operator"], True)
    body = get_body()
    if "result" not in body or body["result"] is None:
        err("ERR_VALIDATION", 400, "Missing field: result")
    result = body["result"]
    if result not in ("PICKED_UP", "NO_SHOW"):
        err("ERR_VALIDATION", 400, "result must be PICKED_UP or NO_SHOW")

    o = orders.get(oid)
    if o is None:
        err("ERR_NOT_FOUND", 404, "Order not found")
    if o["pickup_status"] != "SCHEDULED":
        err("ERR_PICKUP_NOT_SCHEDULED", 409, "Order pickup is not SCHEDULED")

    if result == "PICKED_UP":
        o["pickup_status"] = "PICKED_UP"
        touch(o)
    else:
        o["pickup_status"] = "NO_SHOW"
        touch(o)
        window = pickup_windows.get(o["pickup_window_id"])
        if window is not None:
            window["booked_count"] = max(0, window["booked_count"] - 1)
            touch(window)
        buyer = buyers.get(o["buyer_id"])
        if buyer is not None:
            buyer["no_show_strikes"] = buyer["no_show_strikes"] + 1
            if buyer["no_show_strikes"] >= SUSPEND_STRIKE_THRESHOLD and buyer["status"] == "VERIFIED":
                buyer["status"] = "SUSPENDED"
            touch(buyer)
    return resp_object(serialize(o), 200)


# ===========================================================================
# PICKUP WINDOW
# ===========================================================================
@app.route("/pickup-windows", methods=["POST"])
def create_pickup_window():
    check_auth(["Operator"], True)
    body = get_body()
    estate_id = req_str(body, "estate_id")
    starts = req_datetime(body, "starts_at")
    ends = req_datetime(body, "ends_at")
    if not (ends > starts):
        err("ERR_VALIDATION", 400, "ends_at must be strictly after starts_at")
    capacity = req_int(body, "capacity", minv=1)
    label = opt_str(body, "label")

    estate = estates.get(estate_id)
    if estate is None:
        err("ERR_NOT_FOUND", 404, "Estate not found")

    # half-open overlap vs existing windows of the same estate
    for w in pickup_windows.values():
        if w["estate_id"] != estate_id:
            continue
        ws = parse_dt(w["starts_at"])
        we = parse_dt(w["ends_at"])
        if starts < we and ws < ends:
            err("ERR_WINDOW_OVERLAP", 409, "New window overlaps an existing window")

    w = new_common()
    w.update({
        "estate_id": estate_id,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "capacity": capacity,
        "booked_count": 0,
        "label": label,
    })
    pickup_windows[w["id"]] = w
    return resp_object(serialize(w), 201)


# ===========================================================================
# DISPUTE
# ===========================================================================
@app.route("/disputes", methods=["POST"])
def create_dispute():
    role, uid = check_auth(["Buyer"], True)
    body = get_body()
    order_id = req_str(body, "order_id")
    lot_id = req_str(body, "lot_id")
    reason = req_str(body, "reason")

    o = orders.get(order_id)
    if o is None:
        err("ERR_NOT_FOUND", 404, "Order not found")
    lot = lots.get(lot_id)
    if lot is None:
        err("ERR_NOT_FOUND", 404, "Lot not found")

    if o["buyer_id"] != uid:
        err("ERR_CROSS_OWNER", 403, "Order does not belong to acting buyer")

    if o["payment_status"] != "PAID":
        err("ERR_INVALID_STATE", 409, "Order must be PAID to dispute")

    if lot_id not in o["lot_ids"]:
        err("ERR_LOT_NOT_IN_ORDER", 409, "Lot is not part of the disputed order")

    d = new_common()
    d.update({
        "order_id": order_id,
        "lot_id": lot_id,
        "reason": reason,
        "status": "OPEN",
        "outcome": None,
        "resolution_note": None,
    })
    disputes[d["id"]] = d
    return resp_object(serialize(d), 201)


@app.route("/disputes/<did>", methods=["GET"])
def get_dispute(did):
    check_auth(["Operator", "Buyer"], True)
    d = disputes.get(did)
    if d is None:
        err("ERR_NOT_FOUND", 404, "Dispute not found")
    return resp_object(serialize(d), 200)


@app.route("/disputes", methods=["GET"])
def list_disputes():
    check_auth(["Operator", "Buyer"], True)
    limit, offset = get_pagination()
    order_id = request.args.get("order_id")
    lot_id = request.args.get("lot_id")
    items = list(disputes.values())
    if order_id is not None:
        items = [d for d in items if d["order_id"] == order_id]
    if lot_id is not None:
        items = [d for d in items if d["lot_id"] == lot_id]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(d) for d in page], limit, offset, total, has_more)


@app.route("/disputes/<did>", methods=["PATCH"])
def patch_dispute(did):
    role, uid = check_auth(["Operator", "Buyer"], True)
    body = get_body()
    if "status" not in body or body["status"] is None:
        err("ERR_VALIDATION", 400, "Missing field: status")
    target = body["status"]
    if target not in DISPUTE_STATUSES:
        err("ERR_VALIDATION", 400, "Invalid dispute status")
    resolution_note = opt_str(body, "resolution_note")

    d = disputes.get(did)
    if d is None:
        err("ERR_NOT_FOUND", 404, "Dispute not found")
    order = orders.get(d["order_id"])

    cur = d["status"]

    if role == "Buyer":
        # ownership of the disputed order
        if order is None or order["buyer_id"] != uid:
            err("ERR_CROSS_OWNER", 403, "Dispute order does not belong to acting buyer")
        # only legal buyer transition
        if (cur, target) != ("NEEDS_INFO", "UNDER_REVIEW"):
            err("ERR_INVALID_STATE", 409, "Illegal dispute transition for buyer")
        d["status"] = "UNDER_REVIEW"
        if resolution_note is not None:
            d["resolution_note"] = resolution_note
        touch(d)
        return resp_object(serialize(d), 200)

    # Operator transitions
    if (cur, target) == ("OPEN", "UNDER_REVIEW"):
        d["status"] = "UNDER_REVIEW"
        if resolution_note is not None:
            d["resolution_note"] = resolution_note
        touch(d)
    elif (cur, target) == ("UNDER_REVIEW", "NEEDS_INFO"):
        d["status"] = "NEEDS_INFO"
        if resolution_note is not None:
            d["resolution_note"] = resolution_note
        touch(d)
    elif (cur, target) == ("UNDER_REVIEW", "REJECTED"):
        d["status"] = "REJECTED"
        d["outcome"] = "SELLER_FAVOR"
        if resolution_note is not None:
            d["resolution_note"] = resolution_note
        touch(d)
    elif (cur, target) == ("UNDER_REVIEW", "RESOLVED"):
        d["status"] = "RESOLVED"
        d["outcome"] = "BUYER_FAVOR"
        if resolution_note is not None:
            d["resolution_note"] = resolution_note
        touch(d)
        _resolve_buyer_favor(d)
    else:
        err("ERR_INVALID_STATE", 409, "Illegal dispute transition")

    return resp_object(serialize(d), 200)


def _resolve_buyer_favor(dispute):
    order = orders.get(dispute["order_id"])
    lot = lots.get(dispute["lot_id"])
    if order is None or lot is None:
        return

    # hop 1: compute refund as marginal share; remove lot; recompute totals
    total_before = order["total_cents"]
    if lot["id"] in order["lot_ids"]:
        order["lot_ids"].remove(lot["id"])
    order_charges(order)
    refund_amount = total_before - order["total_cents"]

    ref = new_appendonly()
    ref.update({
        "order_id": order["id"],
        "kind": "REFUND",
        "amount_cents": refund_amount,
        "note": "Dispute reversal refund",
    })
    payments[ref["id"]] = ref
    order["payment_status"] = "REFUNDED"
    order_charges(order)  # recompute amount_paid including the refund
    touch(order)

    # hop 2: lot SOLD -> PASSED, clear sale fields, winning bid is_winning=false
    win_bid = high_bid_of_lot(lot["id"])
    if win_bid is not None:
        win_bid["is_winning"] = False
    lot["status"] = "PASSED"
    lot["hammer_price_cents"] = None
    lot["winning_order_id"] = None
    touch(lot)

    # hop 3: buyer ledgers
    recompute_buyer(order["buyer_id"])

    # hop 4: re-derive estate settlement if already SETTLED
    estate = estates.get(order["estate_id"])
    if estate is not None and estate["status"] == "SETTLED":
        settle_amounts(estate)
        touch(estate)


# ===========================================================================
# DONATION
# ===========================================================================
@app.route("/donations/<did>", methods=["GET"])
def get_donation(did):
    check_auth(["Operator", "Buyer", "Anonymous"], require_auth=False)
    d = donations.get(did)
    if d is None:
        err("ERR_NOT_FOUND", 404, "Donation not found")
    return resp_object(serialize(d), 200)


@app.route("/donations", methods=["GET"])
def list_donations():
    check_auth(["Operator", "Buyer", "Anonymous"], require_auth=False)
    limit, offset = get_pagination()
    lot_id = request.args.get("lot_id")
    estate_id = request.args.get("estate_id")
    items = list(donations.values())
    if lot_id is not None:
        items = [d for d in items if d["lot_id"] == lot_id]
    if estate_id is not None:
        items = [d for d in items if d["estate_id"] == estate_id]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return resp_array([serialize(d) for d in page], limit, offset, total, has_more)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
