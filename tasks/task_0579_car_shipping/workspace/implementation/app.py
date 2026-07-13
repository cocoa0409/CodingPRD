import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Error catalogue
# =============================================================================
ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_ORDER_OWNER": 403,
    "ERR_NOT_OFFER_OWNER": 403,
    "ERR_NOT_ASSIGNED_CARRIER": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_NO_VEHICLES": 409,
    "ERR_QUOTE_NOT_OFFERED": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_DEPOSIT_NOT_PAID": 402,
    "ERR_PAY_EXCEEDS_TOTAL": 402,
    "ERR_OVERPAYMENT": 402,
    "ERR_OFFER_NOT_ACTIVE": 409,
    "ERR_LISTING_NOT_OPEN": 409,
    "ERR_CARRIER_SUSPENDED": 409,
    "ERR_EQUIPMENT_MISMATCH": 409,
    "ERR_INSURANCE_EXPIRED": 409,
    "ERR_INSURANCE_INADEQUATE": 409,
    "ERR_PICKUP_ETA_OUT_OF_WINDOW": 422,
    "ERR_TERMINAL_SLOT_CONFLICT": 409,
    "ERR_CARRIER_SCHEDULE_CONFLICT": 409,
    "ERR_ASSIGNMENT_NOT_DISPATCHED": 409,
    "ERR_ALREADY_PICKED_UP": 409,
    "ERR_DUPLICATE_INSPECTION": 409,
    "ERR_BALANCE_OUTSTANDING": 409,
    "ERR_OPEN_CLAIM": 409,
    "ERR_CLAIM_NOT_ACTIONABLE": 409,
    "ERR_NO_DAMAGE_ON_RECORD": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_MC_NUMBER": 409,
    "ERR_DUPLICATE_EMAIL": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# =============================================================================
# Constants
# =============================================================================
BAND1_RATE, BAND2_RATE, BAND3_RATE = 95, 75, 60
BAND1_MAX, BAND2_MAX = 500, 1500
INOP_SURCHARGE_CENTS = 15000
MULTI_CAR_PCT_PER_EXTRA = Decimal("0.05")
MULTI_CAR_MAX_PCT = Decimal("0.15")
ENCLOSED_PCT = Decimal("0.40")
EXPEDITE_PCT = Decimal("0.25")
QUOTE_TTL_HOURS = 72
DEPOSIT_PCT = Decimal("0.20")
DEPOSIT_FLOOR_CENTS = 10000
DEPOSIT_CAP_CENTS = 40000

ROLES = {"Shipper", "Broker", "Carrier", "Admin"}

# =============================================================================
# In-memory store
# =============================================================================
DB = {
    "shippers": {},
    "terminals": {},
    "carriers": {},
    "orders": {},
    "vehicles": {},
    "quotes": {},
    "listings": {},
    "offers": {},
    "assignments": {},
    "inspections": {},
    "ledger": {},
    "claims": {},
}

