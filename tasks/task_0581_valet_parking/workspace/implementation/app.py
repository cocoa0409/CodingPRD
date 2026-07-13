import os
import math
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
LIABILITY_SUSPEND_THRESHOLD = 10000   # cents
SHIFT_REST_BUFFER_SECONDS = 30 * 60   # 30 minutes
ROLES = {"Attendant", "Cashier", "Supervisor"}

DEFAULTS_EVENT = {
    "free_grace_minutes": 15,
    "hourly_rate_cents": 800,
    "daily_max_cents": 2500,
    "event_surcharge_cents": 500,
    "overflow_surcharge_cents": 700,
    "tip_split_mode": "EQUAL",
}

# =============================================================================
# Error catalog
# =============================================================================
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_VALIDATION": 400,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_ATTENDANT_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_RETRIEVAL_NOT_FOUND": 404,
    "ERR_VALIDATION_GRANT_NOT_FOUND": 404,
    "ERR_DAMAGE_CLAIM_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_LANE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_EVENT_NOT_ACTIVE": 409,
    "ERR_EVENT_NOT_CLOSABLE": 409,
    "ERR_TICKET_NOT_PARKED": 409,
    "ERR_CLAIM_NOT_OPEN": 409,
    "ERR_CLAIM_NOT_APPROVED": 409,
    "ERR_RETRIEVAL_BAD_STATE": 409,
    "ERR_SHIFT_NOT_ACTIVE": 409,
    "ERR_REPORT_ALREADY_FINALIZED": 409,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_CHECKIN_OUTSIDE_EVENT_WINDOW": 422,
    "ERR_OPEN_DAMAGE_CLAIM": 409,
    "ERR_ATTENDANT_SHIFT_INACTIVE": 409,
    "ERR_LANE_WINDOW_CONFLICT": 409,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_KEY_TAG_IN_USE": 409,
    "ERR_LOT_AT_CAPACITY": 409,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_VALIDATION_NOT_APPLICABLE": 409,
    "ERR_GRANT_ALREADY_REVERSED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").title()


def err(error_id, message=None):
    raise ApiError(error_id, message)


