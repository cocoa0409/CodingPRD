"""Antiques & Estate-Sale Auction House API.

Single-file Flask implementation. In-memory storage only; the store starts
empty on every boot. Every behavior traces to a sentence in PRD.md.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from PRD §3 / SCAFFOLD calculations)
# ---------------------------------------------------------------------------
ROLES = {"AuctionStaff", "Appraiser", "SettlementOfficer", "Consignor", "Bidder"}

PAYOUT_METHODS = {"CHECK", "ACH", "STORE_CREDIT"}
SALE_TYPES = {"LIVE", "ONLINE", "TIMED"}
BID_TYPES = {"ABSENTEE", "LIVE", "ONLINE"}
FULFILLMENT_METHODS = {"PICKUP", "SHIP"}

INTAKE_BUFFER_MINUTES = 60
FREE_STORAGE_DAYS = 7
DAILY_STORAGE_CENTS = 500
HIGH_VALUE_LOT_CENTS = 1000000
MIN_DEPOSIT_FOR_HIGH_VALUE_CENTS = 100000

TIER1_UPPER = 300000
TIER2_UPPER = 2000000

# ---------------------------------------------------------------------------
# In-memory store (empty on boot; no seeding)
# ---------------------------------------------------------------------------
DB = {
    "salerooms": {},
    "consignors": {},
    "bidders": {},
    "auctions": {},
    "consignments": {},
    "lots": {},
    "bids": {},
    "invoices": {},
    "invoice_lines": {},
    "settlements": {},
    "disputes": {},
}
SEQ = {"n": 0}
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time / formatting helpers
# ---------------------------------------------------------------------------
def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def now_wall():
    return fmt(datetime.now(timezone.utc))


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_wall()}


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok_object(entity, code=200):
    return jsonify({"meta": meta_base(), "response_type": "object",
                    "data": public(entity) if entity is not None else {}}), code


def ok_empty(code=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": {}}), code


def ok_array(items, limit, offset, total):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = offset + len(items) < total
    return jsonify({"meta": m, "response_type": "array",
                    "data": [public(i) for i in items]}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({"meta": meta_base(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.http_status


# ---------------------------------------------------------------------------
# Entity base / touch
# ---------------------------------------------------------------------------
def base_entity():
    SEQ["n"] += 1
    ts = now_wall()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": SEQ["n"],
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_wall()


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "missing or unrecognized X-User-ID / X-User-Role")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "acting role not permitted for this endpoint")


ALL_ROLES = list(ROLES)


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        err("ERR_VALIDATION", 400, "request body must be a JSON object")
    return b


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field, allow_empty=False):
    if field not in body:
        err("ERR_VALIDATION", 400, "missing field: %s" % field)
    v = body[field]
    if not isinstance(v, str):
        err("ERR_VALIDATION", 400, "field %s must be a string" % field)
    if not allow_empty and v == "":
        err("ERR_VALIDATION", 400, "field %s must be non-empty" % field)
    return v


def req_int(body, field, minimum=None, maximum=None):
    if field not in body:
        err("ERR_VALIDATION", 400, "missing field: %s" % field)
    v = body[field]
    if not is_int(v):
        err("ERR_VALIDATION", 400, "field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, "field %s below minimum" % field)
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", 400, "field %s above maximum" % field)
    return v


def opt_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_int(v):
        err("ERR_VALIDATION", 400, "field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, "field %s below minimum" % field)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field, allow_empty=True)
    if v not in allowed:
        err("ERR_VALIDATION", 400, "field %s invalid enum" % field)
    return v


def req_datetime(body, field):
    v = req_str(body, field)
    try:
        return parse_iso(v)
    except Exception:
        err("ERR_VALIDATION", 400, "field %s must be ISO 8601" % field)


def req_rate(body, field):
    if field not in body:
        err("ERR_VALIDATION", 400, "missing field: %s" % field)
    v = body[field]
    if not is_num(v):
        err("ERR_VALIDATION", 400, "field %s must be a number" % field)
    if not (0 <= v < 1):
        err("ERR_VALIDATION", 400, "field %s must be in [0,1)" % field)
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def find(kind, _id, err_id):
    ent = DB[kind].get(_id)
    if ent is None:
        err(err_id, 404, "%s not found" % kind)
    return ent


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate_and_respond(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def buyers_premium(h):
    p = (Decimal("0.25") * Decimal(min(h, TIER1_UPPER))
         + Decimal("0.20") * Decimal(max(0, min(h, TIER2_UPPER) - TIER1_UPPER))
         + Decimal("0.15") * Decimal(max(0, h - TIER2_UPPER)))
    return round_half_up(p)


def next_min_bid(lot):
    c = lot["current_high_bid_cents"]
    if c == 0:
        return lot["starting_bid_cents"]
    if c < 10000:
        inc = 1000
    elif c < 100000:
        inc = 5000
    elif c < 1000000:
        inc = 10000
    else:
        inc = 50000
    return c + inc


def storage_final_cents(invoice):
    start = parse_iso(invoice["storage_start_at"])
    elapsed = (CLOCK["now"] - start).total_seconds()
    days_stored = int(elapsed // 86400)
    chargeable = max(0, days_stored - FREE_STORAGE_DAYS)
    return chargeable * DAILY_STORAGE_CENTS


# ---------------------------------------------------------------------------
# Cross-entity computations
# ---------------------------------------------------------------------------
def lot_active_bids(lot_id):
    return [b for b in DB["bids"].values()
            if b["lot_id"] == lot_id and b["status"] == "ACTIVE"]


def recompute_lot_high(lot):
    actives = lot_active_bids(lot["id"])
    if not actives:
        lot["current_high_bid_cents"] = 0
        lot["current_high_bid_id"] = None
        return
    winner = sorted(actives, key=lambda b: (-b["amount_cents"], b["created_at"], b["_seq"]))[0]
    lot["current_high_bid_cents"] = winner["amount_cents"]
    lot["current_high_bid_id"] = winner["id"]


def invoice_lines_of(invoice_id):
    return [l for l in DB["invoice_lines"].values() if l["invoice_id"] == invoice_id]


def refresh_payment_status(invoice):
    ap = invoice["amount_paid_cents"]
    td = invoice["total_due_cents"]
    if ap == td:
        invoice["payment_status"] = "PAID"
    elif ap > 0:
        invoice["payment_status"] = "PARTIALLY_PAID"
    else:
        invoice["payment_status"] = "UNPAID"


def recompute_invoice_totals(invoice):
    active = [l for l in invoice_lines_of(invoice["id"]) if l["status"] == "ACTIVE"]
    invoice["hammer_subtotal_cents"] = sum(l["hammer_price_cents"] for l in active)
    invoice["premium_subtotal_cents"] = sum(l["buyers_premium_cents"] for l in active)
    invoice["total_due_cents"] = (invoice["hammer_subtotal_cents"]
                                  + invoice["premium_subtotal_cents"]
                                  + invoice["storage_fee_cents"]
                                  + invoice["shipping_fee_cents"])
    refresh_payment_status(invoice)


def compute_settlement_figures(settlement):
    consignment = DB["consignments"].get(settlement["consignment_id"])
    rate = consignment["commission_rate"] if consignment else 0
    lots = [l for l in DB["lots"].values()
            if l["consignment_id"] == settlement["consignment_id"]
            and l["sale_status"] == "HAMMERED"]
    gross = sum(l["hammer_price_cents"] for l in lots)
    commission = round_half_up(Decimal(gross) * Decimal(str(rate)))
    settlement["gross_hammer_cents"] = gross
    settlement["seller_commission_cents"] = commission
    settlement["net_payout_cents"] = gross - commission
    settlement["lot_count"] = len(lots)


# ===========================================================================
# ADMIN — logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    dt = req_datetime(body, "to_iso8601")
    CLOCK["now"] = dt
    return ok_empty(200)


# ===========================================================================
# Salerooms
# ===========================================================================
@app.route("/salerooms", methods=["POST"])
def create_saleroom():
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    name = req_str(body, "name")
    location = req_str(body, "location")
    capacity = req_int(body, "capacity", minimum=1)
    e = base_entity()
    e.update({"name": name, "location": location, "capacity": capacity})
    DB["salerooms"][e["id"]] = e
    return ok_object(e, 201)


# ===========================================================================
# Consignors
# ===========================================================================
@app.route("/consignors", methods=["POST"])
def create_consignor():
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    display_name = req_str(body, "display_name")
    email = req_str(body, "email")
    payout_method = "CHECK"
    if "payout_method" in body and body["payout_method"] is not None:
        payout_method = req_enum(body, "payout_method", PAYOUT_METHODS)
    e = base_entity()
    e.update({"display_name": display_name, "email": email, "payout_method": payout_method})
    DB["consignors"][e["id"]] = e
    return ok_object(e, 201)


# ===========================================================================
# Bidders
# ===========================================================================
@app.route("/bidders", methods=["POST"])
def create_bidder():
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    display_name = req_str(body, "display_name")
    email = req_str(body, "email")
    paddle_number = req_str(body, "paddle_number")
    deposit_cents = opt_int(body, "deposit_cents", 0, minimum=0)
    # priority 8: paddle uniqueness
    for b in DB["bidders"].values():
        if b["paddle_number"] == paddle_number:
            err("ERR_DUPLICATE_PADDLE", 409, "paddle_number already registered")
    e = base_entity()
    e.update({"display_name": display_name, "email": email, "paddle_number": paddle_number,
              "deposit_cents": deposit_cents, "status": "ACTIVE"})
    DB["bidders"][e["id"]] = e
    return ok_object(e, 201)


@app.route("/bidders/<bid_id>/suspend", methods=["POST"])
def suspend_bidder(bid_id):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    bidder = find("bidders", bid_id, "ERR_BIDDER_NOT_FOUND")
    if bidder["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "bidder is not ACTIVE")
    bidder["status"] = "SUSPENDED"
    touch(bidder)
    return ok_object(bidder, 200)


# ===========================================================================
# Auctions
# ===========================================================================
@app.route("/auctions", methods=["POST"])
def create_auction():
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    title = req_str(body, "title")
    sale_type = req_enum(body, "sale_type", SALE_TYPES)
    saleroom_id = req_str(body, "saleroom_id")
    start = req_datetime(body, "scheduled_start")
    end = req_datetime(body, "scheduled_end")
    if not (end > start):
        err("ERR_VALIDATION", 400, "scheduled_end must be after scheduled_start")
    find("salerooms", saleroom_id, "ERR_SALEROOM_NOT_FOUND")
    # priority 14: saleroom double booking (half-open overlap)
    for a in DB["auctions"].values():
        if a["saleroom_id"] != saleroom_id:
            continue
        s2 = parse_iso(a["scheduled_start"])
        e2 = parse_iso(a["scheduled_end"])
        if start < e2 and s2 < end:
            err("ERR_SALEROOM_DOUBLE_BOOKED", 409, "saleroom window collides")
    e = base_entity()
    e.update({"title": title, "sale_type": sale_type, "saleroom_id": saleroom_id,
              "scheduled_start": body["scheduled_start"], "scheduled_end": body["scheduled_end"],
              "status": "SCHEDULED"})
    DB["auctions"][e["id"]] = e
    return ok_object(e, 201)


@app.route("/auctions/<aid>/open", methods=["POST"])
def open_auction(aid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    a = find("auctions", aid, "ERR_AUCTION_NOT_FOUND")
    if a["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "auction is not SCHEDULED")
    a["status"] = "OPEN"
    touch(a)
    return ok_object(a, 200)


@app.route("/auctions/<aid>/close", methods=["POST"])
def close_auction(aid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    a = find("auctions", aid, "ERR_AUCTION_NOT_FOUND")
    if a["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "auction is not OPEN")
    a["status"] = "CLOSED"
    touch(a)
    return ok_object(a, 200)


@app.route("/auctions/<aid>", methods=["GET"])
def get_auction(aid):
    authenticate()
    a = find("auctions", aid, "ERR_AUCTION_NOT_FOUND")
    return ok_object(a, 200)


@app.route("/auctions", methods=["GET"])
def list_auctions():
    authenticate()
    items = list(DB["auctions"].values())
    sr = request.args.get("saleroom_id")
    st = request.args.get("status")
    if sr is not None:
        items = [i for i in items if i["saleroom_id"] == sr]
    if st is not None:
        items = [i for i in items if i["status"] == st]
    return paginate_and_respond(items)


# ===========================================================================
# Consignments
# ===========================================================================
@app.route("/consignments", methods=["POST"])
def create_consignment():
    uid, role = authenticate()
    authorize(role, {"AuctionStaff", "Consignor"})
    body = get_body()
    consignor_id = req_str(body, "consignor_id")
    commission_rate = req_rate(body, "commission_rate")
    est_low = req_int(body, "estimate_low_cents", minimum=0)
    est_high = req_int(body, "estimate_high_cents")
    if est_high < est_low:
        err("ERR_VALIDATION", 400, "estimate_high_cents must be >= estimate_low_cents")
    win_start = req_datetime(body, "intake_window_start")
    win_end = req_datetime(body, "intake_window_end")
    if not (win_end > win_start):
        err("ERR_VALIDATION", 400, "intake_window_end must be after intake_window_start")
    # existence
    find("consignors", consignor_id, "ERR_CONSIGNOR_NOT_FOUND")
    # ownership (priority 5)
    if role == "Consignor" and consignor_id != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "consignor_id must equal X-User-ID")
    # priority 15: intake window spacing (closed intervals + buffer)
    buffer_s = INTAKE_BUFFER_MINUTES * 60
    for c in DB["consignments"].values():
        if c["consignor_id"] != consignor_id:
            continue
        s2 = parse_iso(c["intake_window_start"])
        e2 = parse_iso(c["intake_window_end"])
        gap_ok = (e2.timestamp() + buffer_s <= win_start.timestamp()) or \
                 (win_end.timestamp() + buffer_s <= s2.timestamp())
        if not gap_ok:
            err("ERR_INTAKE_WINDOW_CONFLICT", 409, "intake window within buffer of another")
    e = base_entity()
    e.update({
        "consignor_id": consignor_id, "commission_rate": commission_rate,
        "estimate_low_cents": est_low, "estimate_high_cents": est_high,
        "intake_window_start": body["intake_window_start"],
        "intake_window_end": body["intake_window_end"],
        "status": "SUBMITTED",
        "appraised_low_cents": None, "appraised_high_cents": None, "appraisal_notes": None,
    })
    DB["consignments"][e["id"]] = e
    return ok_object(e, 201)


@app.route("/consignments/<cid>/appraise", methods=["POST"])
def appraise_consignment(cid):
    _, role = authenticate()
    authorize(role, {"Appraiser"})
    body = get_body()
    low = req_int(body, "appraised_low_cents")
    high = req_int(body, "appraised_high_cents")
    notes = None
    if "appraisal_notes" in body and body["appraisal_notes"] is not None:
        notes = req_str(body, "appraisal_notes", allow_empty=True)
    c = find("consignments", cid, "ERR_CONSIGNMENT_NOT_FOUND")
    if c["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "consignment is not SUBMITTED")
    c["appraised_low_cents"] = low
    c["appraised_high_cents"] = high
    c["appraisal_notes"] = notes
    c["status"] = "APPRAISED"
    touch(c)
    return ok_object(c, 200)


@app.route("/consignments/<cid>/decision", methods=["POST"])
def decide_consignment(cid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    outcome = req_enum(body, "outcome", {"ACCEPT", "DECLINE"})
    c = find("consignments", cid, "ERR_CONSIGNMENT_NOT_FOUND")
    if c["status"] != "APPRAISED":
        err("ERR_CONSIGNMENT_NOT_APPRAISED", 409, "consignment is not APPRAISED")
    c["status"] = "ACCEPTED" if outcome == "ACCEPT" else "DECLINED"
    touch(c)
    return ok_object(c, 200)


@app.route("/consignments/<cid>", methods=["GET"])
def get_consignment(cid):
    authenticate()
    c = find("consignments", cid, "ERR_CONSIGNMENT_NOT_FOUND")
    return ok_object(c, 200)


@app.route("/consignments", methods=["GET"])
def list_consignments():
    authenticate()
    items = list(DB["consignments"].values())
    co = request.args.get("consignor_id")
    st = request.args.get("status")
    if co is not None:
        items = [i for i in items if i["consignor_id"] == co]
    if st is not None:
        items = [i for i in items if i["status"] == st]
    return paginate_and_respond(items)


@app.route("/consignments/<cid>/settlement", methods=["POST"])
def create_settlement(cid):
    _, role = authenticate()
    authorize(role, {"SettlementOfficer", "AuctionStaff"})
    c = find("consignments", cid, "ERR_CONSIGNMENT_NOT_FOUND")
    e = base_entity()
    e.update({
        "consignment_id": c["id"],
        "gross_hammer_cents": 0, "seller_commission_cents": 0,
        "net_payout_cents": 0, "lot_count": 0, "status": "DRAFT",
    })
    compute_settlement_figures(e)  # provisional
    DB["settlements"][e["id"]] = e
    return ok_object(e, 201)


# ===========================================================================
# Lots
# ===========================================================================
@app.route("/lots", methods=["POST"])
def create_lot():
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    consignment_id = req_str(body, "consignment_id")
    auction_id = req_str(body, "auction_id")
    title = req_str(body, "title")
    category = req_str(body, "category")
    reserve_cents = req_int(body, "reserve_cents", minimum=0)
    starting_bid_cents = req_int(body, "starting_bid_cents", minimum=1)
    est_low = req_int(body, "estimate_low_cents")
    est_high = req_int(body, "estimate_high_cents")
    if est_high < est_low:
        err("ERR_VALIDATION", 400, "estimate_high_cents must be >= estimate_low_cents")
    lot_number = req_int(body, "lot_number", minimum=1)
    # existence left-to-right (body FKs in input order)
    consignment = find("consignments", consignment_id, "ERR_CONSIGNMENT_NOT_FOUND")
    find("auctions", auction_id, "ERR_AUCTION_NOT_FOUND")
    # state (priority 7)
    if consignment["status"] != "ACCEPTED":
        err("ERR_CONSIGNMENT_NOT_ACCEPTED", 409, "consignment is not ACCEPTED")
    e = base_entity()
    e.update({
        "consignment_id": consignment_id, "auction_id": auction_id,
        "title": title, "category": category, "reserve_cents": reserve_cents,
        "starting_bid_cents": starting_bid_cents,
        "estimate_low_cents": est_low, "estimate_high_cents": est_high,
        "lot_number": lot_number, "sale_status": "CATALOGED",
        "current_high_bid_cents": 0, "current_high_bid_id": None,
        "hammer_price_cents": None, "winning_bid_id": None,
    })
    DB["lots"][e["id"]] = e
    return ok_object(e, 201)


@app.route("/lots/<lid>/open", methods=["POST"])
def open_lot(lid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    lot = find("lots", lid, "ERR_LOT_NOT_FOUND")
    if lot["sale_status"] != "CATALOGED":
        err("ERR_INVALID_STATE", 409, "lot is not CATALOGED")
    auction = DB["auctions"].get(lot["auction_id"])
    if auction is None or auction["status"] != "OPEN":
        err("ERR_AUCTION_NOT_OPEN", 409, "lot's auction is not OPEN")
    lot["sale_status"] = "OPEN"
    touch(lot)
    return ok_object(lot, 200)


@app.route("/lots/<lid>/hammer", methods=["POST"])
def hammer_lot(lid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    lot = find("lots", lid, "ERR_LOT_NOT_FOUND")
    if lot["sale_status"] != "OPEN":
        err("ERR_LOT_NOT_OPEN", 409, "lot is not OPEN")
    actives = lot_active_bids(lot["id"])
    if not actives:
        err("ERR_NO_BIDS", 409, "no ACTIVE bids on the lot")
    if lot["current_high_bid_cents"] < lot["reserve_cents"]:
        err("ERR_RESERVE_NOT_MET", 409, "current high bid below reserve")
    # winner: max amount, tie earliest created_at (id never a tiebreak)
    winner = sorted(actives, key=lambda b: (-b["amount_cents"], b["created_at"], b["_seq"]))[0]
    winner["status"] = "WINNING"
    touch(winner)
    for b in actives:
        if b["id"] != winner["id"]:
            b["status"] = "OUTBID"
            touch(b)
    lot["sale_status"] = "HAMMERED"
    lot["hammer_price_cents"] = winner["amount_cents"]
    lot["winning_bid_id"] = winner["id"]
    # CASCADE: find-or-create invoice
    invoice = None
    for inv in DB["invoices"].values():
        if inv["bidder_id"] == winner["bidder_id"] and inv["auction_id"] == lot["auction_id"]:
            invoice = inv
            break
    if invoice is None:
        invoice = base_entity()
        invoice.update({
            "bidder_id": winner["bidder_id"], "auction_id": lot["auction_id"],
            "hammer_subtotal_cents": 0, "premium_subtotal_cents": 0,
            "storage_fee_cents": 0, "shipping_fee_cents": 0, "total_due_cents": 0,
            "amount_paid_cents": 0, "total_refunded_cents": 0,
            "payment_status": "UNPAID", "fulfillment_status": "PENDING",
            "fulfillment_method": None, "storage_start_at": fmt(CLOCK["now"]),
        })
        DB["invoices"][invoice["id"]] = invoice
    # create invoice line
    premium = buyers_premium(winner["amount_cents"])
    line = base_entity()
    line.update({
        "invoice_id": invoice["id"], "lot_id": lot["id"],
        "hammer_price_cents": winner["amount_cents"],
        "buyers_premium_cents": premium,
        "line_total_cents": winner["amount_cents"] + premium,
        "status": "ACTIVE",
    })
    DB["invoice_lines"][line["id"]] = line
    # recompute invoice totals + version bump
    recompute_invoice_totals(invoice)
    touch(invoice)
    # lot version bump for the hammer
    touch(lot)
    return ok_object(lot, 200)


@app.route("/lots/<lid>/pass", methods=["POST"])
def pass_lot(lid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    lot = find("lots", lid, "ERR_LOT_NOT_FOUND")
    if lot["sale_status"] != "OPEN":
        err("ERR_LOT_NOT_OPEN", 409, "lot is not OPEN")
    for b in lot_active_bids(lot["id"]):
        b["status"] = "OUTBID"
        touch(b)
    lot["sale_status"] = "PASSED"
    touch(lot)
    return ok_object(lot, 200)


@app.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    authenticate()
    lot = find("lots", lid, "ERR_LOT_NOT_FOUND")
    return ok_object(lot, 200)


@app.route("/lots", methods=["GET"])
def list_lots():
    authenticate()
    items = list(DB["lots"].values())
    cid = request.args.get("consignment_id")
    aid = request.args.get("auction_id")
    st = request.args.get("sale_status")
    if cid is not None:
        items = [i for i in items if i["consignment_id"] == cid]
    if aid is not None:
        items = [i for i in items if i["auction_id"] == aid]
    if st is not None:
        items = [i for i in items if i["sale_status"] == st]
    return paginate_and_respond(items)


# ===========================================================================
# Bids
# ===========================================================================
@app.route("/lots/<lid>/bids", methods=["POST"])
def place_bid(lid):
    uid, role = authenticate()
    authorize(role, {"Bidder"})
    body = get_body()
    bidder_id = req_str(body, "bidder_id")
    bid_type = req_enum(body, "bid_type", BID_TYPES)
    amount_cents = req_int(body, "amount_cents", minimum=1)
    expected_lot_version = req_int(body, "expected_lot_version", minimum=1)
    # existence: path lot then body bidder
    lot = find("lots", lid, "ERR_LOT_NOT_FOUND")
    bidder = find("bidders", bidder_id, "ERR_BIDDER_NOT_FOUND")
    # ownership (priority 5)
    if bidder_id != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "bidder_id must equal X-User-ID")
    # OCC (priority 6)
    if expected_lot_version != lot["version"]:
        err("ERR_STALE_VERSION", 412, "expected_lot_version does not match")
    # state (priority 7)
    if lot["sale_status"] != "OPEN":
        err("ERR_LOT_NOT_OPEN", 409, "lot is not OPEN")
    # business: suspension, then min-increment, then deposit
    if bidder["status"] != "ACTIVE":
        err("ERR_BIDDER_SUSPENDED", 403, "bidder is SUSPENDED")
    if amount_cents < next_min_bid(lot):
        err("ERR_BID_TOO_LOW", 409, "bid below next minimum bid")
    if amount_cents >= HIGH_VALUE_LOT_CENTS and bidder["deposit_cents"] < MIN_DEPOSIT_FOR_HIGH_VALUE_CENTS:
        err("ERR_INSUFFICIENT_DEPOSIT", 402, "insufficient deposit for high-value bid")
    # accept: supersede prior high
    prior_id = lot["current_high_bid_id"]
    if prior_id is not None:
        prior = DB["bids"].get(prior_id)
        if prior is not None and prior["status"] == "ACTIVE":
            prior["status"] = "OUTBID"
            touch(prior)
    bid = base_entity()
    bid.update({
        "lot_id": lot["id"], "bidder_id": bidder_id, "bid_type": bid_type,
        "amount_cents": amount_cents, "expected_lot_version": expected_lot_version,
        "status": "ACTIVE",
    })
    DB["bids"][bid["id"]] = bid
    lot["current_high_bid_cents"] = amount_cents
    lot["current_high_bid_id"] = bid["id"]
    touch(lot)
    return ok_object(bid, 201)


@app.route("/bids/<bid_id>/retract", methods=["POST"])
def retract_bid(bid_id):
    _, role = authenticate()
    authorize(role, {"Bidder", "AuctionStaff"})
    bid = find("bids", bid_id, "ERR_BID_NOT_FOUND")
    if bid["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "bid is not ACTIVE")
    lot = DB["lots"].get(bid["lot_id"])
    if lot is None or lot["sale_status"] != "OPEN":
        err("ERR_LOT_NOT_OPEN", 409, "lot is no longer OPEN")
    was_high = (lot["current_high_bid_id"] == bid["id"])
    bid["status"] = "RETRACTED"
    touch(bid)
    if was_high:
        recompute_lot_high(lot)
        touch(lot)
    return ok_object(bid, 200)


@app.route("/bids/<bid_id>", methods=["GET"])
def get_bid(bid_id):
    authenticate()
    bid = find("bids", bid_id, "ERR_BID_NOT_FOUND")
    return ok_object(bid, 200)


@app.route("/bids", methods=["GET"])
def list_bids():
    authenticate()
    items = list(DB["bids"].values())
    lid = request.args.get("lot_id")
    bidder_id = request.args.get("bidder_id")
    st = request.args.get("status")
    if lid is not None:
        items = [i for i in items if i["lot_id"] == lid]
    if bidder_id is not None:
        items = [i for i in items if i["bidder_id"] == bidder_id]
    if st is not None:
        items = [i for i in items if i["status"] == st]
    return paginate_and_respond(items)


# ===========================================================================
# Invoices
# ===========================================================================
@app.route("/invoices/<iid>/payments", methods=["POST"])
def pay_invoice(iid):
    uid, role = authenticate()
    authorize(role, {"Bidder", "AuctionStaff"})
    body = get_body()
    amount_cents = req_int(body, "amount_cents", minimum=1)
    invoice = find("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    # ownership (priority 5)
    if role == "Bidder" and invoice["bidder_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "invoice does not belong to bidder")
    # business: overpayment (priority 17)
    if invoice["amount_paid_cents"] + amount_cents > invoice["total_due_cents"]:
        err("ERR_OVERPAYMENT", 409, "payment exceeds remaining balance")
    invoice["amount_paid_cents"] += amount_cents
    refresh_payment_status(invoice)
    touch(invoice)
    return ok_object(invoice, 200)


@app.route("/invoices/<iid>/ready", methods=["POST"])
def ready_invoice(iid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    body = get_body()
    method = req_enum(body, "fulfillment_method", FULFILLMENT_METHODS)
    shipping = opt_int(body, "shipping_fee_cents", 0, minimum=0)
    invoice = find("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    if invoice["fulfillment_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "invoice fulfillment is not PENDING")
    invoice["fulfillment_method"] = method
    invoice["storage_fee_cents"] = storage_final_cents(invoice)
    invoice["shipping_fee_cents"] = shipping if method == "SHIP" else 0
    recompute_invoice_totals(invoice)
    invoice["fulfillment_status"] = "READY"
    touch(invoice)
    return ok_object(invoice, 200)


@app.route("/invoices/<iid>/fulfill", methods=["POST"])
def fulfill_invoice(iid):
    _, role = authenticate()
    authorize(role, {"AuctionStaff"})
    invoice = find("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    if invoice["fulfillment_status"] != "READY":
        err("ERR_INVALID_STATE", 409, "invoice fulfillment is not READY")
    if invoice["payment_status"] != "PAID":
        err("ERR_INVOICE_NOT_PAID", 409, "invoice is not PAID")
    invoice["fulfillment_status"] = "PICKED_UP" if invoice["fulfillment_method"] == "PICKUP" else "SHIPPED"
    touch(invoice)
    return ok_object(invoice, 200)


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    authenticate()
    invoice = find("invoices", iid, "ERR_INVOICE_NOT_FOUND")
    return ok_object(invoice, 200)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    authenticate()
    items = list(DB["invoices"].values())
    bidder_id = request.args.get("bidder_id")
    aid = request.args.get("auction_id")
    ps = request.args.get("payment_status")
    if bidder_id is not None:
        items = [i for i in items if i["bidder_id"] == bidder_id]
    if aid is not None:
        items = [i for i in items if i["auction_id"] == aid]
    if ps is not None:
        items = [i for i in items if i["payment_status"] == ps]
    return paginate_and_respond(items)


# ===========================================================================
# Invoice Lines
# ===========================================================================
@app.route("/invoice-lines/<line_id>", methods=["GET"])
def get_invoice_line(line_id):
    authenticate()
    line = find("invoice_lines", line_id, "ERR_INVOICE_LINE_NOT_FOUND")
    return ok_object(line, 200)


@app.route("/invoice-lines", methods=["GET"])
def list_invoice_lines():
    authenticate()
    items = list(DB["invoice_lines"].values())
    iid = request.args.get("invoice_id")
    lid = request.args.get("lot_id")
    if iid is not None:
        items = [i for i in items if i["invoice_id"] == iid]
    if lid is not None:
        items = [i for i in items if i["lot_id"] == lid]
    return paginate_and_respond(items)


# ===========================================================================
# Settlements
# ===========================================================================
@app.route("/settlements/<sid>/approve", methods=["POST"])
def approve_settlement(sid):
    _, role = authenticate()
    authorize(role, {"SettlementOfficer"})
    settlement = find("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    if settlement["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "settlement is not DRAFT")
    # every invoice with a non-VOID line for this consignment's HAMMERED lots must be PAID
    cid = settlement["consignment_id"]
    hammered_lot_ids = {l["id"] for l in DB["lots"].values()
                        if l["consignment_id"] == cid and l["sale_status"] == "HAMMERED"}
    invoice_ids = set()
    for line in DB["invoice_lines"].values():
        if line["lot_id"] in hammered_lot_ids and line["status"] != "VOID":
            invoice_ids.add(line["invoice_id"])
    for inv_id in invoice_ids:
        inv = DB["invoices"].get(inv_id)
        if inv is not None and inv["payment_status"] != "PAID":
            err("ERR_INVOICES_UNPAID", 409, "related invoices are not all PAID")
    compute_settlement_figures(settlement)  # final variant
    settlement["status"] = "APPROVED"
    touch(settlement)
    return ok_object(settlement, 200)


@app.route("/settlements/<sid>/pay", methods=["POST"])
def pay_settlement(sid):
    _, role = authenticate()
    authorize(role, {"SettlementOfficer"})
    settlement = find("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    if settlement["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "settlement is not APPROVED")
    settlement["status"] = "PAID"
    touch(settlement)
    return ok_object(settlement, 200)


@app.route("/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    authenticate()
    settlement = find("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    return ok_object(settlement, 200)


@app.route("/settlements", methods=["GET"])
def list_settlements():
    authenticate()
    items = list(DB["settlements"].values())
    cid = request.args.get("consignment_id")
    st = request.args.get("status")
    if cid is not None:
        items = [i for i in items if i["consignment_id"] == cid]
    if st is not None:
        items = [i for i in items if i["status"] == st]
    return paginate_and_respond(items)


# ===========================================================================
# Disputes
# ===========================================================================
@app.route("/disputes", methods=["POST"])
def create_dispute():
    uid, role = authenticate()
    authorize(role, {"Bidder"})
    body = get_body()
    invoice_line_id = req_str(body, "invoice_line_id")
    reason = req_str(body, "reason")
    line = find("invoice_lines", invoice_line_id, "ERR_INVOICE_LINE_NOT_FOUND")
    invoice = DB["invoices"].get(line["invoice_id"])
    # ownership (priority 5)
    if invoice is None or invoice["bidder_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "line does not belong to bidder")
    # business: no live dispute already (priority 13)
    for d in DB["disputes"].values():
        if d["invoice_line_id"] == invoice_line_id and d["status"] in ("OPEN", "UNDER_REVIEW"):
            err("ERR_LINE_ALREADY_DISPUTED", 409, "an open/under-review dispute exists")
    e = base_entity()
    e.update({
        "invoice_line_id": invoice_line_id, "bidder_id": invoice["bidder_id"],
        "reason": reason, "status": "OPEN", "resolution_notes": None, "refund_cents": 0,
    })
    DB["disputes"][e["id"]] = e
    return ok_object(e, 201)


@app.route("/disputes/<did>/review", methods=["POST"])
def review_dispute(did):
    _, role = authenticate()
    authorize(role, {"Appraiser"})
    d = find("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "dispute is not OPEN")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return ok_object(d, 200)


@app.route("/disputes/<did>/request-info", methods=["POST"])
def request_info_dispute(did):
    _, role = authenticate()
    authorize(role, {"Appraiser"})
    get_body()  # optional note accepted, no ledger effect
    d = find("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "dispute is not UNDER_REVIEW")
    d["status"] = "OPEN"
    touch(d)
    return ok_object(d, 200)


@app.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    _, role = authenticate()
    authorize(role, {"Appraiser"})
    body = get_body()
    outcome = req_enum(body, "outcome", {"UPHELD", "REJECTED"})
    notes = None
    if "resolution_notes" in body and body["resolution_notes"] is not None:
        notes = req_str(body, "resolution_notes", allow_empty=True)
    d = find("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "dispute is not UNDER_REVIEW")
    line = DB["invoice_lines"].get(d["invoice_line_id"])

    if outcome == "REJECTED":
        d["status"] = "REJECTED"
        d["resolution_notes"] = notes
        touch(d)
        return ok_object(d, 200)

    # UPHELD: requires line still ACTIVE
    if line is None or line["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "challenged line is not ACTIVE")
    d["refund_cents"] = line["line_total_cents"]
    d["resolution_notes"] = notes
    d["status"] = "UPHELD"
    touch(d)
    # void the line
    line["status"] = "VOID"
    touch(line)
    # recompute invoice
    invoice = DB["invoices"].get(line["invoice_id"])
    if invoice is not None:
        invoice["total_refunded_cents"] += line["line_total_cents"]
        recompute_invoice_totals(invoice)
        touch(invoice)
    # rescind the lot
    lot = DB["lots"].get(line["lot_id"])
    if lot is not None and lot["sale_status"] == "HAMMERED":
        lot["sale_status"] = "RESCINDED"
        touch(lot)
        # recompute any DRAFT settlement for the lot's consignment
        for s in DB["settlements"].values():
            if s["consignment_id"] == lot["consignment_id"] and s["status"] == "DRAFT":
                compute_settlement_figures(s)
                touch(s)
    return ok_object(d, 200)


@app.route("/disputes/<did>", methods=["GET"])
def get_dispute(did):
    authenticate()
    d = find("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    return ok_object(d, 200)


@app.route("/disputes", methods=["GET"])
def list_disputes():
    authenticate()
    items = list(DB["disputes"].values())
    line_id = request.args.get("invoice_line_id")
    bidder_id = request.args.get("bidder_id")
    st = request.args.get("status")
    if line_id is not None:
        items = [i for i in items if i["invoice_line_id"] == line_id]
    if bidder_id is not None:
        items = [i for i in items if i["bidder_id"] == bidder_id]
    if st is not None:
        items = [i for i in items if i["status"] == st]
    return paginate_and_respond(items)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
