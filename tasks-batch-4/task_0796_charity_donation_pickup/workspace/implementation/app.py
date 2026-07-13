import os
import uuid
import random
import string
import calendar
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from PRD §3.6 / SCAFFOLD calculations)
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"Anonymous", "Donor", "Dispatcher", "Driver", "PartnerAdmin", "PlatformAdmin"}

ITEM_CATEGORIES = {"FURNITURE", "CLOTHING", "ELECTRONICS", "APPLIANCE", "HOUSEHOLD"}
CONDITIONS = {"NEW", "GOOD", "FAIR", "POOR"}
STREAMS = {"RECYCLE", "REUSE", "LANDFILL"}
DIVERTED_STREAMS = {"RECYCLE", "REUSE"}

DONATION_MAX_CF = 50
FREE_DONATION_MAX_CF = 50

HAUL_BASE_FEE_CENTS = 3500
TIER_A_MAX_CF = 100
TIER_A_RATE = 40
TIER_B_MAX_CF = 250
TIER_B_RATE = 60
TIER_C_RATE = 80
ATTENDED_SURCHARGE_CENTS = 2000
DIVERSION_CREDIT_PER_LB_CENTS = 5
DIVERSION_CREDIT_MAX_PCT = Decimal("0.30")

TRAVEL_BUFFER_MIN = 15

FACTOR = {
    "NEW": Decimal("1.00"),
    "GOOD": Decimal("0.70"),
    "FAIR": Decimal("0.40"),
    "POOR": Decimal("0.15"),
}

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process boot)
# ---------------------------------------------------------------------------
db = {
    "partners": {},
    "vehicles": {},
    "routes": {},
    "donors": {},
    "plans": {},
    "requests": {},
    "items": {},
    "stops": {},
    "receipts": {},
    "invoices": {},
}

