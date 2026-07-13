"""Commuter Rail Fare & Conductor API — single-file Flask implementation.

In-memory only (dicts). Store starts empty on every boot; the per-test-server
harness relaunches this process before every test. No seeding at startup.
"""
import os
import uuid
import string
import random
import calendar
import itertools
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Domain constants (single source of truth — scaffold §1)
# ---------------------------------------------------------------------------
REDUCED_FARE_DISCOUNT_PCT = Decimal("0.50")
FARE_CAP_CENTS = 5000
REFUND_FEE_CENTS = 200
ONBOARD_SURCHARGE_CENTS = 200
EVASION_BASE_PENALTY_CENTS = 5000
REPEAT_EVASION_THRESHOLD = 2
EVASION_FARE_ESTIMATE_CENTS = 1000
EVASION_REVOCATION_THRESHOLD = 3
SERVICE_CREDIT_MIN_DELAY_MINUTES = 30
SENIOR_MIN_AGE = 65
TICKET_ACTIVATION_DEADLINE_DAYS = 90
REFUND_WINDOW_DAYS = 60
DISRUPTION_BUFFER_MINUTES = 15
SINGLE_VALIDITY_MINUTES = 90
ZONE_MILES = {1: 10, 2: 20, 3: 30, 4: 40, 5: 50, 6: 60}

ROLES = {"Passenger", "Conductor", "FareAdmin"}

TICKET_TYPES = {"SINGLE", "MONTHLY"}
TRAVEL_PERIODS = {"PEAK", "OFF_PEAK"}
APPORTIONMENT_METHODS = {"ZONE_COUNT", "DISTANCE"}
REDUCED_CATEGORIES = {"SENIOR", "STUDENT", "DISABILITY"}
REFUND_DESTINATIONS = {"WALLET", "ORIGINAL"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
_seq_counter = itertools.count(1)

STORE = {
    "clock": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
    "fare_products": {},
    "agencies": {},
    "passengers": {},
    "applications": {},
    "tickets": {},
    "inspections": {},
    "upgrades": {},
    "citations": {},
    "refund_requests": {},
    "disruptions": {},
    "service_credits": {},
}


def now():
    return STORE["clock"]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


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
def parse_dt(value, field="datetime"):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} must be an ISO-8601 string")
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} is not a valid ISO-8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value.strip())
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} is not a valid date")


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def first_of_next_month(dt):
    y, m = dt.year, dt.month
    if m == 12:
        y += 1
        m = 1
    else:
        m += 1
    return datetime(y, m, 1, tzinfo=timezone.utc)


def start_of_day(dt):
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def age_in_years(dob, at):
    at_d = at.date()
    years = at_d.year - dob.year - ((at_d.month, at_d.day) < (dob.month, dob.day))
    return years


# ---------------------------------------------------------------------------
# Serialization: convert internal record -> JSON-safe dict
# ---------------------------------------------------------------------------
def serialize(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.startswith("_"):
                continue
            out[k] = serialize(v)
        return out
    if isinstance(value, list):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return iso(value)
    return value


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": iso(now())}


def success(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def obj_response(record, status=200):
    return success(serialize(record), status=status, response_type="object")


def error_response(err):
    meta = meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    g.user_id = user_id
    g.role = role
    return user_id, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------
def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}")
    return body[field]


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} must be an integer")
    return value


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} must be a non-empty string")
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} must be one of {sorted(allowed)}")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} must be a boolean")
    return value


def as_zone(value, field):
    v = as_int(value, field)
    if not (1 <= v <= 6):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{field} must be between 1 and 6")
    return v


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_or_404(collection, rid, error_id):
    rec = STORE[collection].get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "Referenced resource does not exist")
    return rec


def get_passenger(pid):
    return get_or_404("passengers", pid, "ERR_PASSENGER_NOT_FOUND")


def get_fare_product(fid):
    return get_or_404("fare_products", fid, "ERR_FARE_PRODUCT_NOT_FOUND")


def get_ticket(tid):
    return get_or_404("tickets", tid, "ERR_TICKET_NOT_FOUND")


def find_fare_product(origin, dest, ttype):
    for fp in STORE["fare_products"].values():
        if fp["origin_zone"] == origin and fp["destination_zone"] == dest and fp["ticket_type"] == ttype:
            return fp
    return None


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------
def touch(record):
    """Bump a versioned entity's updated_at + version (a mutation)."""
    record["updated_at"] = now()
    record["version"] = record.get("version", 1) + 1


def base_common(versioned):
    n = now()
    rec = {"id": new_id(), "created_at": n, "_seq": next_seq()}
    if versioned:
        rec["updated_at"] = n
        rec["version"] = 1
    return rec


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pag(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{name} must be an integer")
    if val < minimum or (maximum is not None and val > maximum):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"{name} out of range")
    return val


def paginate(records):
    limit = parse_pag("limit", 10, 1, 100)
    offset = parse_pag("offset", 0, 0, None)
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, pagination


