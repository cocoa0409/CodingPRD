import os
import math
import uuid
import random
import string
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Coordinator", "Client", "Sitter"}

SIZE_SURCHARGE = {"SMALL": 0, "MEDIUM": 1500, "LARGE": 3500}
PET_SURCHARGE = 1000
WEEKEND_MULTIPLIER = Decimal("1.25")
STANDARD_VISIT_MINUTES = 30
MIN_FACTOR = Decimal("0.5")
MAX_FACTOR = Decimal("2.0")

DISCOUNT_TIER1_MIN = 20000
DISCOUNT_TIER2_MIN = 50000
SERVICE_FEE_RATE = Decimal("0.08")
TAX_RATE = Decimal("0.07")

SEVERITY_RESERVE = {"MINOR": 50000, "MAJOR": 200000, "EMERGENCY": 500000}

MISS_PENALTY = 20
ESCALATION_PENALTY = 10
MIN_RELIABILITY = 60

FREQ_STEP = {"DAILY": 1, "WEEKLY": 7, "BIWEEKLY": 14}

SCHEDULE_BUFFER = timedelta(0)

CHECKLIST_TASKS = {"MAIL", "PLANTS", "SECURITY"}
SIZE_TIERS = {"SMALL", "MEDIUM", "LARGE"}
BILLING_TIERS = {"STANDARD", "PREMIUM"}
POLICY_TYPES = {"BOND", "LIABILITY"}
INCIDENT_CATEGORIES = {"BREAK_IN", "WATER_LEAK", "FIRE", "MEDICAL", "OTHER"}
INCIDENT_SEVERITIES = {"MINOR", "MAJOR", "EMERGENCY"}
LOG_ENTRY_TYPES = {"PHOTO", "GPS_PING", "NOTE"}

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_NOT_OWNER": 403,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_SITTER_NOT_FOUND": 404,
    "ERR_BGCHECK_NOT_FOUND": 404,
    "ERR_COVERAGE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_VISITLOG_NOT_FOUND": 404,
    "ERR_KEY_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_CHECKLIST_CONFIG_EMPTY": 422,
    "ERR_STALE_SITTER_VERSION": 412,
    "ERR_BGCHECK_NOT_PENDING": 409,
    "ERR_BOOKING_NOT_DRAFT": 409,
    "ERR_BOOKING_NOT_PENDING_ASSIGNMENT": 409,
    "ERR_BOOKING_NOT_SCHEDULED": 409,
    "ERR_BOOKING_NOT_ACTIVE": 409,
    "ERR_BOOKING_NOT_CANCELLABLE": 409,
    "ERR_BOOKING_NOT_COMPLETED": 409,
    "ERR_VISITS_NOT_RESOLVED": 409,
    "ERR_SITTER_NOT_CLEARED": 409,
    "ERR_SITTER_COVERAGE_INACTIVE": 403,
    "ERR_SITTER_RELIABILITY_TOO_LOW": 403,
    "ERR_SITTER_SCHEDULE_CONFLICT": 409,
    "ERR_PROPERTY_BOOKING_OVERLAP": 409,
    "ERR_VISIT_NOT_SCHEDULED": 409,
    "ERR_VISIT_NOT_IN_PROGRESS": 409,
    "ERR_VISIT_WINDOW_OPEN": 409,
    "ERR_OUTSIDE_GEOFENCE": 422,
    "ERR_VISIT_EVIDENCE_MISSING": 422,
    "ERR_CHECKLIST_INCOMPLETE": 422,
    "ERR_UNRESOLVED_INCIDENT": 409,
    "ERR_KEY_NOT_AT_OFFICE": 409,
    "ERR_KEY_NOT_CHECKED_OUT": 409,
    "ERR_NO_KEY_COPIES_AVAILABLE": 409,
    "ERR_KEY_NOT_READY": 409,
    "ERR_INCIDENT_NOT_OPEN": 409,
    "ERR_INCIDENT_NOT_RESOLVABLE": 409,
    "ERR_NO_LIABILITY_COVERAGE": 409,
    "ERR_INVOICE_NOT_ISSUED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clients = {}
        self.properties = {}
        self.sitters = {}
        self.background_checks = {}
        self.coverage_policies = {}
        self.bookings = {}
        self.visits = {}
        self.visit_logs = {}
        self.key_assignments = {}
        self.incidents = {}
        self.invoices = {}
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()

NOT_FOUND = {
    "clients": "ERR_CLIENT_NOT_FOUND",
    "properties": "ERR_PROPERTY_NOT_FOUND",
    "sitters": "ERR_SITTER_NOT_FOUND",
    "background_checks": "ERR_BGCHECK_NOT_FOUND",
    "coverage_policies": "ERR_COVERAGE_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "visits": "ERR_VISIT_NOT_FOUND",
    "visit_logs": "ERR_VISITLOG_NOT_FOUND",
    "key_assignments": "ERR_KEY_NOT_FOUND",
    "incidents": "ERR_INCIDENT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_dt():
    return db.clock


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def now_iso():
    return fmt_dt(now_dt())


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_entity(common=True):
    ts = now_iso()
    ent = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if common:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def touch(ent):
    ent["updated_at"] = now_iso()
    if "version" in ent:
        ent["version"] = ent["version"] + 1


def touch_no_version(ent):
    ent["updated_at"] = now_iso()


def public(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}


def respond(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def respond_obj(ent, status=200):
    return respond(public(ent), "object", status)


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    meta = meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    meta = meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "missing auth headers")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unknown role")
    g.uid = uid
    g.role = role
    return uid, role


def authorize(allowed):
    uid, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role %s not permitted" % role)
    return uid, role


def check_owner(owner_id):
    """Ownership check for entity-backed actors (Client/Sitter)."""
    if g.role in ("Client", "Sitter") and g.uid != owner_id:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", "not the owner")


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "body must be an object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "missing field: %s" % field)
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "field %s invalid" % field)
    return v