_state = {"seq": 0, "clock": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def clock_now():
    return _state["clock"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


NOT_FOUND = {
    "partners": "ERR_PARTNER_NOT_FOUND",
    "vehicles": "ERR_VEHICLE_NOT_FOUND",
    "routes": "ERR_ROUTE_NOT_FOUND",
    "donors": "ERR_DONOR_NOT_FOUND",
    "requests": "ERR_REQUEST_NOT_FOUND",
    "items": "ERR_ITEM_NOT_FOUND",
    "receipts": "ERR_RECEIPT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(d, n):
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def advance_cadence(d, frequency):
    if frequency == "WEEKLY":
        return d + timedelta(days=7)
    if frequency == "BIWEEKLY":
        return d + timedelta(days=14)
    return add_months(d, 1)  # MONTHLY


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta(pagination=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": make_meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(extra):
    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def public(rec, kind=None):
    d = {k: v for k, v in rec.items() if not k.startswith("_")}
    if kind == "stop":
        d["sequence"] = compute_sequence(rec)
    return d


def compute_sequence(stop):
    siblings = [s for s in db["stops"].values() if s["route_id"] == stop["route_id"]]
    siblings.sort(key=lambda s: (parse_dt(s["slot_start"]), s["_seq"]))
    for idx, s in enumerate(siblings, start=1):
        if s["id"] == stop["id"]:
            return idx
    return 1


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def check_auth(allowed_roles, auth_exempt=False):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if auth_exempt:
        if role is None:
            role = "Anonymous"
    else:
        if not role or not uid or role not in KNOWN_ROLES:
            raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid credentials")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")
    return uid, role


READ_ROLES = {"Donor", "Dispatcher", "Driver", "PartnerAdmin", "PlatformAdmin"}


# ---------------------------------------------------------------------------
# Field validation helpers (lowest priority -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "body must be a JSON object")
    return body


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        bad(f"{key} is required")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        bad(f"{key} must be one of {sorted(allowed)}")
    return v


def req_int(body, key, minimum=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        bad(f"{key} must be an integer")
    if minimum is not None and v < minimum:
        bad(f"{key} must be >= {minimum}")
    return v


def opt_enum(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if v not in allowed:
        bad(f"{key} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(kind, rid):
    rec = db[kind].get(rid)
    if rec is None:
        raise ApiError(NOT_FOUND[kind], 404, f"{kind} not found")
    return rec


def body_ref(kind, value):
    """Existence check for a body FK; only checked when a value is provided."""
    if value is None:
        return None
    rec = db[kind].get(value)
    if rec is None:
        raise ApiError(NOT_FOUND[kind], 404, f"{kind} not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, kind=None):
    records = sorted(records, key=lambda r: r["_seq"])
    limit, offset = get_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [public(r, kind) for r in page], pagination


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tiered_volume_charge(V):
    if V <= TIER_A_MAX_CF:
        return V * TIER_A_RATE
    if V <= TIER_B_MAX_CF:
        return TIER_A_MAX_CF * TIER_A_RATE + (V - TIER_A_MAX_CF) * TIER_B_RATE
    return (TIER_A_MAX_CF * TIER_A_RATE
            + (TIER_B_MAX_CF - TIER_A_MAX_CF) * TIER_B_RATE
            + (V - TIER_B_MAX_CF) * TIER_C_RATE)


def haul_subtotal(V, pickup_mode):
    subtotal = HAUL_BASE_FEE_CENTS + tiered_volume_charge(V)
    if pickup_mode == "ATTENDED":
        subtotal += ATTENDED_SURCHARGE_CENTS
    return subtotal


def request_items(request_id):
    return [it for it in db["items"].values() if it["request_id"] == request_id]


def recompute_request_derived(req):
    items = request_items(req["id"])
    declared = sum(it["volume_cf"] for it in items)
    req["declared_volume_cf"] = declared
    req["is_free_donation"] = (req["disposition"] == "DONATION" and declared <= FREE_DONATION_MAX_CF)
    if req["disposition"] == "HAUL":
        req["estimated_haul_fee_cents"] = haul_subtotal(declared, req["pickup_mode"])
    else:
        req["estimated_haul_fee_cents"] = 0


def tax_receipt_value(items, use_appraised):
    total = 0
    for it in items:
        if use_appraised and it.get("appraised_value_cents") is not None:
            v = it["appraised_value_cents"]
            c = it.get("appraised_condition") or it["declared_condition"]
        else:
            v = it["declared_value_cents"]
            c = it["declared_condition"]
        total += rhu(Decimal(v) * FACTOR[c])
    return total


def haul_final(req):
    items = request_items(req["id"])
    V = req["measured_volume_cf"]
    subtotal = haul_subtotal(V, req["pickup_mode"])
    diverted_weight = sum(it["weight_lbs"] for it in items if it.get("stream") in DIVERTED_STREAMS)
    cap = rhu(Decimal(subtotal) * DIVERSION_CREDIT_MAX_PCT)
    credit = min(DIVERSION_CREDIT_PER_LB_CENTS * diverted_weight, cap)
    amount_due = max(0, subtotal - credit)
    return subtotal, credit, amount_due


def recompute_partner(partner):
    year = clock_now().year
    ytd = 0
    for r in db["receipts"].values():
        if r["partner_id"] == partner["id"] and r["status"] == "ISSUED":
            if parse_dt(r["issued_at"]).year == year:
                ytd += r["final_value_cents"]
    partner["ytd_donation_value_cents"] = ytd

    diverted = 0
    for it in db["items"].values():
        req = db["requests"].get(it["request_id"])
        if req is None:
            continue
        if req["partner_id"] == partner["id"] and req["status"] == "COMPLETED" and it.get("stream") in DIVERTED_STREAMS:
            diverted += it["weight_lbs"]
    partner["diverted_weight_lbs"] = diverted


def recompute_route(route):
    stops = [s for s in db["stops"].values() if s["route_id"] == route["id"]]
    route["reserved_volume_cf"] = sum(s["reserved_volume_cf"] for s in stops if s["status"] == "RESERVED")
    route["total_stop_count"] = sum(1 for s in stops if s["status"] in ("RESERVED", "SERVICED"))
    route["serviced_stop_count"] = sum(1 for s in stops if s["status"] == "SERVICED")


def request_stop(request_id):
    for s in db["stops"].values():
        if s["request_id"] == request_id and s["status"] == "RESERVED":
            return s
    # fall back to any stop for the request
    for s in db["stops"].values():
        if s["request_id"] == request_id:
            return s
    return None


# ===========================================================================
# ROUTES
# ===========================================================================
@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok"}), 200


# ---- CharityPartner --------------------------------------------------------
@app.route("/partners", methods=["POST"])
def create_partner():
    check_auth({"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    region_code = req_str(body, "region_code")
    tax_id = req_str(body, "tax_id")
    cats = body.get("accepted_categories")
    if not isinstance(cats, list) or len(cats) == 0 or any(c not in ITEM_CATEGORIES for c in cats):
        bad("accepted_categories must be a non-empty subset of the category set")
    status = opt_enum(body, "status", {"ACTIVE", "SUSPENDED"}, default="ACTIVE")
    rec = new_record({
        "name": name,
        "region_code": region_code,
        "tax_id": tax_id,
        "accepted_categories": list(cats),
        "status": status,
        "ytd_donation_value_cents": 0,
        "diverted_weight_lbs": 0,
    })
    db["partners"][rec["id"]] = rec
    return success(public(rec), "object", 201)


@app.route("/partners/<pid>", methods=["GET"])
def get_partner(pid):
    check_auth(READ_ROLES)
    rec = get_or_404("partners", pid)
    return success(public(rec), "object", 200)


@app.route("/partners/<pid>", methods=["PATCH"])
def update_partner(pid):
    uid, role = check_auth({"PartnerAdmin", "PlatformAdmin"})
    rec = get_or_404("partners", pid)
    if role == "PartnerAdmin" and uid != rec["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "may only reconfigure own partner record")
    body = get_body()
    changed = False
    if "status" in body and body.get("status") is not None:
        status = req_enum(body, "status", {"ACTIVE", "SUSPENDED"})
        rec["status"] = status
        changed = True
    if "accepted_categories" in body and body.get("accepted_categories") is not None:
        cats = body.get("accepted_categories")
        if not isinstance(cats, list) or len(cats) == 0 or any(c not in ITEM_CATEGORIES for c in cats):
            bad("accepted_categories must be a non-empty subset of the category set")
        rec["accepted_categories"] = list(cats)
        changed = True
    if changed:
        touch(rec)
    return success(public(rec), "object", 200)


# ---- Vehicle ---------------------------------------------------------------
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    check_auth({"PlatformAdmin"})
    body = get_body()
    label = req_str(body, "label")
    capacity = req_int(body, "capacity_cf")
    if capacity <= 0:
        bad("capacity_cf must be > 0")
    home_depot = req_str(body, "home_depot_code")
    status = opt_enum(body, "status", {"ACTIVE", "OUT_OF_SERVICE"}, default="ACTIVE")
    rec = new_record({
        "label": label,
        "capacity_cf": capacity,
        "home_depot_code": home_depot,
        "status": status,
    })
    db["vehicles"][rec["id"]] = rec
    return success(public(rec), "object", 201)


# ---- Route -----------------------------------------------------------------
def windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.route("/routes", methods=["POST"])
def create_route():
    check_auth({"Dispatcher"})
    body = get_body()
    # priority 5: body FK existence (order: vehicle then partner)
    vehicle = body_ref("vehicles", body.get("vehicle_id"))
    partner = body_ref("partners", body.get("partner_id"))
    # priority 8: route-window conflict (needs well-formed window)
    # field validity for required fields / parse
    if vehicle is None:
        bad("vehicle_id is required")
    if partner is None:
        bad("partner_id is required")
    service_date = req_str(body, "service_date")
    try:
        datetime.strptime(service_date, "%Y-%m-%d")
    except ValueError:
        bad("service_date must be YYYY-MM-DD")
    ws_raw = req_str(body, "window_start")
    we_raw = req_str(body, "window_end")
    ws = parse_dt(ws_raw)
    we = parse_dt(we_raw)
    if we <= ws:
        bad("window_end must be after window_start")
    # window conflict check
    for other in db["routes"].values():
        if other["vehicle_id"] == vehicle["id"] and other["service_date"] == service_date \
                and other["status"] != "CLOSED":
            if windows_overlap(ws, we, parse_dt(other["window_start"]), parse_dt(other["window_end"])):
                raise ApiError("ERR_ROUTE_WINDOW_CONFLICT", 409, "route window overlaps an existing route")
    rec = new_record({
        "vehicle_id": vehicle["id"],
        "partner_id": partner["id"],
        "service_date": service_date,
        "window_start": ws_raw,
        "window_end": we_raw,
        "status": "PLANNED",
        "reserved_volume_cf": 0,
        "total_stop_count": 0,
        "serviced_stop_count": 0,
    })
    db["routes"][rec["id"]] = rec
    return success(public(rec), "object", 201)


@app.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    check_auth(READ_ROLES)
    rec = get_or_404("routes", rid)
    return success(public(rec), "object", 200)


@app.route("/routes", methods=["GET"])
def list_routes():
    check_auth(READ_ROLES)
    recs = list(db["routes"].values())
    vid = request.args.get("vehicle_id")
    pid = request.args.get("partner_id")
    status = request.args.get("status")
    if vid is not None:
        recs = [r for r in recs if r["vehicle_id"] == vid]
    if pid is not None:
        recs = [r for r in recs if r["partner_id"] == pid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    data, pg = paginate(recs)
    return success(data, "array", 200, pg)


@app.route("/routes/<rid>/open", methods=["POST"])
def open_route(rid):
    check_auth({"Dispatcher"})
    route = get_or_404("routes", rid)
    if route["status"] != "PLANNED":
        raise ApiError("ERR_ROUTE_INVALID_STATE", 409, "route is not PLANNED")
    vehicle = db["vehicles"].get(route["vehicle_id"])
    if vehicle is None or vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_OUT_OF_SERVICE", 409, "vehicle is out of service")
    route["status"] = "OPEN"
    touch(route)
    return success(public(route), "object", 200)


@app.route("/routes/<rid>/close", methods=["POST"])
def close_route(rid):
    check_auth({"Dispatcher"})
    route = get_or_404("routes", rid)
    if route["status"] != "OPEN":
        raise ApiError("ERR_ROUTE_INVALID_STATE", 409, "route is not OPEN")
    reserved = [s for s in db["stops"].values()
                if s["route_id"] == route["id"] and s["status"] == "RESERVED"]
    if reserved:
        raise ApiError("ERR_ROUTE_INVALID_STATE", 409, "route still has RESERVED stops")
    route["status"] = "CLOSED"
    touch(route)
    return success(public(route), "object", 200)


@app.route("/routes/<rid>/stops", methods=["GET"])
def list_route_stops(rid):
    check_auth(READ_ROLES)
    get_or_404("routes", rid)
    recs = [s for s in db["stops"].values() if s["route_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    data, pg = paginate(recs, kind="stop")
    return success(data, "array", 200, pg)


# ---- Donor -----------------------------------------------------------------
@app.route("/donors", methods=["POST"])
def create_donor():
    check_auth({"Anonymous", "PlatformAdmin"}, auth_exempt=True)
    body = get_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    address = req_str(body, "address")
    region_code = req_str(body, "region_code")
    rec = new_record({
        "email": email,
        "full_name": full_name,
        "address": address,
        "region_code": region_code,
        "status": "ACTIVE",
    })
    db["donors"][rec["id"]] = rec
    return success(public(rec), "object", 201)


@app.route("/donors/<did>", methods=["GET"])
def get_donor(did):
    check_auth(READ_ROLES)
    rec = get_or_404("donors", did)
    return success(public(rec), "object", 200)


# ---- PickupRequest ---------------------------------------------------------
@app.route("/pickup-requests", methods=["POST"])
def create_request():
    uid, role = check_auth({"Donor"})
    body = get_body()
    donor_id = body.get("donor_id")
    # priority 4: ownership (only when donor_id supplied)
    if donor_id is not None and str(donor_id) != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "donor_id must match acting donor")
    # priority 5: body FK existence
    body_ref("donors", donor_id)
    body_ref("partners", body.get("partner_id"))
    if body.get("recurring_plan_id") is not None:
        body_ref("plans", body.get("recurring_plan_id"))
    # priority 17: field validity
    if donor_id is None:
        bad("donor_id is required")
    partner_id = body.get("partner_id")
    if partner_id is None:
        bad("partner_id is required")
    pickup_mode = req_enum(body, "pickup_mode", {"ATTENDED", "UNATTENDED"})
    disposition = req_enum(body, "disposition", {"DONATION", "HAUL"})
    address = req_str(body, "address")
    porch_photo_url = body.get("porch_photo_url")
    if porch_photo_url is not None and not isinstance(porch_photo_url, str):
        bad("porch_photo_url must be a string")
    safety = body.get("safety_attestation", False)
    if safety is None:
        safety = False
    if not isinstance(safety, bool):
        bad("safety_attestation must be a boolean")
    rec = new_record({
        "donor_id": donor_id,
        "partner_id": partner_id,
        "recurring_plan_id": body.get("recurring_plan_id"),
        "pickup_mode": pickup_mode,
        "disposition": disposition,
        "address": address,
        "porch_photo_url": porch_photo_url,
        "safety_attestation": safety,
        "declared_volume_cf": 0,
        "measured_volume_cf": None,
        "is_free_donation": (disposition == "DONATION"),
        "estimated_haul_fee_cents": 0,
        "status": "REQUESTED",
    })
    db["requests"][rec["id"]] = rec
    return success(public(rec), "object", 201)


@app.route("/pickup-requests/<rid>", methods=["GET"])
def get_request(rid):
    check_auth(READ_ROLES)
    rec = get_or_404("requests", rid)
    return success(public(rec), "object", 200)


@app.route("/pickup-requests", methods=["GET"])
def list_requests():
    check_auth(READ_ROLES)
    recs = list(db["requests"].values())
    for key in ("donor_id", "partner_id", "recurring_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r.get(key) == val]
    data, pg = paginate(recs)
    return success(data, "array", 200, pg)


@app.route("/pickup-requests/<rid>/items", methods=["POST"])
def add_item(rid):
    uid, role = check_auth({"Donor"})
    req = get_or_404("requests", rid)
    if uid != req["donor_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning donor")
    if req["status"] != "REQUESTED":
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409, "items may only be added to a REQUESTED request")
    body = get_body()
    category = req_enum(body, "category", ITEM_CATEGORIES)
    volume = req_int(body, "volume_cf")
    if volume <= 0:
        bad("volume_cf must be > 0")
    weight = req_int(body, "weight_lbs", minimum=0)
    declared_value = req_int(body, "declared_value_cents", minimum=0)
    declared_condition = req_enum(body, "declared_condition", CONDITIONS)
    item = new_record({
        "request_id": req["id"],
        "category": category,
        "volume_cf": volume,
        "weight_lbs": weight,
        "declared_value_cents": declared_value,
        "declared_condition": declared_condition,
        "appraised_value_cents": None,
        "appraised_condition": None,
        "stream": None,
    })
    db["items"][item["id"]] = item
    recompute_request_derived(req)
    touch(req)
    return success(public(item), "object", 201)


@app.route("/pickup-requests/<rid>/items", methods=["GET"])
def list_items(rid):
    check_auth(READ_ROLES)
    get_or_404("requests", rid)
    recs = [it for it in db["items"].values() if it["request_id"] == rid]
    data, pg = paginate(recs)
    return success(data, "array", 200, pg)


@app.route("/pickup-requests/<rid>/stops", methods=["GET"])
def list_request_stops(rid):
    check_auth(READ_ROLES)
    get_or_404("requests", rid)
    recs = [s for s in db["stops"].values() if s["request_id"] == rid]
    data, pg = paginate(recs, kind="stop")
    return success(data, "array", 200, pg)


@app.route("/pickup-requests/<rid>/haul-invoices", methods=["GET"])
def list_request_invoices(rid):
    check_auth(READ_ROLES)
    get_or_404("requests", rid)
    recs = [inv for inv in db["invoices"].values() if inv["request_id"] == rid]
    data, pg = paginate(recs)
    return success(data, "array", 200, pg)


@app.route("/pickup-requests/<rid>/schedule", methods=["POST"])
def schedule_request(rid):
    check_auth({"Dispatcher"})
    req = get_or_404("requests", rid)  # priority 3 path existence
    body = get_body()
    route = body_ref("routes", body.get("route_id"))  # priority 5 body existence
    if route is None:
        bad("route_id is required")
    # priority 6: transition legality
    if req["status"] != "REQUESTED":
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409, "request is not REQUESTED")
    # priority 7: cross-entity gate
    if route["status"] != "OPEN":
        raise ApiError("ERR_ROUTE_NOT_OPEN", 409, "route is not OPEN")
    partner = db["partners"].get(req["partner_id"])
    vehicle = db["vehicles"].get(route["vehicle_id"])
    items = request_items(req["id"])
    # 8: at least one item
    if len(items) < 1:
        raise ApiError("ERR_NO_ITEMS", 422, "request has no donation items")
    # 9: porch attestation for UNATTENDED
    if req["pickup_mode"] == "UNATTENDED":
        if not req.get("porch_photo_url") or req.get("safety_attestation") is not True:
            raise ApiError("ERR_PORCH_ATTESTATION_REQUIRED", 422, "porch photo and safety attestation required")
    # 10: donation categories accepted
    if req["disposition"] == "DONATION":
        accepted = set(partner["accepted_categories"]) if partner else set()
        if any(it["category"] not in accepted for it in items):
            raise ApiError("ERR_CATEGORY_NOT_ACCEPTED", 422, "item category not accepted by partner")
    # 11: donation volume cap
    if req["disposition"] == "DONATION" and req["declared_volume_cf"] > DONATION_MAX_CF:
        raise ApiError("ERR_DONATION_OVER_LIMIT", 422, "donation exceeds volume cap")
    # 12: slot within window
    slot_start_raw = body.get("slot_start")
    slot_end_raw = body.get("slot_end")
    if not isinstance(slot_start_raw, str) or not isinstance(slot_end_raw, str):
        bad("slot_start and slot_end are required")
    slot_start = parse_dt(slot_start_raw)
    slot_end = parse_dt(slot_end_raw)
    win_start = parse_dt(route["window_start"])
    win_end = parse_dt(route["window_end"])
    if not (slot_start >= win_start and slot_end <= win_end and slot_end > slot_start):
        raise ApiError("ERR_SLOT_OUTSIDE_WINDOW", 422, "slot outside route window")
    # 13: buffer conflict
    buf = timedelta(minutes=TRAVEL_BUFFER_MIN)
    for s in db["stops"].values():
        if s["route_id"] != route["id"] or s["status"] not in ("RESERVED", "SERVICED"):
            continue
        es = parse_dt(s["slot_start"]) - buf
        ee = parse_dt(s["slot_end"]) + buf
        if slot_start < ee and es < slot_end:
            raise ApiError("ERR_STOP_SLOT_CONFLICT", 409, "slot conflicts with an adjacent stop")
    # 14: capacity
    if route["reserved_volume_cf"] + req["declared_volume_cf"] > vehicle["capacity_cf"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED", 409, "route capacity exceeded")
    # 15: OCC
    expected = body.get("expected_route_version")
    if expected != route["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_route_version does not match")
    # --- side effects ---
    stop = new_record({
        "route_id": route["id"],
        "request_id": req["id"],
        "slot_start": slot_start_raw,
        "slot_end": slot_end_raw,
        "reserved_volume_cf": req["declared_volume_cf"],
        "status": "RESERVED",
    })
    db["stops"][stop["id"]] = stop
    recompute_route(route)
    touch(route)
    req["status"] = "SCHEDULED"
    touch(req)
    return success(public(stop, "stop"), "object", 201)


@app.route("/pickup-requests/<rid>/complete", methods=["POST"])
def complete_request(rid):
    check_auth({"Driver"})
    req = get_or_404("requests", rid)
    if req["status"] != "SCHEDULED":
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409, "request is not SCHEDULED")
    body = get_body()
    measured = req_int(body, "measured_volume_cf", minimum=0)
    req["measured_volume_cf"] = measured
    req["status"] = "COMPLETED"
    touch(req)
    stop = request_stop(req["id"])
    if stop is not None and stop["status"] == "RESERVED":
        stop["status"] = "SERVICED"
        touch(stop)
        route = db["routes"].get(stop["route_id"])
        if route is not None:
            recompute_route(route)
            touch(route)
    partner = db["partners"].get(req["partner_id"])
    if req["disposition"] == "DONATION":
        items = request_items(req["id"])
        provisional = tax_receipt_value(items, use_appraised=False)
        final = tax_receipt_value(items, use_appraised=True)
        receipt = new_record({
            "request_id": req["id"],
            "partner_id": req["partner_id"],
            "receipt_number": "RCPT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10)),
            "provisional_value_cents": provisional,
            "final_value_cents": final,
            "issued_at": iso_ms(clock_now()),
            "status": "ISSUED",
        })
        db["receipts"][receipt["id"]] = receipt
        if partner is not None:
            recompute_partner(partner)
            touch(partner)
    else:  # HAUL
        final_cents, credit, amount_due = haul_final(req)
        invoice = new_record({
            "request_id": req["id"],
            "estimate_cents": req["estimated_haul_fee_cents"],
            "final_cents": final_cents,
            "diversion_credit_cents": credit,
            "amount_due_cents": amount_due,
            "status": "INVOICED",
        })
        db["invoices"][invoice["id"]] = invoice
        if partner is not None:
            recompute_partner(partner)
            touch(partner)
    return success(public(req), "object", 200)


@app.route("/pickup-requests/<rid>/no-show", methods=["POST"])
def no_show_request(rid):
    check_auth({"Driver"})
    req = get_or_404("requests", rid)
    if req["status"] != "SCHEDULED":
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409, "request is not SCHEDULED")
    req["status"] = "NO_SHOW"
    touch(req)
    stop = request_stop(req["id"])
    if stop is not None and stop["status"] == "RESERVED":
        stop["status"] = "CANCELLED"
        touch(stop)
        route = db["routes"].get(stop["route_id"])
        if route is not None:
            recompute_route(route)
            touch(route)
    return success(public(req), "object", 200)


@app.route("/pickup-requests/<rid>/cancel", methods=["POST"])
def cancel_request(rid):
    uid, role = check_auth({"Donor"})
    req = get_or_404("requests", rid)
    if uid != req["donor_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning donor")
    if req["status"] not in ("REQUESTED", "SCHEDULED"):
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409, "request cannot be cancelled")
    was_scheduled = req["status"] == "SCHEDULED"
    req["status"] = "CANCELLED"
    touch(req)
    if was_scheduled:
        stop = request_stop(req["id"])
        if stop is not None and stop["status"] == "RESERVED":
            stop["status"] = "CANCELLED"
            touch(stop)
            route = db["routes"].get(stop["route_id"])
            if route is not None:
                recompute_route(route)
                touch(route)
    return success(public(req), "object", 200)


# ---- DonationItem appraisal ------------------------------------------------
@app.route("/donation-items/<iid>", methods=["PATCH"])
def appraise_item(iid):
    check_auth({"Driver"})
    item = get_or_404("items", iid)
    req = db["requests"].get(item["request_id"])
    if req is None or req["status"] != "SCHEDULED":
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409, "item's request is not SCHEDULED")
    body = get_body()
    changed = False
    if "appraised_value_cents" in body and body.get("appraised_value_cents") is not None:
        v = body.get("appraised_value_cents")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            bad("appraised_value_cents must be an integer >= 0")
        item["appraised_value_cents"] = v
        changed = True
    if "appraised_condition" in body and body.get("appraised_condition") is not None:
        item["appraised_condition"] = req_enum(body, "appraised_condition", CONDITIONS)
        changed = True
    if "weight_lbs" in body and body.get("weight_lbs") is not None:
        w = body.get("weight_lbs")
        if isinstance(w, bool) or not isinstance(w, int) or w < 0:
            bad("weight_lbs must be an integer >= 0")
        item["weight_lbs"] = w
        changed = True
    if "stream" in body and body.get("stream") is not None:
        item["stream"] = req_enum(body, "stream", STREAMS)
        changed = True
    if changed:
        touch(item)
    return success(public(item), "object", 200)


# ---- DonationReceipt -------------------------------------------------------
@app.route("/donation-receipts/<rcid>", methods=["GET"])
def get_receipt(rcid):
    check_auth(READ_ROLES)
    rec = get_or_404("receipts", rcid)
    return success(public(rec), "object", 200)


@app.route("/donation-receipts", methods=["GET"])
def list_receipts():
    check_auth(READ_ROLES)
    recs = list(db["receipts"].values())
    for key in ("request_id", "partner_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r.get(key) == val]
    data, pg = paginate(recs)
    return success(data, "array", 200, pg)


@app.route("/donation-receipts/<rcid>/void", methods=["POST"])
def void_receipt(rcid):
    uid, role = check_auth({"PartnerAdmin"})
    receipt = get_or_404("receipts", rcid)
    if uid != receipt["partner_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning partner admin")
    if receipt["status"] != "ISSUED":
        raise ApiError("ERR_RECEIPT_NOT_VOIDABLE", 409, "receipt is not ISSUED")
    receipt["status"] = "VOIDED"
    touch(receipt)
    partner = db["partners"].get(receipt["partner_id"])
    if partner is not None:
        recompute_partner(partner)
        touch(partner)
    return success(public(receipt), "object", 200)


# ---- HaulInvoice -----------------------------------------------------------
@app.route("/haul-invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    uid, role = check_auth({"Donor"})
    invoice = get_or_404("invoices", iid)
    req = db["requests"].get(invoice["request_id"])
    if req is None or uid != req["donor_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning donor")
    if invoice["status"] != "INVOICED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", 409, "invoice is not INVOICED")
    invoice["status"] = "PAID"
    touch(invoice)
    return success(public(invoice), "object", 200)


# ---- RecurringPlan ---------------------------------------------------------
@app.route("/recurring-plans", methods=["POST"])
def create_plan():
    uid, role = check_auth({"Donor"})
    body = get_body()
    donor_id = body.get("donor_id")
    if donor_id is not None and str(donor_id) != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "donor_id must match acting donor")
    body_ref("donors", donor_id)
    body_ref("partners", body.get("partner_id"))
    if donor_id is None:
        bad("donor_id is required")
    partner_id = body.get("partner_id")
    if partner_id is None:
        bad("partner_id is required")
    pickup_mode = req_enum(body, "pickup_mode", {"ATTENDED", "UNATTENDED"})
    address = req_str(body, "address")
    default_disposition = req_enum(body, "default_disposition", {"DONATION", "HAUL"})
    frequency = req_enum(body, "frequency", {"WEEKLY", "BIWEEKLY", "MONTHLY"})
    next_date = advance_cadence(clock_now().date(), frequency)
    rec = new_record({
        "donor_id": donor_id,
        "partner_id": partner_id,
        "pickup_mode": pickup_mode,
        "address": address,
        "default_disposition": default_disposition,
        "frequency": frequency,
        "next_pickup_date": next_date.isoformat(),
        "status": "ACTIVE",
    })
    db["plans"][rec["id"]] = rec
    return success(public(rec), "object", 201)


@app.route("/recurring-plans/<pid>", methods=["GET"])
def get_plan(pid):
    check_auth(READ_ROLES)
    rec = get_or_404("plans", pid)
    return success(public(rec), "object", 200)


@app.route("/recurring-plans", methods=["GET"])
def list_plans():
    check_auth(READ_ROLES)
    recs = list(db["plans"].values())
    for key in ("donor_id", "partner_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r.get(key) == val]
    data, pg = paginate(recs)
    return success(data, "array", 200, pg)


def _plan_owner_check(plan, uid):
    if uid != plan["donor_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owning donor")


@app.route("/recurring-plans/<pid>/pause", methods=["POST"])
def pause_plan(pid):
    uid, role = check_auth({"Donor"})
    plan = get_or_404("plans", pid)
    _plan_owner_check(plan, uid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "plan is not ACTIVE")
    plan["status"] = "PAUSED"
    touch(plan)
    return success(public(plan), "object", 200)


@app.route("/recurring-plans/<pid>/resume", methods=["POST"])
def resume_plan(pid):
    uid, role = check_auth({"Donor"})
    plan = get_or_404("plans", pid)
    _plan_owner_check(plan, uid)
    if plan["status"] != "PAUSED":
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "plan is not PAUSED")
    partner = db["partners"].get(plan["partner_id"])
    if partner is None or partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_SUSPENDED", 409, "partner is suspended")
    plan["status"] = "ACTIVE"
    touch(plan)
    return success(public(plan), "object", 200)


@app.route("/recurring-plans/<pid>/cancel", methods=["POST"])
def cancel_plan(pid):
    uid, role = check_auth({"Donor"})
    plan = get_or_404("plans", pid)
    _plan_owner_check(plan, uid)
    if plan["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "plan cannot be cancelled")
    plan["status"] = "CANCELLED"
    touch(plan)
    return success(public(plan), "object", 200)


@app.route("/recurring-plans/<pid>/generate", methods=["POST"])
def generate_plan(pid):
    check_auth({"Dispatcher"})
    plan = get_or_404("plans", pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "plan is not ACTIVE")
    disposition = plan["default_disposition"]
    rec = new_record({
        "donor_id": plan["donor_id"],
        "partner_id": plan["partner_id"],
        "recurring_plan_id": plan["id"],
        "pickup_mode": plan["pickup_mode"],
        "disposition": disposition,
        "address": plan["address"],
        "porch_photo_url": None,
        "safety_attestation": False,
        "declared_volume_cf": 0,
        "measured_volume_cf": None,
        "is_free_donation": (disposition == "DONATION"),
        "estimated_haul_fee_cents": 0,
        "status": "REQUESTED",
    })
    db["requests"][rec["id"]] = rec
    cur = date.fromisoformat(plan["next_pickup_date"])
    plan["next_pickup_date"] = advance_cadence(cur, plan["frequency"]).isoformat()
    touch(plan)
    return success(public(rec), "object", 201)


# ---- Logical clock ---------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    check_auth({"PlatformAdmin"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        bad("to_iso8601 is required")
    _state["clock"] = parse_dt(to_iso)
    return success({}, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
