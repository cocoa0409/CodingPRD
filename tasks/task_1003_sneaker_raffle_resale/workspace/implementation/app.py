"""Sneaker Raffle Resale API — single-file Flask implementation.

In-memory only. Store starts empty on every boot. Logical clock defaults to
2026-07-01T00:00:00Z. All monetary amounts are integer cents; precision-sensitive
math uses decimal.Decimal with ROUND_HALF_UP.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)
try:
    app.json.sort_keys = False  # Flask >=2.3
except Exception:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Buyer", "Seller", "Authenticator", "PlatformAdmin", "CustomerService"}
ALL_ROLES = ["Buyer", "Seller", "Authenticator", "PlatformAdmin", "CustomerService"]

SHIPPING_FEE_CENTS = 1500
PROCESSING_PCT = Decimal("0.029")
PROCESSING_FLAT_CENTS = Decimal("30")
HIGH_VALUE_CENTS = 50000
MIN_FEE_CENTS = 500
MAX_FEE_CENTS = 10000
DOWNGRADE_PENALTY_PCT = Decimal("0.15")
BASE_RATE = {"STANDARD": Decimal("0.09"), "PRO": Decimal("0.07"), "ELITE": Decimal("0.05")}
COND_VAL = {"DEADSTOCK": Decimal("1.0"), "VNDS": Decimal("0.85"), "USED": Decimal("0.6")}
BOX_VAL = {"PERFECT": Decimal("1.0"), "GOOD": Decimal("0.8"), "DAMAGED": Decimal("0.5"), "MISSING": Decimal("0.0")}
COND_RANK = {"DEADSTOCK": 3, "VNDS": 2, "USED": 1}
BOT_RISK_THRESHOLD = 0.6
MIN_ACCOUNT_AGE_DAYS = 3
RELEASE_COOLDOWN_HOURS = 24
BUY_LIMIT_PER_SKU_24H = 2
DISPUTE_WINDOW_DAYS = 3

CONDITION_GRADES = {"DEADSTOCK", "VNDS", "USED"}
BOX_GRADES = {"PERFECT", "GOOD", "DAMAGED", "MISSING"}

# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------
DB = {
    "accounts": {}, "skus": {}, "releases": {}, "raffle_entries": {},
    "authenticators": {}, "consignment_items": {}, "listings": {}, "bids": {},
    "orders": {}, "disputes": {},
}
_SEQ = [0]
_CLOCK = {"now": datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def clock_now():
    return _CLOCK["now"]


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_str():
    return fmt_dt(clock_now())


def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


def _meta(extra=None):
    m = {"api_request_id": "req_" + uuid.uuid4().hex[:20], "api_request_timestamp": now_str()}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, list_meta=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": _meta(list_meta), "response_type": rtype, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http


@app.errorhandler(404)
def _handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or malformed auth headers")
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    g.uid = uid
    g.role = role
    return uid, role


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def v_str(b, key):
    val = b.get(key)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_VALIDATION", 422, "%s is required" % key)
    return val


def v_int_pos(b, key):
    val = b.get(key)
    if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
        raise ApiError("ERR_VALIDATION", 422, "%s must be a positive integer" % key)
    return val


def v_int_min(b, key, minimum):
    val = b.get(key)
    if isinstance(val, bool) or not isinstance(val, int) or val < minimum:
        raise ApiError("ERR_VALIDATION", 422, "%s must be >= %d" % (key, minimum))
    return val


def v_enum(b, key, allowed):
    val = b.get(key)
    if val not in allowed:
        raise ApiError("ERR_VALIDATION", 422, "%s invalid" % key)
    return val


def v_bool(b, key):
    val = b.get(key)
    if not isinstance(val, bool):
        raise ApiError("ERR_VALIDATION", 422, "%s must be boolean" % key)
    return val


def v_dt(b, key):
    val = b.get(key)
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", 422, "%s must be a datetime string" % key)
    try:
        parse_dt(val)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "%s is not a valid datetime" % key)
    return val


# ---------------------------------------------------------------------------
# Rounding / calculations
# ---------------------------------------------------------------------------
def rhu_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(dec):
    return float(dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def level_for(count):
    if count >= 20:
        return "ELITE"
    if count >= 5:
        return "PRO"
    return "STANDARD"


def txn_fee(seller_level, sale_price_cents):
    base = BASE_RATE[seller_level]
    band = Decimal("0.01") if sale_price_cents >= HIGH_VALUE_CENTS else Decimal("0")
    eff = base - band
    raw = rhu_cents(Decimal(sale_price_cents) * eff)
    return max(MIN_FEE_CENTS, min(MAX_FEE_CENTS, raw))


def buyer_breakdown(sale_price_cents):
    subtotal = sale_price_cents + SHIPPING_FEE_CENTS
    proc = rhu_cents(PROCESSING_PCT * Decimal(subtotal) + PROCESSING_FLAT_CENTS)
    total = sale_price_cents + SHIPPING_FEE_CENTS + proc
    return SHIPPING_FEE_CENTS, proc, total


def grade_score(cond, box, acc_complete):
    c = COND_VAL[cond]
    bx = BOX_VAL[box]
    a = Decimal("1.0") if acc_complete else Decimal("0.0")
    return rhu4(Decimal("0.6") * c + Decimal("0.25") * bx + Decimal("0.15") * a)


def tenure_days(created_dt):
    return int((clock_now() - created_dt).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def base_record():
    ts = now_str()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next_seq(), "_dt": clock_now()}


def touch(rec):
    rec["updated_at"] = now_str()
    rec["version"] += 1


def get_or_404(coll, rid, err):
    rec = DB[coll].get(rid)
    if rec is None:
        raise ApiError(err, 404, "%s not found" % coll)
    return rec


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ser_account(a):
    d = _pub(a)
    d["seller_level"] = level_for(a["completed_sales_count"])
    return d


def ser_release(r):
    d = _pub(r)
    d["available_units"] = r["allocated_quantity"] - r["reserved_units"] - r["sold_units"]
    return d


def ser_plain(r):
    return _pub(r)


SERIALIZERS = {
    "accounts": ser_account, "releases": ser_release,
}


def serialize(coll, rec):
    return SERIALIZERS.get(coll, ser_plain)(rec)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def _page_param(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except Exception:
        return default
    if val < lo:
        val = lo
    if hi is not None and val > hi:
        val = hi
    return val


def paginate(coll, items):
    items = sorted(items, key=lambda r: r["_seq"])
    total = len(items)
    limit = _page_param("limit", 10, 1, 100)
    offset = _page_param("offset", 0, 0, None)
    page = items[offset:offset + limit]
    lm = {"limit": limit, "offset": offset, "total_count": total,
          "has_more": offset + limit < total}
    return [serialize(coll, r) for r in page], lm


def filtered(coll, filters):
    out = []
    for r in DB[coll].values():
        keep = True
        for field, qparam in filters:
            qv = request.args.get(qparam)
            if qv is not None and qv != "":
                if str(r.get(field)) != qv:
                    keep = False
                    break
        if keep:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------
def create_order(buyer_account_id, sku_id, seller_account_id, source_type, size,
                 sale_price_cents, listing_id=None, bid_id=None, raffle_entry_id=None):
    o = base_record()
    if seller_account_id:
        lvl = level_for(DB["accounts"][seller_account_id]["completed_sales_count"])
    else:
        lvl = "STANDARD"
    fee = txn_fee(lvl, sale_price_cents)
    shipping, proc, total = buyer_breakdown(sale_price_cents)
    o.update({
        "buyer_account_id": buyer_account_id,
        "sku_id": sku_id,
        "seller_account_id": seller_account_id,
        "listing_id": listing_id,
        "bid_id": bid_id,
        "raffle_entry_id": raffle_entry_id,
        "source_type": source_type,
        "size": size,
        "sale_price_cents": sale_price_cents,
        "shipping_fee_cents": shipping,
        "transaction_fee_cents": fee,
        "payment_processing_fee_cents": proc,
        "buyer_total_cents": total,
        "downgrade_adjustment_cents": 0,
        "provisional_payout_cents": sale_price_cents - fee,
        "final_payout_cents": None,
        "payment_status": "AUTHORIZED",
        "fulfillment_status": "AWAITING_SHIPMENT",
        "dispute_deadline": None,
    })
    DB["orders"][o["id"]] = o
    return o


def find_consignment_for_order(order_id):
    for ci in DB["consignment_items"].values():
        if ci["order_id"] == order_id:
            return ci
    return None


# ===========================================================================
# Routes: setup / configuration
# ===========================================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlatformAdmin"])
    b = body()
    iso = v_dt(b, "to_iso8601")
    _CLOCK["now"] = parse_dt(iso)
    return ok({}, 200)


# ===========================================================================
# Accounts
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    auth(["PlatformAdmin"])
    b = body()
    email = v_str(b, "email")
    full_name = v_str(b, "full_name")
    a = base_record()
    a.update({
        "email": email, "full_name": full_name,
        "verification_status": "UNVERIFIED", "trust_score": 0.5,
        "completed_sales_count": 0, "balance_cents": 0, "strikes": 0,
    })
    DB["accounts"][a["id"]] = a
    return ok(ser_account(a), 201)


@app.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    auth(ALL_ROLES)
    a = get_or_404("accounts", rid, "ERR_ACCOUNT_NOT_FOUND")
    return ok(ser_account(a), 200)


@app.route("/accounts/<rid>/verify", methods=["POST"])
def verify_account(rid):
    auth(["PlatformAdmin"])
    a = get_or_404("accounts", rid, "ERR_ACCOUNT_NOT_FOUND")
    a["verification_status"] = "VERIFIED"
    touch(a)
    return ok(ser_account(a), 200)


# ===========================================================================
# SKUs
# ===========================================================================
@app.route("/skus", methods=["POST"])
def create_sku():
    auth(["PlatformAdmin"])
    b = body()
    style_code = v_str(b, "style_code")
    name = v_str(b, "name")
    brand = v_str(b, "brand")
    retail = v_int_pos(b, "retail_price_cents")
    category = "GENERAL"
    if b.get("release_category") is not None:
        category = v_enum(b, "release_category", {"LIMITED", "GENERAL"})
    s = base_record()
    s.update({"style_code": style_code, "name": name, "brand": brand,
              "retail_price_cents": retail, "release_category": category})
    DB["skus"][s["id"]] = s
    return ok(ser_plain(s), 201)


@app.route("/skus/<rid>", methods=["GET"])
def get_sku(rid):
    auth(ALL_ROLES)
    s = get_or_404("skus", rid, "ERR_SKU_NOT_FOUND")
    return ok(ser_plain(s), 200)


# ===========================================================================
# Authenticators
# ===========================================================================
@app.route("/authenticators", methods=["POST"])
def create_authenticator():
    auth(["PlatformAdmin"])
    b = body()
    name = v_str(b, "name")
    location_code = v_str(b, "location_code")
    capacity = 8
    if b.get("daily_capacity") is not None:
        capacity = v_int_min(b, "daily_capacity", 1)
    au = base_record()
    au.update({"name": name, "location_code": location_code, "daily_capacity": capacity})
    DB["authenticators"][au["id"]] = au
    return ok(ser_plain(au), 201)


@app.route("/authenticators/<rid>", methods=["GET"])
def get_authenticator(rid):
    auth(["Authenticator", "PlatformAdmin", "CustomerService"])
    au = get_or_404("authenticators", rid, "ERR_AUTHENTICATOR_NOT_FOUND")
    return ok(ser_plain(au), 200)


# ===========================================================================
# Releases & raffle
# ===========================================================================
@app.route("/releases", methods=["POST"])
def create_release():
    auth(["PlatformAdmin"])
    b = body()
    # existence: sku
    sku_id = b.get("sku_id")
    if isinstance(sku_id, str) and sku_id:
        if sku_id not in DB["skus"]:
            raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    # body validation
    sku_id = v_str(b, "sku_id")
    if sku_id not in DB["skus"]:
        raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    allocated = v_int_min(b, "allocated_quantity", 1)
    price = v_int_pos(b, "release_price_cents")
    entry_opens = v_dt(b, "entry_opens_at")
    entry_closes = v_dt(b, "entry_closes_at")
    purchase_opens = v_dt(b, "purchase_opens_at")
    purchase_closes = v_dt(b, "purchase_closes_at")
    if not (parse_dt(entry_opens) < parse_dt(entry_closes)):
        raise ApiError("ERR_VALIDATION", 422, "entry window start must be before end")
    if not (parse_dt(purchase_opens) < parse_dt(purchase_closes)):
        raise ApiError("ERR_VALIDATION", 422, "purchase window start must be before end")
    # cooldown / overlap check against same-sku non-cancelled releases
    new_start = parse_dt(entry_opens)
    new_end = parse_dt(purchase_closes)
    cooldown = timedelta(hours=RELEASE_COOLDOWN_HOURS)
    for r in DB["releases"].values():
        if r["sku_id"] != sku_id or r["status"] == "CANCELLED":
            continue
        es = parse_dt(r["entry_opens_at"])
        ee = parse_dt(r["purchase_closes_at"])
        gap_ok = (new_start - ee >= cooldown) or (es - new_end >= cooldown)
        if not gap_ok:
            raise ApiError("ERR_RELEASE_WINDOW_OVERLAP", 409, "release window overlaps same-sku drop")
    r = base_record()
    r.update({
        "sku_id": sku_id, "allocated_quantity": allocated, "release_price_cents": price,
        "entry_opens_at": entry_opens, "entry_closes_at": entry_closes,
        "purchase_opens_at": purchase_opens, "purchase_closes_at": purchase_closes,
        "status": "SCHEDULED", "entry_count": 0, "winner_count": 0,
        "reserved_units": 0, "sold_units": 0,
    })
    DB["releases"][r["id"]] = r
    return ok(ser_release(r), 201)


@app.route("/releases/<rid>", methods=["GET"])
def get_release(rid):
    auth(ALL_ROLES)
    r = get_or_404("releases", rid, "ERR_RELEASE_NOT_FOUND")
    return ok(ser_release(r), 200)


@app.route("/releases", methods=["GET"])
def list_releases():
    auth(ALL_ROLES)
    items = filtered("releases", [("sku_id", "sku_id"), ("status", "status")])
    data, lm = paginate("releases", items)
    return ok(data, 200, lm)


@app.route("/releases/<rid>/open", methods=["POST"])
def open_release(rid):
    auth(["PlatformAdmin"])
    r = get_or_404("releases", rid, "ERR_RELEASE_NOT_FOUND")
    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_RELEASE_NOT_OPEN", 409, "release not in SCHEDULED state")
    if clock_now() < parse_dt(r["entry_opens_at"]):
        raise ApiError("ERR_VALIDATION", 422, "entry window has not opened yet")
    r["status"] = "OPEN"
    touch(r)
    return ok(ser_release(r), 200)


@app.route("/releases/<rid>/draw", methods=["POST"])
def draw_release(rid):
    auth(["PlatformAdmin"])
    r = get_or_404("releases", rid, "ERR_RELEASE_NOT_FOUND")
    b = body()
    expected = b.get("expected_release_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 422, "expected_release_version required")
    if r["status"] != "OPEN":
        raise ApiError("ERR_RELEASE_NOT_DRAWN", 409, "release not in OPEN state")
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_release_version mismatch")
    if clock_now() < parse_dt(r["entry_closes_at"]):
        raise ApiError("ERR_VALIDATION", 422, "entry window has not closed yet")
    entries = [e for e in DB["raffle_entries"].values() if e["release_id"] == rid]
    eligible = [e for e in entries if e["result"] == "PENDING" and not e["bot_flag"]]
    if len(eligible) == 0:
        raise ApiError("ERR_NO_ELIGIBLE_ENTRIES", 422, "no eligible entries for draw")
    ranked = sorted(eligible, key=lambda e: (-e["fairness_score"], e["_seq"]))
    n_win = min(r["allocated_quantity"], len(ranked))
    winners = ranked[:n_win]
    winner_ids = {e["id"] for e in winners}
    for e in eligible:
        if e["id"] in winner_ids:
            e["result"] = "WON"
            e["claim_deadline"] = r["purchase_closes_at"]
        else:
            e["result"] = "LOST"
        touch(e)
    r["winner_count"] = len(winners)
    r["reserved_units"] += len(winners)
    r["status"] = "DRAWN"
    touch(r)
    return ok(ser_release(r), 200)


@app.route("/releases/<rid>/settle", methods=["POST"])
def settle_release(rid):
    auth(["PlatformAdmin"])
    r = get_or_404("releases", rid, "ERR_RELEASE_NOT_FOUND")
    if r["status"] != "DRAWN":
        raise ApiError("ERR_RELEASE_NOT_DRAWN", 409, "release not in DRAWN state")
    if clock_now() < parse_dt(r["purchase_closes_at"]):
        raise ApiError("ERR_VALIDATION", 422, "purchase window has not closed yet")
    expired = 0
    for e in DB["raffle_entries"].values():
        if e["release_id"] == rid and e["result"] == "WON" and e["claim_status"] == "NONE":
            e["claim_status"] = "EXPIRED"
            touch(e)
            expired += 1
    r["reserved_units"] -= expired
    r["status"] = "SETTLED"
    touch(r)
    return ok(ser_release(r), 200)


@app.route("/releases/<rid>/cancel", methods=["POST"])
def cancel_release(rid):
    auth(["PlatformAdmin"])
    r = get_or_404("releases", rid, "ERR_RELEASE_NOT_FOUND")
    if r["status"] not in ("SCHEDULED", "OPEN"):
        raise ApiError("ERR_RELEASE_NOT_OPEN", 409, "release cannot be cancelled from this state")
    if r["status"] == "OPEN":
        for e in DB["raffle_entries"].values():
            if e["release_id"] == rid and e["result"] == "PENDING":
                e["result"] = "LOST"
                touch(e)
    r["status"] = "CANCELLED"
    touch(r)
    return ok(ser_release(r), 200)


@app.route("/releases/<rid>/enter", methods=["POST"])
def enter_raffle(rid):
    uid, _ = auth(["Buyer"])
    r = get_or_404("releases", rid, "ERR_RELEASE_NOT_FOUND")
    acct = DB["accounts"].get(uid)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "acting account not found")
    if r["status"] != "OPEN":
        raise ApiError("ERR_RELEASE_NOT_OPEN", 409, "release not OPEN")
    if acct["verification_status"] != "VERIFIED":
        raise ApiError("ERR_ACCOUNT_NOT_VERIFIED", 403, "account not verified")
    td = tenure_days(acct["_dt"])
    if td < MIN_ACCOUNT_AGE_DAYS:
        raise ApiError("ERR_BOT_FLAGGED", 403, "account too young")
    now = clock_now()
    if not (parse_dt(r["entry_opens_at"]) <= now < parse_dt(r["entry_closes_at"])):
        raise ApiError("ERR_ENTRY_WINDOW_CLOSED", 422, "outside entry window")
    for e in DB["raffle_entries"].values():
        if e["release_id"] == rid and e["account_id"] == uid:
            raise ApiError("ERR_DUPLICATE_ENTRY", 409, "already entered this release")
    # bot risk: entries by this account for the same sku in trailing 24h
    sku_id = r["sku_id"]
    window_start = now - timedelta(hours=24)
    cnt = 0
    for e in DB["raffle_entries"].values():
        if e["account_id"] != uid:
            continue
        rel = DB["releases"].get(e["release_id"])
        if not rel or rel["sku_id"] != sku_id:
            continue
        if e["_dt"] > window_start:
            cnt += 1
    bot_risk = min(1.0, 0.2 * max(0, cnt - 2))
    bot_flag = bot_risk >= BOT_RISK_THRESHOLD
    tenure_factor = 1.0 if td >= 30 else (0.5 if td >= 7 else 0.0)
    fairness = rhu4(
        Decimal("0.5") * Decimal(str(acct["trust_score"]))
        + Decimal("0.3") * Decimal(str(tenure_factor))
        + Decimal("0.2") * (Decimal("1") - Decimal(str(bot_risk)))
    )
    e = base_record()
    e.update({
        "release_id": rid, "account_id": uid,
        "bot_risk_score": bot_risk, "bot_flag": bot_flag, "fairness_score": fairness,
        "result": "PENDING", "claim_status": "NONE", "claim_deadline": None,
    })
    DB["raffle_entries"][e["id"]] = e
    r["entry_count"] += 1
    touch(r)
    return ok(ser_plain(e), 201)


@app.route("/raffle-entries/<rid>", methods=["GET"])
def get_entry(rid):
    auth(["Buyer", "PlatformAdmin", "CustomerService"])
    e = get_or_404("raffle_entries", rid, "ERR_RAFFLE_ENTRY_NOT_FOUND")
    return ok(ser_plain(e), 200)


@app.route("/raffle-entries", methods=["GET"])
def list_entries():
    auth(["Buyer", "PlatformAdmin", "CustomerService"])
    items = filtered("raffle_entries",
                     [("release_id", "release_id"), ("account_id", "account_id"),
                      ("result", "result")])
    data, lm = paginate("raffle_entries", items)
    return ok(data, 200, lm)


@app.route("/raffle-entries/<rid>/claim", methods=["POST"])
def claim_entry(rid):
    uid, _ = auth(["Buyer"])
    e = get_or_404("raffle_entries", rid, "ERR_RAFFLE_ENTRY_NOT_FOUND")
    if e["account_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your entry")
    r = DB["releases"].get(e["release_id"])
    if r is None or r["status"] != "DRAWN":
        raise ApiError("ERR_RELEASE_NOT_DRAWN", 409, "release not in DRAWN state")
    if e["result"] != "WON":
        raise ApiError("ERR_ENTRY_NOT_WON", 409, "entry did not win")
    now = clock_now()
    if not (parse_dt(r["purchase_opens_at"]) <= now < parse_dt(r["purchase_closes_at"])):
        raise ApiError("ERR_PURCHASE_WINDOW_CLOSED", 422, "outside purchase window")
    if e["claim_status"] != "NONE":
        raise ApiError("ERR_ENTRY_ALREADY_CLAIMED", 409, "entry already claimed")
    e["claim_status"] = "CLAIMED"
    touch(e)
    o = create_order(
        buyer_account_id=uid, sku_id=r["sku_id"], seller_account_id=None,
        source_type="RAFFLE", size=None, sale_price_cents=r["release_price_cents"],
        raffle_entry_id=e["id"],
    )
    r["reserved_units"] -= 1
    r["sold_units"] += 1
    touch(r)
    return ok(ser_plain(o), 201)


# ===========================================================================
# Listings
# ===========================================================================
@app.route("/listings", methods=["POST"])
def create_listing():
    uid, _ = auth(["Seller"])
    b = body()
    seller_account_id = b.get("seller_account_id")
    if seller_account_id is not None and seller_account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "seller_account_id must match acting seller")
    # existence
    if isinstance(seller_account_id, str) and seller_account_id:
        if seller_account_id not in DB["accounts"]:
            raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    sku_id = b.get("sku_id")
    if isinstance(sku_id, str) and sku_id and sku_id not in DB["skus"]:
        raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    # validation
    sku_id = v_str(b, "sku_id")
    seller_account_id = v_str(b, "seller_account_id")
    if seller_account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "seller_account_id must match acting seller")
    if seller_account_id not in DB["accounts"]:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    if sku_id not in DB["skus"]:
        raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    size = v_str(b, "size")
    condition = v_enum(b, "condition", CONDITION_GRADES)
    pricing_mode = v_enum(b, "pricing_mode", {"FIXED", "BID_ASK"})
    ask = v_int_pos(b, "ask_price_cents")
    expires_at = None
    if b.get("expires_at") is not None:
        expires_at = v_dt(b, "expires_at")
    l = base_record()
    l.update({
        "sku_id": sku_id, "seller_account_id": seller_account_id, "size": size,
        "condition": condition, "pricing_mode": pricing_mode, "ask_price_cents": ask,
        "expires_at": expires_at, "status": "ACTIVE",
    })
    DB["listings"][l["id"]] = l
    return ok(ser_plain(l), 201)


@app.route("/listings/<rid>", methods=["GET"])
def get_listing(rid):
    auth(["Buyer", "Seller", "PlatformAdmin", "CustomerService"])
    l = get_or_404("listings", rid, "ERR_LISTING_NOT_FOUND")
    return ok(ser_plain(l), 200)


@app.route("/listings", methods=["GET"])
def list_listings():
    auth(["Buyer", "Seller", "PlatformAdmin", "CustomerService"])
    items = filtered("listings",
                     [("sku_id", "sku_id"), ("seller_account_id", "seller_account_id"),
                      ("status", "status")])
    data, lm = paginate("listings", items)
    return ok(data, 200, lm)


@app.route("/listings/<rid>/reprice", methods=["POST"])
def reprice_listing(rid):
    uid, _ = auth(["Seller"])
    l = get_or_404("listings", rid, "ERR_LISTING_NOT_FOUND")
    if l["seller_account_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your listing")
    b = body()
    new_ask = v_int_pos(b, "new_ask_price_cents")
    expected = b.get("expected_listing_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 422, "expected_listing_version required")
    if expected != l["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "listing version has advanced")
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "listing not active")
    l["ask_price_cents"] = new_ask
    touch(l)
    return ok(ser_plain(l), 200)


@app.route("/listings/<rid>/buy", methods=["POST"])
def buy_listing(rid):
    uid, _ = auth(["Buyer"])
    l = get_or_404("listings", rid, "ERR_LISTING_NOT_FOUND")
    acct = DB["accounts"].get(uid)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "acting account not found")
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "listing not active")
    if acct["verification_status"] != "VERIFIED":
        raise ApiError("ERR_ACCOUNT_NOT_VERIFIED", 403, "account not verified")
    if uid == l["seller_account_id"]:
        raise ApiError("ERR_SELF_PURCHASE", 403, "cannot buy your own listing")
    # per-sku purchase limit: FIXED buys of this sku in trailing 24h
    window_start = clock_now() - timedelta(hours=24)
    cnt = 0
    for o in DB["orders"].values():
        if (o["buyer_account_id"] == uid and o["source_type"] == "FIXED"
                and o["sku_id"] == l["sku_id"] and o["_dt"] > window_start):
            cnt += 1
    if cnt >= BUY_LIMIT_PER_SKU_24H:
        raise ApiError("ERR_PURCHASE_LIMIT_REACHED", 409, "purchase limit reached")
    o = create_order(
        buyer_account_id=uid, sku_id=l["sku_id"], seller_account_id=l["seller_account_id"],
        source_type="FIXED", size=l["size"], sale_price_cents=l["ask_price_cents"],
        listing_id=l["id"],
    )
    l["status"] = "MATCHED"
    touch(l)
    return ok(ser_plain(o), 201)


@app.route("/listings/<rid>/match", methods=["POST"])
def match_listing(rid):
    uid, _ = auth(["Seller"])
    l = get_or_404("listings", rid, "ERR_LISTING_NOT_FOUND")
    if l["seller_account_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your listing")
    b = body()
    bid_id = b.get("bid_id")
    if isinstance(bid_id, str) and bid_id and bid_id not in DB["bids"]:
        raise ApiError("ERR_BID_NOT_FOUND", 404, "bid not found")
    bid_id = v_str(b, "bid_id")
    bid = DB["bids"].get(bid_id)
    if bid is None:
        raise ApiError("ERR_BID_NOT_FOUND", 404, "bid not found")
    expected = b.get("expected_listing_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 422, "expected_listing_version required")
    if expected != l["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "listing version has advanced")
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "listing not active")
    seller = DB["accounts"].get(uid)
    if seller is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "acting account not found")
    if seller["verification_status"] != "VERIFIED":
        raise ApiError("ERR_ACCOUNT_NOT_VERIFIED", 403, "account not verified")
    if bid["buyer_account_id"] == l["seller_account_id"]:
        raise ApiError("ERR_SELF_PURCHASE", 403, "cannot match your own bid")
    if bid["sku_id"] != l["sku_id"] or bid["size"] != l["size"]:
        raise ApiError("ERR_SKU_MISMATCH", 422, "bid sku/size mismatch")
    if bid["amount_cents"] < l["ask_price_cents"]:
        raise ApiError("ERR_BID_BELOW_ASK", 422, "bid below ask")
    bid["status"] = "MATCHED"
    touch(bid)
    o = create_order(
        buyer_account_id=bid["buyer_account_id"], sku_id=l["sku_id"],
        seller_account_id=l["seller_account_id"], source_type="BID_MATCH",
        size=l["size"], sale_price_cents=bid["amount_cents"],
        listing_id=l["id"], bid_id=bid["id"],
    )
    l["status"] = "MATCHED"
    touch(l)
    return ok(ser_plain(o), 201)


# ===========================================================================
# Bids
# ===========================================================================
@app.route("/bids", methods=["POST"])
def create_bid():
    uid, _ = auth(["Buyer"])
    b = body()
    buyer_account_id = b.get("buyer_account_id")
    if buyer_account_id is not None and buyer_account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "buyer_account_id must match acting buyer")
    if isinstance(buyer_account_id, str) and buyer_account_id:
        if buyer_account_id not in DB["accounts"]:
            raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    sku_id = b.get("sku_id")
    if isinstance(sku_id, str) and sku_id and sku_id not in DB["skus"]:
        raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    sku_id = v_str(b, "sku_id")
    buyer_account_id = v_str(b, "buyer_account_id")
    if buyer_account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "buyer_account_id must match acting buyer")
    if buyer_account_id not in DB["accounts"]:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    if sku_id not in DB["skus"]:
        raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    size = v_str(b, "size")
    amount = v_int_pos(b, "amount_cents")
    expires_at = None
    if b.get("expires_at") is not None:
        expires_at = v_dt(b, "expires_at")
    bd = base_record()
    bd.update({
        "sku_id": sku_id, "buyer_account_id": buyer_account_id, "size": size,
        "amount_cents": amount, "expires_at": expires_at, "status": "OPEN",
    })
    DB["bids"][bd["id"]] = bd
    return ok(ser_plain(bd), 201)


@app.route("/bids/<rid>", methods=["GET"])
def get_bid(rid):
    auth(["Buyer", "Seller", "PlatformAdmin", "CustomerService"])
    bd = get_or_404("bids", rid, "ERR_BID_NOT_FOUND")
    return ok(ser_plain(bd), 200)


@app.route("/bids", methods=["GET"])
def list_bids():
    auth(["Buyer", "Seller", "PlatformAdmin", "CustomerService"])
    items = filtered("bids",
                     [("sku_id", "sku_id"), ("buyer_account_id", "buyer_account_id"),
                      ("status", "status")])
    data, lm = paginate("bids", items)
    return ok(data, 200, lm)


# ===========================================================================
# Orders
# ===========================================================================
@app.route("/orders/<rid>", methods=["GET"])
def get_order(rid):
    auth(["Buyer", "Seller", "PlatformAdmin", "CustomerService"])
    o = get_or_404("orders", rid, "ERR_ORDER_NOT_FOUND")
    return ok(ser_plain(o), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    auth(["Buyer", "Seller", "PlatformAdmin", "CustomerService"])
    items = filtered("orders", [
        ("buyer_account_id", "buyer_account_id"),
        ("seller_account_id", "seller_account_id"),
        ("sku_id", "sku_id"), ("listing_id", "listing_id"),
        ("bid_id", "bid_id"), ("raffle_entry_id", "raffle_entry_id"),
    ])
    data, lm = paginate("orders", items)
    return ok(data, 200, lm)


@app.route("/orders/<rid>/ship-to-buyer", methods=["POST"])
def ship_order(rid):
    auth(["PlatformAdmin"])
    o = get_or_404("orders", rid, "ERR_ORDER_NOT_FOUND")
    if o["source_type"] == "RAFFLE":
        if o["fulfillment_status"] != "AWAITING_SHIPMENT":
            raise ApiError("ERR_ORDER_STATE_INVALID", 409, "raffle order not awaiting shipment")
    else:
        ci = find_consignment_for_order(o["id"])
        if ci is None or ci["status"] != "AUTHENTICATED":
            raise ApiError("ERR_ITEM_NOT_AUTHENTICATED", 409, "consignment item not authenticated")
        if o["fulfillment_status"] != "AUTHENTICATED":
            raise ApiError("ERR_ORDER_STATE_INVALID", 409, "order not in AUTHENTICATED state")
    o["fulfillment_status"] = "SHIPPED_TO_BUYER"
    o["dispute_deadline"] = fmt_dt(clock_now() + timedelta(days=DISPUTE_WINDOW_DAYS))
    touch(o)
    return ok(ser_plain(o), 200)


@app.route("/orders/<rid>/verify", methods=["POST"])
def verify_order(rid):
    uid, _ = auth(["Buyer"])
    o = get_or_404("orders", rid, "ERR_ORDER_NOT_FOUND")
    if o["buyer_account_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your order")
    if o["fulfillment_status"] != "SHIPPED_TO_BUYER":
        raise ApiError("ERR_ORDER_STATE_INVALID", 409, "order not shipped")
    if o["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_ORDER_STATE_INVALID", 409, "payment not authorized")
    o["payment_status"] = "CAPTURED"
    o["fulfillment_status"] = "VERIFIED"
    # downgrade adjustment from authenticated vs declared condition
    downgrade = 0
    ci = find_consignment_for_order(o["id"])
    if ci is not None and ci.get("authenticated_condition_grade") and ci.get("declared_condition_grade"):
        if COND_RANK[ci["authenticated_condition_grade"]] < COND_RANK[ci["declared_condition_grade"]]:
            downgrade = rhu_cents(DOWNGRADE_PENALTY_PCT * Decimal(o["sale_price_cents"]))
    seller_id = o["seller_account_id"]
    if seller_id:
        lvl = level_for(DB["accounts"][seller_id]["completed_sales_count"])
    else:
        lvl = "STANDARD"
    final_fee = txn_fee(lvl, o["sale_price_cents"])
    final_payout = o["sale_price_cents"] - final_fee - downgrade
    o["downgrade_adjustment_cents"] = downgrade
    o["transaction_fee_cents"] = final_fee
    o["final_payout_cents"] = final_payout
    touch(o)
    # cascade: credit seller ledger (resale only)
    if seller_id and o["source_type"] in ("FIXED", "BID_MATCH"):
        seller = DB["accounts"][seller_id]
        seller["balance_cents"] += final_payout
        seller["completed_sales_count"] += 1
        # seller_level is computed from completed_sales_count on serialize;
        # trust_score has no defined recompute formula and is left unchanged.
        touch(seller)
    return ok(ser_plain(o), 200)


# ===========================================================================
# Consignment items
# ===========================================================================
@app.route("/consignment-items", methods=["POST"])
def create_consignment():
    uid, _ = auth(["Seller"])
    b = body()
    seller_account_id = b.get("seller_account_id")
    if seller_account_id is not None and seller_account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "seller_account_id must match acting seller")
    if isinstance(seller_account_id, str) and seller_account_id:
        if seller_account_id not in DB["accounts"]:
            raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    sku_id = b.get("sku_id")
    if isinstance(sku_id, str) and sku_id and sku_id not in DB["skus"]:
        raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    order_id = b.get("order_id")
    if isinstance(order_id, str) and order_id and order_id not in DB["orders"]:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "order not found")
    order_id = v_str(b, "order_id")
    seller_account_id = v_str(b, "seller_account_id")
    sku_id = v_str(b, "sku_id")
    if seller_account_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "seller_account_id must match acting seller")
    if seller_account_id not in DB["accounts"]:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    if sku_id not in DB["skus"]:
        raise ApiError("ERR_SKU_NOT_FOUND", 404, "sku not found")
    if order_id not in DB["orders"]:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "order not found")
    dcond = v_enum(b, "declared_condition_grade", CONDITION_GRADES)
    dbox = v_enum(b, "declared_box_grade", BOX_GRADES)
    dacc = v_bool(b, "declared_accessories_complete")
    ci = base_record()
    ci.update({
        "order_id": order_id, "seller_account_id": seller_account_id, "sku_id": sku_id,
        "authenticator_id": None,
        "declared_condition_grade": dcond, "declared_box_grade": dbox,
        "declared_accessories_complete": dacc,
        "authenticated_condition_grade": None, "authenticated_box_grade": None,
        "authenticated_accessories_complete": None,
        "declared_grade_score": grade_score(dcond, dbox, dacc),
        "authenticated_grade_score": None,
        "inspection_window_start": None, "inspection_window_end": None,
        "inspection_result": "PENDING", "status": "INTAKE_PENDING",
    })
    DB["consignment_items"][ci["id"]] = ci
    return ok(ser_plain(ci), 201)


@app.route("/consignment-items/<rid>", methods=["GET"])
def get_consignment(rid):
    auth(["Seller", "Authenticator", "PlatformAdmin", "CustomerService"])
    ci = get_or_404("consignment_items", rid, "ERR_CONSIGNMENT_NOT_FOUND")
    return ok(ser_plain(ci), 200)


@app.route("/consignment-items", methods=["GET"])
def list_consignments():
    auth(["Seller", "Authenticator", "PlatformAdmin", "CustomerService"])
    items = filtered("consignment_items", [
        ("order_id", "order_id"), ("seller_account_id", "seller_account_id"),
        ("sku_id", "sku_id"), ("authenticator_id", "authenticator_id"),
        ("status", "status"),
    ])
    data, lm = paginate("consignment_items", items)
    return ok(data, 200, lm)


@app.route("/consignment-items/<rid>/receive", methods=["POST"])
def receive_consignment(rid):
    auth(["Authenticator"])
    ci = get_or_404("consignment_items", rid, "ERR_CONSIGNMENT_NOT_FOUND")
    if ci["status"] != "INTAKE_PENDING":
        raise ApiError("ERR_CONSIGNMENT_NOT_RECEIVED", 409, "item not in INTAKE_PENDING")
    ci["status"] = "RECEIVED"
    touch(ci)
    order = DB["orders"].get(ci["order_id"])
    if order is not None:
        order["fulfillment_status"] = "IN_AUTHENTICATION"
        touch(order)
    return ok(ser_plain(ci), 200)


@app.route("/consignment-items/<rid>/schedule-inspection", methods=["POST"])
def schedule_inspection(rid):
    auth(["Authenticator"])
    ci = get_or_404("consignment_items", rid, "ERR_CONSIGNMENT_NOT_FOUND")
    b = body()
    authenticator_id = b.get("authenticator_id")
    if isinstance(authenticator_id, str) and authenticator_id:
        if authenticator_id not in DB["authenticators"]:
            raise ApiError("ERR_AUTHENTICATOR_NOT_FOUND", 404, "authenticator not found")
    authenticator_id = v_str(b, "authenticator_id")
    if authenticator_id not in DB["authenticators"]:
        raise ApiError("ERR_AUTHENTICATOR_NOT_FOUND", 404, "authenticator not found")
    win_start = v_dt(b, "inspection_window_start")
    win_end = v_dt(b, "inspection_window_end")
    if not (parse_dt(win_start) < parse_dt(win_end)):
        raise ApiError("ERR_VALIDATION", 422, "inspection window start must be before end")
    if ci["status"] != "RECEIVED":
        raise ApiError("ERR_CONSIGNMENT_NOT_RECEIVED", 409, "item not in RECEIVED state")
    ns, ne = parse_dt(win_start), parse_dt(win_end)
    for other in DB["consignment_items"].values():
        if other["id"] == ci["id"] or other["status"] != "UNDER_AUTHENTICATION":
            continue
        if other["authenticator_id"] != authenticator_id:
            continue
        if other["inspection_window_start"] is None or other["inspection_window_end"] is None:
            continue
        os_, oe = parse_dt(other["inspection_window_start"]), parse_dt(other["inspection_window_end"])
        if ns < oe and os_ < ne:  # half-open overlap; touching endpoints allowed
            raise ApiError("ERR_AUTHENTICATOR_UNAVAILABLE", 409, "authenticator slot overlap")
    ci["authenticator_id"] = authenticator_id
    ci["inspection_window_start"] = win_start
    ci["inspection_window_end"] = win_end
    ci["status"] = "UNDER_AUTHENTICATION"
    touch(ci)
    return ok(ser_plain(ci), 200)


@app.route("/consignment-items/<rid>/complete-inspection", methods=["POST"])
def complete_inspection(rid):
    auth(["Authenticator"])
    ci = get_or_404("consignment_items", rid, "ERR_CONSIGNMENT_NOT_FOUND")
    b = body()
    result = v_enum(b, "inspection_result", {"PASS", "FAIL"})
    if ci["status"] != "UNDER_AUTHENTICATION":
        raise ApiError("ERR_CONSIGNMENT_NOT_RECEIVED", 409, "item not under authentication")
    order = DB["orders"].get(ci["order_id"])
    if result == "PASS":
        acond = v_enum(b, "authenticated_condition_grade", CONDITION_GRADES)
        abox = v_enum(b, "authenticated_box_grade", BOX_GRADES)
        aacc = v_bool(b, "authenticated_accessories_complete")
        ci["authenticated_condition_grade"] = acond
        ci["authenticated_box_grade"] = abox
        ci["authenticated_accessories_complete"] = aacc
        ci["authenticated_grade_score"] = grade_score(acond, abox, aacc)
        ci["inspection_result"] = "PASS"
        ci["status"] = "AUTHENTICATED"
        touch(ci)
        if order is not None:
            order["fulfillment_status"] = "AUTHENTICATED"
            touch(order)
    else:
        ci["inspection_result"] = "FAIL"
        ci["status"] = "REJECTED"
        touch(ci)
        if order is not None:
            order["fulfillment_status"] = "FAILED_AUTH"
            order["payment_status"] = "VOIDED"
            touch(order)
        seller = DB["accounts"].get(ci["seller_account_id"])
        if seller is not None:
            seller["strikes"] += 1
            touch(seller)
    return ok(ser_plain(ci), 200)


# ===========================================================================
# Disputes
# ===========================================================================
@app.route("/disputes", methods=["POST"])
def create_dispute():
    uid, _ = auth(["Buyer"])
    b = body()
    filed_by = b.get("filed_by_account_id")
    if isinstance(filed_by, str) and filed_by and filed_by not in DB["accounts"]:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    order_id = b.get("order_id")
    if isinstance(order_id, str) and order_id and order_id not in DB["orders"]:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "order not found")
    order_id = v_str(b, "order_id")
    filed_by = v_str(b, "filed_by_account_id")
    if filed_by not in DB["accounts"]:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    order = DB["orders"].get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "order not found")
    if filed_by != uid or filed_by != order["buyer_account_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "filer must be the order's buyer")
    reason = v_enum(b, "reason", {"NOT_AS_DESCRIBED", "NOT_RECEIVED", "INAUTHENTIC"})
    if order["fulfillment_status"] not in ("SHIPPED_TO_BUYER", "VERIFIED"):
        raise ApiError("ERR_ORDER_NOT_DISPUTABLE", 409, "order not disputable")
    if order["dispute_deadline"] is None or clock_now() > parse_dt(order["dispute_deadline"]):
        raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED", 422, "dispute window expired")
    dp = base_record()
    dp.update({
        "order_id": order_id, "filed_by_account_id": filed_by, "reason": reason,
        "resolution_note": None, "status": "OPEN",
    })
    DB["disputes"][dp["id"]] = dp
    return ok(ser_plain(dp), 201)


@app.route("/disputes/<rid>", methods=["GET"])
def get_dispute(rid):
    auth(["Buyer", "PlatformAdmin", "CustomerService"])
    dp = get_or_404("disputes", rid, "ERR_DISPUTE_NOT_FOUND")
    return ok(ser_plain(dp), 200)


@app.route("/disputes", methods=["GET"])
def list_disputes():
    auth(["Buyer", "PlatformAdmin", "CustomerService"])
    items = filtered("disputes", [
        ("order_id", "order_id"), ("filed_by_account_id", "filed_by_account_id"),
        ("status", "status"),
    ])
    data, lm = paginate("disputes", items)
    return ok(data, 200, lm)


@app.route("/disputes/<rid>/resolve", methods=["POST"])
def resolve_dispute(rid):
    auth(["CustomerService"])
    dp = get_or_404("disputes", rid, "ERR_DISPUTE_NOT_FOUND")
    b = body()
    outcome = v_enum(b, "outcome", {"REFUND", "DENY"})
    note = None
    if b.get("resolution_note") is not None:
        note = v_str(b, "resolution_note")
    if dp["status"] != "OPEN":
        raise ApiError("ERR_DISPUTE_ALREADY_RESOLVED", 409, "dispute already resolved")
    dp["resolution_note"] = note
    if outcome == "DENY":
        dp["status"] = "RESOLVED_DENIED"
        touch(dp)
        return ok(ser_plain(dp), 200)
    # REFUND: reverse the sale
    dp["status"] = "RESOLVED_REFUND"
    touch(dp)
    order = DB["orders"].get(dp["order_id"])
    if order is not None:
        order["payment_status"] = "REFUNDED"
        touch(order)
        seller_id = order["seller_account_id"]
        if (seller_id and order["source_type"] in ("FIXED", "BID_MATCH")
                and order["final_payout_cents"] is not None):
            seller = DB["accounts"].get(seller_id)
            if seller is not None:
                seller["balance_cents"] -= order["final_payout_cents"]
                seller["completed_sales_count"] -= 1
                touch(seller)
    return ok(ser_plain(dp), 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