def list_response(records):
    page, pagination = paginate(records)
    return success([serialize(r) for r in page], status=200, response_type="array", pagination=pagination)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_purchase_price(fp, travel_period, reduced_applied):
    subtotal = fp["base_fare_cents"] + (fp["peak_surcharge_cents"] if travel_period == "PEAK" else 0)
    if reduced_applied:
        discount = round_half_up(Decimal(subtotal) * REDUCED_FARE_DISCOUNT_PCT)
        price = subtotal - discount
    else:
        price = subtotal
    return min(price, FARE_CAP_CENTS)


def compute_revenue_allocations(origin_zone, destination_zone, method, total):
    lo, hi = min(origin_zone, destination_zone), max(origin_zone, destination_zone)
    span = set(range(lo, hi + 1))
    agencies = sorted(STORE["agencies"].values(), key=lambda a: (a["created_at"], a["_seq"]))
    weighted = []
    for a in agencies:
        served = span & set(a["zones_served"])
        if method == "ZONE_COUNT":
            weight = len(served)
        else:  # DISTANCE
            weight = sum(ZONE_MILES[z] for z in served)
        if weight > 0:
            weighted.append((a, weight))
    if not weighted:
        return []
    W = sum(w for _, w in weighted)
    floors = []
    for a, w in weighted:
        raw_floor = (total * w) // W
        floors.append([a, w, raw_floor])
    remainder = total - sum(f[2] for f in floors)
    # distribute leftover cents: weight DESC, tie-break created_at ASC (then seq)
    order = sorted(range(len(floors)),
                   key=lambda i: (-floors[i][1], floors[i][0]["created_at"], floors[i][0]["_seq"]))
    for k in range(remainder):
        floors[order[k]][2] += 1
    # output in agency creation order
    return [{"agency_id": a["id"], "agency_code": a["code"], "amount_cents": amt} for a, w, amt in floors]


def compute_refund_amount(ticket):
    if ticket["status"] == "PURCHASED":
        return max(0, ticket["purchase_price_cents"] - REFUND_FEE_CENTS)
    # ACTIVATED MONTHLY -> prorated
    activated = ticket["activated_at"]
    total_days = calendar.monthrange(activated.year, activated.month)[1]
    elapsed = (now() - start_of_day(activated)).total_seconds() / 86400.0
    used_days = int(elapsed // 1) + 1
    remaining_days = max(0, total_days - used_days)
    gross = (ticket["purchase_price_cents"] * remaining_days) // total_days
    return max(0, gross - REFUND_FEE_CENTS)


def compute_service_credit(delay_minutes, price):
    if delay_minutes < 30:
        return 0
    elif delay_minutes < 60:
        return (price * 25) // 100
    elif delay_minutes < 120:
        return (price * 50) // 100
    else:
        return price


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------
def require_owner(owning_passenger_id):
    if g.role == "Passenger" and g.user_id != owning_passenger_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Passenger does not own this resource")


# ===========================================================================
# Endpoints
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"FareAdmin"})
    body = body_json()
    to_iso = require(body, "to_iso8601")
    STORE["clock"] = parse_dt(to_iso, "to_iso8601")
    return success({}, status=200, response_type="object")


# ---- Fare products --------------------------------------------------------
@app.route("/fare-products", methods=["POST"])
def create_fare_product():
    authenticate({"FareAdmin"})
    body = body_json()
    origin = as_zone(require(body, "origin_zone"), "origin_zone")
    dest = as_zone(require(body, "destination_zone"), "destination_zone")
    ttype = as_enum(require(body, "ticket_type"), "ticket_type", TICKET_TYPES)
    base = as_int(require(body, "base_fare_cents"), "base_fare_cents")
    peak = as_int(require(body, "peak_surcharge_cents"), "peak_surcharge_cents")
    if base < 0 or peak < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "fares must be >= 0")
    method = body.get("apportionment_method", "ZONE_COUNT")
    if method is None:
        method = "ZONE_COUNT"
    method = as_enum(method, "apportionment_method", APPORTIONMENT_METHODS)
    rec = base_common(False)
    rec.update({
        "origin_zone": origin, "destination_zone": dest, "ticket_type": ttype,
        "base_fare_cents": base, "peak_surcharge_cents": peak,
        "apportionment_method": method,
    })
    STORE["fare_products"][rec["id"]] = rec
    return obj_response(rec, 201)


# ---- Agencies -------------------------------------------------------------
@app.route("/agencies", methods=["POST"])
def create_agency():
    authenticate({"FareAdmin"})
    body = body_json()
    code = as_str(require(body, "code"), "code")
    zones = require(body, "zones_served")
    if not isinstance(zones, list) or len(zones) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "zones_served must be a non-empty array")
    parsed = [as_zone(z, "zones_served") for z in zones]
    rec = base_common(False)
    rec.update({"code": code, "zones_served": parsed})
    STORE["agencies"][rec["id"]] = rec
    return obj_response(rec, 201)


