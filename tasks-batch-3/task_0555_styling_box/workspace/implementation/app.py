"""Styling Box API — Personal Styling Subscription Box (Stitch Fix style).

Python + Flask, in-memory only. State starts empty on every boot; every entity
is constructed by tests via the declared endpoints. No seeding, no persistence.
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculations + PRD §3)
# ---------------------------------------------------------------------------
RECOGNIZED_ROLES = {"Anonymous", "Client", "Stylist", "OpsAdmin"}

STYLING_FEE_CENTS = 2000
BUY_THE_LOOK_DISCOUNT_PCT = Decimal("0.25")
SHIPPING_FEE_CENTS = 795
FREE_SHIP_NET_THRESHOLD_CENTS = 7500
TRY_AT_HOME_DAYS = 3
MIN_ITEMS = 3
MAX_ITEMS = 5

TAX_RATE = {"CA": Decimal("0.0725"), "NY": Decimal("0.04"), "OR": Decimal("0")}
CADENCE_DAYS = {"EVERY_2_WEEKS": 14, "MONTHLY": 30, "EVERY_2_MONTHS": 60, "QUARTERLY": 90}
CADENCE_VALUES = set(CADENCE_DAYS.keys())
REGION_VALUES = {"CA", "NY", "OR"}
PRICE_TIERS = {"BUDGET", "MID", "PREMIUM"}
CATEGORIES = {"TOP", "BOTTOM", "SHOE", "ACCESSORY"}
RATINGS = {"TOO_SMALL", "SLIGHTLY_SMALL", "PERFECT", "SLIGHTLY_LARGE", "TOO_LARGE"}

ADJUSTMENT = {
    "TOO_SMALL": Decimal("1"),
    "SLIGHTLY_SMALL": Decimal("0.5"),
    "PERFECT": Decimal("0"),
    "SLIGHTLY_LARGE": Decimal("-0.5"),
    "TOO_LARGE": Decimal("-1"),
}
MATCH = {
    "PERFECT": Decimal("1"),
    "SLIGHTLY_SMALL": Decimal("0.6"),
    "SLIGHTLY_LARGE": Decimal("0.6"),
    "TOO_SMALL": Decimal("0"),
    "TOO_LARGE": Decimal("0"),
}

DECAY = Decimal("0.5")

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0)

# ---------------------------------------------------------------------------
# In-memory store (empty on boot)
# ---------------------------------------------------------------------------
DB = {
    "clients": {},
    "style_profiles": {},
    "products": {},
    "stylists": {},
    "fixes": {},
    "fix_items": {},
    "feedback": {},
    "returns": {},
    "holds": {},
    "purchases": {},
}
CLOCK = {"now": DEFAULT_CLOCK}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now():
    return CLOCK["now"]


def fmt_ts(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?)?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(s):
    """Parse an ISO-8601 string into a naive UTC datetime (py3.9 safe)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    m = _ISO_RE.match(s.strip())
    if not m:
        raise ValueError("bad iso: %s" % s)
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    hh = int(hh) if hh is not None else 0
    mm = int(mm) if mm is not None else 0
    ss = int(ss) if ss is not None else 0
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    dt = datetime(int(y), int(mo), int(d), hh, mm, ss, micro)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        off = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * off
    return dt


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": fmt_ts(now())}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_list(items, limit, offset, total, code=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _nf(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def _mna(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(*allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in RECOGNIZED_ROLES or not uid:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_common():
    ts = fmt_ts(now())
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def base_event():
    return {"id": new_id(), "created_at": fmt_ts(now())}


def touch(entity):
    entity["updated_at"] = fmt_ts(now())
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "Malformed request body")
    return b