_seq_counter = [0]
CLOCK = [datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def now():
    return CLOCK[0]


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# =============================================================================
# Time helpers
# =============================================================================
def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


# =============================================================================
# Money helpers
# =============================================================================
def round_half_up(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


# =============================================================================
# Envelope helpers
# =============================================================================
def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": format_dt(now())}


def respond_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_array(items, limit, offset, total_count):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# =============================================================================
# Auth helpers
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_MISSING_AUTH", "Missing authentication headers")
    if role not in ROLES:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Unknown role")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted")


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return body


# =============================================================================
# Common field helpers
# =============================================================================
def add_common(rec, versioned=True):
    ts = now()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["_seq"] = next_seq()
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1


# =============================================================================
# Serialization
# =============================================================================
FIELD_SPECS = {
    "shipper": ["id", "email", "full_name", "created_at", "updated_at", "version"],
    "terminal": ["id", "name", "dock_zip", "dock_count", "buffer_minutes",
                 "created_at", "updated_at", "version"],
    "carrier": ["id", "legal_name", "mc_number", "cargo_insurance_limit_cents",
                "insurance_expiry_date", "equipment_type", "rating",
                "aggregate_exposure_cents", "status",
                "created_at", "updated_at", "version"],
    "order": ["id", "shipper_id", "origin_zip", "dest_zip", "route_miles",
              "transport_type", "delivery_mode", "service_level",
              "pickup_window_start", "pickup_window_end", "quoted_total_cents",
              "settled_total_cents", "deposit_cents", "cod_balance_cents",
              "terminal_id", "terminal_slot_start", "terminal_slot_end",
              "amount_paid_cents", "outstanding_balance_cents",
              "assigned_carrier_id", "status", "has_open_claim",
              "created_at", "updated_at", "version"],
    "vehicle": ["id", "order_id", "make", "model", "year", "is_inoperable",
                "declared_value_cents", "created_at", "updated_at", "version"],
    "quote": ["id", "order_id", "base_cents", "transport_surcharge_cents",
              "inoperable_surcharge_cents", "multi_car_discount_cents",
              "total_cents", "valid_until", "status",
              "created_at", "updated_at", "version"],
    "listing": ["id", "order_id", "offered_carrier_pay_cents", "expedited",
                "best_offer_id", "status", "created_at", "updated_at", "version"],
    "offer": ["id", "listing_id", "carrier_id", "ask_pay_cents", "pickup_eta",
              "round_no", "status", "created_at", "updated_at", "version"],
    "assignment": ["id", "order_id", "carrier_id", "offer_id", "carrier_pay_cents",
                   "status", "created_at", "updated_at", "version"],
    "inspection": ["id", "order_id", "phase", "damage_count",
                   "observed_inoperable_count", "odometer", "signed_by_carrier_id",
                   "created_at", "updated_at", "version"],
    "ledger": ["id", "order_id", "kind", "amount_cents", "status", "created_at"],
    "claim": ["id", "order_id", "carrier_id", "claimed_cents", "approved_cents",
              "status", "created_at", "updated_at", "version"],
}

DT_OBJECT_FIELDS = {"created_at", "updated_at", "valid_until"}


def serialize(kind, rec):
    out = {}
    for f in FIELD_SPECS[kind]:
        val = rec.get(f)
        if f in DT_OBJECT_FIELDS and isinstance(val, datetime):
            val = format_dt(val)
        out[f] = val
    return out


# =============================================================================
# Pagination + listing
# =============================================================================
def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            limit = 10
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(kind, records, predicate=None):
    limit, offset = parse_pagination()
    items = [r for r in records if predicate is None or predicate(r)]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return respond_array([serialize(kind, r) for r in page], limit, offset, total)


# =============================================================================
# Lookups
# =============================================================================
def lookup(coll, rid):
    rec = DB[coll].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return rec


# =============================================================================
# Validation helpers
# =============================================================================
def require_present(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing field: %s" % key)
    return body[key]


def require_str(body, key):
    v = require_present(body, key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "Invalid string: %s" % key)
    return v


def require_pos_int(body, key):
    v = require_present(body, key)
    if not is_int(v) or v <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field must be a positive integer: %s" % key)
    return v


def require_nonneg_int(body, key):
    v = require_present(body, key)
    if not is_int(v) or v < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field must be a non-negative integer: %s" % key)
    return v


def require_enum(body, key, members):
    v = require_present(body, key)
    if v not in members:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid enum for %s" % key)
    return v


# =============================================================================
# Calculations
# =============================================================================
def compute_quote_components(vehicles_list, route_miles, transport_type,
                             service_level, inoperable_count):
    # 1. Distance base (marginal bands, sum-then-round)
    m1 = min(route_miles, BAND1_MAX)
    m2 = max(0, min(route_miles, BAND2_MAX) - BAND1_MAX)
    m3 = max(0, route_miles - BAND2_MAX)
    base_cents = round_half_up(m1 * BAND1_RATE + m2 * BAND2_RATE + m3 * BAND3_RATE)

    # 2. Transport surcharge
    enclosed_add = round_half_up(Decimal(base_cents) * ENCLOSED_PCT) if transport_type == "ENCLOSED" else 0
    expedite_add = round_half_up(Decimal(base_cents) * EXPEDITE_PCT) if service_level == "EXPEDITED" else 0
    transport_surcharge_cents = enclosed_add + expedite_add

    # 3. Inoperable surcharge
    inoperable_surcharge_cents = INOP_SURCHARGE_CENTS * inoperable_count

    # 4. Multi-car discount
    n = len(vehicles_list)
    sum_bt = base_cents + transport_surcharge_cents
    if n >= 2:
        raw = round_half_up(Decimal(sum_bt) * MULTI_CAR_PCT_PER_EXTRA * (n - 1))
        cap = round_half_up(Decimal(sum_bt) * MULTI_CAR_MAX_PCT)
        multi_car_discount_cents = min(raw, cap)
    else:
        multi_car_discount_cents = 0

    total_cents = base_cents + transport_surcharge_cents + inoperable_surcharge_cents - multi_car_discount_cents
    return {
        "base_cents": base_cents,
        "transport_surcharge_cents": transport_surcharge_cents,
        "inoperable_surcharge_cents": inoperable_surcharge_cents,
        "multi_car_discount_cents": multi_car_discount_cents,
        "total_cents": total_cents,
    }


def compute_deposit_split(quoted_total):
    raw = round_half_up(Decimal(quoted_total) * DEPOSIT_PCT)
    deposit = min(max(raw, DEPOSIT_FLOOR_CENTS), DEPOSIT_CAP_CENTS)
    cod = quoted_total - deposit
    return deposit, cod


def order_vehicles(order_id):
    return [v for v in DB["vehicles"].values() if v["order_id"] == order_id]


def order_declared_value(order_id):
    return sum(v["declared_value_cents"] for v in order_vehicles(order_id))


def recompute_order_balances(order):
    posted = [l for l in DB["ledger"].values()
              if l["order_id"] == order["id"] and l["status"] == "POSTED"]
    amount_paid = sum(l["amount_cents"] for l in posted
                      if l["kind"] in ("DEPOSIT", "COD_PAYMENT"))
    order["amount_paid_cents"] = amount_paid
    if order["quoted_total_cents"] is not None:
        order["outstanding_balance_cents"] = order["quoted_total_cents"] - amount_paid
    else:
        order["outstanding_balance_cents"] = None


def recompute_has_open_claim(order):
    return any(c["order_id"] == order["id"] and c["status"] in ("SUBMITTED", "RETURNED_FOR_INFO", "APPROVED")
               for c in DB["claims"].values())


def update_has_open_claim(order):
    new_val = recompute_has_open_claim(order)
    if new_val != order["has_open_claim"]:
        order["has_open_claim"] = new_val
        touch(order)


def recompute_carrier_exposure(carrier):
    active_orders = {a["order_id"] for a in DB["assignments"].values()
                     if a["carrier_id"] == carrier["id"] and a["status"] == "DISPATCHED"}
    total = 0
    for oid in active_orders:
        total += order_declared_value(oid)
    if total != carrier["aggregate_exposure_cents"]:
        carrier["aggregate_exposure_cents"] = total
        touch(carrier)


def recompute_best_offer(listing):
    pending = [o for o in DB["offers"].values()
               if o["listing_id"] == listing["id"] and o["status"] == "PENDING"]
    if not pending:
        new_best = None
    else:
        pending.sort(key=lambda o: (o["ask_pay_cents"], o["_seq"]))
        new_best = pending[0]["id"]
    changed = new_best != listing["best_offer_id"]
    listing["best_offer_id"] = new_best
    return changed


# =============================================================================
# Interval helpers
# =============================================================================
def overlap_half_open(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


def intersect_closed(a1, a2, b1, b2):
    return a1 <= b2 and b1 <= a2


# =============================================================================
# Shipper endpoints
# =============================================================================
@app.route("/shippers", methods=["POST"])
def create_shipper():
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Admin"})
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    if any(s["email"] == email for s in DB["shippers"].values()):
        raise ApiError("ERR_DUPLICATE_EMAIL", "Email already registered")
    rec = {"email": email, "full_name": full_name}
    add_common(rec)
    DB["shippers"][rec["id"]] = rec
    return respond_object(serialize("shipper", rec), 201)


@app.route("/shippers/<sid>", methods=["GET"])
def get_shipper(sid):
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Admin"})
    rec = lookup("shippers", sid)
    return respond_object(serialize("shipper", rec), 200)


# =============================================================================
# Terminal endpoints
# =============================================================================
@app.route("/terminals", methods=["POST"])
def create_terminal():
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin"})
    body = get_body()
    name = require_str(body, "name")
    dock_zip = require_str(body, "dock_zip")
    dock_count = require_present(body, "dock_count")
    if not is_int(dock_count) or dock_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", "dock_count must be >= 1")
    buffer_minutes = body.get("buffer_minutes", 60)
    if buffer_minutes is None:
        buffer_minutes = 60
    if not is_int(buffer_minutes) or buffer_minutes < 0:
        raise ApiError("ERR_INVALID_REQUEST", "buffer_minutes must be a non-negative integer")
    rec = {"name": name, "dock_zip": dock_zip, "dock_count": dock_count,
           "buffer_minutes": buffer_minutes}
    add_common(rec)
    DB["terminals"][rec["id"]] = rec
    return respond_object(serialize("terminal", rec), 201)


@app.route("/terminals", methods=["GET"])
def list_terminals():
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin"})
    dock_zip = request.args.get("dock_zip")

    def pred(r):
        return dock_zip is None or r["dock_zip"] == dock_zip
    return list_response("terminal", DB["terminals"].values(), pred)


@app.route("/terminals/<tid>", methods=["GET"])
def get_terminal(tid):
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin"})
    rec = lookup("terminals", tid)
    return respond_object(serialize("terminal", rec), 200)


# =============================================================================
# Carrier endpoints
# =============================================================================
@app.route("/carriers", methods=["POST"])
def create_carrier():
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin"})
    body = get_body()
    legal_name = require_str(body, "legal_name")
    mc_number = require_str(body, "mc_number")
    limit = require_present(body, "cargo_insurance_limit_cents")
    if not is_int(limit) or limit < 0:
        raise ApiError("ERR_INVALID_REQUEST", "cargo_insurance_limit_cents must be a non-negative integer")
    insurance_expiry_raw = require_str(body, "insurance_expiry_date")
    parse_dt(insurance_expiry_raw)  # validate format
    equipment_type = require_enum(body, "equipment_type", {"OPEN", "ENCLOSED"})
    rating = body.get("rating", 3.0)
    if rating is None:
        rating = 3.0
    if not isinstance(rating, (int, float)) or isinstance(rating, bool):
        raise ApiError("ERR_INVALID_REQUEST", "rating must be a number")
    if rating < 0 or rating > 5:
        raise ApiError("ERR_INVALID_REQUEST", "rating must be between 0.0 and 5.0")
    if any(c["mc_number"] == mc_number for c in DB["carriers"].values()):
        raise ApiError("ERR_DUPLICATE_MC_NUMBER", "mc_number already registered")
    rec = {
        "legal_name": legal_name, "mc_number": mc_number,
        "cargo_insurance_limit_cents": limit,
        "insurance_expiry_date": insurance_expiry_raw,
        "equipment_type": equipment_type, "rating": rating,
        "aggregate_exposure_cents": 0, "status": "ACTIVE",
    }
    add_common(rec)
    DB["carriers"][rec["id"]] = rec
    return respond_object(serialize("carrier", rec), 201)


@app.route("/carriers", methods=["GET"])
def list_carriers():
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin"})
    equipment_type = request.args.get("equipment_type")
    status = request.args.get("status")

    def pred(r):
        if equipment_type is not None and r["equipment_type"] != equipment_type:
            return False
        if status is not None and r["status"] != status:
            return False
        return True
    return list_response("carrier", DB["carriers"].values(), pred)


@app.route("/carriers/<cid>", methods=["GET"])
def get_carrier(cid):
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Carrier"})
    rec = lookup("carriers", cid)
    return respond_object(serialize("carrier", rec), 200)


@app.route("/carriers/<cid>/suspend", methods=["POST"])
def suspend_carrier(cid):
    _uid, role = authenticate()
    authorize(role, {"Admin"})
    rec = lookup("carriers", cid)
    if rec["status"] != "SUSPENDED":
        rec["status"] = "SUSPENDED"
        touch(rec)
    return respond_object(serialize("carrier", rec), 200)


# =============================================================================
# ShipmentOrder endpoints
# =============================================================================
@app.route("/shipment-orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    authorize(role, {"Shipper"})
    body = get_body()
    origin_zip = require_str(body, "origin_zip")
    dest_zip = require_str(body, "dest_zip")
    route_miles = require_present(body, "route_miles")
    if not is_int(route_miles) or route_miles <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "route_miles must be > 0")
    transport_type = require_enum(body, "transport_type", {"OPEN", "ENCLOSED"})
    delivery_mode = body.get("delivery_mode", "DOOR_TO_DOOR")
    if delivery_mode is None:
        delivery_mode = "DOOR_TO_DOOR"
    if delivery_mode not in ("DOOR_TO_DOOR", "TERMINAL"):
        raise ApiError("ERR_INVALID_REQUEST", "invalid delivery_mode")
    service_level = body.get("service_level", "STANDARD")
    if service_level is None:
        service_level = "STANDARD"
    if service_level not in ("STANDARD", "EXPEDITED"):
        raise ApiError("ERR_INVALID_REQUEST", "invalid service_level")
    pws_raw = require_str(body, "pickup_window_start")
    pwe_raw = require_str(body, "pickup_window_end")
    pws = parse_dt(pws_raw)
    pwe = parse_dt(pwe_raw)
    if pwe <= pws:
        raise ApiError("ERR_INVALID_REQUEST", "pickup_window_end must be after start")

    terminal_id = None
    tss_raw = None
    tse_raw = None
    if delivery_mode == "TERMINAL":
        terminal_id = body.get("terminal_id")
        tss_raw = body.get("terminal_slot_start")
        tse_raw = body.get("terminal_slot_end")
        if not terminal_id or not tss_raw or not tse_raw:
            raise ApiError("ERR_INVALID_REQUEST", "terminal fields required for TERMINAL mode")
        tss = parse_dt(tss_raw)
        tse = parse_dt(tse_raw)
        if tse <= tss:
            raise ApiError("ERR_INVALID_REQUEST", "terminal_slot_end must be after start")
        terminal = DB["terminals"].get(terminal_id)
        if terminal is None:
            raise ApiError("ERR_NOT_FOUND", "terminal not found")
        # dock overlap check
        buf = timedelta(minutes=terminal["buffer_minutes"])
        conflicts = 0
        for o in DB["orders"].values():
            if o["terminal_id"] != terminal_id:
                continue
            if o["status"] == "CANCELLED":
                continue
            e_start = parse_dt(o["terminal_slot_start"]) - buf
            e_end = parse_dt(o["terminal_slot_end"]) + buf
            if intersect_closed(e_start, e_end, tss, tse):
                conflicts += 1
        if conflicts >= terminal["dock_count"]:
            raise ApiError("ERR_TERMINAL_SLOT_CONFLICT", "no free dock at terminal")

    rec = {
        "shipper_id": uid, "origin_zip": origin_zip, "dest_zip": dest_zip,
        "route_miles": route_miles, "transport_type": transport_type,
        "delivery_mode": delivery_mode, "service_level": service_level,
        "pickup_window_start": pws_raw, "pickup_window_end": pwe_raw,
        "quoted_total_cents": None, "settled_total_cents": None,
        "deposit_cents": None, "cod_balance_cents": None,
        "terminal_id": terminal_id, "terminal_slot_start": tss_raw,
        "terminal_slot_end": tse_raw, "amount_paid_cents": 0,
        "outstanding_balance_cents": None, "assigned_carrier_id": None,
        "status": "DRAFT", "has_open_claim": False,
        "_accepted_quote_id": None,
    }
    add_common(rec)
    DB["orders"][rec["id"]] = rec
    return respond_object(serialize("order", rec), 201)


@app.route("/shipment-orders", methods=["GET"])
def list_orders():
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin"})
    shipper_id = request.args.get("shipper_id")
    status = request.args.get("status")
    assigned_carrier_id = request.args.get("assigned_carrier_id")
    terminal_id = request.args.get("terminal_id")

    def pred(r):
        if shipper_id is not None and r["shipper_id"] != shipper_id:
            return False
        if status is not None and r["status"] != status:
            return False
        if assigned_carrier_id is not None and r["assigned_carrier_id"] != assigned_carrier_id:
            return False
        if terminal_id is not None and r["terminal_id"] != terminal_id:
            return False
        return True
    return list_response("order", DB["orders"].values(), pred)


@app.route("/shipment-orders/<oid>", methods=["GET"])
def get_order(oid):
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin", "Carrier"})
    rec = lookup("orders", oid)
    return respond_object(serialize("order", rec), 200)


@app.route("/shipment-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = authenticate()
    authorize(role, {"Shipper"})
    order = lookup("orders", oid)
    if order["shipper_id"] != uid:
        raise ApiError("ERR_NOT_ORDER_OWNER", "Not the order owner")
    if order["status"] not in ("DRAFT", "QUOTED", "LISTED"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be cancelled at this stage")
    order["status"] = "CANCELLED"
    # refund deposit if a POSTED DEPOSIT exists
    has_deposit = any(l["order_id"] == order["id"] and l["kind"] == "DEPOSIT" and l["status"] == "POSTED"
                      for l in DB["ledger"].values())
    if has_deposit and order["deposit_cents"]:
        refund = {"order_id": order["id"], "kind": "REFUND",
                  "amount_cents": -order["deposit_cents"], "status": "POSTED"}
        add_common(refund, versioned=False)
        DB["ledger"][refund["id"]] = refund
        recompute_order_balances(order)
    # withdraw open listings + decline their offers
    for listing in DB["listings"].values():
        if listing["order_id"] == order["id"] and listing["status"] == "OPEN":
            listing["status"] = "WITHDRAWN"
            for off in DB["offers"].values():
                if off["listing_id"] == listing["id"] and off["status"] in ("PENDING", "COUNTERED"):
                    off["status"] = "DECLINED"
                    touch(off)
            recompute_best_offer(listing)
            touch(listing)
    touch(order)
    return respond_object(serialize("order", order), 200)


@app.route("/shipment-orders/<oid>/close", methods=["POST"])
def close_order(oid):
    _uid, role = authenticate()
    authorize(role, {"Broker"})
    order = lookup("orders", oid)
    if order["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "Order not in DELIVERED state")
    if order["outstanding_balance_cents"] != 0:
        raise ApiError("ERR_BALANCE_OUTSTANDING", "Outstanding balance must be 0")
    if order["has_open_claim"]:
        raise ApiError("ERR_OPEN_CLAIM", "Order has an open claim")
    order["status"] = "CLOSED"
    touch(order)
    return respond_object(serialize("order", order), 200)


# =============================================================================
# Vehicle endpoints
# =============================================================================
@app.route("/shipment-orders/<oid>/vehicles", methods=["POST"])
def create_vehicle(oid):
    uid, role = authenticate()
    authorize(role, {"Shipper"})
    order = lookup("orders", oid)
    if order["shipper_id"] != uid:
        raise ApiError("ERR_NOT_ORDER_OWNER", "Not the order owner")
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Vehicles can only be attached to a DRAFT order")
    body = get_body()
    make = require_str(body, "make")
    model = require_str(body, "model")
    year = require_present(body, "year")
    if not is_int(year):
        raise ApiError("ERR_INVALID_REQUEST", "year must be an integer")
    declared_value = require_present(body, "declared_value_cents")
    if not is_int(declared_value) or declared_value < 0:
        raise ApiError("ERR_INVALID_REQUEST", "declared_value_cents must be a non-negative integer")
    is_inoperable = body.get("is_inoperable", False)
    if is_inoperable is None:
        is_inoperable = False
    if not isinstance(is_inoperable, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_inoperable must be boolean")
    rec = {"order_id": order["id"], "make": make, "model": model, "year": year,
           "is_inoperable": is_inoperable, "declared_value_cents": declared_value}
    add_common(rec)
    DB["vehicles"][rec["id"]] = rec
    touch(order)
    return respond_object(serialize("vehicle", rec), 201)


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin", "Carrier"})
    order_id = request.args.get("order_id")

    def pred(r):
        return order_id is None or r["order_id"] == order_id
    return list_response("vehicle", DB["vehicles"].values(), pred)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin", "Carrier"})
    rec = lookup("vehicles", vid)
    return respond_object(serialize("vehicle", rec), 200)


# =============================================================================
# Quote endpoints
# =============================================================================
@app.route("/shipment-orders/<oid>/quotes", methods=["POST"])
def create_quote(oid):
    uid, role = authenticate()
    authorize(role, {"Shipper", "Broker"})
    order = lookup("orders", oid)
    if role == "Shipper" and order["shipper_id"] != uid:
        raise ApiError("ERR_NOT_ORDER_OWNER", "Not the order owner")
    body = get_body()
    expected = require_present(body, "expected_order_version")
    if not is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_order_version must be an integer")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", "Order version has advanced")

    vehicles_list = order_vehicles(order["id"])
    inop_count = sum(1 for v in vehicles_list if v["is_inoperable"])
    comps = compute_quote_components(vehicles_list, order["route_miles"],
                                     order["transport_type"], order["service_level"],
                                     inop_count)
    created = now()
    valid_until = created + timedelta(hours=QUOTE_TTL_HOURS)
    # supersede prior OFFERED quotes on this order
    for q in DB["quotes"].values():
        if q["order_id"] == order["id"] and q["status"] == "OFFERED":
            q["status"] = "SUPERSEDED"
            touch(q)
    rec = {
        "order_id": order["id"],
        "base_cents": comps["base_cents"],
        "transport_surcharge_cents": comps["transport_surcharge_cents"],
        "inoperable_surcharge_cents": comps["inoperable_surcharge_cents"],
        "multi_car_discount_cents": comps["multi_car_discount_cents"],
        "total_cents": comps["total_cents"],
        "valid_until": valid_until, "status": "OFFERED",
    }
    add_common(rec)
    rec["created_at"] = created
    rec["updated_at"] = created
    DB["quotes"][rec["id"]] = rec
    touch(order)
    return respond_object(serialize("quote", rec), 201)


@app.route("/quotes", methods=["GET"])
def list_quotes():
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin"})
    order_id = request.args.get("order_id")
    status = request.args.get("status")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True
    return list_response("quote", DB["quotes"].values(), pred)


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin"})
    rec = lookup("quotes", qid)
    return respond_object(serialize("quote", rec), 200)


@app.route("/shipment-orders/<oid>/quotes/<qid>/accept", methods=["POST"])
def accept_quote(oid, qid):
    uid, role = authenticate()
    authorize(role, {"Shipper"})
    order = lookup("orders", oid)
    quote = DB["quotes"].get(qid)
    if quote is None or quote["order_id"] != order["id"]:
        raise ApiError("ERR_NOT_FOUND", "Quote not found")
    if order["shipper_id"] != uid:
        raise ApiError("ERR_NOT_ORDER_OWNER", "Not the order owner")
    if len(order_vehicles(order["id"])) < 1:
        raise ApiError("ERR_NO_VEHICLES", "Order has no vehicles")
    if quote["status"] != "OFFERED":
        raise ApiError("ERR_QUOTE_NOT_OFFERED", "Quote is not OFFERED")
    if now() > quote["valid_until"]:
        raise ApiError("ERR_QUOTE_EXPIRED", "Quote has expired")

    order["quoted_total_cents"] = quote["total_cents"]
    deposit, cod = compute_deposit_split(quote["total_cents"])
    order["deposit_cents"] = deposit
    order["cod_balance_cents"] = cod
    order["_accepted_quote_id"] = quote["id"]
    recompute_order_balances(order)
    quote["status"] = "ACCEPTED"
    touch(quote)
    for q in DB["quotes"].values():
        if q["order_id"] == order["id"] and q["id"] != quote["id"] and q["status"] == "OFFERED":
            q["status"] = "SUPERSEDED"
            touch(q)
    order["status"] = "QUOTED"
    touch(order)
    return respond_object(serialize("order", order), 200)


# =============================================================================
# LedgerEntry endpoints
# =============================================================================
@app.route("/shipment-orders/<oid>/ledger-entries", methods=["POST"])
def create_ledger(oid):
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin"})
    order = lookup("orders", oid)
    body = get_body()
    kind = require_enum(body, "kind", {"DEPOSIT", "COD_PAYMENT", "REFUND", "CLAIM_PAYOUT"})
    amount = require_present(body, "amount_cents")
    if not is_int(amount):
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be an integer")
    if kind in ("DEPOSIT", "COD_PAYMENT"):
        if amount <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "inflow amount must be positive")
    else:
        if amount >= 0:
            raise ApiError("ERR_INVALID_REQUEST", "outflow amount must be negative")
    if kind == "COD_PAYMENT":
        outstanding = order["outstanding_balance_cents"]
        if outstanding is not None and amount > outstanding:
            raise ApiError("ERR_OVERPAYMENT", "COD payment exceeds outstanding balance")

    before_paid = order["amount_paid_cents"]
    before_out = order["outstanding_balance_cents"]
    rec = {"order_id": order["id"], "kind": kind, "amount_cents": amount, "status": "POSTED"}
    add_common(rec, versioned=False)
    DB["ledger"][rec["id"]] = rec
    recompute_order_balances(order)
    if order["amount_paid_cents"] != before_paid or order["outstanding_balance_cents"] != before_out:
        touch(order)
    return respond_object(serialize("ledger", rec), 201)


@app.route("/ledger-entries", methods=["GET"])
def list_ledger():
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Shipper"})
    order_id = request.args.get("order_id")
    kind = request.args.get("kind")
    status = request.args.get("status")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if kind is not None and r["kind"] != kind:
            return False
        if status is not None and r["status"] != status:
            return False
        return True
    return list_response("ledger", DB["ledger"].values(), pred)


@app.route("/ledger-entries/<lid>", methods=["GET"])
def get_ledger(lid):
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Shipper"})
    rec = lookup("ledger", lid)
    return respond_object(serialize("ledger", rec), 200)


@app.route("/ledger-entries/<lid>/void", methods=["POST"])
def void_ledger(lid):
    _uid, role = authenticate()
    authorize(role, {"Admin"})
    rec = lookup("ledger", lid)
    order = DB["orders"].get(rec["order_id"])
    if rec["status"] != "VOIDED":
        rec["status"] = "VOIDED"
        if order is not None:
            before_paid = order["amount_paid_cents"]
            before_out = order["outstanding_balance_cents"]
            recompute_order_balances(order)
            if order["amount_paid_cents"] != before_paid or order["outstanding_balance_cents"] != before_out:
                touch(order)
    return respond_object(serialize("ledger", rec), 200)


# =============================================================================
# LoadListing endpoints
# =============================================================================
@app.route("/shipment-orders/<oid>/listings", methods=["POST"])
def create_listing(oid):
    _uid, role = authenticate()
    authorize(role, {"Broker"})
    order = lookup("orders", oid)
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Order must be QUOTED to list")
    body = get_body()
    pay = require_pos_int(body, "offered_carrier_pay_cents")
    # deposit paid precondition (PRD §3.4: deposit first, then pay)
    if order["amount_paid_cents"] < (order["deposit_cents"] or 0):
        raise ApiError("ERR_DEPOSIT_NOT_PAID", "Deposit must be paid before listing")
    if pay > order["quoted_total_cents"]:
        raise ApiError("ERR_PAY_EXCEEDS_TOTAL", "Offered pay exceeds order total")
    rec = {"order_id": order["id"], "offered_carrier_pay_cents": pay,
           "expedited": (order["service_level"] == "EXPEDITED"),
           "best_offer_id": None, "status": "OPEN"}
    add_common(rec)
    DB["listings"][rec["id"]] = rec
    order["status"] = "LISTED"
    touch(order)
    return respond_object(serialize("listing", rec), 201)


@app.route("/listings", methods=["GET"])
def list_listings():
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Carrier"})
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    expedited = request.args.get("expedited")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if status is not None and r["status"] != status:
            return False
        if expedited is not None:
            want = expedited.lower() == "true"
            if r["expedited"] != want:
                return False
        return True
    return list_response("listing", DB["listings"].values(), pred)


@app.route("/listings/<lid>", methods=["GET"])
def get_listing(lid):
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Carrier"})
    rec = lookup("listings", lid)
    return respond_object(serialize("listing", rec), 200)


# =============================================================================
# DispatchOffer endpoints
# =============================================================================
def _get_offer_on_listing(lid, offer_id):
    listing = lookup("listings", lid)
    offer = DB["offers"].get(offer_id)
    if offer is None or offer["listing_id"] != listing["id"]:
        raise ApiError("ERR_NOT_FOUND", "Offer not found")
    return listing, offer


@app.route("/listings/<lid>/offers", methods=["POST"])
def create_offer(lid):
    uid, role = authenticate()
    authorize(role, {"Carrier"})
    listing = lookup("listings", lid)
    if listing["status"] != "OPEN":
        raise ApiError("ERR_LISTING_NOT_OPEN", "Listing is not OPEN")
    body = get_body()
    ask = require_pos_int(body, "ask_pay_cents")
    pickup_eta_raw = require_str(body, "pickup_eta")
    eta = parse_dt(pickup_eta_raw)
    order = DB["orders"].get(listing["order_id"])
    pws = parse_dt(order["pickup_window_start"])
    pwe = parse_dt(order["pickup_window_end"])
    if eta < pws or eta > pwe:
        raise ApiError("ERR_PICKUP_ETA_OUT_OF_WINDOW", "pickup_eta outside pickup window")
    rec = {"listing_id": listing["id"], "carrier_id": uid, "ask_pay_cents": ask,
           "pickup_eta": pickup_eta_raw, "round_no": 1, "status": "PENDING"}
    add_common(rec)
    DB["offers"][rec["id"]] = rec
    if recompute_best_offer(listing):
        touch(listing)
    return respond_object(serialize("offer", rec), 201)


@app.route("/offers", methods=["GET"])
def list_offers():
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Carrier"})
    listing_id = request.args.get("listing_id")
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")

    def pred(r):
        if listing_id is not None and r["listing_id"] != listing_id:
            return False
        if carrier_id is not None and r["carrier_id"] != carrier_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True
    return list_response("offer", DB["offers"].values(), pred)


@app.route("/offers/<off_id>", methods=["GET"])
def get_offer(off_id):
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Carrier"})
    rec = lookup("offers", off_id)
    return respond_object(serialize("offer", rec), 200)


@app.route("/listings/<lid>/offers/<off_id>/counter", methods=["POST"])
def counter_offer(lid, off_id):
    _uid, role = authenticate()
    authorize(role, {"Broker"})
    listing, offer = _get_offer_on_listing(lid, off_id)
    if offer["status"] != "PENDING":
        raise ApiError("ERR_OFFER_NOT_ACTIVE", "Offer is not PENDING")
    if listing["status"] != "OPEN":
        raise ApiError("ERR_LISTING_NOT_OPEN", "Listing is not OPEN")
    body = get_body()
    require_pos_int(body, "counter_pay_cents")
    offer["round_no"] += 1
    offer["status"] = "COUNTERED"
    touch(offer)
    return respond_object(serialize("offer", offer), 200)


@app.route("/listings/<lid>/offers/<off_id>/reoffer", methods=["POST"])
def reoffer_offer(lid, off_id):
    uid, role = authenticate()
    authorize(role, {"Carrier"})
    listing, offer = _get_offer_on_listing(lid, off_id)
    if offer["carrier_id"] != uid:
        raise ApiError("ERR_NOT_OFFER_OWNER", "Not the offer owner")
    if offer["status"] != "COUNTERED":
        raise ApiError("ERR_OFFER_NOT_ACTIVE", "Offer is not COUNTERED")
    body = get_body()
    ask = require_pos_int(body, "ask_pay_cents")
    if "pickup_eta" in body and body["pickup_eta"] is not None:
        pickup_eta_raw = body["pickup_eta"]
        parse_dt(pickup_eta_raw)
        offer["pickup_eta"] = pickup_eta_raw
    offer["ask_pay_cents"] = ask
    offer["round_no"] += 1
    offer["status"] = "PENDING"
    touch(offer)
    if recompute_best_offer(listing):
        touch(listing)
    return respond_object(serialize("offer", offer), 200)


@app.route("/listings/<lid>/offers/<off_id>/withdraw", methods=["POST"])
def withdraw_offer(lid, off_id):
    uid, role = authenticate()
    authorize(role, {"Carrier"})
    listing, offer = _get_offer_on_listing(lid, off_id)
    if offer["carrier_id"] != uid:
        raise ApiError("ERR_NOT_OFFER_OWNER", "Not the offer owner")
    if offer["status"] not in ("PENDING", "COUNTERED"):
        raise ApiError("ERR_OFFER_NOT_ACTIVE", "Offer is not active")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    if recompute_best_offer(listing):
        touch(listing)
    return respond_object(serialize("offer", offer), 200)


@app.route("/listings/<lid>/offers/<off_id>/accept", methods=["POST"])
def accept_offer(lid, off_id):
    _uid, role = authenticate()
    authorize(role, {"Broker"})
    listing, offer = _get_offer_on_listing(lid, off_id)
    order = DB["orders"].get(listing["order_id"])
    # Gate 1: offer active
    if offer["status"] not in ("PENDING", "COUNTERED"):
        raise ApiError("ERR_OFFER_NOT_ACTIVE", "Offer is not active")
    carrier = DB["carriers"].get(offer["carrier_id"])
    if carrier is None:
        raise ApiError("ERR_NOT_FOUND", "Carrier not found")
    # Gate 2: not suspended
    if carrier["status"] == "SUSPENDED":
        raise ApiError("ERR_CARRIER_SUSPENDED", "Carrier is suspended")
    # Gate 3: insurance not expired
    if now() > parse_dt(carrier["insurance_expiry_date"]):
        raise ApiError("ERR_INSURANCE_EXPIRED", "Carrier insurance certificate expired")
    # Gate 4: schedule conflict (half-open)
    pws = parse_dt(order["pickup_window_start"])
    pwe = parse_dt(order["pickup_window_end"])
    for a in DB["assignments"].values():
        if a["carrier_id"] != carrier["id"] or a["status"] != "DISPATCHED":
            continue
        other = DB["orders"].get(a["order_id"])
        if other is None or other["id"] == order["id"]:
            continue
        o_start = parse_dt(other["pickup_window_start"])
        o_end = parse_dt(other["pickup_window_end"])
        if overlap_half_open(pws, pwe, o_start, o_end):
            raise ApiError("ERR_CARRIER_SCHEDULE_CONFLICT", "Carrier schedule conflict")
    # Gate 5: equipment match
    if carrier["equipment_type"] != order["transport_type"]:
        raise ApiError("ERR_EQUIPMENT_MISMATCH", "Carrier equipment mismatch")
    # Gate 6: insurance adequate (per-load)
    per_load = order_declared_value(order["id"])
    if carrier["cargo_insurance_limit_cents"] < per_load:
        raise ApiError("ERR_INSURANCE_INADEQUATE", "Carrier insurance inadequate")
    # Gate 7: pay not exceeding total
    if offer["ask_pay_cents"] > order["quoted_total_cents"]:
        raise ApiError("ERR_PAY_EXCEEDS_TOTAL", "Offer pay exceeds order total")

    assignment = {"order_id": order["id"], "carrier_id": carrier["id"],
                  "offer_id": offer["id"], "carrier_pay_cents": offer["ask_pay_cents"],
                  "status": "DISPATCHED"}
    add_common(assignment)
    DB["assignments"][assignment["id"]] = assignment

    order["assigned_carrier_id"] = carrier["id"]
    offer["status"] = "ACCEPTED"
    touch(offer)
    # decline sibling active offers
    for sib in DB["offers"].values():
        if sib["listing_id"] == listing["id"] and sib["id"] != offer["id"] \
                and sib["status"] in ("PENDING", "COUNTERED"):
            sib["status"] = "DECLINED"
            touch(sib)
    listing["status"] = "AWARDED"
    recompute_best_offer(listing)
    touch(listing)
    recompute_carrier_exposure(carrier)
    order["status"] = "DISPATCHED"
    touch(order)
    return respond_object(serialize("assignment", assignment), 200)


# =============================================================================
# Assignment endpoints
# =============================================================================
@app.route("/assignments", methods=["GET"])
def list_assignments():
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Carrier"})
    order_id = request.args.get("order_id")
    carrier_id = request.args.get("carrier_id")
    offer_id = request.args.get("offer_id")
    status = request.args.get("status")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if carrier_id is not None and r["carrier_id"] != carrier_id:
            return False
        if offer_id is not None and r["offer_id"] != offer_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True
    return list_response("assignment", DB["assignments"].values(), pred)


@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _uid, role = authenticate()
    authorize(role, {"Broker", "Admin", "Carrier"})
    rec = lookup("assignments", aid)
    return respond_object(serialize("assignment", rec), 200)


@app.route("/assignments/<aid>/revoke", methods=["POST"])
def revoke_assignment(aid):
    _uid, role = authenticate()
    authorize(role, {"Broker"})
    assignment = lookup("assignments", aid)
    if assignment["status"] != "DISPATCHED":
        raise ApiError("ERR_ASSIGNMENT_NOT_DISPATCHED", "Assignment is not DISPATCHED")
    order = DB["orders"].get(assignment["order_id"])
    pickup_exists = any(i["order_id"] == order["id"] and i["phase"] == "PICKUP"
                        for i in DB["inspections"].values())
    if pickup_exists:
        raise ApiError("ERR_ALREADY_PICKED_UP", "Order already picked up")
    assignment["status"] = "REVOKED"
    touch(assignment)
    order["assigned_carrier_id"] = None
    # reopen listing
    for listing in DB["listings"].values():
        if listing["order_id"] == order["id"] and listing["status"] == "AWARDED":
            listing["status"] = "OPEN"
            recompute_best_offer(listing)
            touch(listing)
    carrier = DB["carriers"].get(assignment["carrier_id"])
    if carrier is not None:
        recompute_carrier_exposure(carrier)
    order["status"] = "LISTED"
    touch(order)
    return respond_object(serialize("assignment", assignment), 200)


# =============================================================================
# Inspection endpoints
# =============================================================================
@app.route("/shipment-orders/<oid>/inspections", methods=["POST"])
def create_inspection(oid):
    uid, role = authenticate()
    authorize(role, {"Carrier"})
    order = lookup("orders", oid)
    # ownership: must be the order's dispatched carrier
    if order["assigned_carrier_id"] is None or order["assigned_carrier_id"] != uid:
        raise ApiError("ERR_NOT_ASSIGNED_CARRIER", "Not the assigned carrier")
    body = get_body()
    phase = require_enum(body, "phase", {"PICKUP", "DELIVERY"})
    odometer = require_present(body, "odometer")
    if not is_int(odometer) or odometer < 0:
        raise ApiError("ERR_INVALID_REQUEST", "odometer must be a non-negative integer")
    damage_count = body.get("damage_count", 0)
    if damage_count is None:
        damage_count = 0
    if not is_int(damage_count) or damage_count < 0:
        raise ApiError("ERR_INVALID_REQUEST", "damage_count must be a non-negative integer")
    observed_inop = body.get("observed_inoperable_count", 0)
    if observed_inop is None:
        observed_inop = 0
    if not is_int(observed_inop) or observed_inop < 0:
        raise ApiError("ERR_INVALID_REQUEST", "observed_inoperable_count must be a non-negative integer")

    pickup_exists = any(i["order_id"] == order["id"] and i["phase"] == "PICKUP"
                        for i in DB["inspections"].values())
    delivery_exists = any(i["order_id"] == order["id"] and i["phase"] == "DELIVERY"
                          for i in DB["inspections"].values())

    if phase == "PICKUP":
        if pickup_exists:
            raise ApiError("ERR_DUPLICATE_INSPECTION", "PICKUP inspection already exists")
        if order["status"] != "DISPATCHED":
            raise ApiError("ERR_INVALID_STATE", "Order not in DISPATCHED state")
    else:  # DELIVERY
        if delivery_exists:
            raise ApiError("ERR_DUPLICATE_INSPECTION", "DELIVERY inspection already exists")
        if not pickup_exists:
            raise ApiError("ERR_DUPLICATE_INSPECTION", "PICKUP inspection required first")
        if order["status"] != "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE", "Order not in PICKED_UP state")

    rec = {"order_id": order["id"], "phase": phase, "damage_count": damage_count,
           "observed_inoperable_count": observed_inop, "odometer": odometer,
           "signed_by_carrier_id": uid}
    add_common(rec)
    DB["inspections"][rec["id"]] = rec

    if phase == "PICKUP":
        order["status"] = "PICKED_UP"
        touch(order)
    else:
        # settlement pricing
        quote = DB["quotes"].get(order["_accepted_quote_id"])
        base = quote["base_cents"]
        transport = quote["transport_surcharge_cents"]
        discount = quote["multi_car_discount_cents"]
        pickup_insp = next(i for i in DB["inspections"].values()
                           if i["order_id"] == order["id"] and i["phase"] == "PICKUP")
        observed = pickup_insp["observed_inoperable_count"]
        settled = base + transport + INOP_SURCHARGE_CENTS * observed - discount
        order["settled_total_cents"] = settled
        # complete assignment
        for a in DB["assignments"].values():
            if a["order_id"] == order["id"] and a["status"] == "DISPATCHED":
                a["status"] = "COMPLETED"
                touch(a)
                carrier = DB["carriers"].get(a["carrier_id"])
                if carrier is not None:
                    recompute_carrier_exposure(carrier)
                break
        order["status"] = "DELIVERED"
        touch(order)
    return respond_object(serialize("inspection", rec), 201)


@app.route("/inspections", methods=["GET"])
def list_inspections():
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin", "Carrier"})
    order_id = request.args.get("order_id")
    signed_by = request.args.get("signed_by_carrier_id")
    phase = request.args.get("phase")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if signed_by is not None and r["signed_by_carrier_id"] != signed_by:
            return False
        if phase is not None and r["phase"] != phase:
            return False
        return True
    return list_response("inspection", DB["inspections"].values(), pred)


@app.route("/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin", "Carrier"})
    rec = lookup("inspections", iid)
    return respond_object(serialize("inspection", rec), 200)


# =============================================================================
# Claim endpoints
# =============================================================================
@app.route("/shipment-orders/<oid>/claims", methods=["POST"])
def create_claim(oid):
    uid, role = authenticate()
    authorize(role, {"Shipper"})
    order = lookup("orders", oid)
    if order["shipper_id"] != uid:
        raise ApiError("ERR_NOT_ORDER_OWNER", "Not the order owner")
    body = get_body()
    claimed = require_pos_int(body, "claimed_cents")
    rec = {"order_id": order["id"], "carrier_id": order["assigned_carrier_id"],
           "claimed_cents": claimed, "approved_cents": None, "status": "SUBMITTED"}
    add_common(rec)
    DB["claims"][rec["id"]] = rec
    update_has_open_claim(order)
    return respond_object(serialize("claim", rec), 201)


@app.route("/claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin", "Carrier"})
    order_id = request.args.get("order_id")
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if carrier_id is not None and r["carrier_id"] != carrier_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True
    return list_response("claim", DB["claims"].values(), pred)


@app.route("/claims/<clid>", methods=["GET"])
def get_claim(clid):
    _uid, role = authenticate()
    authorize(role, {"Shipper", "Broker", "Admin", "Carrier"})
    rec = lookup("claims", clid)
    return respond_object(serialize("claim", rec), 200)


@app.route("/claims/<clid>/return", methods=["POST"])
def return_claim(clid):
    _uid, role = authenticate()
    authorize(role, {"Admin"})
    claim = lookup("claims", clid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", "Claim not actionable")
    claim["status"] = "RETURNED_FOR_INFO"
    touch(claim)
    return respond_object(serialize("claim", claim), 200)


@app.route("/claims/<clid>/resubmit", methods=["POST"])
def resubmit_claim(clid):
    uid, role = authenticate()
    authorize(role, {"Shipper"})
    claim = lookup("claims", clid)
    order = DB["orders"].get(claim["order_id"])
    if order is None or order["shipper_id"] != uid:
        raise ApiError("ERR_NOT_ORDER_OWNER", "Not the order owner")
    if claim["status"] != "RETURNED_FOR_INFO":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", "Claim not actionable")
    body = get_body()
    claimed = require_pos_int(body, "claimed_cents")
    claim["claimed_cents"] = claimed
    claim["status"] = "SUBMITTED"
    touch(claim)
    return respond_object(serialize("claim", claim), 200)


@app.route("/claims/<clid>/approve", methods=["POST"])
def approve_claim(clid):
    _uid, role = authenticate()
    authorize(role, {"Admin"})
    claim = lookup("claims", clid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", "Claim not actionable")
    order = DB["orders"].get(claim["order_id"])
    delivery_damaged = any(i["order_id"] == order["id"] and i["phase"] == "DELIVERY" and i["damage_count"] > 0
                           for i in DB["inspections"].values())
    if order["status"] != "DELIVERED" or not delivery_damaged:
        raise ApiError("ERR_NO_DAMAGE_ON_RECORD", "No damage on record")
    carrier = DB["carriers"].get(claim["carrier_id"])
    eligible = min(claim["claimed_cents"], order_declared_value(order["id"]))
    limit = carrier["cargo_insurance_limit_cents"] if carrier is not None else 0
    approved = min(eligible, limit)
    claim["approved_cents"] = approved
    claim["status"] = "APPROVED"
    touch(claim)
    return respond_object(serialize("claim", claim), 200)


@app.route("/claims/<clid>/deny", methods=["POST"])
def deny_claim(clid):
    _uid, role = authenticate()
    authorize(role, {"Admin"})
    claim = lookup("claims", clid)
    if claim["status"] not in ("SUBMITTED", "RETURNED_FOR_INFO"):
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", "Claim not actionable")
    claim["status"] = "DENIED"
    touch(claim)
    order = DB["orders"].get(claim["order_id"])
    if order is not None:
        update_has_open_claim(order)
    return respond_object(serialize("claim", claim), 200)


@app.route("/claims/<clid>/pay", methods=["POST"])
def pay_claim(clid):
    _uid, role = authenticate()
    authorize(role, {"Admin"})
    claim = lookup("claims", clid)
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", "Claim not actionable")
    order = DB["orders"].get(claim["order_id"])
    payout = {"order_id": order["id"], "kind": "CLAIM_PAYOUT",
              "amount_cents": -(claim["approved_cents"] or 0), "status": "POSTED"}
    add_common(payout, versioned=False)
    DB["ledger"][payout["id"]] = payout
    recompute_order_balances(order)  # CLAIM_PAYOUT does not affect amount_paid
    claim["status"] = "PAID"
    touch(claim)
    update_has_open_claim(order)
    return respond_object(serialize("claim", claim), 200)


# =============================================================================
# Logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    authorize(role, {"Admin"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    CLOCK[0] = parse_dt(to_iso)
    return respond_object({}, 200)


# =============================================================================
# Health
# =============================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