# ---- Passengers -----------------------------------------------------------
@app.route("/passengers", methods=["POST"])
def create_passenger():
    authenticate({"FareAdmin"})
    body = body_json()
    email = as_str(require(body, "email"), "email")
    full_name = as_str(require(body, "full_name"), "full_name")
    dob_raw = as_str(require(body, "date_of_birth"), "date_of_birth")
    parse_date(dob_raw, "date_of_birth")  # validate format
    rec = base_common(True)
    rec.update({
        "email": email, "full_name": full_name, "date_of_birth": dob_raw,
        "reduced_fare_category": "NONE", "reduced_fare_valid_until": None,
        "wallet_credit_cents": 0, "evasion_count": 0,
    })
    STORE["passengers"][rec["id"]] = rec
    return obj_response(rec, 201)


@app.route("/passengers/<pid>", methods=["GET"])
def get_passenger_ep(pid):
    authenticate({"FareAdmin", "Passenger", "Conductor"})
    rec = get_passenger(pid)
    return obj_response(rec, 200)


# ---- Reduced-fare applications -------------------------------------------
@app.route("/reduced-fare-applications", methods=["POST"])
def create_application():
    authenticate({"Passenger"})
    body = body_json()
    # existence (3)
    pid = require(body, "passenger_id")
    passenger = get_passenger(pid)
    # ownership (4)
    require_owner(passenger["id"])
    # body validity (4)
    category = as_enum(require(body, "category"), "category", REDUCED_CATEGORIES)
    proof_ref = as_str(require(body, "proof_document_ref"), "proof_document_ref")
    proof_expires = parse_dt(require(body, "proof_expires_at"), "proof_expires_at")
    expected_version = as_int(require(body, "expected_passenger_version"), "expected_passenger_version")
    # OCC (10)
    if expected_version != passenger["version"]:
        raise ApiError("ERR_STALE_PASSENGER_VERSION", 412, "expected_passenger_version is stale")
    # supersede any prior SUBMITTED application for this passenger
    for prior in STORE["applications"].values():
        if prior["passenger_id"] == passenger["id"] and prior["status"] == "SUBMITTED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    rec = base_common(True)
    rec.update({
        "passenger_id": passenger["id"], "category": category,
        "proof_document_ref": proof_ref, "proof_expires_at": proof_expires,
        "valid_until": None, "status": "SUBMITTED", "decision_reason": None,
    })
    STORE["applications"][rec["id"]] = rec
    # creating an application advances the passenger version
    touch(passenger)
    return obj_response(rec, 201)


@app.route("/reduced-fare-applications/<aid>", methods=["GET"])
def get_application(aid):
    authenticate({"FareAdmin", "Passenger"})
    rec = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    return obj_response(rec, 200)


@app.route("/reduced-fare-applications", methods=["GET"])
def list_applications():
    authenticate({"FareAdmin", "Passenger"})
    items = list(STORE["applications"].values())
    pid = request.args.get("passenger_id")
    status = request.args.get("status")
    if pid is not None:
        items = [a for a in items if a["passenger_id"] == pid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


@app.route("/reduced-fare-applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    authenticate({"FareAdmin"})
    app_rec = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if app_rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", 409, "Application is not SUBMITTED")
    passenger = get_passenger(app_rec["passenger_id"])
    if app_rec["category"] == "SENIOR":
        dob = parse_date(passenger["date_of_birth"], "date_of_birth")
        if age_in_years(dob, now()) < SENIOR_MIN_AGE:
            raise ApiError("ERR_SENIOR_AGE_NOT_MET", 422, "Passenger is under the senior minimum age")
    valid_until = min(app_rec["proof_expires_at"], now() + timedelta(days=365))
    app_rec["valid_until"] = valid_until
    app_rec["status"] = "APPROVED"
    touch(app_rec)
    passenger["reduced_fare_category"] = app_rec["category"]
    passenger["reduced_fare_valid_until"] = valid_until
    touch(passenger)
    return obj_response(app_rec, 200)


@app.route("/reduced-fare-applications/<aid>/reject", methods=["POST"])
def reject_application(aid):
    authenticate({"FareAdmin"})
    app_rec = get_or_404("applications", aid, "ERR_APPLICATION_NOT_FOUND")
    body = body_json()
    reason = as_str(require(body, "reason"), "reason")
    if app_rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", 409, "Application is not SUBMITTED")
    app_rec["decision_reason"] = reason
    app_rec["status"] = "REJECTED"
    touch(app_rec)
    return obj_response(app_rec, 200)


# ---- Tickets --------------------------------------------------------------
@app.route("/tickets", methods=["POST"])
def create_ticket():
    authenticate({"Passenger"})
    body = body_json()
    # existence (3): passenger then fare product (body order)
    pid = require(body, "passenger_id")
    passenger = get_passenger(pid)
    fid = require(body, "fare_product_id")
    fp = get_fare_product(fid)
    # ownership (4)
    require_owner(passenger["id"])
    # body validity (4)
    travel_period = as_enum(require(body, "travel_period"), "travel_period", TRAVEL_PERIODS)
    use_reduced = body.get("use_reduced_fare", False)
    if use_reduced is None:
        use_reduced = False
    use_reduced = as_bool(use_reduced, "use_reduced_fare")
    wallet_apply = body.get("wallet_apply_cents", 0)
    if wallet_apply is None:
        wallet_apply = 0
    wallet_apply = as_int(wallet_apply, "wallet_apply_cents")
    if wallet_apply < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "wallet_apply_cents must be >= 0")
    # reduced-fare eligibility (6)
    if use_reduced:
        eligible = (passenger["reduced_fare_category"] != "NONE"
                    and passenger["reduced_fare_valid_until"] is not None
                    and passenger["reduced_fare_valid_until"] >= now())
        if not eligible:
            raise ApiError("ERR_REDUCED_FARE_NOT_ELIGIBLE", 422, "Passenger has no valid reduced-fare eligibility")
    # wallet sufficiency (9)
    if wallet_apply > passenger["wallet_credit_cents"]:
        raise ApiError("ERR_INSUFFICIENT_WALLET", 402, "wallet_apply_cents exceeds wallet balance")

    reduced_applied = bool(use_reduced)
    price = compute_purchase_price(fp, travel_period, reduced_applied)
    allocations = compute_revenue_allocations(
        fp["origin_zone"], fp["destination_zone"], fp["apportionment_method"], price)

    rec = base_common(True)
    rec.update({
        "passenger_id": passenger["id"], "fare_product_id": fp["id"],
        "ticket_type": fp["ticket_type"], "origin_zone": fp["origin_zone"],
        "destination_zone": fp["destination_zone"], "travel_period": travel_period,
        "wallet_applied_cents": wallet_apply, "reduced_fare_applied": reduced_applied,
        "purchase_price_cents": price, "apportionment_method": fp["apportionment_method"],
        "revenue_allocations": allocations, "status": "PURCHASED",
        "activated_at": None, "expires_at": None, "refund_amount_cents": None,
    })
    STORE["tickets"][rec["id"]] = rec
    if wallet_apply > 0:
        passenger["wallet_credit_cents"] -= wallet_apply
        touch(passenger)
    return obj_response(rec, 201)


@app.route("/tickets/<tid>", methods=["GET"])
def get_ticket_ep(tid):
    authenticate({"FareAdmin", "Passenger", "Conductor"})
    return obj_response(get_ticket(tid), 200)


@app.route("/tickets", methods=["GET"])
def list_tickets():
    authenticate({"FareAdmin", "Passenger", "Conductor"})
    items = list(STORE["tickets"].values())
    pid = request.args.get("passenger_id")
    fid = request.args.get("fare_product_id")
    status = request.args.get("status")
    if pid is not None:
        items = [t for t in items if t["passenger_id"] == pid]
    if fid is not None:
        items = [t for t in items if t["fare_product_id"] == fid]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items)


