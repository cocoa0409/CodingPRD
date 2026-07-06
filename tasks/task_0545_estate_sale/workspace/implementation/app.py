"""Estate Sale & Senior Downsizing API — Python + Flask, in-memory only.

Boots empty on every process start. No seeding, no disk persistence.
"""
import os
import math
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "SaleManager", "Appraiser", "Cashier", "Client"}

# Project statuses
P_LEAD, P_ASSESSED, P_PROPOSED, P_COUNTERED, P_CONTRACTED = (
    "LEAD", "ASSESSED", "PROPOSED", "COUNTERED", "CONTRACTED")
P_SALE_SETUP, P_SALE_LIVE, P_SETTLING, P_SETTLED, P_CANCELLED = (
    "SALE_SETUP", "SALE_LIVE", "SETTLING", "SETTLED", "CANCELLED")
PROJECT_STATUSES = {P_LEAD, P_ASSESSED, P_PROPOSED, P_COUNTERED, P_CONTRACTED,
                    P_SALE_SETUP, P_SALE_LIVE, P_SETTLING, P_SETTLED, P_CANCELLED}
PROJECT_TERMINAL = {P_SETTLED, P_CANCELLED}

PROJECT_TRANSITIONS = {
    (P_LEAD, P_ASSESSED),
    (P_ASSESSED, P_PROPOSED),
    (P_PROPOSED, P_COUNTERED),
    (P_COUNTERED, P_PROPOSED),
    (P_PROPOSED, P_CONTRACTED),
    (P_CONTRACTED, P_SALE_SETUP),
    (P_SALE_SETUP, P_SALE_LIVE),
    (P_SALE_LIVE, P_SETTLING),
}
MANAGER_TARGETS = {P_ASSESSED, P_PROPOSED, P_SALE_SETUP, P_SALE_LIVE, P_SETTLING}
CLIENT_TARGETS = {P_COUNTERED, P_CONTRACTED}

# Lot statuses
L_NEW, L_RESEARCHED, L_PRICED, L_STAGED, L_TAGGED, L_LISTED = (
    "NEW", "RESEARCHED", "PRICED", "STAGED", "TAGGED", "LISTED")
L_BID_CLOSED, L_SOLD, L_UNSOLD, L_WITHDRAWN = (
    "BID_CLOSED", "SOLD", "UNSOLD", "WITHDRAWN")
LOT_STATUSES = {L_NEW, L_RESEARCHED, L_PRICED, L_STAGED, L_TAGGED, L_LISTED,
                L_BID_CLOSED, L_SOLD, L_UNSOLD, L_WITHDRAWN}
LOT_TERMINAL = {L_SOLD, L_UNSOLD, L_WITHDRAWN}

# SaleEvent statuses
SE_SCHEDULED, SE_OPEN, SE_CLOSED, SE_CANCELLED = (
    "SCHEDULED", "OPEN", "CLOSED", "CANCELLED")

# Transaction / Bid / HaulJob statuses
T_RECORDED, T_VOIDED = "RECORDED", "VOIDED"
B_PLACED, B_WON, B_LOST, B_VOIDED = "PLACED", "WON", "LOST", "VOIDED"
H_SCHEDULED, H_COMPLETED, H_CANCELLED = "SCHEDULED", "COMPLETED", "CANCELLED"

HANDLING_TYPES = {"CONSIGNMENT", "BUYOUT"}
BID_MODES = {"FIRST_PRICE", "SECOND_PRICE"}
PAYMENT_METHODS = {"CASH", "CARD"}
DISPOSITION_TYPES = {"DONATION", "HAULAWAY", "BUYBACK"}

# Calculation constants
TIER1_THRESHOLD_CENTS = 500000
TIER1_RATE = Decimal("0.40")
TIER2_RATE = Decimal("0.30")
CARD_FEE_RATE = Decimal("0.029")
SALE_WINDOW_MAX_SECONDS = 4 * 86400
TRUCK_BUFFER_SECONDS = 60 * 60
SECONDS_PER_DAY = 86400

DEFAULT_MIN_COMMISSION = 50000
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
LOCK = threading.RLock()


class DB:
    def __init__(self):
        self.clients = {}
        self.projects = {}
        self.lots = {}
        self.sale_events = {}
        self.crews = {}
        self.transactions = {}
        self.bids = {}
        self.haul_jobs = {}
        self.trucks = {}
        self.settlements = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


db = DB()