def _bad(msg="Invalid request body"):
    raise ApiError("ERR_VALIDATION", 422, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        _bad("Field '%s' must be a non-empty string" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        _bad("Field '%s' must be a string" % key)
    return v


def req_int(body, key, minimum=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field '%s' must be an integer" % key)
    if minimum is not None and v < minimum:
        _bad("Field '%s' must be >= %d" % (key, minimum))
    return v


def opt_int(body, key, default=None, minimum=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, minimum)


def req_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        _bad("Field '%s' must be one of %s" % (key, sorted(allowed)))
    return v


def opt_array(body, key, default=None):
    if key not in body or body[key] is None:
        return [] if default is None else default
    v = body[key]
    if not isinstance(v, list):
        _bad("Field '%s' must be an array" % key)
    return v


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_client(cid):
    c = DB["clients"].get(cid)
    if not c:
        raise ApiError("ERR_CLIENT_NOT_FOUND", 404, "Client not found")
    return c


def get_fix(fid):
    f = DB["fixes"].get(fid)
    if not f:
        raise ApiError("ERR_FIX_NOT_FOUND", 404, "Fix not found")
    return f


def get_product(pid):
    p = DB["products"].get(pid)
    if not p:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "Product not found")
    return p


def get_stylist(sid):
    s = DB["stylists"].get(sid)
    if not s:
        raise ApiError("ERR_STYLIST_NOT_FOUND", 404, "Stylist not found")
    return s


def get_purchase(pid):
    p = DB["purchases"].get(pid)
    if not p:
        raise ApiError("ERR_PURCHASE_NOT_FOUND", 404, "Purchase not found")
    return p


def get_return_of_fix(fid, rid):
    r = DB["returns"].get(rid)
    if not r or r["fix_id"] != fid:
        raise ApiError("ERR_RETURN_NOT_FOUND", 404, "Return shipment not found")
    return r


def get_fixitem_of_fix(fid, iid):
    i = DB["fix_items"].get(iid)
    if not i or i["fix_id"] != fid:
        raise ApiError("ERR_FIXITEM_NOT_FOUND", 404, "Fix item not found")
    return i


def items_of_fix(fid):
    return [i for i in DB["fix_items"].values() if i["fix_id"] == fid]


def profile_of_client(cid):
    for sp in DB["style_profiles"].values():
        if sp["client_id"] == cid:
            return sp
    return None


# ---------------------------------------------------------------------------
# Inventory operations (PRD §2.7)
# ---------------------------------------------------------------------------
def inv_reserve(p):
    p["available_count"] -= 1
    p["reserved_count"] += 1
    touch(p)


def inv_sell_from_reserve(p):
    p["reserved_count"] -= 1
    p["sold_count"] += 1
    touch(p)


def inv_release(p):
    p["reserved_count"] -= 1
    p["available_count"] += 1
    touch(p)


def inv_direct_sell(p, q):
    p["available_count"] -= q
    p["sold_count"] += q
    touch(p)


def inv_compensate(p, q):
    p["sold_count"] -= q
    p["available_count"] += q
    touch(p)


def inv_restock(p, q):
    p["total_stock"] += q
    p["available_count"] += q
    touch(p)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def rhu(dec):
    return int(dec.to_integral_value(rounding=ROUND_HALF_UP))


def compute_fix_charge(kept_items, item_count, region_code):
    subtotal = sum(i["price_cents"] for i in kept_items)
    k = len(kept_items)
    all_kept = (k == item_count) and (item_count >= 1)
    discount = rhu(Decimal(subtotal) * BUY_THE_LOOK_DISCOUNT_PCT) if all_kept else 0
    credit = STYLING_FEE_CENTS if k >= 1 else 0
    net = max(0, subtotal - discount - credit)
    if k == 0:
        shipping = 0
    elif net >= FREE_SHIP_NET_THRESHOLD_CENTS:
        shipping = 0
    else:
        shipping = SHIPPING_FEE_CENTS
    taxable = net + shipping
    tax = rhu(Decimal(taxable) * TAX_RATE[region_code])
    total = taxable + tax
    return {
        "subtotal": subtotal,
        "all_kept": all_kept,
        "discount": discount,
        "credit": credit,
        "net": net,
        "shipping": shipping,
        "tax": tax,
        "total": total,
    }


def _sorted_recent(rows):
    """Most-recent-first by created_at; ties broken by fix item created_at ASC."""
    def fi_created(f):
        fi = DB["fix_items"].get(f["fix_item_id"])
        return fi["created_at"] if fi else f["created_at"]
    rows = sorted(rows, key=fi_created)              # secondary: fix item created ASC
    rows = sorted(rows, key=lambda f: f["created_at"], reverse=True)  # primary: created DESC
    return rows


def _implied(f):
    return Decimal(f["product_size"]) + ADJUSTMENT[f["rating"]]


def recompute_style_profile(client_id):
    sp = profile_of_client(client_id)
    if not sp:
        return
    fbs = [f for f in DB["feedback"].values() if f["client_id"] == client_id]

    # learned sizes per category
    cat_field = {"TOP": ("learned_top_size", "quiz_top_size", "weighted"),
                 "BOTTOM": ("learned_bottom_size", "quiz_bottom_size", "weighted"),
                 "SHOE": ("learned_shoe_size", "quiz_shoe_size", "latest")}
    for cat, (field, quiz_field, variant) in cat_field.items():
        rows = _sorted_recent([f for f in fbs if f["category"] == cat])
        if not rows:
            sp[field] = sp[quiz_field]
            continue
        if variant == "latest":
            sp[field] = rhu(_implied(rows[0]))
        else:
            num = Decimal(0)
            den = Decimal(0)
            for r, f in enumerate(rows):
                w = DECAY ** r
                num += w * _implied(f)
                den += w
            sp[field] = rhu(num / den)

    # fit confidence over all feedback
    if not fbs:
        sp["fit_confidence"] = 0
    else:
        total_match = sum((MATCH[f["rating"]] for f in fbs), Decimal(0))
        sp["fit_confidence"] = rhu(Decimal(100) * total_match / Decimal(len(fbs)))

    touch(sp)


def stylist_active_count(sid):
    return len([f for f in DB["fixes"].values()
                if f["stylist_id"] == sid and f["status"] in ("STYLING", "PREVIEW", "SHIPPED", "DELIVERED")])


def recompute_stylist(sid):
    if sid and sid in DB["stylists"]:
        touch(DB["stylists"][sid])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_client(c):
    return {k: c[k] for k in ("id", "created_at", "updated_at", "version",
                              "email", "full_name", "region_code", "cadence", "status")}


def ser_profile(sp):
    fbc = len([f for f in DB["feedback"].values() if f["client_id"] == sp["client_id"]])
    return {
        "id": sp["id"], "created_at": sp["created_at"], "updated_at": sp["updated_at"],
        "version": sp["version"], "client_id": sp["client_id"],
        "quiz_top_size": sp["quiz_top_size"], "quiz_bottom_size": sp["quiz_bottom_size"],
        "quiz_shoe_size": sp["quiz_shoe_size"], "price_tier": sp["price_tier"],
        "style_tags": sp["style_tags"],
        "learned_top_size": sp["learned_top_size"], "learned_bottom_size": sp["learned_bottom_size"],
        "learned_shoe_size": sp["learned_shoe_size"], "fit_confidence": sp["fit_confidence"],
        "feedback_count": fbc,
    }


def ser_product(p):
    return {k: p[k] for k in ("id", "created_at", "updated_at", "version",
                              "sku", "name", "category", "size", "price_cents", "style_tags",
                              "status", "total_stock", "available_count", "reserved_count", "sold_count")}


def ser_stylist(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "email": s["email"], "name": s["name"],
        "max_concurrent_fixes": s["max_concurrent_fixes"], "status": s["status"],
        "active_fix_count": stylist_active_count(s["id"]),
    }


def ser_fix(f):
    items = items_of_fix(f["id"])
    counted = [i for i in items if i["status"] in ("SELECTED", "KEPT", "RETURNED")]
    item_count = len(counted)
    kept_count = len([i for i in items if i["status"] == "KEPT"])
    returned_count = len([i for i in items if i["status"] == "RETURNED"])
    subtotal = f.get("subtotal_cents")
    if subtotal is None:
        subtotal = sum(i["price_cents"] for i in counted)
    return {
        "id": f["id"], "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"], "client_id": f["client_id"], "stylist_id": f["stylist_id"],
        "status": f["status"],
        "scheduled_ship_date": fmt_ts(f["scheduled_ship_date"]),
        "shipped_at": fmt_ts(f["shipped_at"]),
        "delivered_at": fmt_ts(f["delivered_at"]),
        "checkout_deadline": fmt_ts(f["checkout_deadline"]),
        "item_count": item_count, "kept_count": kept_count, "returned_count": returned_count,
        "subtotal_cents": subtotal,
        "estimated_charge_cents": f["estimated_charge_cents"],
        "charge_cents": f["charge_cents"],
        "buy_the_look_applied": f["buy_the_look_applied"],
        "shipping_fee_cents": f["shipping_fee_cents"],
        "tax_cents": f["tax_cents"],
        "styling_fee_charged_cents": f["styling_fee_charged_cents"],
        "styling_fee_credit_cents": f["styling_fee_credit_cents"],
        "styling_fee_forfeited_cents": f["styling_fee_forfeited_cents"],
    }


def ser_item(i):
    return {k: i[k] for k in ("id", "created_at", "updated_at", "version",
                              "fix_id", "product_id", "price_cents", "size", "category", "status")}


def ser_feedback(f):
    return {k: f[k] for k in ("id", "created_at", "client_id", "fix_item_id",
                              "product_size", "category", "rating")}


def ser_return(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "fix_id": r["fix_id"], "status": r["status"],
        "item_ids": r["item_ids"], "received_at": fmt_ts(r["received_at"]),
    }


def ser_hold(h):
    return {
        "id": h["id"], "created_at": h["created_at"], "client_id": h["client_id"],
        "start_date": fmt_ts(h["start_date"]), "end_date": fmt_ts(h["end_date"]),
    }


def ser_purchase(p):
    return {k: p[k] for k in ("id", "created_at", "updated_at", "version",
                              "client_id", "product_id", "quantity", "unit_price_cents",
                              "total_cents", "status")}


# ---------------------------------------------------------------------------
# Pagination + list helper
# ---------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate_and_respond(rows, serializer):
    rows = sorted(rows, key=lambda r: r["created_at"])
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Fix state helpers
# ---------------------------------------------------------------------------
TERMINAL_FIX = ("CLOSED", "CANCELLED")


def require_fix_state(fix, required, not_x_error):
    if fix["status"] in TERMINAL_FIX:
        raise ApiError("ERR_FIX_TERMINAL", 409, "Fix is terminal")
    if isinstance(required, (list, tuple, set)):
        if fix["status"] not in required:
            raise ApiError(not_x_error, 409, "Fix not in required state")
    else:
        if fix["status"] != required:
            raise ApiError(not_x_error, 409, "Fix not in required state")


def cancel_fix_cascade(fix):
    """Cancel a fix: release SELECTED items (restock), recompute stylist."""
    for i in items_of_fix(fix["id"]):
        if i["status"] == "SELECTED":
            i["status"] = "RELEASED"
            touch(i)
            inv_release(DB["products"][i["product_id"]])
    sid = fix["stylist_id"]
    fix["status"] = "CANCELLED"
    touch(fix)
    if sid:
        recompute_stylist(sid)


# ===========================================================================
# ROUTES
# ===========================================================================

# ----- Clients ------------------------------------------------------------
@app.route("/clients", methods=["POST"])
def create_client():
    body = get_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    region = req_enum(body, "region_code", REGION_VALUES)
    cadence = opt_str(body, "cadence", "MONTHLY")
    if cadence not in CADENCE_VALUES:
        _bad("cadence invalid")
    if any(c["email"] == email for c in DB["clients"].values()):
        _bad("email already registered")
    c = base_common()
    c.update({"email": email, "full_name": full_name, "region_code": region,
              "cadence": cadence, "status": "PROSPECT"})
    DB["clients"][c["id"]] = c
    return ok(ser_client(c), 201)


@app.route("/clients/<cid>", methods=["GET"])
def fetch_client(cid):
    uid, role = auth("Client", "OpsAdmin")
    c = get_client(cid)
    if role == "Client" and c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    return ok(ser_client(c))


@app.route("/clients/<cid>/style-profile", methods=["POST"])
def create_profile(cid):
    uid, role = auth("Client")
    body = get_body()
    top = req_int(body, "quiz_top_size")
    bottom = req_int(body, "quiz_bottom_size")
    shoe = req_int(body, "quiz_shoe_size")
    tier = req_enum(body, "price_tier", PRICE_TIERS)
    tags = opt_array(body, "style_tags", [])
    c = get_client(cid)
    if c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if c["status"] != "PROSPECT":
        raise ApiError("ERR_STYLEPROFILE_EXISTS", 409, "Style profile already exists")
    sp = base_common()
    sp.update({"client_id": c["id"], "quiz_top_size": top, "quiz_bottom_size": bottom,
               "quiz_shoe_size": shoe, "price_tier": tier, "style_tags": tags,
               "learned_top_size": top, "learned_bottom_size": bottom, "learned_shoe_size": shoe,
               "fit_confidence": 0})
    DB["style_profiles"][sp["id"]] = sp
    c["status"] = "ACTIVE"
    touch(c)
    return ok(ser_profile(sp), 201)


@app.route("/clients/<cid>/style-profile", methods=["GET"])
def get_profile(cid):
    uid, role = auth("Client", "Stylist", "OpsAdmin")
    c = get_client(cid)
    if role == "Client" and c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    sp = profile_of_client(cid)
    rows = [sp] if sp else []
    return paginate_and_respond(rows, ser_profile)


def _client_action(cid, uid):
    c = get_client(cid)
    if c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    return c


@app.route("/clients/<cid>/pause", methods=["POST"])
def pause_client(cid):
    uid, role = auth("Client")
    c = _client_action(cid, uid)
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not active")
    c["status"] = "PAUSED"
    touch(c)
    for f in list(DB["fixes"].values()):
        if f["client_id"] == cid and f["status"] == "REQUESTED":
            cancel_fix_cascade(f)
    return ok(ser_client(c))


@app.route("/clients/<cid>/resume", methods=["POST"])
def resume_client(cid):
    uid, role = auth("Client")
    c = _client_action(cid, uid)
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if c["status"] != "PAUSED":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not paused")
    c["status"] = "ACTIVE"
    touch(c)
    interval = CADENCE_DAYS[c["cadence"]]
    for f in DB["fixes"].values():
        if f["client_id"] == cid and f["status"] == "REQUESTED":
            f["scheduled_ship_date"] = now() + timedelta(days=interval)
            touch(f)
    return ok(ser_client(c))


@app.route("/clients/<cid>/cancel", methods=["POST"])
def cancel_client(cid):
    uid, role = auth("Client")
    c = _client_action(cid, uid)
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if c["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not active")
    fixes = [f for f in DB["fixes"].values() if f["client_id"] == cid]
    if any(f["status"] in ("SHIPPED", "DELIVERED") for f in fixes):
        raise ApiError("ERR_CLIENT_HAS_INFLIGHT_FIX", 409, "Client has in-flight fix")
    c["status"] = "CANCELLED"
    touch(c)
    for f in fixes:
        if f["status"] in ("REQUESTED", "STYLING", "PREVIEW"):
            cancel_fix_cascade(f)
    return ok(ser_client(c))


@app.route("/clients/<cid>/skip", methods=["POST"])
def skip_client(cid):
    uid, role = auth("Client")
    c = _client_action(cid, uid)
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not active")
    pending = [f for f in DB["fixes"].values() if f["client_id"] == cid and f["status"] == "REQUESTED"]
    if len(pending) != 1:
        raise ApiError("ERR_NO_PENDING_FIX", 409, "Skip requires exactly one pending fix")
    f = pending[0]
    interval = CADENCE_DAYS[c["cadence"]]
    f["scheduled_ship_date"] = f["scheduled_ship_date"] + timedelta(days=interval)
    touch(f)
    return ok(ser_fix(f))


# ----- Fixes --------------------------------------------------------------
@app.route("/clients/<cid>/fixes", methods=["POST"])
def schedule_fix(cid):
    uid, role = auth("Client")
    body = get_body()
    expected = req_int(body, "expected_client_version")
    c = get_client(cid)
    if c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale client version")
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not active")
    # supersede prior REQUESTED fixes
    for f in list(DB["fixes"].values()):
        if f["client_id"] == cid and f["status"] == "REQUESTED":
            cancel_fix_cascade(f)
    interval = CADENCE_DAYS[c["cadence"]]
    fx = base_common()
    fx.update({
        "client_id": cid, "stylist_id": None, "status": "REQUESTED",
        "scheduled_ship_date": now() + timedelta(days=interval),
        "shipped_at": None, "delivered_at": None, "checkout_deadline": None,
        "subtotal_cents": None, "estimated_charge_cents": None, "charge_cents": None,
        "buy_the_look_applied": False, "shipping_fee_cents": 0, "tax_cents": 0,
        "styling_fee_charged_cents": 0, "styling_fee_credit_cents": 0,
        "styling_fee_forfeited_cents": 0,
    })
    DB["fixes"][fx["id"]] = fx
    c["version"] += 1
    c["updated_at"] = fmt_ts(now())
    return ok(ser_fix(fx), 201)


@app.route("/clients/<cid>/fixes", methods=["GET"])
def list_client_fixes(cid):
    uid, role = auth("Client", "OpsAdmin")
    c = get_client(cid)
    if role == "Client" and c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    rows = [f for f in DB["fixes"].values() if f["client_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [f for f in rows if f["status"] == status]
    return paginate_and_respond(rows, ser_fix)


@app.route("/fixes/<fid>", methods=["GET"])
def fetch_fix(fid):
    uid, role = auth("Client", "Stylist", "OpsAdmin")
    f = get_fix(fid)
    if role == "Client" and f["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if role == "Stylist" and f["stylist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    return ok(ser_fix(f))


@app.route("/fixes", methods=["GET"])
def list_fixes():
    uid, role = auth("Stylist", "OpsAdmin")
    rows = list(DB["fixes"].values())
    if role == "Stylist":
        rows = [f for f in rows if f["stylist_id"] == uid]
    sid = request.args.get("stylist_id")
    if sid:
        rows = [f for f in rows if f["stylist_id"] == sid]
    cid = request.args.get("client_id")
    if cid:
        rows = [f for f in rows if f["client_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [f for f in rows if f["status"] == status]
    return paginate_and_respond(rows, ser_fix)


@app.route("/fixes/<fid>/assign", methods=["POST"])
def assign_fix(fid):
    uid, role = auth("OpsAdmin")
    body = get_body()
    stylist_id = req_str(body, "stylist_id")
    f = get_fix(fid)
    s = get_stylist(stylist_id)
    # state: fix REQUESTED, client ACTIVE
    if f["status"] in TERMINAL_FIX:
        raise ApiError("ERR_FIX_TERMINAL", 409, "Fix is terminal")
    if f["status"] != "REQUESTED":
        raise ApiError("ERR_FIX_TERMINAL", 409, "Fix not in REQUESTED state")
    c = DB["clients"][f["client_id"]]
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not active")
    # sibling status
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_STYLIST_INACTIVE", 409, "Stylist is inactive")
    # capacity
    if stylist_active_count(stylist_id) >= s["max_concurrent_fixes"]:
        raise ApiError("ERR_STYLIST_AT_CAPACITY", 409, "Stylist at capacity")
    f["stylist_id"] = stylist_id
    f["status"] = "STYLING"
    touch(f)
    recompute_stylist(stylist_id)
    return ok(ser_fix(f))


@app.route("/fixes/<fid>/items", methods=["POST"])
def add_item(fid):
    uid, role = auth("Stylist")
    body = get_body()
    product_id = req_str(body, "product_id")
    f = get_fix(fid)
    p = get_product(product_id)
    if f["stylist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    require_fix_state(f, "STYLING", "ERR_FIX_NOT_STYLING")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_UNAVAILABLE", 409, "Product unavailable")
    current = len([i for i in items_of_fix(fid) if i["status"] in ("SELECTED", "KEPT", "RETURNED")])
    if current >= MAX_ITEMS:
        raise ApiError("ERR_FIX_ITEM_LIMIT", 422, "Fix item limit exceeded")
    if p["available_count"] < 1:
        raise ApiError("ERR_OUT_OF_STOCK", 409, "Out of stock")
    it = base_common()
    it.update({"fix_id": fid, "product_id": product_id, "price_cents": p["price_cents"],
               "size": p["size"], "category": p["category"], "status": "SELECTED"})
    DB["fix_items"][it["id"]] = it
    inv_reserve(p)
    return ok(ser_item(it), 201)


@app.route("/fixes/<fid>/items", methods=["GET"])
def list_items(fid):
    uid, role = auth("Client", "Stylist", "OpsAdmin")
    f = get_fix(fid)
    if role == "Client" and f["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if role == "Stylist" and f["stylist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    rows = items_of_fix(fid)
    status = request.args.get("status")
    if status:
        rows = [i for i in rows if i["status"] == status]
    return paginate_and_respond(rows, ser_item)


@app.route("/fixes/<fid>/items/<iid>/remove", methods=["POST"])
def remove_item(fid, iid):
    uid, role = auth("Stylist")
    f = get_fix(fid)
    it = get_fixitem_of_fix(fid, iid)
    if f["stylist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    require_fix_state(f, ("STYLING", "PREVIEW"), "ERR_FIX_NOT_STYLING")
    if it["status"] != "SELECTED":
        raise ApiError("ERR_FIX_NOT_STYLING", 409, "Item not selected")
    it["status"] = "RELEASED"
    touch(it)
    inv_release(DB["products"][it["product_id"]])
    return ok(ser_item(it))


@app.route("/fixes/<fid>/submit-preview", methods=["POST"])
def submit_preview(fid):
    uid, role = auth("Stylist")
    f = get_fix(fid)
    if f["stylist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    require_fix_state(f, "STYLING", "ERR_FIX_NOT_STYLING")
    count = len([i for i in items_of_fix(fid) if i["status"] in ("SELECTED", "KEPT", "RETURNED")])
    if count < MIN_ITEMS:
        raise ApiError("ERR_FIX_TOO_FEW_ITEMS", 422, "Too few items")
    if count > MAX_ITEMS:
        raise ApiError("ERR_FIX_ITEM_LIMIT", 422, "Too many items")
    f["status"] = "PREVIEW"
    touch(f)
    return ok(ser_fix(f))


@app.route("/fixes/<fid>/request-changes", methods=["POST"])
def request_changes(fid):
    uid, role = auth("Client")
    f = get_fix(fid)
    if f["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    require_fix_state(f, "PREVIEW", "ERR_FIX_NOT_PREVIEW")
    f["status"] = "STYLING"
    touch(f)
    return ok(ser_fix(f))


@app.route("/fixes/<fid>/ship", methods=["POST"])
def ship_fix(fid):
    uid, role = auth("OpsAdmin")
    f = get_fix(fid)
    require_fix_state(f, "PREVIEW", "ERR_FIX_NOT_PREVIEW")
    c = DB["clients"][f["client_id"]]
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not active")
    count = len([i for i in items_of_fix(fid) if i["status"] in ("SELECTED", "KEPT", "RETURNED")])
    if count < MIN_ITEMS:
        raise ApiError("ERR_FIX_TOO_FEW_ITEMS", 422, "Too few items")
    if count > MAX_ITEMS:
        raise ApiError("ERR_FIX_ITEM_LIMIT", 422, "Too many items")
    f["status"] = "SHIPPED"
    f["styling_fee_charged_cents"] = STYLING_FEE_CENTS
    f["shipped_at"] = now()
    touch(f)
    return ok(ser_fix(f))


@app.route("/fixes/<fid>/mark-delivered", methods=["POST"])
def mark_delivered(fid):
    uid, role = auth("OpsAdmin")
    f = get_fix(fid)
    require_fix_state(f, "SHIPPED", "ERR_FIX_NOT_SHIPPED")
    c = DB["clients"][f["client_id"]]
    f["status"] = "DELIVERED"
    f["delivered_at"] = now()
    f["checkout_deadline"] = f["delivered_at"] + timedelta(days=TRY_AT_HOME_DAYS)
    # provisional charge: keep-all over ALL items
    all_items = [i for i in items_of_fix(fid) if i["status"] in ("SELECTED", "KEPT", "RETURNED")]
    res = compute_fix_charge(all_items, len(all_items), c["region_code"])
    f["subtotal_cents"] = res["subtotal"]
    f["estimated_charge_cents"] = res["total"]
    f["buy_the_look_applied"] = res["all_kept"]
    f["shipping_fee_cents"] = res["shipping"]
    f["tax_cents"] = res["tax"]
    touch(f)
    return ok(ser_fix(f))


@app.route("/fixes/<fid>/checkout", methods=["POST"])
def checkout_fix(fid):
    uid, role = auth("Client")
    body = get_body()
    if "kept_item_ids" not in body or not isinstance(body["kept_item_ids"], list):
        _bad("kept_item_ids must be an array")
    kept_ids = body["kept_item_ids"]
    if any(not isinstance(x, str) for x in kept_ids):
        _bad("kept_item_ids must be strings")
    item_feedback = body.get("item_feedback", [])
    if item_feedback is None:
        item_feedback = []
    if not isinstance(item_feedback, list):
        _bad("item_feedback must be an array")
    for fb in item_feedback:
        if not isinstance(fb, dict) or "fix_item_id" not in fb or "rating" not in fb:
            _bad("item_feedback entries need fix_item_id and rating")
        if not isinstance(fb["fix_item_id"], str):
            _bad("fix_item_id must be a string")
        if fb["rating"] not in RATINGS:
            _bad("invalid rating")

    f = get_fix(fid)
    if f["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    require_fix_state(f, "DELIVERED", "ERR_FIX_NOT_DELIVERED")
    if now() > f["checkout_deadline"]:
        raise ApiError("ERR_CHECKOUT_WINDOW_CLOSED", 409, "Checkout window closed")

    items = items_of_fix(fid)
    by_id = {i["id"]: i for i in items}
    selected = {i["id"]: i for i in items if i["status"] == "SELECTED"}
    for kid in kept_ids:
        if kid not in selected:
            raise ApiError("ERR_KEEP_ITEM_INVALID", 422, "kept_item_id not a selected item")
    for fb in item_feedback:
        if fb["fix_item_id"] not in by_id:
            _bad("feedback references unknown fix item")

    kept_set = set(kept_ids)
    c = DB["clients"][f["client_id"]]
    kept_items = []
    for i in items:
        if i["status"] != "SELECTED":
            continue
        if i["id"] in kept_set:
            i["status"] = "KEPT"
            touch(i)
            inv_sell_from_reserve(DB["products"][i["product_id"]])
            kept_items.append(i)
        else:
            i["status"] = "RETURNED"
            touch(i)

    returned_items = [i for i in items_of_fix(fid) if i["status"] == "RETURNED"]
    item_count = len(kept_items) + len(returned_items)
    res = compute_fix_charge(kept_items, item_count, c["region_code"])
    f["subtotal_cents"] = res["subtotal"]
    f["charge_cents"] = res["total"]
    f["buy_the_look_applied"] = res["all_kept"]
    f["shipping_fee_cents"] = res["shipping"]
    f["tax_cents"] = res["tax"]
    if len(kept_items) >= 1:
        f["styling_fee_credit_cents"] = f["styling_fee_charged_cents"]
        f["styling_fee_forfeited_cents"] = 0
    else:
        f["styling_fee_credit_cents"] = 0
        f["styling_fee_forfeited_cents"] = f["styling_fee_charged_cents"]
    f["status"] = "CHECKED_OUT"

    # feedback -> FeedbackEntry
    created_feedback = False
    for fb in item_feedback:
        it = by_id[fb["fix_item_id"]]
        fe = base_event()
        fe.update({"client_id": c["id"], "fix_item_id": it["id"], "product_size": it["size"],
                   "category": it["category"], "rating": fb["rating"]})
        DB["feedback"][fe["id"]] = fe
        created_feedback = True
    if created_feedback:
        recompute_style_profile(c["id"])

    # returns / close
    if len(returned_items) == 0:
        f["status"] = "CLOSED"
    else:
        r = base_common()
        r.update({"fix_id": fid, "status": "LABEL_ISSUED",
                  "item_ids": [i["id"] for i in returned_items], "received_at": None})
        DB["returns"][r["id"]] = r
    touch(f)
    recompute_stylist(f["stylist_id"])
    return ok(ser_fix(f))


@app.route("/fixes/<fid>/returns", methods=["GET"])
def list_returns(fid):
    uid, role = auth("Client", "OpsAdmin")
    f = get_fix(fid)
    if role == "Client" and f["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    rows = [r for r in DB["returns"].values() if r["fix_id"] == fid]
    return paginate_and_respond(rows, ser_return)


@app.route("/fixes/<fid>/returns/<rid>/ship", methods=["POST"])
def ship_return(fid, rid):
    uid, role = auth("Client")
    f = get_fix(fid)
    r = get_return_of_fix(fid, rid)
    if f["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if r["status"] != "LABEL_ISSUED":
        raise ApiError("ERR_RETURN_NOT_RECEIVABLE", 409, "Return not shippable")
    r["status"] = "IN_TRANSIT"
    touch(r)
    return ok(ser_return(r))


@app.route("/fixes/<fid>/returns/<rid>/receive", methods=["POST"])
def receive_return(fid, rid):
    uid, role = auth("OpsAdmin")
    f = get_fix(fid)
    r = get_return_of_fix(fid, rid)
    if r["status"] == "RECEIVED":
        raise ApiError("ERR_RETURN_NOT_RECEIVABLE", 409, "Return already received")
    r["status"] = "RECEIVED"
    r["received_at"] = now()
    touch(r)
    for iid in r["item_ids"]:
        it = DB["fix_items"].get(iid)
        if it and it["status"] == "RETURNED":
            inv_release(DB["products"][it["product_id"]])
    f["status"] = "CLOSED"
    touch(f)
    return ok(ser_return(r))


# ----- Holds --------------------------------------------------------------
@app.route("/clients/<cid>/holds", methods=["POST"])
def create_hold(cid):
    uid, role = auth("Client")
    body = get_body()
    start_raw = req_str(body, "start_date")
    end_raw = req_str(body, "end_date")
    try:
        start = parse_iso(start_raw)
        end = parse_iso(end_raw)
    except ValueError:
        _bad("invalid date")
    c = get_client(cid)
    if c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be after start_date")
    for h in DB["holds"].values():
        if h["client_id"] == cid and start < h["end_date"] and h["start_date"] < end:
            raise ApiError("ERR_HOLD_OVERLAP", 409, "Hold overlaps existing hold")
    h = base_event()
    h.update({"client_id": cid, "start_date": start, "end_date": end})
    DB["holds"][h["id"]] = h
    return ok(ser_hold(h), 201)


@app.route("/clients/<cid>/holds", methods=["GET"])
def list_holds(cid):
    uid, role = auth("Client", "OpsAdmin")
    c = get_client(cid)
    if role == "Client" and c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    rows = [h for h in DB["holds"].values() if h["client_id"] == cid]
    return paginate_and_respond(rows, ser_hold)


# ----- Feedback -----------------------------------------------------------
@app.route("/feedback/<fbid>", methods=["GET"])
def fetch_feedback(fbid):
    auth("Client", "Stylist", "OpsAdmin")
    fe = DB["feedback"].get(fbid)
    if not fe:
        raise ApiError("ERR_FIXITEM_NOT_FOUND", 404, "Feedback not found")
    return ok(ser_feedback(fe))


@app.route("/feedback", methods=["GET"])
def list_feedback():
    auth("Client", "Stylist", "OpsAdmin")
    rows = list(DB["feedback"].values())
    cid = request.args.get("client_id")
    if cid:
        rows = [f for f in rows if f["client_id"] == cid]
    fiid = request.args.get("fix_item_id")
    if fiid:
        rows = [f for f in rows if f["fix_item_id"] == fiid]
    return paginate_and_respond(rows, ser_feedback)


# ----- Products -----------------------------------------------------------
@app.route("/products", methods=["POST"])
def create_product():
    auth("OpsAdmin")
    body = get_body()
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORIES)
    size = req_int(body, "size")
    price = req_int(body, "price_cents", minimum=0)
    stock = req_int(body, "total_stock", minimum=0)
    tags = opt_array(body, "style_tags", [])
    if any(p["sku"] == sku for p in DB["products"].values()):
        _bad("sku already exists")
    p = base_common()
    p.update({"sku": sku, "name": name, "category": category, "size": size,
              "price_cents": price, "style_tags": tags, "status": "ACTIVE",
              "total_stock": stock, "available_count": stock, "reserved_count": 0, "sold_count": 0})
    DB["products"][p["id"]] = p
    return ok(ser_product(p), 201)


@app.route("/products/<pid>", methods=["GET"])
def fetch_product(pid):
    auth("Client", "Stylist", "OpsAdmin")
    p = get_product(pid)
    return ok(ser_product(p))


@app.route("/products/<pid>/discontinue", methods=["POST"])
def discontinue_product(pid):
    auth("OpsAdmin")
    p = get_product(pid)
    p["status"] = "DISCONTINUED"
    touch(p)
    return ok(ser_product(p))


@app.route("/products/<pid>/restock", methods=["POST"])
def restock_product(pid):
    auth("OpsAdmin")
    body = get_body()
    qty = req_int(body, "add_quantity", minimum=1)
    p = get_product(pid)
    inv_restock(p, qty)
    return ok(ser_product(p))


@app.route("/products/<pid>/fix-items", methods=["GET"])
def product_fix_items(pid):
    auth("OpsAdmin")
    get_product(pid)
    rows = [i for i in DB["fix_items"].values() if i["product_id"] == pid]
    status = request.args.get("status")
    if status:
        rows = [i for i in rows if i["status"] == status]
    return paginate_and_respond(rows, ser_item)


@app.route("/products/<pid>/purchases", methods=["GET"])
def product_purchases(pid):
    auth("OpsAdmin")
    get_product(pid)
    rows = [p for p in DB["purchases"].values() if p["product_id"] == pid]
    return paginate_and_respond(rows, ser_purchase)


# ----- Stylists -----------------------------------------------------------
@app.route("/stylists", methods=["POST"])
def create_stylist():
    auth("OpsAdmin")
    body = get_body()
    email = req_str(body, "email")
    name = req_str(body, "name")
    maxfix = opt_int(body, "max_concurrent_fixes", default=5, minimum=1)
    if any(s["email"] == email for s in DB["stylists"].values()):
        _bad("email already exists")
    s = base_common()
    s.update({"email": email, "name": name, "max_concurrent_fixes": maxfix, "status": "ACTIVE"})
    DB["stylists"][s["id"]] = s
    return ok(ser_stylist(s), 201)


@app.route("/stylists/<sid>/deactivate", methods=["POST"])
def deactivate_stylist(sid):
    auth("OpsAdmin")
    s = get_stylist(sid)
    s["status"] = "INACTIVE"
    touch(s)
    return ok(ser_stylist(s))


# ----- Purchases ----------------------------------------------------------
@app.route("/clients/<cid>/purchases", methods=["POST"])
def create_purchase(cid):
    uid, role = auth("Client")
    body = get_body()
    product_id = req_str(body, "product_id")
    quantity = req_int(body, "quantity", minimum=1)
    c = get_client(cid)
    p = get_product(product_id)
    if c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if c["status"] == "CANCELLED":
        raise ApiError("ERR_CLIENT_CANCELLED", 409, "Client is cancelled")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_UNAVAILABLE", 409, "Product unavailable")
    if p["available_count"] < quantity:
        raise ApiError("ERR_OUT_OF_STOCK", 409, "Out of stock")
    pu = base_common()
    pu.update({"client_id": cid, "product_id": product_id, "quantity": quantity,
               "unit_price_cents": p["price_cents"], "total_cents": p["price_cents"] * quantity,
               "status": "PLACED"})
    DB["purchases"][pu["id"]] = pu
    inv_direct_sell(p, quantity)
    return ok(ser_purchase(pu), 201)


@app.route("/clients/<cid>/purchases", methods=["GET"])
def list_purchases(cid):
    uid, role = auth("Client", "OpsAdmin")
    c = get_client(cid)
    if role == "Client" and c["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    rows = [p for p in DB["purchases"].values() if p["client_id"] == cid]
    return paginate_and_respond(rows, ser_purchase)


@app.route("/purchases/<pid>/cancel", methods=["POST"])
def cancel_purchase(pid):
    uid, role = auth("Client")
    pu = get_purchase(pid)
    if pu["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not resource owner")
    if pu["status"] == "CANCELLED":
        raise ApiError("ERR_FIX_TERMINAL", 409, "Purchase already cancelled")
    pu["status"] = "CANCELLED"
    touch(pu)
    inv_compensate(DB["products"][pu["product_id"]], pu["quantity"])
    return ok(ser_purchase(pu))


# ----- System / test-driving ----------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth("OpsAdmin")
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    try:
        CLOCK["now"] = parse_iso(to_iso)
    except ValueError:
        _bad("invalid to_iso8601")
    return ok({})


@app.route("/_ops/run-checkout-sweep", methods=["POST"])
def run_checkout_sweep():
    auth("OpsAdmin")
    for f in list(DB["fixes"].values()):
        if f["status"] != "DELIVERED":
            continue
        if not (now() > f["checkout_deadline"]):
            continue
        c = DB["clients"][f["client_id"]]
        items = [i for i in items_of_fix(f["id"]) if i["status"] == "SELECTED"]
        for i in items:
            i["status"] = "KEPT"
            touch(i)
            inv_sell_from_reserve(DB["products"][i["product_id"]])
        kept_items = [i for i in items_of_fix(f["id"]) if i["status"] == "KEPT"]
        item_count = len(kept_items)  # everything kept, nothing returned
        res = compute_fix_charge(kept_items, item_count, c["region_code"])
        f["subtotal_cents"] = res["subtotal"]
        f["charge_cents"] = res["total"]
        f["buy_the_look_applied"] = res["all_kept"]
        f["shipping_fee_cents"] = res["shipping"]
        f["tax_cents"] = res["tax"]
        if item_count >= 1:
            f["styling_fee_credit_cents"] = f["styling_fee_charged_cents"]
            f["styling_fee_forfeited_cents"] = 0
        else:
            f["styling_fee_credit_cents"] = 0
            f["styling_fee_forfeited_cents"] = f["styling_fee_charged_cents"]
        f["status"] = "CLOSED"
        touch(f)
        recompute_stylist(f["stylist_id"])
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (a robust production WSGI server) rather than the
    # Werkzeug dev server. The dev server's keep-alive handling races under the
    # concurrent-server load of the stability sweep, occasionally corrupting a
    # connection and surfacing as a client-side BadStatusLine. waitress handles
    # HTTP keep-alive reliably, eliminating that flakiness.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