@app.route("/tickets/<tid>/activate", methods=["POST"])
def activate_ticket(tid):
    authenticate({"Passenger"})
    ticket = get_ticket(tid)
    require_owner(ticket["passenger_id"])
    # state (5)
    if ticket["status"] != "PURCHASED":
        raise ApiError("ERR_INVALID_TICKET_STATE", 409, "Ticket is not PURCHASED")
    # activation deadline (7)
    if now() > ticket["created_at"] + timedelta(days=TICKET_ACTIVATION_DEADLINE_DAYS):
        raise ApiError("ERR_TICKET_ACTIVATION_EXPIRED", 409, "Activation window has elapsed")
    n = now()
    if ticket["ticket_type"] == "MONTHLY":
        # overlap (8): another ACTIVATED MONTHLY, same passenger/zone-pair, same validity month
        for other in STORE["tickets"].values():
            if (other["id"] != ticket["id"] and other["status"] == "ACTIVATED"
                    and other["ticket_type"] == "MONTHLY"
                    and other["passenger_id"] == ticket["passenger_id"]
                    and other["origin_zone"] == ticket["origin_zone"]
                    and other["destination_zone"] == ticket["destination_zone"]
                    and other["activated_at"] is not None
                    and (other["activated_at"].year, other["activated_at"].month) == (n.year, n.month)):
                raise ApiError("ERR_PASS_PERIOD_OVERLAP", 409, "Overlapping monthly pass already active")
        expires = first_of_next_month(n)
    else:
        expires = n + timedelta(minutes=SINGLE_VALIDITY_MINUTES)
    ticket["activated_at"] = n
    ticket["expires_at"] = expires
    ticket["status"] = "ACTIVATED"
    touch(ticket)
    return obj_response(ticket, 200)


@app.route("/tickets/<tid>/validate", methods=["POST"])
def validate_ticket(tid):
    authenticate({"Passenger", "Conductor"})
    ticket = get_ticket(tid)
    require_owner(ticket["passenger_id"])
    # state (5): must be ACTIVATED and SINGLE
    if ticket["status"] != "ACTIVATED" or ticket["ticket_type"] != "SINGLE":
        raise ApiError("ERR_INVALID_TICKET_STATE", 409, "Ticket cannot be validated in its current state")
    # temporal (7)
    if now() > ticket["expires_at"]:
        raise ApiError("ERR_TICKET_EXPIRED", 409, "Ticket has expired")
    ticket["status"] = "VALIDATED"
    touch(ticket)
    return obj_response(ticket, 200)