# =============================================================================
# In-memory store  (empty on every boot — no seeding)
# =============================================================================
db = {
    "venues": {},
    "events": {},
    "lots": {},
    "lane_assignments": {},
    "attendants": {},
    "shifts": {},
    "tickets": {},
    "retrieval_requests": {},
    "validation_grants": {},
    "damage_claims": {},
    "reconciliation_reports": {},
}

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# =============================================================================
# Helpers: time, ids, envelope
# =============================================================================
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_dt(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    iso = s
    if iso.endswith("Z") or iso.endswith("z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d"):
            try:
                dt = datetime.strptime(iso, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError("unparseable timestamp: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def make_meta(pagination=None):
    meta = {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    return meta


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def respond(data, response_type="object", status=200, pagination=None):
    body = {"meta": make_meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def respond_object(entity, status=200):
    return respond(public(entity), "object", status)


def respond_list(entities, pagination):
    return respond([public(e) for e in entities], "array", 200, pagination)


# =============================================================================
# Entity creation / mutation
# =============================================================================
def new_entity(collection, fields):
    now = now_iso()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    entity.update(fields)
    db[collection][entity["id"]] = entity
    return entity


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# =============================================================================
# Field validation helpers
# =============================================================================
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def req_str(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", "Field %s must be a non-empty string." % field)
    return v


def req_int(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if not is_int(v):
        err("ERR_VALIDATION", "Field %s must be an integer." % field)
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_int(v):
        err("ERR_VALIDATION", "Field %s must be an integer." % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        err("ERR_VALIDATION", "Field %s must be a string." % field)
    return v


def req_ts_temporal(body, field):
    """Required timestamp on a temporal endpoint -> ERR_INVALID_TIME_WINDOW on absence/malformed."""
    if field not in body or body[field] is None:
        err("ERR_INVALID_TIME_WINDOW", "Missing required timestamp: %s" % field)
    try:
        return parse_dt(body[field]), body[field]
    except ValueError:
        err("ERR_INVALID_TIME_WINDOW", "Malformed timestamp: %s" % field)


def req_ts_valid(body, field):
    """Required timestamp validated as a field -> ERR_VALIDATION on absence/malformed."""
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", "Missing required field: %s" % field)
    try:
        return parse_dt(body[field]), body[field]
    except ValueError:
        err("ERR_VALIDATION", "Malformed timestamp: %s" % field)


# =============================================================================
# Existence helpers
# =============================================================================
_NOT_FOUND = {
    "venues": "ERR_VENUE_NOT_FOUND",
    "events": "ERR_EVENT_NOT_FOUND",
    "lots": "ERR_LOT_NOT_FOUND",
    "attendants": "ERR_ATTENDANT_NOT_FOUND",
    "shifts": "ERR_SHIFT_NOT_FOUND",
    "tickets": "ERR_TICKET_NOT_FOUND",
    "retrieval_requests": "ERR_RETRIEVAL_NOT_FOUND",
    "validation_grants": "ERR_VALIDATION_GRANT_NOT_FOUND",
    "damage_claims": "ERR_DAMAGE_CLAIM_NOT_FOUND",
    "reconciliation_reports": "ERR_REPORT_NOT_FOUND",
    "lane_assignments": "ERR_LANE_ASSIGNMENT_NOT_FOUND",
}


def must_get(collection, entity_id):
    ent = db[collection].get(entity_id)
    if ent is None:
        err(_NOT_FOUND[collection])
    return ent


# =============================================================================
# Auth / RBAC
# =============================================================================
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED")
    return user_id, role


def endpoint(*allowed_roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed_roles:
                err("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# =============================================================================
# Pagination
# =============================================================================
def paginate(items):
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pg = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pg


def collection_sorted(collection, predicate=None):
    items = [e for e in db[collection].values() if (predicate is None or predicate(e))]
    items.sort(key=lambda e: e["_seq"])
    return items


# =============================================================================
# Calculations
# =============================================================================
def parking_fee(start_dt, end_dt, event, in_overflow):
    total_seconds = (end_dt - start_dt).total_seconds()
    secs = int(round(total_seconds))
    if secs <= event["free_grace_minutes"] * 60:
        return 0
    hours = (secs + 3599) // 3600  # ceil to next whole hour
    metered = min(hours * event["hourly_rate_cents"], event["daily_max_cents"])
    fee = metered + event["event_surcharge_cents"]
    if in_overflow:
        fee += event["overflow_surcharge_cents"]
    return int(fee)


def recompute_net_charge(ticket):
    base = ticket["final_fee_cents"]
    if base is None:
        ticket["net_charge_cents"] = None
        return
    net = Decimal(int(base))
    grants = [gr for gr in db["validation_grants"].values()
              if gr["ticket_id"] == ticket["id"] and gr["status"] == "APPLIED"]
    grants.sort(key=lambda gr: gr["_seq"])
    for gr in grants:
        if gr["grant_type"] == "FULL_COMP":
            net = Decimal(0)
        elif gr["grant_type"] == "FLAT":
            net = net - Decimal(int(gr["value"]))
            if net < 0:
                net = Decimal(0)
        elif gr["grant_type"] == "PERCENT":
            net = (net * Decimal(100 - int(gr["value"])) / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
    ticket["net_charge_cents"] = int(net)


def distribute_tip_pool(event):
    shifts = collection_sorted("shifts", lambda s: s["event_id"] == event["id"])
    n = len(shifts)
    if n == 0:
        return
    pool = sum(s["declared_tips_cents"] for s in shifts)
    if event["tip_split_mode"] == "WEIGHTED":
        secs = []
        for s in shifts:
            dur = (parse_dt(s["end_at"]) - parse_dt(s["start_at"])).total_seconds()
            secs.append(int(round(dur)))
        total_secs = sum(secs)
        if total_secs <= 0:
            base = [pool // n for _ in shifts]
        else:
            base = [(pool * secs[i]) // total_secs for i in range(n)]
    else:  # EQUAL
        base = [pool // n for _ in shifts]
    remainder = pool - sum(base)
    for i in range(remainder):
        base[i % n] += 1
    for i, s in enumerate(shifts):
        s["allocated_tip_cents"] = int(base[i])
        touch(s)


def compute_report_figures(report, event):
    tickets = [t for t in db["tickets"].values() if t["event_id"] == event["id"]]
    settled = [t for t in tickets if t["settlement_status"] == "SETTLED"]
    expected = sum((t["net_charge_cents"] or 0) for t in settled)
    overflow_total = sum(event["overflow_surcharge_cents"] for t in settled if t["in_overflow"])
    ticket_ids = {t["id"] for t in tickets}
    liability = sum(
        c["approved_liability_cents"] or 0
        for c in db["damage_claims"].values()
        if c["ticket_id"] in ticket_ids and c["status"] in ("APPROVED", "SETTLED")
    )
    report["expected_revenue_cents"] = int(expected)
    report["overflow_surcharge_total_cents"] = int(overflow_total)
    report["liability_adjustment_cents"] = int(liability)


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    data = {"error_id": e.error_id, "message": e.message}
    return respond(data, "error", e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return respond({"error_id": "ERR_VALIDATION", "message": "Not found."}, "error", 404)


@app.errorhandler(405)
def handle_405(e):
    return respond({"error_id": "ERR_VALIDATION", "message": "Method not allowed."}, "error", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return respond({"error_id": "ERR_VALIDATION", "message": str(e)}, "error", 500)


# =============================================================================
# Venues
# =============================================================================
@app.route("/valet/venues", methods=["POST"])
@endpoint("Supervisor")
def create_venue():
    b = body_json()
    name = req_str(b, "name")
    address = req_str(b, "address")
    currency = opt_str(b, "currency", "USD")
    v = new_entity("venues", {"name": name, "address": address, "currency": currency})
    return respond_object(v, 201)


@app.route("/valet/venues/<vid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_venue(vid):
    return respond_object(must_get("venues", vid))


# =============================================================================
# Events
# =============================================================================
@app.route("/valet/events", methods=["POST"])
@endpoint("Supervisor")
def create_event():
    b = body_json()
    name = req_str(b, "name")
    venue_id = req_str(b, "venue_id")
    must_get("venues", venue_id)
    ws_dt, ws = req_ts_temporal(b, "window_start")
    we_dt, we = req_ts_temporal(b, "window_end")
    if we_dt <= ws_dt:
        err("ERR_INVALID_TIME_WINDOW", "window_end must be strictly after window_start.")
    fields = {
        "venue_id": venue_id,
        "name": name,
        "status": "SCHEDULED",
        "window_start": ws,
        "window_end": we,
        "free_grace_minutes": opt_int(b, "free_grace_minutes", DEFAULTS_EVENT["free_grace_minutes"]),
        "hourly_rate_cents": opt_int(b, "hourly_rate_cents", DEFAULTS_EVENT["hourly_rate_cents"]),
        "daily_max_cents": opt_int(b, "daily_max_cents", DEFAULTS_EVENT["daily_max_cents"]),
        "event_surcharge_cents": opt_int(b, "event_surcharge_cents", DEFAULTS_EVENT["event_surcharge_cents"]),
        "overflow_surcharge_cents": opt_int(b, "overflow_surcharge_cents", DEFAULTS_EVENT["overflow_surcharge_cents"]),
        "tip_split_mode": opt_str(b, "tip_split_mode", DEFAULTS_EVENT["tip_split_mode"]),
    }
    if fields["tip_split_mode"] not in ("EQUAL", "WEIGHTED"):
        err("ERR_VALIDATION", "tip_split_mode must be EQUAL or WEIGHTED.")
    e = new_entity("events", fields)
    return respond_object(e, 201)


@app.route("/valet/events/<eid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_event(eid):
    return respond_object(must_get("events", eid))


@app.route("/valet/events", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_events():
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")

    def pred(e):
        if venue_id is not None and e["venue_id"] != venue_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    items, pg = paginate(collection_sorted("events", pred))
    return respond_list(items, pg)


@app.route("/valet/events/<eid>/activate", methods=["POST"])
@endpoint("Supervisor")
def activate_event(eid):
    e = must_get("events", eid)
    if e["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Event must be SCHEDULED to activate.")
    e["status"] = "ACTIVE"
    touch(e)
    return respond_object(e)


@app.route("/valet/events/<eid>/close", methods=["POST"])
@endpoint("Supervisor")
def close_event(eid):
    e = must_get("events", eid)
    if e["status"] != "ACTIVE":
        err("ERR_EVENT_NOT_CLOSABLE", "Event must be ACTIVE to close.")
    for t in db["tickets"].values():
        if t["event_id"] == eid and t["park_status"] in ("PARKED", "RETRIEVED"):
            err("ERR_EVENT_NOT_CLOSABLE", "Tickets are still on the floor.")
    distribute_tip_pool(e)
    e["status"] = "CLOSED"
    touch(e)
    return respond_object(e)


# =============================================================================
# Lots
# =============================================================================
@app.route("/valet/lots", methods=["POST"])
@endpoint("Supervisor")
def create_lot():
    b = body_json()
    venue_id = req_str(b, "venue_id")
    name = req_str(b, "name")
    capacity = req_int(b, "capacity")
    must_get("venues", venue_id)
    if capacity < 1:
        err("ERR_VALIDATION", "capacity must be >= 1.")
    overflow_lot_id = opt_str(b, "overflow_lot_id", None)
    if overflow_lot_id is not None:
        must_get("lots", overflow_lot_id)
    is_overflow = b.get("is_overflow", False)
    if not isinstance(is_overflow, bool):
        err("ERR_VALIDATION", "is_overflow must be a boolean.")
    lot = new_entity("lots", {
        "venue_id": venue_id,
        "name": name,
        "capacity": capacity,
        "occupied_count": 0,
        "overflow_lot_id": overflow_lot_id,
        "is_overflow": is_overflow,
        "overflow_active": False,
    })
    return respond_object(lot, 201)


@app.route("/valet/lots/<lid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_lot(lid):
    return respond_object(must_get("lots", lid))


@app.route("/valet/lots", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_lots():
    venue_id = request.args.get("venue_id")
    overflow_lot_id = request.args.get("overflow_lot_id")

    def pred(l):
        if venue_id is not None and l["venue_id"] != venue_id:
            return False
        if overflow_lot_id is not None and l["overflow_lot_id"] != overflow_lot_id:
            return False
        return True

    items, pg = paginate(collection_sorted("lots", pred))
    return respond_list(items, pg)


# =============================================================================
# Lane assignments
# =============================================================================
@app.route("/valet/lane-assignments", methods=["POST"])
@endpoint("Supervisor")
def create_lane_assignment():
    b = body_json()
    venue_id = req_str(b, "venue_id")
    event_id = req_str(b, "event_id")
    lane_code = req_str(b, "lane_code")
    must_get("venues", venue_id)
    must_get("events", event_id)
    ws_dt, ws = req_ts_temporal(b, "window_start")
    we_dt, we = req_ts_temporal(b, "window_end")
    if we_dt <= ws_dt:
        err("ERR_INVALID_TIME_WINDOW", "window_end must be strictly after window_start.")
    for la in db["lane_assignments"].values():
        if la["venue_id"] == venue_id and la["lane_code"] == lane_code:
            e_start = parse_dt(la["window_start"])
            e_end = parse_dt(la["window_end"])
            if ws_dt < e_end and e_start < we_dt:  # half-open overlap
                err("ERR_LANE_WINDOW_CONFLICT", "Lane window overlaps an existing reservation.")
    la = new_entity("lane_assignments", {
        "venue_id": venue_id,
        "event_id": event_id,
        "lane_code": lane_code,
        "window_start": ws,
        "window_end": we,
    })
    return respond_object(la, 201)


@app.route("/valet/lane-assignments/<lid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_lane_assignment(lid):
    return respond_object(must_get("lane_assignments", lid))


@app.route("/valet/lane-assignments", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_lane_assignments():
    venue_id = request.args.get("venue_id")
    event_id = request.args.get("event_id")

    def pred(la):
        if venue_id is not None and la["venue_id"] != venue_id:
            return False
        if event_id is not None and la["event_id"] != event_id:
            return False
        return True

    items, pg = paginate(collection_sorted("lane_assignments", pred))
    return respond_list(items, pg)


# =============================================================================
# Attendants
# =============================================================================
@app.route("/valet/attendants", methods=["POST"])
@endpoint("Supervisor")
def create_attendant():
    b = body_json()
    venue_id = req_str(b, "venue_id")
    name = req_str(b, "name")
    must_get("venues", venue_id)
    a = new_entity("attendants", {
        "venue_id": venue_id,
        "name": name,
        "status": "ACTIVE",
        "total_liability_cents": 0,
    })
    return respond_object(a, 201)


@app.route("/valet/attendants/<aid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_attendant(aid):
    return respond_object(must_get("attendants", aid))


@app.route("/valet/attendants", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_attendants():
    venue_id = request.args.get("venue_id")

    def pred(a):
        if venue_id is not None and a["venue_id"] != venue_id:
            return False
        return True

    items, pg = paginate(collection_sorted("attendants", pred))
    return respond_list(items, pg)


# =============================================================================
# Shifts
# =============================================================================
@app.route("/valet/shifts", methods=["POST"])
@endpoint("Supervisor")
def create_shift():
    b = body_json()
    attendant_id = req_str(b, "attendant_id")
    must_get("attendants", attendant_id)
    event_id = opt_str(b, "event_id", None)
    if event_id is not None:
        must_get("events", event_id)
    sa_dt, sa = req_ts_temporal(b, "start_at")
    ea_dt, ea = req_ts_temporal(b, "end_at")
    if ea_dt <= sa_dt:
        err("ERR_INVALID_TIME_WINDOW", "end_at must be strictly after start_at.")
    for s in db["shifts"].values():
        if s["attendant_id"] != attendant_id:
            continue
        e_start = parse_dt(s["start_at"])
        e_end = parse_dt(s["end_at"])
        # conflict when overlapping OR gap smaller than the rest buffer
        if (sa_dt.timestamp() < e_end.timestamp() + SHIFT_REST_BUFFER_SECONDS and
                e_start.timestamp() < ea_dt.timestamp() + SHIFT_REST_BUFFER_SECONDS):
            err("ERR_SHIFT_OVERLAP", "Shift overlaps or violates the rest buffer.")
    s = new_entity("shifts", {
        "attendant_id": attendant_id,
        "event_id": event_id,
        "start_at": sa,
        "end_at": ea,
        "status": "SCHEDULED",
        "declared_tips_cents": 0,
        "allocated_tip_cents": 0,
        "liability_holdback_cents": 0,
    })
    return respond_object(s, 201)


@app.route("/valet/shifts/<sid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_shift(sid):
    return respond_object(must_get("shifts", sid))


@app.route("/valet/shifts", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_shifts():
    attendant_id = request.args.get("attendant_id")
    event_id = request.args.get("event_id")

    def pred(s):
        if attendant_id is not None and s["attendant_id"] != attendant_id:
            return False
        if event_id is not None and s["event_id"] != event_id:
            return False
        return True

    items, pg = paginate(collection_sorted("shifts", pred))
    return respond_list(items, pg)


@app.route("/valet/shifts/<sid>/start", methods=["POST"])
@endpoint("Supervisor")
def start_shift(sid):
    s = must_get("shifts", sid)
    if s["status"] != "SCHEDULED":
        err("ERR_SHIFT_NOT_ACTIVE", "Shift must be SCHEDULED to start.")
    s["status"] = "ACTIVE"
    touch(s)
    return respond_object(s)


@app.route("/valet/shifts/<sid>/close", methods=["POST"])
@endpoint("Supervisor")
def close_shift(sid):
    s = must_get("shifts", sid)
    if s["status"] != "ACTIVE":
        err("ERR_SHIFT_NOT_ACTIVE", "Shift must be ACTIVE to close.")
    s["status"] = "CLOSED"
    touch(s)
    return respond_object(s)


@app.route("/valet/shifts/<sid>/tips", methods=["POST"])
@endpoint("Attendant")
def record_tips(sid):
    s = must_get("shifts", sid)
    if g.user_id != s["attendant_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "Attendant may only record tips into their own shift.")
    b = body_json()
    declared = req_int(b, "declared_tips_cents")
    s["declared_tips_cents"] = declared
    touch(s)
    return respond_object(s)


# =============================================================================
# Tickets
# =============================================================================
@app.route("/valet/tickets", methods=["POST"])
@endpoint("Attendant")
def create_ticket():
    b = body_json()
    event_id = req_str(b, "event_id")
    lot_id = req_str(b, "lot_id")
    attendant_id = req_str(b, "attendant_id")
    license_plate = req_str(b, "license_plate")
    key_tag = req_str(b, "key_tag")
    checkin_dt, checkin_at = req_ts_valid(b, "checkin_at")
    est_dt, est_at = req_ts_valid(b, "estimated_departure_at")
    expected_lot_version = req_int(b, "expected_lot_version")

    # existence (left to right)
    event = must_get("events", event_id)
    primary = must_get("lots", lot_id)
    must_get("attendants", attendant_id)

    # state: event ACTIVE
    if event["status"] != "ACTIVE":
        err("ERR_EVENT_NOT_ACTIVE", "Check-in requires an ACTIVE event.")

    # check-in window
    ws = parse_dt(event["window_start"])
    we = parse_dt(event["window_end"])
    if not (checkin_dt >= ws and checkin_dt < we):
        err("ERR_CHECKIN_OUTSIDE_EVENT_WINDOW", "checkin_at outside the event window.")

    # key_tag uniqueness among non-CLOSED tickets of the event
    for t in db["tickets"].values():
        if t["event_id"] == event_id and t["key_tag"] == key_tag and t["park_status"] != "CLOSED":
            err("ERR_KEY_TAG_IN_USE", "key_tag already held by an open ticket of this event.")

    # capacity / overflow placement
    in_overflow = False
    assigned = primary
    if primary["occupied_count"] >= primary["capacity"]:
        if primary["overflow_lot_id"] is not None:
            assigned = must_get("lots", primary["overflow_lot_id"])
            in_overflow = True
        else:
            err("ERR_LOT_AT_CAPACITY", "Primary lot is full and no overflow is configured.")

    # optimistic concurrency on the primary lot
    if expected_lot_version != primary["version"]:
        err("ERR_STALE_LOT_VERSION", "expected_lot_version does not match the primary lot version.")

    # compute quoted fee
    quoted = parking_fee(checkin_dt, est_dt, event, in_overflow)

    ticket = new_entity("tickets", {
        "event_id": event_id,
        "lot_id": assigned["id"],
        "attendant_id": attendant_id,
        "license_plate": license_plate,
        "key_tag": key_tag,
        "checkin_at": checkin_at,
        "estimated_departure_at": est_at,
        "checkout_at": None,
        "park_status": "PARKED",
        "settlement_status": "UNSETTLED",
        "in_overflow": in_overflow,
        "quoted_fee_cents": quoted,
        "final_fee_cents": None,
        "net_charge_cents": None,
        "_primary_lot_id": primary["id"],
    })

    # occupancy + version reconciliation
    assigned["occupied_count"] += 1
    touch(assigned)
    if in_overflow:
        if not primary["overflow_active"]:
            primary["overflow_active"] = True
        touch(primary)  # increments primary lot version by 1

    return respond_object(ticket, 201)


@app.route("/valet/tickets/<tid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_ticket(tid):
    return respond_object(must_get("tickets", tid))


@app.route("/valet/tickets", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_tickets():
    event_id = request.args.get("event_id")
    lot_id = request.args.get("lot_id")
    attendant_id = request.args.get("attendant_id")
    park_status = request.args.get("park_status")
    settlement_status = request.args.get("settlement_status")

    def pred(t):
        if event_id is not None and t["event_id"] != event_id:
            return False
        if lot_id is not None and t["lot_id"] != lot_id:
            return False
        if attendant_id is not None and t["attendant_id"] != attendant_id:
            return False
        if park_status is not None and t["park_status"] != park_status:
            return False
        if settlement_status is not None and t["settlement_status"] != settlement_status:
            return False
        return True

    items, pg = paginate(collection_sorted("tickets", pred))
    return respond_list(items, pg)


@app.route("/valet/tickets/<tid>/checkout", methods=["POST"])
@endpoint("Cashier")
def checkout_ticket(tid):
    ticket = must_get("tickets", tid)
    if ticket["park_status"] not in ("PARKED", "RETRIEVED"):
        err("ERR_INVALID_STATE", "Ticket must be PARKED or RETRIEVED to check out.")
    b = body_json()
    checkout_dt, checkout_at = req_ts_temporal(b, "checkout_at")
    checkin_dt = parse_dt(ticket["checkin_at"])
    if checkout_dt < checkin_dt:
        err("ERR_INVALID_TIME_WINDOW", "checkout_at must be at or after checkin_at.")
    for c in db["damage_claims"].values():
        if c["ticket_id"] == tid and c["status"] == "OPEN":
            err("ERR_OPEN_DAMAGE_CLAIM", "Ticket has an OPEN damage claim.")

    event = db["events"][ticket["event_id"]]
    final_fee = parking_fee(checkin_dt, checkout_dt, event, ticket["in_overflow"])
    ticket["final_fee_cents"] = final_fee
    recompute_net_charge(ticket)
    ticket["park_status"] = "CLOSED"
    ticket["settlement_status"] = "SETTLED"
    ticket["checkout_at"] = checkout_at
    touch(ticket)

    lot = db["lots"].get(ticket["lot_id"])
    if lot is not None:
        if lot["occupied_count"] > 0:
            lot["occupied_count"] -= 1
        touch(lot)
        if ticket["in_overflow"] and lot["occupied_count"] == 0:
            primary = db["lots"].get(ticket.get("_primary_lot_id"))
            if primary is not None and primary["overflow_active"]:
                primary["overflow_active"] = False
                touch(primary)

    return respond_object(ticket)


@app.route("/valet/tickets/<tid>/validations", methods=["POST"])
@endpoint("Cashier")
def apply_validation(tid):
    ticket = must_get("tickets", tid)
    b = body_json()
    grant_type = req_str(b, "grant_type")
    if grant_type not in ("PERCENT", "FLAT", "FULL_COMP"):
        err("ERR_VALIDATION", "grant_type must be PERCENT, FLAT, or FULL_COMP.")
    if ticket["settlement_status"] == "DISPUTED":
        err("ERR_VALIDATION_NOT_APPLICABLE", "Ticket is DISPUTED; validations are not applicable.")
    value = opt_int(b, "value", 0)
    if grant_type == "FULL_COMP":
        value = 0
    grant = new_entity("validation_grants", {
        "ticket_id": tid,
        "grant_type": grant_type,
        "value": value,
        "status": "APPLIED",
    })
    recompute_net_charge(ticket)
    touch(ticket)
    return respond_object(grant, 201)


# =============================================================================
# Validation grants
# =============================================================================
@app.route("/valet/validation-grants/<gid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_validation_grant(gid):
    return respond_object(must_get("validation_grants", gid))


@app.route("/valet/validation-grants", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_validation_grants():
    ticket_id = request.args.get("ticket_id")

    def pred(gr):
        if ticket_id is not None and gr["ticket_id"] != ticket_id:
            return False
        return True

    items, pg = paginate(collection_sorted("validation_grants", pred))
    return respond_list(items, pg)


@app.route("/valet/validation-grants/<gid>/reverse", methods=["POST"])
@endpoint("Cashier")
def reverse_validation_grant(gid):
    grant = must_get("validation_grants", gid)
    if grant["status"] == "REVERSED":
        err("ERR_GRANT_ALREADY_REVERSED", "Grant is already reversed.")
    ticket = db["tickets"].get(grant["ticket_id"])
    if ticket is not None and ticket["settlement_status"] == "DISPUTED":
        err("ERR_VALIDATION_NOT_APPLICABLE", "Ticket is DISPUTED; validations are not applicable.")
    grant["status"] = "REVERSED"
    touch(grant)
    if ticket is not None:
        recompute_net_charge(ticket)
        touch(ticket)
    return respond_object(grant)


# =============================================================================
# Retrieval requests
# =============================================================================
@app.route("/valet/retrieval-requests", methods=["POST"])
@endpoint("Attendant")
def create_retrieval_request():
    b = body_json()
    ticket_id = req_str(b, "ticket_id")
    requested_dt, requested_at = req_ts_valid(b, "requested_at")
    ticket = must_get("tickets", ticket_id)
    if ticket["park_status"] != "PARKED":
        err("ERR_TICKET_NOT_PARKED", "Retrieval may only be opened for a PARKED ticket.")
    r = new_entity("retrieval_requests", {
        "ticket_id": ticket_id,
        "attendant_id": None,
        "status": "REQUESTED",
        "requested_at": requested_at,
        "ready_at": None,
    })
    return respond_object(r, 201)


@app.route("/valet/retrieval-requests/<rid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_retrieval_request(rid):
    return respond_object(must_get("retrieval_requests", rid))


@app.route("/valet/retrieval-requests", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_retrieval_requests():
    ticket_id = request.args.get("ticket_id")
    attendant_id = request.args.get("attendant_id")
    status = request.args.get("status")

    def pred(r):
        if ticket_id is not None and r["ticket_id"] != ticket_id:
            return False
        if attendant_id is not None and r["attendant_id"] != attendant_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    items, pg = paginate(collection_sorted("retrieval_requests", pred))
    return respond_list(items, pg)


@app.route("/valet/retrieval-requests/<rid>/assign", methods=["POST"])
@endpoint("Attendant")
def assign_retrieval(rid):
    r = must_get("retrieval_requests", rid)
    b = body_json()
    attendant_id = req_str(b, "attendant_id")
    attendant = must_get("attendants", attendant_id)
    if r["status"] != "REQUESTED":
        err("ERR_RETRIEVAL_BAD_STATE", "Assign requires REQUESTED status.")
    has_active = any(
        s["attendant_id"] == attendant_id and s["status"] == "ACTIVE"
        for s in db["shifts"].values()
    )
    if not has_active:
        err("ERR_ATTENDANT_SHIFT_INACTIVE", "Assigned attendant has no ACTIVE shift.")
    r["attendant_id"] = attendant_id
    r["status"] = "ASSIGNED"
    touch(r)
    return respond_object(r)


@app.route("/valet/retrieval-requests/<rid>/stage", methods=["POST"])
@endpoint("Attendant")
def stage_retrieval(rid):
    r = must_get("retrieval_requests", rid)
    if r["status"] != "ASSIGNED":
        err("ERR_RETRIEVAL_BAD_STATE", "Stage requires ASSIGNED status.")
    r["status"] = "STAGING"
    touch(r)
    return respond_object(r)


@app.route("/valet/retrieval-requests/<rid>/ready", methods=["POST"])
@endpoint("Attendant")
def ready_retrieval(rid):
    r = must_get("retrieval_requests", rid)
    if r["status"] != "STAGING":
        err("ERR_RETRIEVAL_BAD_STATE", "Ready requires STAGING status.")
    b = body_json()
    ready_dt, ready_at = req_ts_temporal(b, "ready_at")
    ticket = db["tickets"].get(r["ticket_id"])
    if ticket is None or ticket["park_status"] != "PARKED":
        err("ERR_TICKET_NOT_PARKED", "Ticket is no longer PARKED.")
    r["status"] = "READY"
    r["ready_at"] = ready_at
    touch(r)
    ticket["park_status"] = "RETRIEVED"
    touch(ticket)
    return respond_object(r)


@app.route("/valet/retrieval-requests/<rid>/revert", methods=["POST"])
@endpoint("Attendant")
def revert_retrieval(rid):
    r = must_get("retrieval_requests", rid)
    status = r["status"]
    if status == "READY":
        r["status"] = "STAGING"
        r["ready_at"] = None
        touch(r)
        ticket = db["tickets"].get(r["ticket_id"])
        if ticket is not None:
            ticket["park_status"] = "PARKED"
            touch(ticket)
    elif status == "STAGING":
        r["status"] = "ASSIGNED"
        touch(r)
    elif status == "REQUESTED":
        r["status"] = "CANCELLED"
        touch(r)
    else:
        err("ERR_RETRIEVAL_BAD_STATE", "Revert not allowed from current status.")
    return respond_object(r)


@app.route("/valet/retrieval-requests/<rid>/complete", methods=["POST"])
@endpoint("Attendant")
def complete_retrieval(rid):
    r = must_get("retrieval_requests", rid)
    if r["status"] != "READY":
        err("ERR_RETRIEVAL_BAD_STATE", "Complete requires READY status.")
    r["status"] = "COMPLETED"
    touch(r)
    return respond_object(r)


# =============================================================================
# Damage claims
# =============================================================================
@app.route("/valet/damage-claims", methods=["POST"])
@endpoint("Attendant", "Cashier")
def create_damage_claim():
    b = body_json()
    ticket_id = req_str(b, "ticket_id")
    description = req_str(b, "description")
    claimed_amount_cents = req_int(b, "claimed_amount_cents")
    ticket = must_get("tickets", ticket_id)
    attendant_id = opt_str(b, "attendant_id", None)
    if attendant_id is not None:
        must_get("attendants", attendant_id)
    else:
        attendant_id = ticket["attendant_id"]
    claim = new_entity("damage_claims", {
        "ticket_id": ticket_id,
        "attendant_id": attendant_id,
        "description": description,
        "claimed_amount_cents": claimed_amount_cents,
        "approved_liability_cents": None,
        "status": "OPEN",
    })
    return respond_object(claim, 201)


@app.route("/valet/damage-claims/<cid>", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def get_damage_claim(cid):
    return respond_object(must_get("damage_claims", cid))


@app.route("/valet/damage-claims", methods=["GET"])
@endpoint("Supervisor", "Cashier", "Attendant")
def list_damage_claims():
    ticket_id = request.args.get("ticket_id")
    attendant_id = request.args.get("attendant_id")
    status = request.args.get("status")

    def pred(c):
        if ticket_id is not None and c["ticket_id"] != ticket_id:
            return False
        if attendant_id is not None and c["attendant_id"] != attendant_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    items, pg = paginate(collection_sorted("damage_claims", pred))
    return respond_list(items, pg)


@app.route("/valet/damage-claims/<cid>/approve", methods=["POST"])
@endpoint("Supervisor")
def approve_damage_claim(cid):
    claim = must_get("damage_claims", cid)
    if claim["status"] != "OPEN":
        err("ERR_CLAIM_NOT_OPEN", "Claim must be OPEN to approve.")
    b = body_json()
    override = opt_int(b, "approved_liability_cents", None)
    approved = override if override is not None else claim["claimed_amount_cents"]

    claim["approved_liability_cents"] = approved
    claim["status"] = "APPROVED"
    touch(claim)

    # hop 1: ticket -> DISPUTED, net_charge = 0
    ticket = db["tickets"].get(claim["ticket_id"])
    if ticket is not None:
        ticket["settlement_status"] = "DISPUTED"
        ticket["net_charge_cents"] = 0
        touch(ticket)

    # hop 2: attendant liability
    attendant = db["attendants"].get(claim["attendant_id"])
    if attendant is not None:
        attendant["total_liability_cents"] += approved
        # hop 3: auto-suspend
        if attendant["total_liability_cents"] >= LIABILITY_SUSPEND_THRESHOLD and attendant["status"] == "ACTIVE":
            attendant["status"] = "INACTIVE"
            for s in db["shifts"].values():
                if s["attendant_id"] == attendant["id"] and s["status"] == "ACTIVE":
                    s["status"] = "CLOSED"
                    touch(s)
        touch(attendant)

    return respond_object(claim)


@app.route("/valet/damage-claims/<cid>/deny", methods=["POST"])
@endpoint("Supervisor")
def deny_damage_claim(cid):
    claim = must_get("damage_claims", cid)
    if claim["status"] != "OPEN":
        err("ERR_CLAIM_NOT_OPEN", "Claim must be OPEN to deny.")
    claim["status"] = "DENIED"
    touch(claim)
    return respond_object(claim)


@app.route("/valet/damage-claims/<cid>/settle", methods=["POST"])
@endpoint("Supervisor")
def settle_damage_claim(cid):
    claim = must_get("damage_claims", cid)
    if claim["status"] != "APPROVED":
        err("ERR_CLAIM_NOT_APPROVED", "Claim must be APPROVED to settle.")
    claim["status"] = "SETTLED"
    touch(claim)
    return respond_object(claim)


# =============================================================================
# Reconciliation reports
# =============================================================================
@app.route("/valet/reconciliation-reports", methods=["POST"])
@endpoint("Supervisor")
def create_reconciliation_report():
    b = body_json()
    event_id = req_str(b, "event_id")
    event = must_get("events", event_id)
    if event["status"] != "CLOSED":
        err("ERR_INVALID_STATE", "Reconciliation requires a CLOSED event.")
    report = new_entity("reconciliation_reports", {
        "event_id": event_id,
        "status": "DRAFT",
        "expected_revenue_cents": 0,
        "overflow_surcharge_total_cents": 0,
        "liability_adjustment_cents": 0,
        "declared_cash_cents": None,
        "variance_cents": None,
    })
    compute_report_figures(report, event)
    return respond_object(report, 201)


@app.route("/valet/reconciliation-reports/<rid>", methods=["GET"])
@endpoint("Supervisor", "Cashier")
def get_reconciliation_report(rid):
    return respond_object(must_get("reconciliation_reports", rid))


@app.route("/valet/reconciliation-reports", methods=["GET"])
@endpoint("Supervisor", "Cashier")
def list_reconciliation_reports():
    event_id = request.args.get("event_id")

    def pred(r):
        if event_id is not None and r["event_id"] != event_id:
            return False
        return True

    items, pg = paginate(collection_sorted("reconciliation_reports", pred))
    return respond_list(items, pg)


@app.route("/valet/reconciliation-reports/<rid>/finalize", methods=["POST"])
@endpoint("Supervisor")
def finalize_reconciliation_report(rid):
    report = must_get("reconciliation_reports", rid)
    if report["status"] != "DRAFT":
        err("ERR_REPORT_ALREADY_FINALIZED", "Report is already FINALIZED.")
    b = body_json()
    declared_cash = req_int(b, "declared_cash_cents")
    event = db["events"].get(report["event_id"])
    if event is not None:
        compute_report_figures(report, event)
    report["declared_cash_cents"] = declared_cash
    report["variance_cents"] = declared_cash - (
        report["expected_revenue_cents"] - report["liability_adjustment_cents"])
    report["status"] = "FINALIZED"
    touch(report)
    return respond_object(report)


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