def require_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "field %s below minimum" % field)
    return v


def require_number(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be a number" % field)
    return v


def lookup(store_name, ident):
    store = getattr(db, store_name)
    if ident not in store:
        raise ApiError(NOT_FOUND[store_name], "%s not found" % store_name)
    return store[ident]


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sorted_entities(store_name, predicate=None):
    store = getattr(db, store_name)
    items = list(store.values())
    if predicate:
        items = [e for e in items if predicate(e)]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return items


def list_response(store_name, predicate=None):
    items = sorted_entities(store_name, predicate)
    page, pagination = paginate(items)
    return respond([public(e) for e in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Domain computations
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def within_geofence(lat1, lng1, lat2, lng2, radius):
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    dist = 2 * R * math.asin(min(1.0, math.sqrt(a)))
    return dist <= radius


def per_visit_charge(booking, prop, visit, final):
    size = SIZE_SURCHARGE[prop["size_tier"]]
    pet = PET_SURCHARGE if prop["has_pets"] else 0
    base_sum = booking["base_visit_rate_cents"] + size + pet
    weekend = WEEKEND_MULTIPLIER if visit["is_weekend"] else Decimal("1")
    if final:
        ci = parse_dt(visit["check_in_at"])
        co = parse_dt(visit["check_out_at"])
        seconds = (co - ci).total_seconds()
        minutes = Decimal(str(seconds)) / Decimal("60")
        factor = minutes / Decimal(str(STANDARD_VISIT_MINUTES))
        if factor < MIN_FACTOR:
            factor = MIN_FACTOR
        if factor > MAX_FACTOR:
            factor = MAX_FACTOR
    else:
        factor = Decimal("1")
    val = Decimal(base_sum) * weekend * factor
    return round_half_up(val)


def recompute_invoice(booking):
    invoice = invoice_for_booking(booking["id"])
    if invoice is None:
        return
    done = [
        v for v in db.visits.values()
        if v["booking_id"] == booking["id"] and v["status"] == "DONE"
    ]
    use_final = booking["status"] == "COMPLETED"
    subtotal = 0
    for v in done:
        if use_final and v.get("final_charge_cents") is not None:
            subtotal += v["final_charge_cents"]
        else:
            subtotal += v["provisional_charge_cents"]
    if subtotal >= DISCOUNT_TIER2_MIN:
        rate = Decimal("0.10")
    elif subtotal >= DISCOUNT_TIER1_MIN:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.00")
    discount = round_half_up(Decimal(subtotal) * rate)
    discounted_base = subtotal - discount
    service_fee = round_half_up(Decimal(discounted_base) * SERVICE_FEE_RATE)
    tax = round_half_up((Decimal(discounted_base) + Decimal(service_fee)) * TAX_RATE)
    total = discounted_base + service_fee + tax

    invoice["billed_visit_count"] = len(done)
    invoice["subtotal_cents"] = subtotal
    invoice["discount_cents"] = discount
    invoice["service_fee_cents"] = service_fee
    invoice["tax_cents"] = tax
    invoice["total_cents"] = total
    touch(invoice)


def invoice_for_booking(booking_id):
    for inv in db.invoices.values():
        if inv["booking_id"] == booking_id:
            return inv
    return None


def recompute_reliability(sitter):
    score = 100 - MISS_PENALTY * sitter["missed_visit_count"] - ESCALATION_PENALTY * sitter["escalated_incident_count"]
    if score < 0:
        score = 0
    sitter["reliability_score"] = score
    if score < MIN_RELIABILITY:
        sitter["status"] = "SUSPENDED"


def latest_bgcheck(sitter_id):
    checks = [c for c in db.background_checks.values() if c["sitter_id"] == sitter_id]
    if not checks:
        return None
    checks.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return checks[-1]


def active_policy(sitter_id, policy_type):
    for p in db.coverage_policies.values():
        if p["sitter_id"] == sitter_id and p["policy_type"] == policy_type and p["status"] == "ACTIVE":
            return p
    return None


def visit_windows_for_booking(booking):
    dates = visit_dates_for_booking(booking)
    windows = []
    for d in dates:
        start = datetime(d.year, d.month, d.day, 9, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=STANDARD_VISIT_MINUTES)
        windows.append((start, end))
    return windows


def visit_dates_for_booking(booking):
    d0 = parse_dt(booking["start_date"]).date()
    dN = parse_dt(booking["end_date"]).date()
    dates = []
    if booking["booking_type"] == "VACATION":
        n = (dN - d0).days
        if n < 0:
            return []
        for i in range(n + 1):
            dates.append(d0 + timedelta(days=i))
    else:
        step = FREQ_STEP[booking["frequency"]]
        cur = d0
        while cur <= dN:
            dates.append(cur)
            cur = cur + timedelta(days=step)
    return dates


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize({"Coordinator"})
    body = get_body()
    iso = require(body, "to_iso8601")
    db.clock = parse_dt(iso)
    return respond({}, "object", 200)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@app.route("/home-watch/clients", methods=["POST"])
def create_client():
    authorize({"Coordinator"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    billing_tier = body.get("billing_tier", "STANDARD")
    if billing_tier is None:
        billing_tier = "STANDARD"
    if billing_tier not in BILLING_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid billing_tier")
    ent = base_entity()
    ent.update({
        "full_name": full_name,
        "email": email,
        "billing_tier": billing_tier,
        "status": "ACTIVE",
    })
    db.clients[ent["id"]] = ent
    return respond_obj(ent, 201)


@app.route("/home-watch/clients", methods=["GET"])
def list_clients():
    authorize({"Coordinator", "Client", "Sitter"})
    return list_response("clients")


@app.route("/home-watch/clients/<cid>", methods=["GET"])
def get_client(cid):
    authorize({"Coordinator", "Client", "Sitter"})
    return respond_obj(lookup("clients", cid))


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
@app.route("/home-watch/properties", methods=["POST"])
def create_property():
    authorize({"Coordinator", "Client"})
    body = get_body()
    client_id = body.get("client_id")
    if client_id is not None:
        lookup("clients", client_id)
        check_owner(client_id)
    client_id = require_str(body, "client_id")
    label = require_str(body, "label")
    address = require_str(body, "address")
    size_tier = require_enum(body, "size_tier", SIZE_TIERS)
    has_pets = body.get("has_pets", False)
    if has_pets is None:
        has_pets = False
    if not isinstance(has_pets, bool):
        raise ApiError("ERR_INVALID_REQUEST", "has_pets must be boolean")
    checklist = require(body, "checklist_config")
    if (not isinstance(checklist, list) or len(checklist) == 0
            or any(t not in CHECKLIST_TASKS for t in checklist)):
        raise ApiError("ERR_INVALID_REQUEST", "invalid checklist_config")
    center_lat = require_number(body, "center_lat")
    center_lng = require_number(body, "center_lng")
    geofence = body.get("geofence_radius_m", 150)
    if geofence is None:
        geofence = 150
    if isinstance(geofence, bool) or not isinstance(geofence, int):
        raise ApiError("ERR_INVALID_REQUEST", "geofence_radius_m must be an integer")
    key_copies_total = require_int(body, "key_copies_total", minimum=1)

    ent = base_entity()
    ent.update({
        "client_id": client_id,
        "label": label,
        "address": address,
        "size_tier": size_tier,
        "has_pets": has_pets,
        "checklist_config": list(checklist),
        "center_lat": center_lat,
        "center_lng": center_lng,
        "geofence_radius_m": geofence,
        "key_copies_total": key_copies_total,
        "available_key_copies": key_copies_total,
    })
    db.properties[ent["id"]] = ent
    return respond_obj(ent, 201)


@app.route("/home-watch/properties", methods=["GET"])
def list_properties():
    authorize({"Coordinator", "Client", "Sitter"})
    client_id = request.args.get("client_id")
    pred = None
    if client_id is not None:
        pred = lambda e: e["client_id"] == client_id
    return list_response("properties", pred)


@app.route("/home-watch/properties/<pid>", methods=["GET"])
def get_property(pid):
    authorize({"Coordinator", "Client", "Sitter"})
    return respond_obj(lookup("properties", pid))


# ---------------------------------------------------------------------------
# Sitters
# ---------------------------------------------------------------------------
@app.route("/home-watch/sitters", methods=["POST"])
def create_sitter():
    authorize({"Coordinator"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    ent = base_entity()
    ent.update({
        "full_name": full_name,
        "email": email,
        "background_check_status": "NONE",
        "missed_visit_count": 0,
        "escalated_incident_count": 0,
        "reliability_score": 100,
        "status": "ONBOARDING",
    })
    db.sitters[ent["id"]] = ent
    return respond_obj(ent, 201)


@app.route("/home-watch/sitters", methods=["GET"])
def list_sitters():
    authorize({"Coordinator", "Client", "Sitter"})
    return list_response("sitters")


@app.route("/home-watch/sitters/<sid>", methods=["GET"])
def get_sitter(sid):
    authorize({"Coordinator", "Client", "Sitter"})
    return respond_obj(lookup("sitters", sid))


# ---------------------------------------------------------------------------
# Background checks
# ---------------------------------------------------------------------------
@app.route("/home-watch/background-checks", methods=["POST"])
def create_bgcheck():
    authorize({"Coordinator"})
    body = get_body()
    sitter_id = body.get("sitter_id")
    if sitter_id is not None:
        lookup("sitters", sitter_id)
    sitter_id = require_str(body, "sitter_id")
    provider_ref = require_str(body, "provider_ref")
    expires_at = require(body, "expires_at")
    parse_dt(expires_at)
    sitter = db.sitters[sitter_id]
    ent = base_entity()
    ent.update({
        "sitter_id": sitter_id,
        "provider_ref": provider_ref,
        "expires_at": expires_at,
        "cleared_at": None,
        "status": "SUBMITTED",
    })
    db.background_checks[ent["id"]] = ent
    sitter["background_check_status"] = "SUBMITTED"
    touch(sitter)
    return respond_obj(ent, 201)


@app.route("/home-watch/background-checks/<bid>/decide", methods=["POST"])
def decide_bgcheck(bid):
    authorize({"Coordinator"})
    check = lookup("background_checks", bid)
    body = get_body()
    decision = require_enum(body, "decision", {"CLEARED", "REJECTED"})
    if check["status"] != "SUBMITTED":
        raise ApiError("ERR_BGCHECK_NOT_PENDING", "check not pending")
    sitter = db.sitters[check["sitter_id"]]
    if decision == "CLEARED":
        check["status"] = "CLEARED"
        check["cleared_at"] = now_iso()
        touch(check)
        sitter["background_check_status"] = "CLEARED"
        if sitter["status"] == "ONBOARDING":
            sitter["status"] = "ACTIVE"
        touch(sitter)
    else:
        check["status"] = "REJECTED"
        touch(check)
        sitter["background_check_status"] = "REJECTED"
        touch(sitter)
    return respond_obj(check)


@app.route("/home-watch/background-checks", methods=["GET"])
def list_bgchecks():
    authorize({"Coordinator", "Sitter"})
    sitter_id = request.args.get("sitter_id")
    pred = None
    if sitter_id is not None:
        pred = lambda e: e["sitter_id"] == sitter_id
    return list_response("background_checks", pred)


@app.route("/home-watch/background-checks/<bid>", methods=["GET"])
def get_bgcheck(bid):
    authorize({"Coordinator", "Sitter"})
    return respond_obj(lookup("background_checks", bid))


# ---------------------------------------------------------------------------
# Coverage policies
# ---------------------------------------------------------------------------
@app.route("/home-watch/coverage-policies", methods=["POST"])
def create_coverage():
    authorize({"Coordinator"})
    body = get_body()
    sitter_id = body.get("sitter_id")
    if sitter_id is not None:
        lookup("sitters", sitter_id)
    sitter_id = require_str(body, "sitter_id")
    policy_type = require_enum(body, "policy_type", POLICY_TYPES)
    coverage_amount = require_int(body, "coverage_amount_cents", minimum=1)
    effective_from = require(body, "effective_from")
    parse_dt(effective_from)
    expires_at = require(body, "expires_at")
    parse_dt(expires_at)
    expected_version = require_int(body, "expected_sitter_version")

    sitter = db.sitters[sitter_id]
    if expected_version != sitter["version"]:
        raise ApiError("ERR_STALE_SITTER_VERSION", "stale sitter version")

    # Supersede prior ACTIVE same-type policy
    prior = active_policy(sitter_id, policy_type)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    ent = base_entity()
    ent.update({
        "sitter_id": sitter_id,
        "policy_type": policy_type,
        "coverage_amount_cents": coverage_amount,
        "effective_from": effective_from,
        "expires_at": expires_at,
        "reserved_exposure_cents": 0,
        "paid_out_cents": 0,
        "status": "ACTIVE",
    })
    db.coverage_policies[ent["id"]] = ent
    touch(sitter)  # increments sitter.version by 1
    return respond_obj(ent, 201)


@app.route("/home-watch/coverage-policies", methods=["GET"])
def list_coverage():
    authorize({"Coordinator", "Sitter"})
    sitter_id = request.args.get("sitter_id")
    pred = None
    if sitter_id is not None:
        pred = lambda e: e["sitter_id"] == sitter_id
    return list_response("coverage_policies", pred)


@app.route("/home-watch/coverage-policies/<cid>", methods=["GET"])
def get_coverage(cid):
    authorize({"Coordinator", "Sitter"})
    return respond_obj(lookup("coverage_policies", cid))


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------
@app.route("/home-watch/bookings", methods=["POST"])
def create_booking():
    authorize({"Coordinator", "Client"})
    body = get_body()
    property_id = body.get("property_id")
    if property_id is not None:
        prop = lookup("properties", property_id)
        check_owner(prop["client_id"])
    property_id = require_str(body, "property_id")
    prop = db.properties[property_id]
    booking_type = require_enum(body, "booking_type", {"RECURRING", "VACATION"})
    frequency = body.get("frequency")
    if booking_type == "RECURRING":
        frequency = require_enum(body, "frequency", set(FREQ_STEP.keys()))
    else:
        if frequency is not None:
            raise ApiError("ERR_INVALID_REQUEST", "VACATION booking must omit frequency")
    start_date = require(body, "start_date")
    parse_dt(start_date)
    end_date = require(body, "end_date")
    parse_dt(end_date)
    base_rate = require_int(body, "base_visit_rate_cents", minimum=0)

    ent = base_entity()
    ent.update({
        "property_id": property_id,
        "client_id": prop["client_id"],
        "sitter_id": None,
        "booking_type": booking_type,
        "frequency": frequency if booking_type == "RECURRING" else None,
        "start_date": start_date,
        "end_date": end_date,
        "base_visit_rate_cents": base_rate,
        "status": "DRAFT",
    })
    db.bookings[ent["id"]] = ent
    return respond_obj(ent, 201)


@app.route("/home-watch/bookings", methods=["GET"])
def list_bookings():
    authorize({"Coordinator", "Client", "Sitter"})
    args = request.args

    def pred(e):
        for f in ("property_id", "client_id", "sitter_id", "status"):
            if f in args and e.get(f) != args.get(f):
                return False
        return True
    return list_response("bookings", pred)


@app.route("/home-watch/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    authorize({"Coordinator", "Client", "Sitter"})
    return respond_obj(lookup("bookings", bid))


@app.route("/home-watch/bookings/<bid>/submit", methods=["POST"])
def submit_booking(bid):
    authorize({"Coordinator", "Client"})
    booking = lookup("bookings", bid)
    check_owner(booking["client_id"])
    if booking["status"] != "DRAFT":
        raise ApiError("ERR_BOOKING_NOT_DRAFT", "booking not in DRAFT")
    prop = db.properties[booking["property_id"]]
    if not prop["checklist_config"]:
        raise ApiError("ERR_CHECKLIST_CONFIG_EMPTY", "empty checklist")
    if booking["booking_type"] == "VACATION":
        s0 = parse_dt(booking["start_date"]).date()
        e0 = parse_dt(booking["end_date"]).date()
        for other in db.bookings.values():
            if other["id"] == booking["id"]:
                continue
            if other["property_id"] != booking["property_id"]:
                continue
            if other["booking_type"] != "VACATION":
                continue
            if other["status"] not in ("PENDING_ASSIGNMENT", "SCHEDULED", "ACTIVE"):
                continue
            os = parse_dt(other["start_date"]).date()
            oe = parse_dt(other["end_date"]).date()
            if s0 <= oe and os <= e0:
                raise ApiError("ERR_PROPERTY_BOOKING_OVERLAP", "overlapping vacation booking")
    booking["status"] = "PENDING_ASSIGNMENT"
    touch(booking)
    return respond_obj(booking)


@app.route("/home-watch/bookings/<bid>/assign", methods=["POST"])
def assign_booking(bid):
    authorize({"Coordinator"})
    booking = lookup("bookings", bid)
    body = get_body()
    sitter_id = body.get("sitter_id")
    if sitter_id is not None:
        lookup("sitters", sitter_id)
    sitter_id = require_str(body, "sitter_id")
    sitter = db.sitters[sitter_id]

    if booking["status"] != "PENDING_ASSIGNMENT":
        raise ApiError("ERR_BOOKING_NOT_PENDING_ASSIGNMENT", "booking not pending assignment")

    # 1. Clearance
    check = latest_bgcheck(sitter_id)
    if check is None or check["status"] != "CLEARED" or now_dt() >= parse_dt(check["expires_at"]):
        raise ApiError("ERR_SITTER_NOT_CLEARED", "sitter not cleared")

    # 2. Bond (ACTIVE, in-window)
    bond = active_policy(sitter_id, "BOND")
    if bond is None or not (parse_dt(bond["effective_from"]) <= now_dt() < parse_dt(bond["expires_at"])):
        raise ApiError("ERR_SITTER_COVERAGE_INACTIVE", "no active bond coverage")

    # 3. Reliability
    if sitter["reliability_score"] < MIN_RELIABILITY:
        raise ApiError("ERR_SITTER_RELIABILITY_TOO_LOW", "reliability too low")

    # 4. Schedule conflict
    prospective = visit_windows_for_booking(booking)
    existing = [
        v for v in db.visits.values()
        if v["sitter_id"] == sitter_id and v["status"] in ("SCHEDULED", "IN_PROGRESS")
    ]
    for (ps, pe) in prospective:
        for ev in existing:
            es = parse_dt(ev["scheduled_start"])
            ee = parse_dt(ev["scheduled_end"])
            if ps < ee + SCHEDULE_BUFFER and es < pe + SCHEDULE_BUFFER:
                raise ApiError("ERR_SITTER_SCHEDULE_CONFLICT", "schedule conflict")

    # Commit
    booking["sitter_id"] = sitter_id
    booking["status"] = "SCHEDULED"
    touch(booking)

    for d in visit_dates_for_booking(booking):
        start = datetime(d.year, d.month, d.day, 9, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=STANDARD_VISIT_MINUTES)
        v = base_entity()
        v.update({
            "booking_id": booking["id"],
            "sitter_id": sitter_id,
            "property_id": booking["property_id"],
            "scheduled_start": fmt_dt(start),
            "scheduled_end": fmt_dt(end),
            "check_in_at": None,
            "check_out_at": None,
            "completed_tasks": [],
            "is_weekend": start.weekday() in (5, 6),
            "provisional_charge_cents": 0,
            "final_charge_cents": None,
            "status": "SCHEDULED",
        })
        db.visits[v["id"]] = v

    inv = base_entity()
    inv.update({
        "booking_id": booking["id"],
        "client_id": booking["client_id"],
        "billed_visit_count": 0,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "service_fee_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
    })
    db.invoices[inv["id"]] = inv

    return respond_obj(booking)


@app.route("/home-watch/bookings/<bid>/unassign", methods=["POST"])
def unassign_booking(bid):
    authorize({"Coordinator"})
    booking = lookup("bookings", bid)
    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_BOOKING_NOT_SCHEDULED", "booking not scheduled")
    for v in db.visits.values():
        if v["booking_id"] == booking["id"] and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            touch(v)
    inv = invoice_for_booking(booking["id"])
    if inv is not None:
        inv["status"] = "VOID"
        touch(inv)
    booking["sitter_id"] = None
    booking["status"] = "PENDING_ASSIGNMENT"
    touch(booking)
    return respond_obj(booking)


@app.route("/home-watch/bookings/<bid>/activate", methods=["POST"])
def activate_booking(bid):
    authorize({"Coordinator"})
    booking = lookup("bookings", bid)
    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_BOOKING_NOT_SCHEDULED", "booking not scheduled")
    has_key = any(
        k["booking_id"] == booking["id"] and k["sitter_id"] == booking["sitter_id"]
        and k["status"] == "CHECKED_OUT"
        for k in db.key_assignments.values()
    )
    if not has_key:
        raise ApiError("ERR_KEY_NOT_READY", "no checked-out key")
    inv = invoice_for_booking(booking["id"])
    if inv is not None:
        inv["status"] = "ISSUED"
        touch(inv)
    booking["status"] = "ACTIVE"
    touch(booking)
    return respond_obj(booking)


@app.route("/home-watch/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    authorize({"Coordinator"})
    booking = lookup("bookings", bid)
    if booking["status"] != "ACTIVE":
        raise ApiError("ERR_BOOKING_NOT_ACTIVE", "booking not active")
    visits = [v for v in db.visits.values() if v["booking_id"] == booking["id"]]
    for v in visits:
        if v["status"] not in ("DONE", "MISSED", "CANCELLED"):
            raise ApiError("ERR_VISITS_NOT_RESOLVED", "some visit not resolved")
    prop = db.properties[booking["property_id"]]
    booking["status"] = "COMPLETED"
    touch(booking)
    for v in visits:
        if v["status"] == "DONE":
            v["final_charge_cents"] = per_visit_charge(booking, prop, v, final=True)
            touch(v)
    recompute_invoice(booking)
    return respond_obj(booking)


@app.route("/home-watch/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    authorize({"Coordinator", "Client"})
    booking = lookup("bookings", bid)
    check_owner(booking["client_id"])
    if booking["status"] not in ("DRAFT", "PENDING_ASSIGNMENT", "SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_BOOKING_NOT_CANCELLABLE", "booking not cancellable")
    cascade = booking["status"] in ("SCHEDULED", "ACTIVE")
    booking["status"] = "CANCELLED"
    touch(booking)
    if cascade:
        for v in db.visits.values():
            if v["booking_id"] == booking["id"] and v["status"] in (
                    "SCHEDULED", "IN_PROGRESS", "FLAGGED", "DONE"):
                v["status"] = "CANCELLED"
                touch(v)
        recompute_invoice(booking)
        inv = invoice_for_booking(booking["id"])
        if inv is not None:
            inv["status"] = "VOID"
            touch(inv)
        for k in db.key_assignments.values():
            if k["booking_id"] == booking["id"] and k["status"] == "CHECKED_OUT":
                k["status"] = "RETURNED"
                k["returned_at"] = now_iso()
                touch(k)
                prop = db.properties.get(k["property_id"])
                if prop is not None:
                    prop["available_key_copies"] += 1
                    touch(prop)
    return respond_obj(booking)


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------
@app.route("/home-watch/visits", methods=["GET"])
def list_visits():
    authorize({"Coordinator", "Client", "Sitter"})
    args = request.args

    def pred(e):
        for f in ("booking_id", "property_id", "sitter_id", "status"):
            if f in args and e.get(f) != args.get(f):
                return False
        return True
    return list_response("visits", pred)


@app.route("/home-watch/visits/<vid>", methods=["GET"])
def get_visit(vid):
    authorize({"Coordinator", "Client", "Sitter"})
    return respond_obj(lookup("visits", vid))


@app.route("/home-watch/visits/<vid>/check-in", methods=["POST"])
def visit_check_in(vid):
    authorize({"Sitter"})
    visit = lookup("visits", vid)
    check_owner(visit["sitter_id"])
    body = get_body()
    gps_lat = require_number(body, "gps_lat")
    gps_lng = require_number(body, "gps_lng")
    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_NOT_SCHEDULED", "visit not scheduled")
    booking = db.bookings[visit["booking_id"]]
    if booking["status"] != "ACTIVE":
        raise ApiError("ERR_BOOKING_NOT_ACTIVE", "booking not active")
    prop = db.properties[visit["property_id"]]
    if not within_geofence(gps_lat, gps_lng, prop["center_lat"], prop["center_lng"], prop["geofence_radius_m"]):
        raise ApiError("ERR_OUTSIDE_GEOFENCE", "outside geofence")
    has_key = any(
        k["booking_id"] == booking["id"] and k["sitter_id"] == visit["sitter_id"]
        and k["status"] == "CHECKED_OUT"
        for k in db.key_assignments.values()
    )
    if not has_key:
        raise ApiError("ERR_KEY_NOT_CHECKED_OUT", "no checked-out key")
    visit["status"] = "IN_PROGRESS"
    visit["check_in_at"] = now_iso()
    touch(visit)
    return respond_obj(visit)


@app.route("/home-watch/visits/<vid>/check-out", methods=["POST"])
def visit_check_out(vid):
    authorize({"Sitter"})
    visit = lookup("visits", vid)
    check_owner(visit["sitter_id"])
    body = get_body()
    completed = require(body, "completed_tasks")
    if not isinstance(completed, list):
        raise ApiError("ERR_INVALID_REQUEST", "completed_tasks must be a list")
    if visit["status"] not in ("IN_PROGRESS", "FLAGGED"):
        raise ApiError("ERR_VISIT_NOT_IN_PROGRESS", "visit not in progress")
    if visit["status"] == "FLAGGED":
        for inc in db.incidents.values():
            if inc["visit_id"] == visit["id"] and inc["status"] != "RESOLVED":
                raise ApiError("ERR_UNRESOLVED_INCIDENT", "unresolved incident")
    evidence = any(le["visit_id"] == visit["id"] for le in db.visit_logs.values())
    if not evidence:
        raise ApiError("ERR_VISIT_EVIDENCE_MISSING", "no evidence")
    prop = db.properties[visit["property_id"]]
    if set(completed) != set(prop["checklist_config"]):
        raise ApiError("ERR_CHECKLIST_INCOMPLETE", "checklist incomplete")

    booking = db.bookings[visit["booking_id"]]
    visit["status"] = "DONE"
    visit["check_out_at"] = now_iso()
    visit["completed_tasks"] = list(completed)
    visit["provisional_charge_cents"] = per_visit_charge(booking, prop, visit, final=False)
    touch(visit)
    recompute_invoice(booking)
    return respond_obj(visit)


@app.route("/home-watch/visits/<vid>/mark-missed", methods=["POST"])
def visit_mark_missed(vid):
    authorize({"Coordinator"})
    visit = lookup("visits", vid)
    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_NOT_SCHEDULED", "visit not scheduled")
    if now_dt() < parse_dt(visit["scheduled_end"]):
        raise ApiError("ERR_VISIT_WINDOW_OPEN", "visit window still open")
    visit["status"] = "MISSED"
    touch(visit)
    sitter = db.sitters.get(visit["sitter_id"])
    if sitter is not None:
        sitter["missed_visit_count"] += 1
        recompute_reliability(sitter)
        touch(sitter)
    return respond_obj(visit)


# ---------------------------------------------------------------------------
# Visit log entries
# ---------------------------------------------------------------------------
@app.route("/home-watch/visit-logs", methods=["POST"])
def create_visit_log():
    authorize({"Sitter"})
    body = get_body()
    visit_id = body.get("visit_id")
    if visit_id is not None:
        visit = lookup("visits", visit_id)
        check_owner(visit["sitter_id"])
    visit_id = require_str(body, "visit_id")
    visit = db.visits[visit_id]
    entry_type = require_enum(body, "entry_type", LOG_ENTRY_TYPES)
    gps_lat = require_number(body, "gps_lat")
    gps_lng = require_number(body, "gps_lng")
    captured_at = require(body, "captured_at")
    parse_dt(captured_at)
    photo_url = body.get("photo_url")
    if visit["status"] not in ("IN_PROGRESS", "FLAGGED"):
        raise ApiError("ERR_VISIT_NOT_IN_PROGRESS", "visit not in progress")
    ent = base_entity(common=False)
    ent.update({
        "visit_id": visit_id,
        "entry_type": entry_type,
        "photo_url": photo_url if entry_type == "PHOTO" else None,
        "gps_lat": gps_lat,
        "gps_lng": gps_lng,
        "captured_at": captured_at,
    })
    db.visit_logs[ent["id"]] = ent
    return respond_obj(ent, 201)


@app.route("/home-watch/visit-logs", methods=["GET"])
def list_visit_logs():
    authorize({"Coordinator", "Client", "Sitter"})
    visit_id = request.args.get("visit_id")
    pred = None
    if visit_id is not None:
        pred = lambda e: e["visit_id"] == visit_id
    return list_response("visit_logs", pred)


@app.route("/home-watch/visit-logs/<lid>", methods=["GET"])
def get_visit_log(lid):
    authorize({"Coordinator", "Client", "Sitter"})
    return respond_obj(lookup("visit_logs", lid))


# ---------------------------------------------------------------------------
# Key assignments
# ---------------------------------------------------------------------------
@app.route("/home-watch/key-assignments", methods=["POST"])
def create_key_assignment():
    authorize({"Coordinator"})
    body = get_body()
    property_id = body.get("property_id")
    if property_id is not None:
        lookup("properties", property_id)
    sitter_id = body.get("sitter_id")
    if sitter_id is not None:
        lookup("sitters", sitter_id)
    booking_id = body.get("booking_id")
    if booking_id is not None:
        lookup("bookings", booking_id)
    property_id = require_str(body, "property_id")
    sitter_id = require_str(body, "sitter_id")
    booking_id = require_str(body, "booking_id")
    ent = base_entity()
    ent.update({
        "property_id": property_id,
        "sitter_id": sitter_id,
        "booking_id": booking_id,
        "checked_out_at": None,
        "returned_at": None,
        "status": "AT_OFFICE",
    })
    db.key_assignments[ent["id"]] = ent
    return respond_obj(ent, 201)


@app.route("/home-watch/key-assignments/<kid>/check-out", methods=["POST"])
def key_check_out(kid):
    authorize({"Coordinator", "Sitter"})
    key = lookup("key_assignments", kid)
    check_owner(key["sitter_id"])
    if key["status"] != "AT_OFFICE":
        raise ApiError("ERR_KEY_NOT_AT_OFFICE", "key not at office")
    prop = db.properties[key["property_id"]]
    if prop["available_key_copies"] < 1:
        raise ApiError("ERR_NO_KEY_COPIES_AVAILABLE", "no key copies available")
    key["status"] = "CHECKED_OUT"
    key["checked_out_at"] = now_iso()
    touch(key)
    prop["available_key_copies"] -= 1
    touch(prop)
    return respond_obj(key)


@app.route("/home-watch/key-assignments/<kid>/return", methods=["POST"])
def key_return(kid):
    authorize({"Coordinator", "Sitter"})
    key = lookup("key_assignments", kid)
    check_owner(key["sitter_id"])
    if key["status"] != "CHECKED_OUT":
        raise ApiError("ERR_KEY_NOT_CHECKED_OUT", "key not checked out")
    key["status"] = "RETURNED"
    key["returned_at"] = now_iso()
    touch(key)
    prop = db.properties[key["property_id"]]
    prop["available_key_copies"] += 1
    touch(prop)
    return respond_obj(key)


@app.route("/home-watch/key-assignments/<kid>/report-lost", methods=["POST"])
def key_report_lost(kid):
    authorize({"Coordinator"})
    key = lookup("key_assignments", kid)
    if key["status"] != "CHECKED_OUT":
        raise ApiError("ERR_KEY_NOT_CHECKED_OUT", "key not checked out")
    key["status"] = "LOST"
    touch(key)
    return respond_obj(key)


@app.route("/home-watch/key-assignments", methods=["GET"])
def list_key_assignments():
    authorize({"Coordinator", "Sitter"})
    args = request.args

    def pred(e):
        for f in ("property_id", "sitter_id", "booking_id"):
            if f in args and e.get(f) != args.get(f):
                return False
        return True
    return list_response("key_assignments", pred)


@app.route("/home-watch/key-assignments/<kid>", methods=["GET"])
def get_key_assignment(kid):
    authorize({"Coordinator", "Sitter"})
    return respond_obj(lookup("key_assignments", kid))


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
@app.route("/home-watch/incidents", methods=["POST"])
def create_incident():
    authorize({"Sitter"})
    body = get_body()
    visit_id = body.get("visit_id")
    if visit_id is not None:
        visit = lookup("visits", visit_id)
        check_owner(visit["sitter_id"])
    visit_id = require_str(body, "visit_id")
    visit = db.visits[visit_id]
    category = require_enum(body, "category", INCIDENT_CATEGORIES)
    severity = require_enum(body, "severity", INCIDENT_SEVERITIES)
    if visit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_VISIT_NOT_IN_PROGRESS", "visit not in progress")
    ent = base_entity()
    ent.update({
        "visit_id": visit_id,
        "booking_id": visit["booking_id"],
        "reported_by_sitter_id": g.uid,
        "category": category,
        "severity": severity,
        "assessed_damage_cents": None,
        "estimated_exposure_cents": 0,
        "settled_payout_cents": None,
        "status": "OPEN",
    })
    db.incidents[ent["id"]] = ent
    visit["status"] = "FLAGGED"
    touch(visit)
    return respond_obj(ent, 201)


@app.route("/home-watch/incidents/<iid>/escalate", methods=["POST"])
def escalate_incident(iid):
    authorize({"Coordinator"})
    incident = lookup("incidents", iid)
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INCIDENT_NOT_OPEN", "incident not open")
    policy = active_policy(incident["reported_by_sitter_id"], "LIABILITY")
    if policy is None:
        raise ApiError("ERR_NO_LIABILITY_COVERAGE", "no active liability coverage")
    exposure = min(policy["coverage_amount_cents"], SEVERITY_RESERVE[incident["severity"]])
    incident["estimated_exposure_cents"] = exposure
    incident["_policy_id"] = policy["id"]
    incident["status"] = "ESCALATED"
    touch(incident)
    policy["reserved_exposure_cents"] += exposure
    touch(policy)
    sitter = db.sitters.get(incident["reported_by_sitter_id"])
    if sitter is not None:
        sitter["escalated_incident_count"] += 1
        recompute_reliability(sitter)
        touch(sitter)
    return respond_obj(incident)


@app.route("/home-watch/incidents/<iid>/resolve", methods=["POST"])
def resolve_incident(iid):
    authorize({"Coordinator"})
    incident = lookup("incidents", iid)
    body = get_body()
    assessed = require(body, "assessed_damage_cents")
    if isinstance(assessed, bool) or not isinstance(assessed, int) or assessed < 0:
        raise ApiError("ERR_INVALID_REQUEST", "assessed_damage_cents must be >= 0")
    if incident["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INCIDENT_NOT_RESOLVABLE", "incident not resolvable")

    was_escalated = incident["status"] == "ESCALATED"
    policy = None
    if incident.get("_policy_id"):
        policy = db.coverage_policies.get(incident["_policy_id"])
    if policy is None:
        policy = active_policy(incident["reported_by_sitter_id"], "LIABILITY")

    if policy is not None:
        settled = min(assessed, policy["coverage_amount_cents"])
    else:
        settled = assessed

    incident["assessed_damage_cents"] = assessed
    incident["settled_payout_cents"] = settled
    incident["status"] = "RESOLVED"
    touch(incident)

    if was_escalated and policy is not None:
        policy["reserved_exposure_cents"] -= incident["estimated_exposure_cents"]
        policy["paid_out_cents"] += settled
        if policy["paid_out_cents"] >= policy["coverage_amount_cents"]:
            policy["status"] = "EXHAUSTED"
            sitter = db.sitters.get(incident["reported_by_sitter_id"])
            if sitter is not None:
                sitter["status"] = "SUSPENDED"
                touch(sitter)
        touch(policy)
    return respond_obj(incident)


@app.route("/home-watch/incidents", methods=["GET"])
def list_incidents():
    authorize({"Coordinator", "Client", "Sitter"})
    args = request.args

    def pred(e):
        for f in ("visit_id", "booking_id", "reported_by_sitter_id"):
            if f in args and e.get(f) != args.get(f):
                return False
        return True
    return list_response("incidents", pred)


@app.route("/home-watch/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    authorize({"Coordinator", "Client", "Sitter"})
    return respond_obj(lookup("incidents", iid))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@app.route("/home-watch/invoices", methods=["GET"])
def list_invoices():
    authorize({"Coordinator", "Client"})
    args = request.args

    def pred(e):
        for f in ("booking_id", "client_id"):
            if f in args and e.get(f) != args.get(f):
                return False
        return True
    return list_response("invoices", pred)


@app.route("/home-watch/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    authorize({"Coordinator", "Client"})
    return respond_obj(lookup("invoices", iid))


@app.route("/home-watch/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    authorize({"Coordinator", "Client"})
    invoice = lookup("invoices", iid)
    check_owner(invoice["client_id"])
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_ISSUED", "invoice not issued")
    booking = db.bookings.get(invoice["booking_id"])
    if booking is None or booking["status"] != "COMPLETED":
        raise ApiError("ERR_BOOKING_NOT_COMPLETED", "booking not completed")
    invoice["status"] = "PAID"
    touch(invoice)
    return respond_obj(invoice)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