@app.route("/tickets/<tid>/exchange", methods=["POST"])
def exchange_ticket(tid):
    authenticate({"Passenger"})
    ticket = get_ticket(tid)
    body = body_json()
    # existence (3): new fare product
    fid = require(body, "new_fare_product_id")
    fp = get_fare_product(fid)
    # ownership (4)
    require_owner(ticket["passenger_id"])
    # body validity (4)
    travel_period = as_enum(require(body, "travel_period"), "travel_period", TRAVEL_PERIODS)
    wallet_apply = body.get("wallet_apply_cents", 0)
    if wallet_apply is None:
        wallet_apply = 0
    wallet_apply = as_int(wallet_apply, "wallet_apply_cents")
    if wallet_apply < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "wallet_apply_cents must be >= 0")
    # state (5)
    if ticket["status"] != "PURCHASED":
        raise ApiError("ERR_INVALID_TICKET_STATE", 409, "Ticket is not PURCHASED")
    passenger = get_passenger(ticket["passenger_id"])
    # wallet sufficiency (9)
    if wallet_apply > passenger["wallet_credit_cents"]:
        raise ApiError("ERR_INSUFFICIENT_WALLET", 402, "wallet_apply_cents exceeds wallet balance")

    new_price = compute_purchase_price(fp, travel_period, False)
    new_allocations = compute_revenue_allocations(
        fp["origin_zone"], fp["destination_zone"], fp["apportionment_method"], new_price)

    new_rec = base_common(True)
    new_rec.update({
        "passenger_id": passenger["id"], "fare_product_id": fp["id"],
        "ticket_type": fp["ticket_type"], "origin_zone": fp["origin_zone"],
        "destination_zone": fp["destination_zone"], "travel_period": travel_period,
        "wallet_applied_cents": wallet_apply, "reduced_fare_applied": False,
        "purchase_price_cents": new_price, "apportionment_method": fp["apportionment_method"],
        "revenue_allocations": new_allocations, "status": "PURCHASED",
        "activated_at": None, "expires_at": None, "refund_amount_cents": None,
    })
    STORE["tickets"][new_rec["id"]] = new_rec

    # spend wallet on the new ticket
    if wallet_apply > 0:
        passenger["wallet_credit_cents"] -= wallet_apply
        touch(passenger)
    # downgrade credit
    if ticket["purchase_price_cents"] > new_rec["purchase_price_cents"]:
        passenger["wallet_credit_cents"] += ticket["purchase_price_cents"] - new_rec["purchase_price_cents"]
        touch(passenger)
    # old ticket -> EXCHANGED, allocations zeroed
    for alloc in ticket["revenue_allocations"]:
        alloc["amount_cents"] = 0
    ticket["status"] = "EXCHANGED"
    touch(ticket)
    return obj_response(new_rec, 201)


# ---- Inspections ----------------------------------------------------------
@app.route("/inspections", methods=["POST"])
def create_inspection():
    authenticate({"Conductor"})
    body = body_json()
    pid = require(body, "passenger_id")
    get_passenger(pid)
    ticket = None
    ticket_id = body.get("ticket_id")
    if ticket_id is not None:
        ticket = get_ticket(ticket_id)
    observed = as_zone(require(body, "observed_destination_zone"), "observed_destination_zone")

    if ticket is None:
        result, shortfall = "EVASION", EVASION_FARE_ESTIMATE_CENTS
    else:
        valid = (ticket["status"] == "ACTIVATED"
                 and ticket["expires_at"] is not None
                 and now() <= ticket["expires_at"])
        if not valid:
            result, shortfall = "EVASION", EVASION_FARE_ESTIMATE_CENTS
        elif observed > ticket["destination_zone"]:
            result = "UPGRADE_REQUIRED"
            prod = find_fare_product(ticket["origin_zone"], observed, ticket["ticket_type"])
            if prod is not None:
                full = prod["base_fare_cents"] + (prod["peak_surcharge_cents"] if ticket["travel_period"] == "PEAK" else 0)
                shortfall = max(0, full - ticket["purchase_price_cents"])
            else:
                shortfall = 0
        else:
            result, shortfall = "VALID", 0

    rec = base_common(False)
    rec.update({
        "passenger_id": pid, "ticket_id": ticket_id,
        "observed_destination_zone": observed,
        "result": result, "fare_shortfall_cents": shortfall,
    })
    STORE["inspections"][rec["id"]] = rec
    return obj_response(rec, 201)


