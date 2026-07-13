"""
Live-Event Primary Ticketing & Box Office API.

A single-file Flask implementation. In-memory storage only. The store starts
empty on every boot; every entity is constructed by callers through the declared
API surface. A logical clock (default 2026-05-01T00:00:00Z) drives every
timestamp so time-dependent behavior is deterministic.
"""

import os
import random
import string
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Buyer", "BoxOffice", "Promoter", "GateScanner"}
MAX_SEATS_PER_HOLD = 2

EVENT_STATUSES = {"DRAFT", "ANNOUNCED", "PRESALE", "ONSALE", "POSTPONED", "CANCELED", "COMPLETED"}
LEGAL_EVENT = {
    "ANNOUNCED": {"DRAFT"},
    "PRESALE": {"ANNOUNCED"},
    "ONSALE": {"ANNOUNCED", "PRESALE", "POSTPONED"},
    "POSTPONED": {"ONSALE"},
    "CANCELED": {"DRAFT", "ANNOUNCED", "PRESALE", "ONSALE", "POSTPONED"},
    "COMPLETED": {"ONSALE"},
}

DELIVERY_METHODS = {"MOBILE", "PRINT", "WILL_CALL"}
REFUND_REASONS = {"CUSTOMER_REQUEST", "POSTPONEMENT", "EVENT_CANCELED"}
REFUND_DESTINATIONS = {"ORIGINAL", "CREDIT"}
TRANSFER_KINDS = {"GIFT", "RESALE"}

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_PRICE_LEVEL_NOT_FOUND": 404,
    "ERR_SEAT_NOT_FOUND": 404,
    "ERR_BUYER_NOT_FOUND": 404,
    "ERR_QUEUE_TOKEN_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_REFUND_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_EVENT_NOT_ON_SALE": 409,
    "ERR_NOT_ADMITTED": 409,
    "ERR_ALREADY_ADMITTED": 409,
    "ERR_ADMISSION_WINDOW_EXPIRED": 409,
    "ERR_INVALID_PRESALE_CODE": 409,
    "ERR_EMPTY_SEAT_SELECTION": 422,
    "ERR_SEAT_UNAVAILABLE": 409,
    "ERR_DUPLICATE_SEAT": 409,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_TICKET_NOT_DELIVERED": 409,
    "ERR_TICKET_ALREADY_SCANNED": 409,
    "ERR_TICKET_NOT_TRANSFERABLE": 409,
    "ERR_REFUND_EXCEEDS_BALANCE": 422,
    "ERR_SETTLEMENT_NOT_READY": 409,
}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "buyers": {},
    "events": {},
    "price_levels": {},
    "seats": {},
    "queue_tokens": {},
    "holds": {},
    "orders": {},
    "tickets": {},
    "transfers": {},
    "refunds": {},
    "settlements": {},
}

CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0)}
_SEQ = {"n": 0}
LOCK = threading.RLock()


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now():
    return CLOCK["now"]


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def iso(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime format")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def add_minutes(dt, minutes):
    from datetime import timedelta
    return dt + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Errors and response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)


def meta(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": iso(now())}
    if extra:
        m.update(extra)
    return m


def respond(data, response_type="object", status=200, pagination=None):
    body = {"meta": meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"},
    }
    return jsonify(body), 405


@app.before_request
def _acquire_lock():
    LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        LOCK.release()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Auth / request helpers
# ---------------------------------------------------------------------------
def guard(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or invalid auth headers")
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "role not permitted for this operation")
    return uid, role


def body_json():
    b = request.get_json(silent=True, force=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise err("ERR_VALIDATION", "request body must be a JSON object")
    return b


def require_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "%s is required" % key)
    return v


def require_int(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "%s must be an integer" % key)
    return v


def opt_int(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "%s must be an integer" % key)
    return v


def opt_bool(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", "%s must be a boolean" % key)
    return v


def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, serializer):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    data = [serializer(e) for e in page]
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return respond(data, "array", 200, pagination)


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


def base_record():
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1, "_seq": next_seq()}


def get_or_404(collection, ident, error_id):
    ent = db[collection].get(ident)
    if ent is None:
        raise err(error_id)
    return ent


# ---------------------------------------------------------------------------
# Computations
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def event_seats(event_id):
    return [s for s in db["seats"].values() if s["event_id"] == event_id]


def event_pct_sold(event):
    seats = event_seats(event["id"])
    total = len(seats)
    if total == 0:
        return 0.0
    sold = sum(1 for s in seats if s["status"] == "SOLD")
    return (sold / total) * 100


def current_face_value(seat):
    pl = db["price_levels"][seat["price_level_id"]]
    event = db["events"][seat["event_id"]]
    base = pl["base_face_value_cents"]
    if not pl["dynamic_pricing_enabled"]:
        mult = Decimal("1.00")
    else:
        pct = event_pct_sold(event)
        if pct < 50:
            mult = Decimal("1.00")
        elif pct < 80:
            mult = Decimal("1.25")
        else:
            mult = Decimal("1.50")
    if pl["is_platinum"]:
        mult = max(mult, Decimal("2.00"))
    raw = round_half_up(Decimal(base) * mult)
    floor_c = base
    ceil_c = base * 3
    return min(max(raw, floor_c), ceil_c)


def buyer_credit_balance(buyer_id):
    total = 0
    for r in db["refunds"].values():
        if r["status"] != "COMPLETED" or r["refund_destination"] != "CREDIT":
            continue
        order = db["orders"].get(r["order_id"])
        if order and order["buyer_id"] == buyer_id:
            total += r["amount_cents"]
    return total


def order_tickets(order_id):
    return [t for t in db["tickets"].values() if t["order_id"] == order_id]


def order_refunded_amount(order_id):
    total = 0
    for r in db["refunds"].values():
        if r["order_id"] == order_id and r["status"] == "COMPLETED":
            total += r["amount_cents"]
    return total


def event_orders(event_id):
    return [o for o in db["orders"].values() if o["event_id"] == event_id]