def next_seq():
    db.seq += 1
    return db.seq


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def gen_uuid():
    import uuid
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or raise ApiError."""
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", 400, "Invalid datetime")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # fallback attempts
        parsed = None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M%z", "%Y-%m-%dT%H:%M"):
            try:
                parsed = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            raise err("ERR_VALIDATION", 400, "Invalid datetime: %s" % value)
        dt = parsed
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a Decimal/number half-up to an integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def base_fields():
    ts = now_iso()
    return {
        "id": gen_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID or X-User-Role")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", 403, "Role not permitted")


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", 400, "Body must be an object")
    return body


def require_present(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", 400, "Missing required field: %s" % f)


def as_nonneg_int(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", 400, "Missing required field: %s" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", 400, "Field %s must be a non-negative integer" % field)
    if val < 0:
        raise err("ERR_VALIDATION", 400, "Field %s must be >= 0" % field)
    return val


def as_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", 400, "Missing required field: %s" % field)
        return None
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", 400, "Field %s must be a string" % field)
    return val


def as_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", 400, "Missing required field: %s" % field)
        return None
    val = body[field]
    if val not in allowed:
        raise err("ERR_VALIDATION", 400, "Field %s not a valid value" % field)
    return val


def as_fraction(body, field, required=False):
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_VALIDATION", 400, "Field %s must be numeric" % field)
    if not (0 <= val < 1):
        raise err("ERR_VALIDATION", 400, "Field %s must be in [0,1)" % field)
    return val


# ---------------------------------------------------------------------------
# Response envelopes
# ---------------------------------------------------------------------------
def _meta():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}


def respond_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def respond_array(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_error(e):
    meta = _meta()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return respond_error(e)


@app.errorhandler(404)
def handle_404(e):
    return respond_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return respond_error(ApiError("ERR_VALIDATION", 400, "Method not allowed"))


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return respond_error(e)
    return respond_error(ApiError("ERR_INTERNAL", 500, str(e)))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sorted_by_creation(values):
    return sorted(values, key=lambda x: x["_seq"])


def synchronized(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Domain calculations
# ---------------------------------------------------------------------------
def tiered_commission(gross, min_commission):
    gross = max(0, int(gross))
    tier1 = Decimal(min(gross, TIER1_THRESHOLD_CENTS)) * TIER1_RATE
    tier2 = Decimal(max(gross - TIER1_THRESHOLD_CENTS, 0)) * TIER2_RATE
    tiered = round_half_up(tier1 + tier2)
    return max(tiered, int(min_commission))


def markdown_price(lot, sale_event):
    start = parse_iso(sale_event["start_at"])
    delta = (db.clock - start).total_seconds()
    day_index = max(0, math.floor(delta / SECONDS_PER_DAY))
    if day_index == 0:
        pct = Decimal("0")
    elif day_index == 1:
        pct = Decimal(str(sale_event["markdown_day1_pct"]))
    elif day_index == 2:
        pct = Decimal(str(sale_event["markdown_day2_pct"]))
    else:
        pct = Decimal(str(sale_event["markdown_day3plus_pct"]))
    list_price = lot.get("list_price_cents") or 0
    return round_half_up(Decimal(list_price) * (Decimal(1) - pct))


def recompute_gross_sales(project):
    total = 0
    for t in db.transactions.values():
        if t["status"] != T_RECORDED:
            continue
        lot = db.lots.get(t["lot_id"])
        if lot is not None and lot["project_id"] == project["id"]:
            total += t["final_price_cents"]
    project["gross_sales_cents"] = total


def recompute_buyout_advances(project):
    total = 0
    for lot in db.lots.values():
        if lot["project_id"] == project["id"] and lot["handling_type"] == "BUYOUT":
            if lot.get("buyout_price_cents"):
                total += lot["buyout_price_cents"]
    project["buyout_advances_cents"] = total


def recompute_unsold_lot_count(project):
    count = 0
    for lot in db.lots.values():
        if lot["project_id"] == project["id"] and lot["status"] == L_UNSOLD:
            count += 1
    project["unsold_lot_count"] = count


def recompute_crew_minutes(crew):
    total = 0
    for se in db.sale_events.values():
        if se["crew_id"] == crew["id"] and se["status"] in (SE_SCHEDULED, SE_OPEN):
            total += se["window_minutes"]
    crew["booked_minutes"] = total


def project_lots(project_id):
    return [l for l in db.lots.values() if l["project_id"] == project_id]


def placed_bids_for_lot(lot_id):
    return [b for b in db.bids.values()
            if b["lot_id"] == lot_id and b["status"] == B_PLACED]


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
@synchronized
def set_clock():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    require_present(body, "to_iso8601")
    db.clock = parse_iso(body["to_iso8601"])
    return respond_object({}, 200)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
@app.route("/estate/clients", methods=["POST"])
@synchronized
def create_client():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    name = as_string(body, "name")
    phone = as_string(body, "phone")
    email = as_string(body, "email", required=False)
    entity = base_fields()
    entity.update({"name": name, "phone": phone, "email": email})
    db.clients[entity["id"]] = entity
    return respond_object(serialize(entity), 201)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
def new_project_estimates():
    return {
        "gross_sales_cents": 0,
        "buyout_advances_cents": 0,
        "unsold_lot_count": 0,
        "estimated_gross_consignment_cents": 0,
        "estimated_commission_cents": 0,
        "estimated_net_to_client_cents": 0,
    }


@app.route("/estate/projects", methods=["POST"])
@synchronized
def create_project():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    client_id = as_string(body, "client_id")
    address = as_string(body, "address")
    est_val = as_nonneg_int(body, "estimated_total_value_cents")
    min_comm = as_nonneg_int(body, "minimum_commission_cents", required=False)
    if min_comm is None:
        min_comm = DEFAULT_MIN_COMMISSION
    if client_id not in db.clients:
        raise err("ERR_CLIENT_NOT_FOUND", 404, "client_id does not resolve")
    entity = base_fields()
    entity.update({
        "client_id": client_id,
        "address": address,
        "estimated_total_value_cents": est_val,
        "minimum_commission_cents": min_comm,
        "assessment_notes": None,
        "status": P_LEAD,
    })
    entity.update(new_project_estimates())
    db.projects[entity["id"]] = entity
    return respond_object(serialize(entity), 201)


@app.route("/estate/projects/<project_id>", methods=["GET"])
@synchronized
def get_project(project_id):
    _, role = authenticate()
    authorize(role, ROLES)
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")
    return respond_object(serialize(project), 200)


@app.route("/estate/projects", methods=["GET"])
@synchronized
def list_projects():
    _, role = authenticate()
    authorize(role, ROLES)
    items = list(db.projects.values())
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return respond_array([serialize(p) for p in page], limit, offset, total)


def snapshot_estimates(project):
    gross = 0
    for lot in project_lots(project["id"]):
        if lot["handling_type"] == "CONSIGNMENT" and lot["status"] in (
                L_PRICED, L_STAGED, L_TAGGED, L_LISTED):
            gross += (lot.get("list_price_cents") or 0)
    commission = tiered_commission(gross, project["minimum_commission_cents"])
    project["estimated_gross_consignment_cents"] = gross
    project["estimated_commission_cents"] = commission
    project["estimated_net_to_client_cents"] = gross - commission


@app.route("/estate/projects/<project_id>", methods=["PATCH"])
@synchronized
def patch_project(project_id):
    uid, role = authenticate()
    authorize(role, {"SaleManager", "Client"})
    body = get_body()

    status = body.get("status")
    if status is not None and status not in PROJECT_STATUSES:
        raise err("ERR_VALIDATION", 400, "Invalid status value")

    # validate optional field types
    min_comm = as_nonneg_int(body, "minimum_commission_cents", required=False)
    address = as_string(body, "address", required=False)
    assessment_notes = None
    if "assessment_notes" in body and body["assessment_notes"] is not None:
        assessment_notes = as_string(body, "assessment_notes", required=False)

    # transition-actor authorization (needs no entity)
    if status in MANAGER_TARGETS:
        if role != "SaleManager":
            raise err("ERR_UNAUTHORIZED", 403, "Only SaleManager may drive this transition")
    elif status in CLIENT_TARGETS:
        if role != "Client":
            raise err("ERR_UNAUTHORIZED", 403, "Only Client may drive this transition")

    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")

    # client ownership
    if role == "Client" and project["client_id"] != uid:
        raise err("ERR_UNAUTHORIZED", 403, "Client may only act on their own project")

    # terminal guard
    if project["status"] in PROJECT_TERMINAL:
        raise err("ERR_PROJECT_TERMINAL", 409, "Project is terminal")

    if status is not None:
        if (project["status"], status) not in PROJECT_TRANSITIONS:
            raise err("ERR_INVALID_STATE", 409, "Invalid project transition")

    # apply field updates
    if address is not None:
        project["address"] = address
    if assessment_notes is not None:
        project["assessment_notes"] = assessment_notes
    if min_comm is not None:
        project["minimum_commission_cents"] = min_comm

    if status is not None:
        project["status"] = status
        if status == P_SALE_SETUP:
            snapshot_estimates(project)

    touch(project)
    return respond_object(serialize(project), 200)


@app.route("/estate/projects/<project_id>/cancel", methods=["POST"])
@synchronized
def cancel_project(project_id):
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")
    if project["status"] in PROJECT_TERMINAL:
        raise err("ERR_PROJECT_TERMINAL", 409, "Project is terminal")

    # Cascade 1: non-terminal lots -> WITHDRAWN; Cascade 2: their PLACED bids -> VOIDED
    for lot in project_lots(project_id):
        if lot["status"] not in LOT_TERMINAL:
            lot["status"] = L_WITHDRAWN
            touch(lot)
            for bid in db.bids.values():
                if bid["lot_id"] == lot["id"] and bid["status"] == B_PLACED:
                    bid["status"] = B_VOIDED
                    touch(bid)

    # Cascade 3: SCHEDULED/OPEN sale events -> CANCELLED, release crew minutes
    affected_crews = set()
    for se in db.sale_events.values():
        if se["project_id"] == project_id and se["status"] in (SE_SCHEDULED, SE_OPEN):
            se["status"] = SE_CANCELLED
            touch(se)
            affected_crews.add(se["crew_id"])
    for crew_id in affected_crews:
        crew = db.crews.get(crew_id)
        if crew is not None:
            recompute_crew_minutes(crew)
            touch(crew)

    project["status"] = P_CANCELLED
    touch(project)
    return respond_object(serialize(project), 200)


@app.route("/estate/projects/<project_id>/settlement-statements", methods=["GET"])
@synchronized
def list_project_settlements(project_id):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SaleManager", "Client"})
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")
    items = [s for s in db.settlements.values() if s["project_id"] == project_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return respond_array([serialize(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lot
# ---------------------------------------------------------------------------
@app.route("/estate/lots", methods=["POST"])
@synchronized
def create_lot():
    _, role = authenticate()
    authorize(role, {"Appraiser"})
    body = get_body()
    project_id = as_string(body, "project_id")
    title = as_string(body, "title")
    handling_type = as_enum(body, "handling_type", HANDLING_TYPES, required=False)
    if handling_type is None:
        handling_type = "CONSIGNMENT"
    elif handling_type == "BUYOUT":
        raise err("ERR_VALIDATION", 400, "handling_type BUYOUT not allowed at creation")

    is_bid_lot = body.get("is_bid_lot", False)
    if is_bid_lot is None:
        is_bid_lot = False
    if not isinstance(is_bid_lot, bool):
        raise err("ERR_VALIDATION", 400, "is_bid_lot must be boolean")

    bid_mode = as_enum(body, "bid_mode", BID_MODES, required=False)
    if is_bid_lot and bid_mode is None:
        raise err("ERR_VALIDATION", 400, "bid_mode required for bid lots")

    list_price = as_nonneg_int(body, "list_price_cents", required=False)
    reserve_price = as_nonneg_int(body, "reserve_price_cents", required=False)
    min_increment = as_nonneg_int(body, "min_increment_cents", required=False)
    research_notes = as_string(body, "research_notes", required=False)

    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")
    if project["status"] in PROJECT_TERMINAL:
        raise err("ERR_PROJECT_TERMINAL", 409, "Project is terminal")
    if project["status"] not in (P_CONTRACTED, P_SALE_SETUP, P_SALE_LIVE):
        raise err("ERR_INVALID_STATE", 409, "Lots may only be created on a contracted project")

    entity = base_fields()
    entity.update({
        "project_id": project_id,
        "title": title,
        "handling_type": handling_type,
        "is_bid_lot": is_bid_lot,
        "bid_mode": bid_mode,
        "list_price_cents": list_price,
        "reserve_price_cents": reserve_price,
        "min_increment_cents": min_increment,
        "research_notes": research_notes,
        "researched_by_user_id": None,
        "approved_buyout_by_user_id": None,
        "buyout_price_cents": None,
        "winning_bid_id": None,
        "winning_bid_price_cents": None,
        "final_price_cents": None,
        "status": L_NEW,
    })
    db.lots[entity["id"]] = entity
    return respond_object(serialize(entity), 201)


@app.route("/estate/lots/<lot_id>", methods=["GET"])
@synchronized
def get_lot(lot_id):
    _, role = authenticate()
    authorize(role, ROLES)
    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", 404, "lot_id does not resolve")
    return respond_object(serialize(lot), 200)


@app.route("/estate/lots", methods=["GET"])
@synchronized
def list_lots():
    _, role = authenticate()
    authorize(role, ROLES)
    items = list(db.lots.values())
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    handling_type = request.args.get("handling_type")
    if project_id is not None:
        items = [l for l in items if l["project_id"] == project_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if handling_type is not None:
        items = [l for l in items if l["handling_type"] == handling_type]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return respond_array([serialize(l) for l in page], limit, offset, total)


LOT_TRANSITIONS = {
    (L_NEW, L_RESEARCHED),
    (L_RESEARCHED, L_PRICED),
    (L_PRICED, L_STAGED),
    (L_STAGED, L_TAGGED),
    (L_TAGGED, L_LISTED),
    (L_PRICED, L_RESEARCHED),
    (L_STAGED, L_RESEARCHED),
    (L_TAGGED, L_RESEARCHED),
    (L_LISTED, L_RESEARCHED),
    (L_LISTED, L_BID_CLOSED),
}


def resolve_bid_winner(lot):
    reserve = lot.get("reserve_price_cents") or 0
    min_inc = lot.get("min_increment_cents") or 0
    placed = placed_bids_for_lot(lot["id"])
    candidates = [b for b in placed if b["amount_cents"] >= reserve]
    candidates.sort(key=lambda b: (-b["amount_cents"], b["_seq"]))

    if not candidates:
        # empty-set fallback -> UNSOLD
        lot["winning_bid_id"] = None
        lot["winning_bid_price_cents"] = None
        lot["status"] = L_UNSOLD
        # all placed bids -> LOST
        for b in placed:
            b["status"] = B_LOST
            touch(b)
        touch(lot)
        project = db.projects.get(lot["project_id"])
        if project is not None:
            recompute_unsold_lot_count(project)
            touch(project)
        return

    winner = candidates[0]
    highest = winner["amount_cents"]
    second = candidates[1]["amount_cents"] if len(candidates) >= 2 else None

    if lot["bid_mode"] == "FIRST_PRICE":
        price = highest
    else:  # SECOND_PRICE
        if second is not None:
            price = min(highest, second + min_inc)
        else:
            price = reserve

    lot["winning_bid_id"] = winner["id"]
    lot["winning_bid_price_cents"] = price
    lot["status"] = L_BID_CLOSED
    for b in placed:
        b["status"] = B_WON if b["id"] == winner["id"] else B_LOST
        touch(b)
    touch(lot)


@app.route("/estate/lots/<lot_id>", methods=["PATCH"])
@synchronized
def patch_lot(lot_id):
    _, role = authenticate()
    authorize(role, {"Appraiser"})
    body = get_body()

    status = body.get("status")
    if status is not None and status not in LOT_STATUSES:
        raise err("ERR_VALIDATION", 400, "Invalid status value")

    list_price = as_nonneg_int(body, "list_price_cents", required=False)
    reserve_price = as_nonneg_int(body, "reserve_price_cents", required=False)
    min_increment = as_nonneg_int(body, "min_increment_cents", required=False)
    research_notes = as_string(body, "research_notes", required=False)
    bid_mode = as_enum(body, "bid_mode", BID_MODES, required=False)

    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", 404, "lot_id does not resolve")

    project = db.projects.get(lot["project_id"])

    # apply field updates first (available to preconditions such as pricing)
    if list_price is not None:
        lot["list_price_cents"] = list_price
    if reserve_price is not None:
        lot["reserve_price_cents"] = reserve_price
    if min_increment is not None:
        lot["min_increment_cents"] = min_increment
    if research_notes is not None:
        lot["research_notes"] = research_notes
    if bid_mode is not None:
        lot["bid_mode"] = bid_mode

    if status is None:
        # field-only update
        if lot["status"] in LOT_TERMINAL:
            raise err("ERR_INVALID_STATE", 409, "Lot is terminal")
        touch(lot)
        return respond_object(serialize(lot), 200)

    current = lot["status"]
    if (current, status) not in LOT_TRANSITIONS:
        raise err("ERR_INVALID_STATE", 409, "Invalid lot transition")

    # transition-specific preconditions & side effects
    if status == L_RESEARCHED and current == L_NEW:
        if project is None or project["status"] not in (P_CONTRACTED, P_SALE_SETUP, P_SALE_LIVE):
            raise err("ERR_INVALID_STATE", 409, "Project not ready for research")
        lot["status"] = L_RESEARCHED
        lot["researched_by_user_id"] = request.headers.get("X-User-ID")

    elif status == L_RESEARCHED and current in (L_PRICED, L_STAGED, L_TAGGED, L_LISTED):
        # re-research loop (lot not yet sold — guaranteed by non-terminal current)
        lot["status"] = L_RESEARCHED

    elif status == L_PRICED:
        if lot.get("list_price_cents") is None:
            raise err("ERR_VALIDATION", 400, "list_price_cents required to price a lot")
        lot["status"] = L_PRICED

    elif status == L_STAGED:
        lot["status"] = L_STAGED

    elif status == L_TAGGED:
        lot["status"] = L_TAGGED

    elif status == L_LISTED:
        if project is None or project["status"] not in (P_SALE_SETUP, P_SALE_LIVE):
            raise err("ERR_PROJECT_NOT_IN_SALE", 409, "Project not in sale phase")
        lot["status"] = L_LISTED

    elif status == L_BID_CLOSED:
        if not lot["is_bid_lot"]:
            raise err("ERR_NOT_BID_LOT", 409, "Not a bid lot")
        resolve_bid_winner(lot)  # may end BID_CLOSED or UNSOLD; touches lot
        return respond_object(serialize(lot), 200)

    touch(lot)
    return respond_object(serialize(lot), 200)


@app.route("/estate/lots/<lot_id>/approve-buyout", methods=["POST"])
@synchronized
def approve_buyout(lot_id):
    uid, role = authenticate()
    authorize(role, {"SaleManager"})
    body = get_body()
    buyout_price = as_nonneg_int(body, "buyout_price_cents")

    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", 404, "lot_id does not resolve")

    # segregation of duties
    if lot.get("researched_by_user_id") is not None and uid == lot["researched_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403,
                  "Approver must differ from the lot researcher")

    lot["handling_type"] = "BUYOUT"
    lot["buyout_price_cents"] = buyout_price
    lot["approved_buyout_by_user_id"] = uid
    touch(lot)

    project = db.projects.get(lot["project_id"])
    if project is not None:
        recompute_buyout_advances(project)
        touch(project)
    return respond_object(serialize(lot), 200)


@app.route("/estate/lots/<lot_id>/bids", methods=["GET"])
@synchronized
def list_lot_bids(lot_id):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SaleManager", "Appraiser", "Cashier"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", 404, "lot_id does not resolve")
    items = [b for b in db.bids.values() if b["lot_id"] == lot_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return respond_array([serialize(b) for b in page], limit, offset, total)


# ---------------------------------------------------------------------------
# SaleEvent
# ---------------------------------------------------------------------------
@app.route("/estate/sale-events", methods=["POST"])
@synchronized
def create_sale_event():
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    body = get_body()
    project_id = as_string(body, "project_id")
    crew_id = as_string(body, "crew_id")
    start_raw = as_string(body, "start_at")
    end_raw = as_string(body, "end_at")
    md1 = as_fraction(body, "markdown_day1_pct")
    md2 = as_fraction(body, "markdown_day2_pct")
    md3 = as_fraction(body, "markdown_day3plus_pct")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)

    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")
    crew = db.crews.get(crew_id)
    if crew is None:
        raise err("ERR_CREW_NOT_FOUND", 404, "crew_id does not resolve")

    # temporal: crew double-booking (half-open overlap)
    for se in db.sale_events.values():
        if se["crew_id"] != crew_id or se["status"] not in (SE_SCHEDULED, SE_OPEN):
            continue
        o_start = parse_iso(se["start_at"])
        o_end = parse_iso(se["end_at"])
        if start_dt < o_end and o_start < end_dt:
            raise err("ERR_CREW_DOUBLE_BOOKED", 409, "Crew already booked for this window")

    # constraint: window length <= 4 days
    length_seconds = (end_dt - start_dt).total_seconds()
    if length_seconds > SALE_WINDOW_MAX_SECONDS:
        raise err("ERR_SALE_WINDOW_TOO_LONG", 422, "Sale window exceeds 4 days")

    window_minutes = int(length_seconds // 60)

    entity = base_fields()
    entity.update({
        "project_id": project_id,
        "crew_id": crew_id,
        "start_at": start_raw,
        "end_at": end_raw,
        "markdown_day1_pct": md1 if md1 is not None else 0.25,
        "markdown_day2_pct": md2 if md2 is not None else 0.50,
        "markdown_day3plus_pct": md3 if md3 is not None else 0.75,
        "window_minutes": window_minutes,
        "status": SE_SCHEDULED,
    })
    db.sale_events[entity["id"]] = entity
    recompute_crew_minutes(crew)
    touch(crew)
    return respond_object(serialize(entity), 201)


@app.route("/estate/sale-events/<sale_event_id>", methods=["GET"])
@synchronized
def get_sale_event(sale_event_id):
    _, role = authenticate()
    authorize(role, ROLES)
    se = db.sale_events.get(sale_event_id)
    if se is None:
        raise err("ERR_SALE_EVENT_NOT_FOUND", 404, "sale_event_id does not resolve")
    return respond_object(serialize(se), 200)


@app.route("/estate/sale-events", methods=["GET"])
@synchronized
def list_sale_events():
    _, role = authenticate()
    authorize(role, ROLES)
    items = list(db.sale_events.values())
    project_id = request.args.get("project_id")
    crew_id = request.args.get("crew_id")
    if project_id is not None:
        items = [s for s in items if s["project_id"] == project_id]
    if crew_id is not None:
        items = [s for s in items if s["crew_id"] == crew_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return respond_array([serialize(s) for s in page], limit, offset, total)


@app.route("/estate/sale-events/<sale_event_id>", methods=["PATCH"])
@synchronized
def patch_sale_event(sale_event_id):
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    body = get_body()
    status = as_enum(body, "status", {SE_SCHEDULED, SE_OPEN, SE_CLOSED, SE_CANCELLED})

    se = db.sale_events.get(sale_event_id)
    if se is None:
        raise err("ERR_SALE_EVENT_NOT_FOUND", 404, "sale_event_id does not resolve")

    if status == SE_OPEN:
        if se["status"] != SE_SCHEDULED:
            raise err("ERR_INVALID_STATE", 409, "Sale event not SCHEDULED")
        project = db.projects.get(se["project_id"])
        if project is None or project["status"] != P_SALE_LIVE:
            raise err("ERR_PROJECT_NOT_IN_SALE", 409, "Project not SALE_LIVE")
        se["status"] = SE_OPEN
        touch(se)
        crew = db.crews.get(se["crew_id"])
        if crew is not None:
            recompute_crew_minutes(crew)
            touch(crew)
        return respond_object(serialize(se), 200)

    raise err("ERR_INVALID_STATE", 409, "Unsupported sale event transition")


@app.route("/estate/sale-events/<sale_event_id>/close", methods=["POST"])
@synchronized
def close_sale_event(sale_event_id):
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    se = db.sale_events.get(sale_event_id)
    if se is None:
        raise err("ERR_SALE_EVENT_NOT_FOUND", 404, "sale_event_id does not resolve")
    if se["status"] != SE_OPEN:
        raise err("ERR_INVALID_STATE", 409, "Sale event not OPEN")

    se["status"] = SE_CLOSED
    touch(se)

    project = db.projects.get(se["project_id"])
    if project is not None:
        for lot in project_lots(project["id"]):
            if lot["status"] == L_LISTED:
                lot["status"] = L_UNSOLD
                touch(lot)
        recompute_unsold_lot_count(project)
        touch(project)

    crew = db.crews.get(se["crew_id"])
    if crew is not None:
        recompute_crew_minutes(crew)
        touch(crew)

    return respond_object(serialize(se), 200)


# ---------------------------------------------------------------------------
# Crew
# ---------------------------------------------------------------------------
@app.route("/estate/crews", methods=["POST"])
@synchronized
def create_crew():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    name = as_string(body, "name")
    entity = base_fields()
    entity.update({"name": name, "booked_minutes": 0})
    db.crews[entity["id"]] = entity
    return respond_object(serialize(entity), 201)


@app.route("/estate/crews/<crew_id>", methods=["GET"])
@synchronized
def get_crew(crew_id):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SaleManager", "Appraiser", "Cashier"})
    crew = db.crews.get(crew_id)
    if crew is None:
        raise err("ERR_CREW_NOT_FOUND", 404, "crew_id does not resolve")
    return respond_object(serialize(crew), 200)


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------
@app.route("/estate/transactions", methods=["POST"])
@synchronized
def create_transaction():
    _, role = authenticate()
    authorize(role, {"Cashier"})
    body = get_body()
    sale_event_id = as_string(body, "sale_event_id")
    lot_id = as_string(body, "lot_id")
    payment_method = as_enum(body, "payment_method", PAYMENT_METHODS)
    buyer_name = as_string(body, "buyer_name", required=False)

    se = db.sale_events.get(sale_event_id)
    if se is None:
        raise err("ERR_SALE_EVENT_NOT_FOUND", 404, "sale_event_id does not resolve")
    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", 404, "lot_id does not resolve")

    # state: lot sellable
    if lot["is_bid_lot"]:
        if lot["status"] != L_BID_CLOSED or lot.get("winning_bid_id") is None:
            raise err("ERR_LOT_NOT_SELLABLE", 409, "Bid lot not sellable")
    else:
        if lot["status"] != L_LISTED:
            raise err("ERR_LOT_NOT_SELLABLE", 409, "Fixed lot not LISTED")

    # state: sale event OPEN
    if se["status"] != SE_OPEN:
        raise err("ERR_SALE_NOT_OPEN", 409, "Sale event not OPEN")

    # compute final price
    if lot["is_bid_lot"]:
        final_price = lot["winning_bid_price_cents"]
    else:
        final_price = markdown_price(lot, se)
        reserve = lot.get("reserve_price_cents")
        if reserve is not None and final_price < reserve:
            raise err("ERR_BELOW_RESERVE", 422, "Markdown price below reserve")

    if payment_method == "CARD":
        card_fee = round_half_up(Decimal(final_price) * CARD_FEE_RATE)
    else:
        card_fee = 0

    entity = base_fields()
    entity.update({
        "sale_event_id": sale_event_id,
        "lot_id": lot_id,
        "payment_method": payment_method,
        "buyer_name": buyer_name,
        "final_price_cents": final_price,
        "card_fee_cents": card_fee,
        "status": T_RECORDED,
    })
    db.transactions[entity["id"]] = entity

    # lot -> SOLD
    lot["final_price_cents"] = final_price
    lot["status"] = L_SOLD
    touch(lot)

    # project gross sales + version bump
    project = db.projects.get(lot["project_id"])
    if project is not None:
        recompute_gross_sales(project)
        touch(project)

    return respond_object(serialize(entity), 201)


@app.route("/estate/transactions/<transaction_id>", methods=["GET"])
@synchronized
def get_transaction(transaction_id):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SaleManager", "Cashier"})
    t = db.transactions.get(transaction_id)
    if t is None:
        raise err("ERR_TRANSACTION_NOT_FOUND", 404, "transaction_id does not resolve")
    return respond_object(serialize(t), 200)


@app.route("/estate/transactions", methods=["GET"])
@synchronized
def list_transactions():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SaleManager", "Cashier"})
    items = list(db.transactions.values())
    sale_event_id = request.args.get("sale_event_id")
    lot_id = request.args.get("lot_id")
    if sale_event_id is not None:
        items = [t for t in items if t["sale_event_id"] == sale_event_id]
    if lot_id is not None:
        items = [t for t in items if t["lot_id"] == lot_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return respond_array([serialize(t) for t in page], limit, offset, total)


@app.route("/estate/transactions/<transaction_id>/void", methods=["POST"])
@synchronized
def void_transaction(transaction_id):
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    t = db.transactions.get(transaction_id)
    if t is None:
        raise err("ERR_TRANSACTION_NOT_FOUND", 404, "transaction_id does not resolve")
    if t["status"] != T_RECORDED:
        raise err("ERR_INVALID_STATE", 409, "Transaction not RECORDED")

    t["status"] = T_VOIDED
    touch(t)

    lot = db.lots.get(t["lot_id"])
    if lot is not None:
        lot["status"] = L_BID_CLOSED if lot["is_bid_lot"] else L_LISTED
        lot["final_price_cents"] = None
        touch(lot)
        project = db.projects.get(lot["project_id"])
        if project is not None:
            recompute_gross_sales(project)
            touch(project)

    return respond_object(serialize(t), 200)


# ---------------------------------------------------------------------------
# Bid
# ---------------------------------------------------------------------------
@app.route("/estate/bids", methods=["POST"])
@synchronized
def create_bid():
    _, role = authenticate()
    authorize(role, {"Cashier"})
    body = get_body()
    lot_id = as_string(body, "lot_id")
    amount = as_nonneg_int(body, "amount_cents")
    bidder_name = as_string(body, "bidder_name")

    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", 404, "lot_id does not resolve")

    if not lot["is_bid_lot"]:
        raise err("ERR_NOT_BID_LOT", 409, "Not a bid lot")

    reserve = lot.get("reserve_price_cents") or 0
    min_inc = lot.get("min_increment_cents") or 0
    placed = placed_bids_for_lot(lot_id)
    current_high = max((b["amount_cents"] for b in placed), default=None)

    if amount < reserve:
        raise err("ERR_BID_TOO_LOW", 422, "Bid below reserve")
    if current_high is not None and amount < current_high + min_inc:
        raise err("ERR_BID_TOO_LOW", 422, "Bid below current high plus increment")

    entity = base_fields()
    entity.update({
        "lot_id": lot_id,
        "amount_cents": amount,
        "bidder_name": bidder_name,
        "status": B_PLACED,
    })
    db.bids[entity["id"]] = entity
    return respond_object(serialize(entity), 201)


# ---------------------------------------------------------------------------
# HaulJob
# ---------------------------------------------------------------------------
@app.route("/estate/haul-jobs", methods=["POST"])
@synchronized
def create_haul_job():
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    body = get_body()
    project_id = as_string(body, "project_id")
    truck_id = as_string(body, "truck_id")
    disposition_type = as_enum(body, "disposition_type", DISPOSITION_TYPES)
    start_raw = as_string(body, "start_at")
    end_raw = as_string(body, "end_at")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)

    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise err("ERR_TRUCK_NOT_FOUND", 404, "truck_id does not resolve")

    # temporal: truck closed-window overlap within 60-min buffer
    exp_start = start_dt - timedelta(seconds=TRUCK_BUFFER_SECONDS)
    exp_end = end_dt + timedelta(seconds=TRUCK_BUFFER_SECONDS)
    for hj in db.haul_jobs.values():
        if hj["truck_id"] != truck_id or hj["status"] != H_SCHEDULED:
            continue
        o_start = parse_iso(hj["start_at"])
        o_end = parse_iso(hj["end_at"])
        # closed-interval overlap of expanded new window vs existing window
        if exp_start <= o_end and o_start <= exp_end:
            raise err("ERR_TRUCK_UNAVAILABLE", 409, "Truck unavailable in this window")

    entity = base_fields()
    entity.update({
        "project_id": project_id,
        "truck_id": truck_id,
        "disposition_type": disposition_type,
        "start_at": start_raw,
        "end_at": end_raw,
        "status": H_SCHEDULED,
    })
    db.haul_jobs[entity["id"]] = entity
    return respond_object(serialize(entity), 201)


@app.route("/estate/haul-jobs/<haul_job_id>", methods=["GET"])
@synchronized
def get_haul_job(haul_job_id):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SaleManager", "Client"})
    hj = db.haul_jobs.get(haul_job_id)
    if hj is None:
        raise err("ERR_HAUL_JOB_NOT_FOUND", 404, "haul_job_id does not resolve")
    return respond_object(serialize(hj), 200)


@app.route("/estate/haul-jobs", methods=["GET"])
@synchronized
def list_haul_jobs():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SaleManager", "Client"})
    items = list(db.haul_jobs.values())
    project_id = request.args.get("project_id")
    truck_id = request.args.get("truck_id")
    if project_id is not None:
        items = [h for h in items if h["project_id"] == project_id]
    if truck_id is not None:
        items = [h for h in items if h["truck_id"] == truck_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return respond_array([serialize(h) for h in page], limit, offset, total)


@app.route("/estate/haul-jobs/<haul_job_id>", methods=["PATCH"])
@synchronized
def patch_haul_job(haul_job_id):
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    body = get_body()
    status = as_enum(body, "status", {H_SCHEDULED, H_COMPLETED, H_CANCELLED})

    hj = db.haul_jobs.get(haul_job_id)
    if hj is None:
        raise err("ERR_HAUL_JOB_NOT_FOUND", 404, "haul_job_id does not resolve")

    if status in (H_COMPLETED, H_CANCELLED):
        if hj["status"] != H_SCHEDULED:
            raise err("ERR_INVALID_STATE", 409, "Haul job not SCHEDULED")
        hj["status"] = status
        touch(hj)
        return respond_object(serialize(hj), 200)

    raise err("ERR_INVALID_STATE", 409, "Unsupported haul job transition")


# ---------------------------------------------------------------------------
# Truck
# ---------------------------------------------------------------------------
@app.route("/estate/trucks", methods=["POST"])
@synchronized
def create_truck():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    name = as_string(body, "name")
    entity = base_fields()
    entity.update({"name": name})
    db.trucks[entity["id"]] = entity
    return respond_object(serialize(entity), 201)


# ---------------------------------------------------------------------------
# SettlementStatement
# ---------------------------------------------------------------------------
@app.route("/estate/settlement-statements", methods=["POST"])
@synchronized
def create_settlement():
    _, role = authenticate()
    authorize(role, {"SaleManager"})
    body = get_body()
    project_id = as_string(body, "project_id")
    expected_version = as_nonneg_int(body, "expected_project_version")

    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_PROJECT_NOT_FOUND", 404, "project_id does not resolve")

    # OCC (priority 5, before state)
    if expected_version != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", 412, "Stale project version")

    # state (priority 6)
    if project["status"] in PROJECT_TERMINAL:
        raise err("ERR_PROJECT_TERMINAL", 409, "Project is terminal")
    if project["status"] != P_SETTLING:
        raise err("ERR_INVALID_STATE", 409, "Project not in SETTLING")

    # Compute final figures
    gross_consignment = 0
    card_fees = 0
    for t in db.transactions.values():
        if t["status"] != T_RECORDED:
            continue
        lot = db.lots.get(t["lot_id"])
        if lot is None or lot["project_id"] != project_id:
            continue
        if lot["handling_type"] != "CONSIGNMENT":
            continue
        gross_consignment += t["final_price_cents"]
        if t["payment_method"] == "CARD":
            card_fees += round_half_up(Decimal(t["final_price_cents"]) * CARD_FEE_RATE)

    commission = tiered_commission(gross_consignment, project["minimum_commission_cents"])
    net_to_client = gross_consignment - commission - card_fees
    unsold = sum(1 for l in project_lots(project_id) if l["status"] == L_UNSOLD)

    # supersede prior statements
    for s in db.settlements.values():
        if s["project_id"] == project_id and not s["superseded"]:
            s["superseded"] = True
            touch(s)

    entity = base_fields()
    entity.update({
        "project_id": project_id,
        "expected_project_version": expected_version,
        "gross_consignment_cents": gross_consignment,
        "commission_cents": commission,
        "card_fees_cents": card_fees,
        "buyout_advances_cents": project["buyout_advances_cents"],
        "net_to_client_cents": net_to_client,
        "unsold_lot_count": unsold,
        "superseded": False,
    })
    db.settlements[entity["id"]] = entity

    project["status"] = P_SETTLED
    touch(project)

    return respond_object(serialize(entity), 201)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