@app.route("/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    authenticate({"FareAdmin", "Conductor"})
    return obj_response(get_or_404("inspections", iid, "ERR_INSPECTION_NOT_FOUND"), 200)


@app.route("/inspections", methods=["GET"])
def list_inspections():
    authenticate({"FareAdmin", "Conductor"})
    items = list(STORE["inspections"].values())
    pid = request.args.get("passenger_id")
    tid = request.args.get("ticket_id")
    if pid is not None:
        items = [i for i in items if i["passenger_id"] == pid]
    if tid is not None:
        items = [i for i in items if i["ticket_id"] == tid]
    return list_response(items)


# ---- Upgrades -------------------------------------------------------------
@app.route("/upgrades", methods=["POST"])
def create_upgrade():
    authenticate({"Conductor"})
    body = body_json()
    iid = require(body, "inspection_id")
    inspection = get_or_404("inspections", iid, "ERR_INSPECTION_NOT_FOUND")
    tid = require(body, "ticket_id")
    ticket = get_ticket(tid)
    # ticket/inspection linkage (6)
    if inspection["ticket_id"] != ticket["id"]:
        raise ApiError("ERR_UPGRADE_TICKET_MISMATCH", 409, "Upgrade ticket does not match the inspection ticket")
    # upgrade required (8)
    if inspection["result"] != "UPGRADE_REQUIRED":
        raise ApiError("ERR_UPGRADE_NOT_REQUIRED", 409, "Inspection did not require an upgrade")
    observed = inspection["observed_destination_zone"]
    # implied product existence (fare for the observed zone pair)
    prod = find_fare_product(ticket["origin_zone"], observed, ticket["ticket_type"])
    if prod is None:
        raise ApiError("ERR_FARE_PRODUCT_NOT_FOUND", 404, "No fare product for the observed zone pair")
    new_full = prod["base_fare_cents"] + (prod["peak_surcharge_cents"] if ticket["travel_period"] == "PEAK" else 0)
    upgrade_fare = max(0, new_full - ticket["purchase_price_cents"]) + ONBOARD_SURCHARGE_CENTS

    from_zone = ticket["destination_zone"]
    rec = base_common(False)
    rec.update({
        "inspection_id": inspection["id"], "ticket_id": ticket["id"],
        "from_zone": from_zone, "to_zone": observed, "upgrade_fare_cents": upgrade_fare,
    })
    STORE["upgrades"][rec["id"]] = rec
    ticket["destination_zone"] = observed
    touch(ticket)
    return obj_response(rec, 201)


@app.route("/upgrades/<uid>", methods=["GET"])
def get_upgrade(uid):
    authenticate({"FareAdmin", "Conductor", "Passenger"})
    return obj_response(get_or_404("upgrades", uid, "ERR_UPGRADE_NOT_FOUND"), 200)


@app.route("/upgrades", methods=["GET"])
def list_upgrades():
    authenticate({"FareAdmin", "Conductor"})
    items = list(STORE["upgrades"].values())
    iid = request.args.get("inspection_id")
    tid = request.args.get("ticket_id")
    if iid is not None:
        items = [u for u in items if u["inspection_id"] == iid]
    if tid is not None:
        items = [u for u in items if u["ticket_id"] == tid]
    return list_response(items)


# ---- Citations ------------------------------------------------------------
@app.route("/citations", methods=["POST"])
def create_citation():
    authenticate({"Conductor"})
    body = body_json()
    iid = require(body, "inspection_id")
    inspection = get_or_404("inspections", iid, "ERR_INSPECTION_NOT_FOUND")
    pid = require(body, "passenger_id")
    passenger = get_passenger(pid)
    # evasion required (8)
    if inspection["result"] != "EVASION":
        raise ApiError("ERR_NO_EVASION_FOUND", 409, "Inspection did not result in evasion")

    prior = passenger["evasion_count"]
    multiplier = 2 if prior >= REPEAT_EVASION_THRESHOLD else 1
    base_penalty = EVASION_BASE_PENALTY_CENTS * multiplier
    fare_shortfall = inspection["fare_shortfall_cents"]
    total_penalty = base_penalty + fare_shortfall

    rec = base_common(True)
    rec.update({
        "inspection_id": inspection["id"], "passenger_id": passenger["id"],
        "base_penalty_cents": base_penalty, "fare_shortfall_cents": fare_shortfall,
        "total_penalty_cents": total_penalty, "status": "ISSUED",
        "contest_grounds": None, "resolution_decision": None,
    })
    STORE["citations"][rec["id"]] = rec

    # cascade hop 2: evasion_count increment
    passenger["evasion_count"] += 1
    touch(passenger)
    # cascade hop 3: revocation of approved reduced-fare eligibility
    if passenger["evasion_count"] >= EVASION_REVOCATION_THRESHOLD:
        for appn in STORE["applications"].values():
            if appn["passenger_id"] == passenger["id"] and appn["status"] == "APPROVED":
                appn["status"] = "REVOKED"
                touch(appn)
                passenger["reduced_fare_category"] = "NONE"
                passenger["reduced_fare_valid_until"] = None
                touch(passenger)
    return obj_response(rec, 201)


@app.route("/citations/<cid>", methods=["GET"])
def get_citation(cid):
    authenticate({"FareAdmin", "Conductor", "Passenger"})
    return obj_response(get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND"), 200)


@app.route("/citations", methods=["GET"])
def list_citations():
    authenticate({"FareAdmin", "Conductor", "Passenger"})
    items = list(STORE["citations"].values())
    pid = request.args.get("passenger_id")
    iid = request.args.get("inspection_id")
    status = request.args.get("status")
    if pid is not None:
        items = [c for c in items if c["passenger_id"] == pid]
    if iid is not None:
        items = [c for c in items if c["inspection_id"] == iid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@app.route("/citations/<cid>/pay", methods=["POST"])
def pay_citation(cid):
    authenticate({"Passenger"})
    citation = get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND")
    require_owner(citation["passenger_id"])
    if citation["status"] not in ("ISSUED", "UPHELD"):
        raise ApiError("ERR_INVALID_CITATION_STATE", 409, "Citation cannot be paid in its current state")
    citation["status"] = "PAID"
    touch(citation)
    return obj_response(citation, 200)


@app.route("/citations/<cid>/contest", methods=["POST"])
def contest_citation(cid):
    authenticate({"Passenger"})
    citation = get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND")
    body = body_json()
    require_owner(citation["passenger_id"])
    grounds = as_str(require(body, "grounds"), "grounds")
    if citation["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_CITATION_STATE", 409, "Citation cannot be contested in its current state")
    citation["contest_grounds"] = grounds
    citation["status"] = "CONTESTED"
    touch(citation)
    return obj_response(citation, 200)


@app.route("/citations/<cid>/resolve", methods=["POST"])
def resolve_citation(cid):
    authenticate({"FareAdmin"})
    citation = get_or_404("citations", cid, "ERR_CITATION_NOT_FOUND")
    body = body_json()
    decision = as_enum(require(body, "decision"), "decision", {"UPHELD", "DISMISSED"})
    if citation["status"] != "CONTESTED":
        raise ApiError("ERR_INVALID_CITATION_STATE", 409, "Citation is not CONTESTED")
    citation["resolution_decision"] = decision
    citation["status"] = decision
    if decision == "DISMISSED":
        passenger = get_passenger(citation["passenger_id"])
        passenger["evasion_count"] -= 1
        touch(passenger)
    touch(citation)
    return obj_response(citation, 200)


# ---- Refund requests ------------------------------------------------------
@app.route("/refund-requests", methods=["POST"])
def create_refund_request():
    authenticate({"Passenger"})
    body = body_json()
    tid = require(body, "ticket_id")
    ticket = get_ticket(tid)
    require_owner(ticket["passenger_id"])
    reason = as_str(require(body, "reason"), "reason")
    destination = as_enum(require(body, "refund_destination"), "refund_destination", REFUND_DESTINATIONS)
    # refundable state (5)
    refundable = (ticket["status"] == "PURCHASED"
                  or (ticket["status"] == "ACTIVATED" and ticket["ticket_type"] == "MONTHLY"))
    if not refundable:
        raise ApiError("ERR_TICKET_NOT_REFUNDABLE", 409, "Ticket is not refundable")
    # refund window (7)
    if now() > ticket["created_at"] + timedelta(days=REFUND_WINDOW_DAYS):
        raise ApiError("ERR_REFUND_WINDOW_ELAPSED", 409, "Refund window has elapsed")
    amount = compute_refund_amount(ticket)
    rec = base_common(True)
    rec.update({
        "ticket_id": ticket["id"], "reason": reason, "refund_destination": destination,
        "refund_amount_cents": amount, "status": "REQUESTED", "decision_reason": None,
    })
    STORE["refund_requests"][rec["id"]] = rec
    return obj_response(rec, 201)


@app.route("/refund-requests/<rid>", methods=["GET"])
def get_refund_request(rid):
    authenticate({"FareAdmin", "Passenger"})
    return obj_response(get_or_404("refund_requests", rid, "ERR_REFUND_REQUEST_NOT_FOUND"), 200)


@app.route("/refund-requests", methods=["GET"])
def list_refund_requests():
    authenticate({"FareAdmin", "Passenger"})
    items = list(STORE["refund_requests"].values())
    tid = request.args.get("ticket_id")
    status = request.args.get("status")
    if tid is not None:
        items = [r for r in items if r["ticket_id"] == tid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items)


@app.route("/refund-requests/<rid>/approve", methods=["POST"])
def approve_refund(rid):
    authenticate({"FareAdmin"})
    req = get_or_404("refund_requests", rid, "ERR_REFUND_REQUEST_NOT_FOUND")
    if req["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_REFUND_STATE", 409, "Refund request is not REQUESTED")
    ticket = get_ticket(req["ticket_id"])
    if ticket["status"] not in ("PURCHASED", "ACTIVATED"):
        raise ApiError("ERR_TICKET_NOT_REFUNDABLE", 409, "Ticket is no longer refundable")
    amount = req["refund_amount_cents"]
    ticket["refund_amount_cents"] = amount
    for alloc in ticket["revenue_allocations"]:
        alloc["amount_cents"] = 0
    ticket["status"] = "REFUNDED"
    touch(ticket)
    if req["refund_destination"] == "WALLET":
        passenger = get_passenger(ticket["passenger_id"])
        passenger["wallet_credit_cents"] += amount
        touch(passenger)
    req["status"] = "APPROVED"
    touch(req)
    return obj_response(req, 200)


@app.route("/refund-requests/<rid>/deny", methods=["POST"])
def deny_refund(rid):
    authenticate({"FareAdmin"})
    req = get_or_404("refund_requests", rid, "ERR_REFUND_REQUEST_NOT_FOUND")
    body = body_json()
    reason = as_str(require(body, "reason"), "reason")
    if req["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_REFUND_STATE", 409, "Refund request is not REQUESTED")
    req["decision_reason"] = reason
    req["status"] = "DENIED"
    touch(req)
    return obj_response(req, 200)


# ---- Service disruptions --------------------------------------------------
@app.route("/service-disruptions", methods=["POST"])
def create_disruption():
    authenticate({"FareAdmin"})
    body = body_json()
    line_code = as_str(require(body, "line_code"), "line_code")
    scheduled = parse_dt(require(body, "scheduled_departure"), "scheduled_departure")
    actual = parse_dt(require(body, "actual_departure"), "actual_departure")
    window_start = parse_dt(require(body, "window_start"), "window_start")
    window_end = parse_dt(require(body, "window_end"), "window_end")
    if actual < scheduled:
        raise ApiError("ERR_INVALID_REQUEST", 422, "actual_departure must be >= scheduled_departure")
    if window_end < window_start:
        raise ApiError("ERR_INVALID_REQUEST", 422, "window_end must be >= window_start")
    # per-line window buffer (8)
    buffer = timedelta(minutes=DISRUPTION_BUFFER_MINUTES)
    for other in STORE["disruptions"].values():
        if other["line_code"] != line_code:
            continue
        ows, owe = other["window_start"], other["window_end"]
        if window_start > owe:
            gap = window_start - owe
        elif ows > window_end:
            gap = ows - window_end
        else:
            gap = timedelta(0)
        if gap < buffer:
            raise ApiError("ERR_DISRUPTION_WINDOW_CONFLICT", 409, "Disruption window conflicts with an existing window")
    delay_minutes = int((actual - scheduled).total_seconds() // 60)
    if delay_minutes < 30:
        severity = "MINOR"
    elif delay_minutes < 120:
        severity = "MAJOR"
    else:
        severity = "SEVERE"
    rec = base_common(False)
    rec.update({
        "line_code": line_code, "scheduled_departure": scheduled, "actual_departure": actual,
        "window_start": window_start, "window_end": window_end,
        "delay_minutes": delay_minutes, "severity": severity,
    })
    STORE["disruptions"][rec["id"]] = rec
    return obj_response(rec, 201)


# ---- Service credits ------------------------------------------------------
@app.route("/service-credits", methods=["POST"])
def create_service_credit():
    authenticate({"FareAdmin"})
    body = body_json()
    did = require(body, "disruption_id")
    disruption = get_or_404("disruptions", did, "ERR_DISRUPTION_NOT_FOUND")
    tid = require(body, "ticket_id")
    ticket = get_ticket(tid)
    # delay threshold (8)
    if disruption["delay_minutes"] < SERVICE_CREDIT_MIN_DELAY_MINUTES:
        raise ApiError("ERR_DELAY_BELOW_THRESHOLD", 422, "Disruption delay is below the credit threshold")
    if ticket["status"] not in ("PURCHASED", "ACTIVATED", "VALIDATED"):
        raise ApiError("ERR_INVALID_TICKET_STATE", 409, "Ticket is not eligible for a service credit")
    amount = compute_service_credit(disruption["delay_minutes"], ticket["purchase_price_cents"])
    passenger = get_passenger(ticket["passenger_id"])
    rec = base_common(True)
    rec.update({
        "disruption_id": disruption["id"], "ticket_id": ticket["id"],
        "passenger_id": ticket["passenger_id"], "credit_amount_cents": amount,
        "status": "ISSUED", "void_reason": None,
    })
    STORE["service_credits"][rec["id"]] = rec
    passenger["wallet_credit_cents"] += amount
    touch(passenger)
    return obj_response(rec, 201)


@app.route("/service-credits/<sid>", methods=["GET"])
def get_service_credit(sid):
    authenticate({"FareAdmin", "Passenger"})
    return obj_response(get_or_404("service_credits", sid, "ERR_SERVICE_CREDIT_NOT_FOUND"), 200)


@app.route("/service-credits", methods=["GET"])
def list_service_credits():
    authenticate({"FareAdmin", "Passenger"})
    items = list(STORE["service_credits"].values())
    did = request.args.get("disruption_id")
    tid = request.args.get("ticket_id")
    pid = request.args.get("passenger_id")
    if did is not None:
        items = [s for s in items if s["disruption_id"] == did]
    if tid is not None:
        items = [s for s in items if s["ticket_id"] == tid]
    if pid is not None:
        items = [s for s in items if s["passenger_id"] == pid]
    return list_response(items)


@app.route("/service-credits/<sid>/void", methods=["POST"])
def void_service_credit(sid):
    authenticate({"FareAdmin"})
    credit = get_or_404("service_credits", sid, "ERR_SERVICE_CREDIT_NOT_FOUND")
    body = body_json()
    reason = as_str(require(body, "reason"), "reason")
    if credit["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_CREDIT_STATE", 409, "Service credit is not ISSUED")
    credit["void_reason"] = reason
    credit["status"] = "VOIDED"
    passenger = get_passenger(credit["passenger_id"])
    passenger["wallet_credit_cents"] -= credit["credit_amount_cents"]
    touch(passenger)
    touch(credit)
    return obj_response(credit, 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