def event_tickets(event_id):
    result = []
    for o in event_orders(event_id):
        result.extend(order_tickets(o["id"]))
    return result


def compute_settlement_figures(event_id):
    tickets = event_tickets(event_id)
    gross = sum(t["face_value_cents"] for t in tickets)
    net = sum(t["face_value_cents"] for t in tickets if t["status"] == "VALID")
    service = sum(
        o["service_fee_cents"]
        for o in event_orders(event_id)
        if o["status"] in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED")
    )
    refunds = 0
    order_ids = {o["id"] for o in event_orders(event_id)}
    for r in db["refunds"].values():
        if r["order_id"] in order_ids and r["status"] == "COMPLETED":
            refunds += r["amount_cents"]
    return {
        "gross_face_cents": gross,
        "net_to_promoter_cents": net,
        "service_fees_cents": service,
        "refunds_cents": refunds,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_buyer(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "email": b["email"],
        "credit_balance_cents": buyer_credit_balance(b["id"]),
        "created_at": iso(b["created_at"]),
        "updated_at": iso(b["updated_at"]),
        "version": b["version"],
    }


def ser_event(e):
    seats = event_seats(e["id"])
    total = len(seats)
    avail = sum(1 for s in seats if s["status"] == "AVAILABLE")
    held = sum(1 for s in seats if s["status"] == "HELD")
    sold = sum(1 for s in seats if s["status"] == "SOLD")
    pct = (sold / total) * 100 if total > 0 else 0.0
    presale_uses = 0
    if e["presale_code"] is not None:
        presale_uses = sum(
            1
            for h in db["holds"].values()
            if h["event_id"] == e["id"]
            and h["presale_code"] == e["presale_code"]
            and h["status"] in ("ACTIVE", "CONVERTED")
        )
    return {
        "id": e["id"],
        "promoter_id": e["promoter_id"],
        "name": e["name"],
        "venue_name": e["venue_name"],
        "event_datetime": e.get("event_datetime_str", iso(e["event_datetime"])),
        "hold_ttl_minutes": e["hold_ttl_minutes"],
        "purchase_window_minutes": e["purchase_window_minutes"],
        "presale_code": e["presale_code"],
        "presale_max_uses": e["presale_max_uses"],
        "status": e["status"],
        "total_capacity": total,
        "seats_available": avail,
        "seats_held": held,
        "seats_sold": sold,
        "pct_sold": pct,
        "presale_uses_count": presale_uses,
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_price_level(p):
    return {
        "id": p["id"],
        "event_id": p["event_id"],
        "name": p["name"],
        "base_face_value_cents": p["base_face_value_cents"],
        "is_platinum": p["is_platinum"],
        "service_fee_pct": p["service_fee_pct"],
        "service_fee_flat_cents": p["service_fee_flat_cents"],
        "dynamic_pricing_enabled": p["dynamic_pricing_enabled"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_seat(s):
    return {
        "id": s["id"],
        "event_id": s["event_id"],
        "price_level_id": s["price_level_id"],
        "section": s["section"],
        "row": s["row"],
        "seat_number": s["seat_number"],
        "status": s["status"],
        "current_face_value_cents": current_face_value(s),
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_queue_token(t):
    return {
        "id": t["id"],
        "event_id": t["event_id"],
        "buyer_id": t["buyer_id"],
        "position": t["position"],
        "status": t["status"],
        "admitted_at": iso(t["admitted_at"]),
        "purchase_deadline": iso(t["purchase_deadline"]),
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_hold(h):
    return {
        "id": h["id"],
        "event_id": h["event_id"],
        "buyer_id": h["buyer_id"],
        "seat_ids": list(h["seat_ids"]),
        "presale_code": h["presale_code"],
        "status": h["status"],
        "face_subtotal_cents": h["face_subtotal_cents"],
        "expires_at": iso(h["expires_at"]),
        "created_at": iso(h["created_at"]),
        "updated_at": iso(h["updated_at"]),
        "version": h["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "event_id": o["event_id"],
        "buyer_id": o["buyer_id"],
        "hold_id": o["hold_id"],
        "delivery_method": o["delivery_method"],
        "status": o["status"],
        "face_total_cents": o["face_total_cents"],
        "service_fee_cents": o["service_fee_cents"],
        "order_total_cents": o["order_total_cents"],
        "paid_amount_cents": o["paid_amount_cents"],
        "refunded_amount_cents": order_refunded_amount(o["id"]),
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def ser_ticket(t):
    return {
        "id": t["id"],
        "order_id": t["order_id"],
        "seat_id": t["seat_id"],
        "holder_buyer_id": t["holder_buyer_id"],
        "face_value_cents": t["face_value_cents"],
        "delivery_method": t["delivery_method"],
        "status": t["status"],
        "delivery_status": t["delivery_status"],
        "scan_status": t["scan_status"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_transfer(t):
    return {
        "id": t["id"],
        "ticket_id": t["ticket_id"],
        "from_buyer_id": t["from_buyer_id"],
        "to_buyer_id": t["to_buyer_id"],
        "kind": t["kind"],
        "list_price_cents": t["list_price_cents"],
        "status": t["status"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_refund(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "reason": r["reason"],
        "refund_destination": r["refund_destination"],
        "ticket_ids": list(r["ticket_ids"]),
        "amount_cents": r["amount_cents"],
        "status": r["status"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_settlement(s):
    if s["status"] == "FINALIZED":
        figures = {
            "gross_face_cents": s["gross_face_cents"],
            "net_to_promoter_cents": s["net_to_promoter_cents"],
            "service_fees_cents": s["service_fees_cents"],
            "refunds_cents": s["refunds_cents"],
        }
    else:
        figures = compute_settlement_figures(s["event_id"])
    return {
        "id": s["id"],
        "event_id": s["event_id"],
        "gross_face_cents": figures["gross_face_cents"],
        "service_fees_cents": figures["service_fees_cents"],
        "refunds_cents": figures["refunds_cents"],
        "net_to_promoter_cents": figures["net_to_promoter_cents"],
        "status": s["status"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    guard({"BoxOffice"})
    body = body_json()
    if "to_iso8601" not in body:
        raise err("ERR_VALIDATION", "to_iso8601 is required")
    CLOCK["now"] = parse_iso(body["to_iso8601"])
    return respond({}, "object", 200)


# ---------------------------------------------------------------------------
# Buyers
# ---------------------------------------------------------------------------
@app.route("/buyers", methods=["POST"])
def create_buyer():
    guard({"BoxOffice"})
    body = body_json()
    name = require_str(body, "name")
    email = require_str(body, "email")
    b = base_record()
    b.update({"_type": "buyer", "name": name, "email": email})
    db["buyers"][b["id"]] = b
    return respond(ser_buyer(b), "object", 201)


@app.route("/buyers/<buyer_id>", methods=["GET"])
def get_buyer(buyer_id):
    guard({"Buyer", "BoxOffice"})
    b = get_or_404("buyers", buyer_id, "ERR_BUYER_NOT_FOUND")
    return respond(ser_buyer(b), "object", 200)


@app.route("/buyers/<buyer_id>/queue-tokens", methods=["GET"])
def list_buyer_tokens(buyer_id):
    guard({"Buyer", "BoxOffice"})
    get_or_404("buyers", buyer_id, "ERR_BUYER_NOT_FOUND")
    items = [t for t in db["queue_tokens"].values() if t["buyer_id"] == buyer_id]
    return list_response(items, ser_queue_token)


@app.route("/buyers/<buyer_id>/transfers", methods=["GET"])
def list_buyer_transfers(buyer_id):
    guard({"Buyer", "BoxOffice"})
    get_or_404("buyers", buyer_id, "ERR_BUYER_NOT_FOUND")
    items = [
        t
        for t in db["transfers"].values()
        if t["from_buyer_id"] == buyer_id or t["to_buyer_id"] == buyer_id
    ]
    return list_response(items, ser_transfer)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@app.route("/events", methods=["POST"])
def create_event():
    uid, role = guard({"Promoter", "BoxOffice"})
    body = body_json()
    promoter_id = require_str(body, "promoter_id")
    name = require_str(body, "name")
    venue_name = require_str(body, "venue_name")
    if "event_datetime" not in body:
        raise err("ERR_VALIDATION", "event_datetime is required")
    event_dt = parse_iso(body["event_datetime"])
    hold_ttl = opt_int(body, "hold_ttl_minutes", 15)
    purchase_window = opt_int(body, "purchase_window_minutes", 30)
    presale_code = body.get("presale_code", None)
    if presale_code is not None and not isinstance(presale_code, str):
        raise err("ERR_VALIDATION", "presale_code must be a string")
    presale_max_uses = opt_int(body, "presale_max_uses", 0)

    if role == "Promoter" and promoter_id != uid:
        raise err("ERR_UNAUTHORIZED", "promoter_id must equal the acting promoter")
    if event_dt <= now():
        raise err("ERR_VALIDATION", "event_datetime must be strictly after the current clock")

    e = base_record()
    e.update({
        "_type": "event",
        "promoter_id": promoter_id,
        "name": name,
        "venue_name": venue_name,
        "event_datetime": event_dt,
        "event_datetime_str": body["event_datetime"],
        "hold_ttl_minutes": hold_ttl,
        "purchase_window_minutes": purchase_window,
        "presale_code": presale_code,
        "presale_max_uses": presale_max_uses,
        "status": "DRAFT",
    })
    db["events"][e["id"]] = e
    return respond(ser_event(e), "object", 201)


@app.route("/events/<event_id>", methods=["GET"])
def get_event(event_id):
    guard({"Buyer", "BoxOffice", "Promoter", "GateScanner"})
    e = get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    return respond(ser_event(e), "object", 200)


@app.route("/events/<event_id>/status", methods=["POST"])
def event_status(event_id):
    guard({"Promoter", "BoxOffice"})
    body = body_json()
    target = body.get("target_status")
    if not isinstance(target, str) or target not in EVENT_STATUSES:
        raise err("ERR_VALIDATION", "target_status is required and must be a valid status")
    event = get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")

    if target not in LEGAL_EVENT or event["status"] not in LEGAL_EVENT[target]:
        raise err("ERR_INVALID_STATE", "illegal transition from %s to %s" % (event["status"], target))

    if target == "ANNOUNCED":
        if not any(p["event_id"] == event_id for p in db["price_levels"].values()):
            raise err("ERR_INVALID_STATE", "at least one price level required")
    elif target == "PRESALE":
        if event["presale_code"] is None:
            raise err("ERR_INVALID_STATE", "presale_code required to enter PRESALE")
    elif target == "ONSALE":
        if not event_seats(event_id):
            raise err("ERR_INVALID_STATE", "at least one seat required")
    elif target == "POSTPONED":
        if "new_event_datetime" not in body or body.get("new_event_datetime") is None:
            raise err("ERR_VALIDATION", "new_event_datetime is required for postponement")
        new_dt = parse_iso(body["new_event_datetime"])
        if new_dt <= now():
            raise err("ERR_INVALID_STATE", "new_event_datetime must be strictly after the current clock")
    elif target == "COMPLETED":
        if now() < event["event_datetime"]:
            raise err("ERR_INVALID_STATE", "event has not started yet")

    # Apply side effects
    if target == "POSTPONED":
        event["event_datetime"] = new_dt
        event["event_datetime_str"] = body["new_event_datetime"]
        _expire_active_holds(event_id, to_status="EXPIRED")
    elif target == "CANCELED":
        _cancel_cascade(event_id)
    elif target == "COMPLETED":
        _create_settlement(event_id)

    event["status"] = target
    touch(event)
    return respond(ser_event(event), "object", 200)


def _expire_active_holds(event_id, to_status):
    for h in db["holds"].values():
        if h["event_id"] == event_id and h["status"] == "ACTIVE":
            h["status"] = to_status
            touch(h)
            for sid in h["seat_ids"]:
                seat = db["seats"].get(sid)
                if seat and seat["status"] == "HELD":
                    seat["status"] = "AVAILABLE"
                    touch(seat)


def _create_settlement(event_id):
    s = base_record()
    s.update({
        "_type": "settlement",
        "event_id": event_id,
        "status": "PENDING",
        "gross_face_cents": 0,
        "net_to_promoter_cents": 0,
        "service_fees_cents": 0,
        "refunds_cents": 0,
    })
    db["settlements"][s["id"]] = s


def _cancel_cascade(event_id):
    # Paid/partially-refunded orders -> REFUNDED with an auto full EVENT_CANCELED
    # refund (ORIGINAL); their remaining VALID tickets -> VOID, seats -> AVAILABLE.
    for order in event_orders(event_id):
        if order["status"] in ("PAID", "PARTIALLY_REFUNDED"):
            valid = [t for t in order_tickets(order["id"]) if t["status"] == "VALID"]
            amount = sum(t["face_value_cents"] for t in valid)
            r = base_record()
            r.update({
                "_type": "refund",
                "order_id": order["id"],
                "reason": "EVENT_CANCELED",
                "refund_destination": "ORIGINAL",
                "ticket_ids": [t["id"] for t in valid],
                "amount_cents": amount,
                "status": "COMPLETED",
            })
            db["refunds"][r["id"]] = r
            for t in valid:
                t["status"] = "VOID"
                touch(t)
                seat = db["seats"].get(t["seat_id"])
                if seat:
                    seat["status"] = "AVAILABLE"
                    touch(seat)
            order["status"] = "REFUNDED"
            touch(order)
        elif order["status"] == "PENDING":
            order["status"] = "CANCELED"
            touch(order)
            hold = db["holds"].get(order["hold_id"])
            if hold and hold["status"] == "ACTIVE":
                hold["status"] = "RELEASED"
                touch(hold)
                for sid in hold["seat_ids"]:
                    seat = db["seats"].get(sid)
                    if seat and seat["status"] == "HELD":
                        seat["status"] = "AVAILABLE"
                        touch(seat)
    # Any still-ACTIVE hold -> RELEASED, its held seats -> AVAILABLE.
    _expire_active_holds(event_id, to_status="RELEASED")


@app.route("/events/<event_id>/price-levels", methods=["POST"])
def create_price_level(event_id):
    guard({"Promoter", "BoxOffice"})
    body = body_json()
    get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    name = require_str(body, "name")
    base = require_int(body, "base_face_value_cents")
    if base <= 0:
        raise err("ERR_VALIDATION", "base_face_value_cents must be > 0")
    fee_pct = body.get("service_fee_pct")
    if not isinstance(fee_pct, (int, float)) or isinstance(fee_pct, bool):
        raise err("ERR_VALIDATION", "service_fee_pct is required and must be a number")
    is_platinum = opt_bool(body, "is_platinum", False)
    fee_flat = opt_int(body, "service_fee_flat_cents", 0)
    dynamic = opt_bool(body, "dynamic_pricing_enabled", True)

    p = base_record()
    p.update({
        "_type": "price_level",
        "event_id": event_id,
        "name": name,
        "base_face_value_cents": base,
        "is_platinum": is_platinum,
        "service_fee_pct": fee_pct,
        "service_fee_flat_cents": fee_flat,
        "dynamic_pricing_enabled": dynamic,
    })
    db["price_levels"][p["id"]] = p
    return respond(ser_price_level(p), "object", 201)


@app.route("/events/<event_id>/price-levels", methods=["GET"])
def list_price_levels(event_id):
    guard({"Buyer", "BoxOffice", "Promoter"})
    get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    items = [p for p in db["price_levels"].values() if p["event_id"] == event_id]
    return list_response(items, ser_price_level)


@app.route("/events/<event_id>/seats", methods=["POST"])
def create_seat(event_id):
    guard({"BoxOffice"})
    body = body_json()
    get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    price_level_id = require_str(body, "price_level_id")
    section = require_str(body, "section")
    row = require_str(body, "row")
    seat_number = require_str(body, "seat_number")

    pl = db["price_levels"].get(price_level_id)
    if pl is None or pl["event_id"] != event_id:
        raise err("ERR_PRICE_LEVEL_NOT_FOUND")

    for s in db["seats"].values():
        if (s["event_id"] == event_id and s["section"] == section
                and s["row"] == row and s["seat_number"] == seat_number):
            raise err("ERR_DUPLICATE_SEAT")

    s = base_record()
    s.update({
        "_type": "seat",
        "event_id": event_id,
        "price_level_id": price_level_id,
        "section": section,
        "row": row,
        "seat_number": seat_number,
        "status": "AVAILABLE",
    })
    db["seats"][s["id"]] = s
    return respond(ser_seat(s), "object", 201)


@app.route("/events/<event_id>/queue-tokens", methods=["POST"])
def join_queue(event_id):
    uid, role = guard({"Buyer"})
    body = body_json()
    buyer_id = require_str(body, "buyer_id")
    if buyer_id != uid:
        raise err("ERR_UNAUTHORIZED", "buyer_id must equal the acting buyer")
    get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    get_or_404("buyers", buyer_id, "ERR_BUYER_NOT_FOUND")

    waiting = [
        t for t in db["queue_tokens"].values()
        if t["event_id"] == event_id and t["status"] == "WAITING"
    ]
    position = len(waiting) + 1
    t = base_record()
    t.update({
        "_type": "queue_token",
        "event_id": event_id,
        "buyer_id": buyer_id,
        "position": position,
        "status": "WAITING",
        "admitted_at": None,
        "purchase_deadline": None,
    })
    db["queue_tokens"][t["id"]] = t
    return respond(ser_queue_token(t), "object", 201)


@app.route("/events/<event_id>/queue-tokens", methods=["GET"])
def list_event_tokens(event_id):
    guard({"Buyer", "BoxOffice"})
    get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    items = [t for t in db["queue_tokens"].values() if t["event_id"] == event_id]
    return list_response(items, ser_queue_token)


@app.route("/events/<event_id>/holds", methods=["POST"])
def create_hold(event_id):
    uid, role = guard({"Buyer"})
    body = body_json()

    # ownership (priority 2): body buyer_id must equal acting buyer
    buyer_id = body.get("buyer_id")
    if not isinstance(buyer_id, str) or buyer_id == "":
        raise err("ERR_VALIDATION", "buyer_id is required")
    if buyer_id != uid:
        raise err("ERR_UNAUTHORIZED", "buyer_id must equal the acting buyer")

    seat_ids = body.get("seat_ids")
    if not isinstance(seat_ids, list):
        raise err("ERR_VALIDATION", "seat_ids must be an array")
    expected_version = require_int(body, "expected_event_version")
    presale_code = body.get("presale_code", None)
    if presale_code is not None and not isinstance(presale_code, str):
        raise err("ERR_VALIDATION", "presale_code must be a string")

    # existence (priority 3): event, seats, buyer
    event = get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    seats = []
    for sid in seat_ids:
        seat = db["seats"].get(sid)
        if seat is None or seat["event_id"] != event_id:
            raise err("ERR_SEAT_NOT_FOUND")
        seats.append(seat)
    get_or_404("buyers", buyer_id, "ERR_BUYER_NOT_FOUND")

    # OCC (priority 4)
    if expected_version != event["version"]:
        raise err("ERR_STALE_VERSION")

    # purchasable state (priority 6)
    if event["status"] not in ("ONSALE", "PRESALE"):
        raise err("ERR_EVENT_NOT_ON_SALE")

    # business constraints (priority 8): empty selection, presale
    if len(seat_ids) == 0:
        raise err("ERR_EMPTY_SEAT_SELECTION")
    if event["status"] == "PRESALE":
        if presale_code is None or presale_code != event["presale_code"]:
            raise err("ERR_INVALID_PRESALE_CODE")
        presale_uses = sum(
            1 for h in db["holds"].values()
            if h["event_id"] == event_id
            and h["presale_code"] == event["presale_code"]
            and h["status"] in ("ACTIVE", "CONVERTED")
        )
        if presale_uses >= event["presale_max_uses"]:
            raise err("ERR_INVALID_PRESALE_CODE")

    # admission window (priority 9) for ONSALE
    if event["status"] == "ONSALE":
        admitted = [
            t for t in db["queue_tokens"].values()
            if t["event_id"] == event_id and t["buyer_id"] == buyer_id and t["status"] == "ADMITTED"
        ]
        if not admitted:
            raise err("ERR_NOT_ADMITTED")
        in_window = [t for t in admitted if t["purchase_deadline"] is not None and now() <= t["purchase_deadline"]]
        if not in_window:
            raise err("ERR_ADMISSION_WINDOW_EXPIRED")

    # seat availability (priority 10)
    for seat in seats:
        if seat["status"] != "AVAILABLE":
            raise err("ERR_SEAT_UNAVAILABLE")

    # fiscal cap (priority 11)
    if len(seat_ids) > MAX_SEATS_PER_HOLD:
        raise err("ERR_CAPACITY_EXCEEDED")

    face_subtotal = sum(current_face_value(seat) for seat in seats)
    stored_code = presale_code if event["status"] == "PRESALE" else None
    h = base_record()
    h.update({
        "_type": "hold",
        "event_id": event_id,
        "buyer_id": buyer_id,
        "seat_ids": list(seat_ids),
        "presale_code": stored_code,
        "status": "ACTIVE",
        "face_subtotal_cents": face_subtotal,
        "expires_at": add_minutes(now(), event["hold_ttl_minutes"]),
    })
    db["holds"][h["id"]] = h
    for seat in seats:
        seat["status"] = "HELD"
        touch(seat)
    touch(event)
    return respond(ser_hold(h), "object", 201)


@app.route("/events/<event_id>/sweep-holds", methods=["POST"])
def sweep_holds(event_id):
    guard({"BoxOffice"})
    event = get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    for h in db["holds"].values():
        if h["event_id"] == event_id and h["status"] == "ACTIVE" and now() >= h["expires_at"]:
            h["status"] = "EXPIRED"
            touch(h)
            for sid in h["seat_ids"]:
                seat = db["seats"].get(sid)
                if seat and seat["status"] == "HELD":
                    seat["status"] = "AVAILABLE"
                    touch(seat)
    return respond(ser_event(event), "object", 200)


@app.route("/events/<event_id>/settlement/finalize", methods=["POST"])
def finalize_settlement(event_id):
    guard({"BoxOffice", "Promoter"})
    event = get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    if event["status"] != "COMPLETED":
        raise err("ERR_SETTLEMENT_NOT_READY")
    settlement = None
    for s in db["settlements"].values():
        if s["event_id"] == event_id:
            settlement = s
            break
    if settlement is None:
        raise err("ERR_SETTLEMENT_NOT_READY")
    if settlement["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "settlement already finalized")
    figures = compute_settlement_figures(event_id)
    settlement.update(figures)
    settlement["status"] = "FINALIZED"
    touch(settlement)
    return respond(ser_settlement(settlement), "object", 200)


@app.route("/events/<event_id>/settlement", methods=["GET"])
def get_settlement(event_id):
    guard({"BoxOffice", "Promoter"})
    get_or_404("events", event_id, "ERR_EVENT_NOT_FOUND")
    items = [s for s in db["settlements"].values() if s["event_id"] == event_id]
    return list_response(items, ser_settlement)


# ---------------------------------------------------------------------------
# Seats
# ---------------------------------------------------------------------------
@app.route("/seats/<seat_id>", methods=["GET"])
def get_seat(seat_id):
    guard({"Buyer", "BoxOffice", "Promoter"})
    s = get_or_404("seats", seat_id, "ERR_SEAT_NOT_FOUND")
    return respond(ser_seat(s), "object", 200)


@app.route("/seats", methods=["GET"])
def list_seats():
    guard({"Buyer", "BoxOffice", "Promoter"})
    event_id = request.args.get("event_id")
    price_level_id = request.args.get("price_level_id")
    status = request.args.get("status")
    items = list(db["seats"].values())
    if event_id is not None:
        items = [s for s in items if s["event_id"] == event_id]
    if price_level_id is not None:
        items = [s for s in items if s["price_level_id"] == price_level_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_seat)


# ---------------------------------------------------------------------------
# Queue tokens
# ---------------------------------------------------------------------------
@app.route("/queue-tokens/<token_id>/admit", methods=["POST"])
def admit_token(token_id):
    guard({"BoxOffice"})
    token = get_or_404("queue_tokens", token_id, "ERR_QUEUE_TOKEN_NOT_FOUND")
    if token["status"] != "WAITING":
        raise err("ERR_INVALID_STATE", "token is not WAITING")
    event = db["events"].get(token["event_id"])
    if event is None or event["status"] != "ONSALE":
        raise err("ERR_INVALID_STATE", "event is not ONSALE")
    # already-admitted guard
    for t in db["queue_tokens"].values():
        if (t["event_id"] == token["event_id"] and t["buyer_id"] == token["buyer_id"]
                and t["status"] == "ADMITTED" and t["purchase_deadline"] is not None
                and t["purchase_deadline"] >= now()):
            raise err("ERR_ALREADY_ADMITTED")
    token["status"] = "ADMITTED"
    token["admitted_at"] = now()
    token["purchase_deadline"] = add_minutes(now(), event["purchase_window_minutes"])
    touch(token)
    return respond(ser_queue_token(token), "object", 200)


# ---------------------------------------------------------------------------
# Holds
# ---------------------------------------------------------------------------
@app.route("/holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    guard({"Buyer", "BoxOffice"})
    h = get_or_404("holds", hold_id, "ERR_HOLD_NOT_FOUND")
    return respond(ser_hold(h), "object", 200)


@app.route("/holds", methods=["GET"])
def list_holds():
    guard({"Buyer", "BoxOffice"})
    event_id = request.args.get("event_id")
    buyer_id = request.args.get("buyer_id")
    items = list(db["holds"].values())
    if event_id is not None:
        items = [h for h in items if h["event_id"] == event_id]
    if buyer_id is not None:
        items = [h for h in items if h["buyer_id"] == buyer_id]
    return list_response(items, ser_hold)


@app.route("/holds/<hold_id>/release", methods=["POST"])
def release_hold(hold_id):
    uid, role = guard({"Buyer", "BoxOffice"})
    h = get_or_404("holds", hold_id, "ERR_HOLD_NOT_FOUND")
    if role == "Buyer" and h["buyer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "hold not owned by acting buyer")
    if h["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "hold is not ACTIVE")
    h["status"] = "RELEASED"
    touch(h)
    for sid in h["seat_ids"]:
        seat = db["seats"].get(sid)
        if seat and seat["status"] == "HELD":
            seat["status"] = "AVAILABLE"
            touch(seat)
    return respond(ser_hold(h), "object", 200)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = guard({"Buyer"})
    body = body_json()
    hold_id = require_str(body, "hold_id")
    delivery_method = body.get("delivery_method")
    if delivery_method not in DELIVERY_METHODS:
        raise err("ERR_VALIDATION", "delivery_method must be one of MOBILE|PRINT|WILL_CALL")

    hold = get_or_404("holds", hold_id, "ERR_HOLD_NOT_FOUND")
    if hold["buyer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "hold not owned by acting buyer")
    if hold["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "hold is not ACTIVE")
    event = db["events"].get(hold["event_id"])
    if event is None or event["status"] not in ("ONSALE", "PRESALE"):
        raise err("ERR_EVENT_NOT_ON_SALE")
    if now() >= hold["expires_at"]:
        raise err("ERR_HOLD_EXPIRED")

    # Lock per-seat face at order creation against the current tier.
    locked_faces = {}
    face_total = 0
    service_fee = 0
    for sid in hold["seat_ids"]:
        seat = db["seats"][sid]
        face = current_face_value(seat)
        locked_faces[sid] = face
        face_total += face
        pl = db["price_levels"][seat["price_level_id"]]
        per_seat = round_half_up(Decimal(face) * Decimal(str(pl["service_fee_pct"]))) + pl["service_fee_flat_cents"]
        service_fee += per_seat
    order_total = face_total + service_fee

    o = base_record()
    o.update({
        "_type": "order",
        "event_id": hold["event_id"],
        "buyer_id": hold["buyer_id"],
        "hold_id": hold_id,
        "delivery_method": delivery_method,
        "status": "PENDING",
        "face_total_cents": face_total,
        "service_fee_cents": service_fee,
        "order_total_cents": order_total,
        "paid_amount_cents": 0,
        "_locked_faces": locked_faces,
    })
    db["orders"][o["id"]] = o

    # Order placed within window consumes the buyer's admitted token for the event.
    for t in db["queue_tokens"].values():
        if (t["event_id"] == event["id"] and t["buyer_id"] == uid and t["status"] == "ADMITTED"):
            t["status"] = "EXPIRED"
            touch(t)
            break

    return respond(ser_order(o), "object", 201)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    guard({"Buyer", "BoxOffice"})
    o = get_or_404("orders", order_id, "ERR_ORDER_NOT_FOUND")
    return respond(ser_order(o), "object", 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    guard({"Buyer", "BoxOffice"})
    event_id = request.args.get("event_id")
    buyer_id = request.args.get("buyer_id")
    hold_id = request.args.get("hold_id")
    items = list(db["orders"].values())
    if event_id is not None:
        items = [o for o in items if o["event_id"] == event_id]
    if buyer_id is not None:
        items = [o for o in items if o["buyer_id"] == buyer_id]
    if hold_id is not None:
        items = [o for o in items if o["hold_id"] == hold_id]
    return list_response(items, ser_order)


@app.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    uid, role = guard({"Buyer"})
    order = get_or_404("orders", order_id, "ERR_ORDER_NOT_FOUND")
    if order["buyer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "order not owned by acting buyer")
    if order["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "order is not PENDING")
    event = db["events"].get(order["event_id"])
    if event is None or event["status"] not in ("ONSALE", "PRESALE"):
        raise err("ERR_EVENT_NOT_ON_SALE")
    hold = db["holds"].get(order["hold_id"])
    if hold is None or now() >= hold["expires_at"]:
        raise err("ERR_HOLD_EXPIRED")
    if hold["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "hold is not ACTIVE")

    order["status"] = "PAID"
    order["paid_amount_cents"] = order["order_total_cents"]

    hold["status"] = "CONVERTED"
    touch(hold)

    for sid in hold["seat_ids"]:
        seat = db["seats"][sid]
        seat["status"] = "SOLD"
        touch(seat)
        face = order["_locked_faces"].get(sid, current_face_value(seat))
        tk = base_record()
        tk.update({
            "_type": "ticket",
            "order_id": order["id"],
            "seat_id": sid,
            "holder_buyer_id": order["buyer_id"],
            "face_value_cents": face,
            "delivery_method": order["delivery_method"],
            "status": "VALID",
            "delivery_status": "DELIVERED" if order["delivery_method"] == "MOBILE" else "PENDING",
            "scan_status": "UNSCANNED",
        })
        db["tickets"][tk["id"]] = tk

    touch(order)
    return respond(ser_order(order), "object", 200)


@app.route("/orders/<order_id>/refund-requests", methods=["POST"])
def create_refund_request(order_id):
    uid, role = guard({"Buyer", "BoxOffice"})
    body = body_json()
    reason = body.get("reason")
    if reason not in REFUND_REASONS:
        raise err("ERR_VALIDATION", "reason must be one of CUSTOMER_REQUEST|POSTPONEMENT|EVENT_CANCELED")
    destination = body.get("refund_destination")
    if destination not in REFUND_DESTINATIONS:
        raise err("ERR_VALIDATION", "refund_destination must be ORIGINAL|CREDIT")
    expected_version = require_int(body, "expected_order_version")
    ticket_ids = body.get("ticket_ids", None)
    if ticket_ids is not None and not isinstance(ticket_ids, list):
        raise err("ERR_VALIDATION", "ticket_ids must be an array")

    order = get_or_404("orders", order_id, "ERR_ORDER_NOT_FOUND")

    # existence of ticket_ids members (must belong to this order)
    if ticket_ids is not None:
        for tid in ticket_ids:
            t = db["tickets"].get(tid)
            if t is None or t["order_id"] != order_id:
                raise err("ERR_TICKET_NOT_FOUND")

    if role == "Buyer" and order["buyer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "order not owned by acting buyer")

    if expected_version != order["version"]:
        raise err("ERR_STALE_VERSION")

    if order["status"] not in ("PAID", "PARTIALLY_REFUNDED"):
        raise err("ERR_INVALID_STATE", "order is not refundable")

    if ticket_ids is not None:
        included = [db["tickets"][tid] for tid in ticket_ids]
    else:
        included = [t for t in order_tickets(order_id) if t["status"] == "VALID"]

    amount = sum(t["face_value_cents"] for t in included)
    remaining = order["face_total_cents"] - order_refunded_amount(order_id)
    if amount > remaining:
        raise err("ERR_REFUND_EXCEEDS_BALANCE")

    r = base_record()
    r.update({
        "_type": "refund",
        "order_id": order_id,
        "reason": reason,
        "refund_destination": destination,
        "ticket_ids": [t["id"] for t in included],
        "amount_cents": amount,
        "status": "REQUESTED",
    })
    db["refunds"][r["id"]] = r
    touch(order)  # refund-create bumps order version (OCC parent)
    return respond(ser_refund(r), "object", 201)


@app.route("/orders/<order_id>/refund-requests", methods=["GET"])
def list_order_refunds(order_id):
    guard({"Buyer", "BoxOffice"})
    get_or_404("orders", order_id, "ERR_ORDER_NOT_FOUND")
    items = [r for r in db["refunds"].values() if r["order_id"] == order_id]
    return list_response(items, ser_refund)


# ---------------------------------------------------------------------------
# Refund requests
# ---------------------------------------------------------------------------
@app.route("/refund-requests/<refund_id>/approve", methods=["POST"])
def approve_refund(refund_id):
    guard({"BoxOffice"})
    r = get_or_404("refunds", refund_id, "ERR_REFUND_NOT_FOUND")
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "refund is not REQUESTED")
    order = db["orders"][r["order_id"]]
    included = [db["tickets"][tid] for tid in r["ticket_ids"] if tid in db["tickets"]]
    if any(t["status"] != "VALID" for t in included):
        raise err("ERR_INVALID_STATE", "included tickets must all be VALID")
    remaining = order["face_total_cents"] - order_refunded_amount(order["id"])
    if r["amount_cents"] > remaining:
        raise err("ERR_REFUND_EXCEEDS_BALANCE")

    r["status"] = "COMPLETED"
    touch(r)
    for t in included:
        t["status"] = "REFUNDED"
        touch(t)
        seat = db["seats"].get(t["seat_id"])
        if seat:
            seat["status"] = "AVAILABLE"
            touch(seat)

    refunded = order_refunded_amount(order["id"])
    order["status"] = "REFUNDED" if refunded >= order["face_total_cents"] else "PARTIALLY_REFUNDED"
    touch(order)

    if r["refund_destination"] == "CREDIT":
        buyer = db["buyers"].get(order["buyer_id"])
        if buyer:
            touch(buyer)

    return respond(ser_refund(r), "object", 200)


@app.route("/refund-requests/<refund_id>/reject", methods=["POST"])
def reject_refund(refund_id):
    guard({"BoxOffice"})
    r = get_or_404("refunds", refund_id, "ERR_REFUND_NOT_FOUND")
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "refund is not REQUESTED")
    r["status"] = "REJECTED"
    touch(r)
    return respond(ser_refund(r), "object", 200)


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
@app.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    guard({"Buyer", "BoxOffice", "GateScanner"})
    t = get_or_404("tickets", ticket_id, "ERR_TICKET_NOT_FOUND")
    return respond(ser_ticket(t), "object", 200)


@app.route("/tickets", methods=["GET"])
def list_tickets():
    guard({"Buyer", "BoxOffice", "GateScanner"})
    order_id = request.args.get("order_id")
    seat_id = request.args.get("seat_id")
    holder_buyer_id = request.args.get("holder_buyer_id")
    items = list(db["tickets"].values())
    if order_id is not None:
        items = [t for t in items if t["order_id"] == order_id]
    if seat_id is not None:
        items = [t for t in items if t["seat_id"] == seat_id]
    if holder_buyer_id is not None:
        items = [t for t in items if t["holder_buyer_id"] == holder_buyer_id]
    return list_response(items, ser_ticket)


@app.route("/tickets/<ticket_id>/transfers", methods=["GET"])
def list_ticket_transfers(ticket_id):
    guard({"Buyer", "BoxOffice"})
    get_or_404("tickets", ticket_id, "ERR_TICKET_NOT_FOUND")
    items = [t for t in db["transfers"].values() if t["ticket_id"] == ticket_id]
    return list_response(items, ser_transfer)


@app.route("/tickets/<ticket_id>/deliver", methods=["POST"])
def deliver_ticket(ticket_id):
    guard({"BoxOffice"})
    t = get_or_404("tickets", ticket_id, "ERR_TICKET_NOT_FOUND")
    if t["status"] != "VALID" or t["delivery_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "ticket is not deliverable")
    t["delivery_status"] = "DELIVERED"
    touch(t)
    return respond(ser_ticket(t), "object", 200)


@app.route("/tickets/<ticket_id>/scan", methods=["POST"])
def scan_ticket(ticket_id):
    guard({"GateScanner"})
    t = get_or_404("tickets", ticket_id, "ERR_TICKET_NOT_FOUND")
    if t["status"] != "VALID":
        raise err("ERR_INVALID_STATE", "ticket is not VALID")
    if t["delivery_status"] != "DELIVERED":
        raise err("ERR_TICKET_NOT_DELIVERED")
    if t["scan_status"] == "SCANNED":
        raise err("ERR_TICKET_ALREADY_SCANNED")
    order = db["orders"].get(t["order_id"])
    event = db["events"].get(order["event_id"]) if order else None
    if event is None or event["status"] != "ONSALE":
        raise err("ERR_INVALID_STATE", "event is not ONSALE")
    t["scan_status"] = "SCANNED"
    touch(t)
    return respond(ser_ticket(t), "object", 200)


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------
@app.route("/transfers", methods=["POST"])
def create_transfer():
    uid, role = guard({"Buyer"})
    body = body_json()
    ticket_id = require_str(body, "ticket_id")
    to_buyer_id = require_str(body, "to_buyer_id")
    kind = body.get("kind")
    if kind not in TRANSFER_KINDS:
        raise err("ERR_VALIDATION", "kind must be GIFT|RESALE")
    list_price = body.get("list_price_cents", None)
    if kind == "RESALE":
        if isinstance(list_price, bool) or not isinstance(list_price, int) or list_price <= 0:
            raise err("ERR_VALIDATION", "RESALE requires positive list_price_cents")
    else:  # GIFT
        if list_price is not None:
            raise err("ERR_VALIDATION", "GIFT must not carry list_price_cents")

    ticket = get_or_404("tickets", ticket_id, "ERR_TICKET_NOT_FOUND")
    get_or_404("buyers", to_buyer_id, "ERR_BUYER_NOT_FOUND")

    if ticket["holder_buyer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "ticket not held by acting buyer")

    if ticket["status"] != "VALID":
        raise err("ERR_TICKET_NOT_TRANSFERABLE")
    if ticket["scan_status"] == "SCANNED":
        raise err("ERR_TICKET_ALREADY_SCANNED")

    tr = base_record()
    tr.update({
        "_type": "transfer",
        "ticket_id": ticket_id,
        "from_buyer_id": uid,
        "to_buyer_id": to_buyer_id,
        "kind": kind,
        "list_price_cents": list_price if kind == "RESALE" else None,
        "status": "INITIATED",
    })
    db["transfers"][tr["id"]] = tr
    return respond(ser_transfer(tr), "object", 201)


@app.route("/transfers/<transfer_id>/accept", methods=["POST"])
def accept_transfer(transfer_id):
    uid, role = guard({"Buyer"})
    tr = get_or_404("transfers", transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if tr["to_buyer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "only the recipient may accept")
    if tr["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "transfer is not INITIATED")
    ticket = db["tickets"][tr["ticket_id"]]
    if ticket["status"] != "VALID":
        raise err("ERR_TICKET_NOT_TRANSFERABLE")
    if ticket["scan_status"] == "SCANNED":
        raise err("ERR_TICKET_ALREADY_SCANNED")
    order = db["orders"].get(ticket["order_id"])
    event = db["events"].get(order["event_id"]) if order else None
    if event is not None and event["status"] in ("CANCELED", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "event is not in a transferable state")

    tr["status"] = "ACCEPTED"
    touch(tr)
    ticket["holder_buyer_id"] = tr["to_buyer_id"]
    touch(ticket)
    return respond(ser_transfer(tr), "object", 200)


@app.route("/transfers/<transfer_id>/decline", methods=["POST"])
def decline_transfer(transfer_id):
    uid, role = guard({"Buyer"})
    tr = get_or_404("transfers", transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if tr["to_buyer_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "only the recipient may decline")
    if tr["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "transfer is not INITIATED")
    tr["status"] = "DECLINED"
    touch(tr)
    return respond(ser_transfer(tr), "object", 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
