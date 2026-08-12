"""Core infrastructure: in-memory store, logical clock, envelope, errors, auth, validation."""
import re
import uuid
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify


# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD / PRD)
# ---------------------------------------------------------------------------
TOTAL_SEATS = 5
CURE_PERIOD_DAYS = 14
PENALTY_CAP_PCT = Decimal("25")
TRANCHE_OPEN_LEAD_DAYS = 30
RESCISSION_WINDOW_DAYS = 30
BUDGET_NOTICE_LEAD_DAYS = 14
ASSESSMENT_NOTICE_LEAD_DAYS = 30
STATUTORY_CAP_PCT = Decimal("20.00")
EVENT_LEAD_DAYS = 14
VIOLATION_CURE_DAYS = 14
APPEAL_WINDOW_DAYS = 30
FINE_CAP_CENTS = 1000000
TIER1_DAILY_CENTS = 5000
TIER2_DAILY_CENTS = 10000
TIER3_DAILY_CENTS = 20000
MAX_REVIEW_ROUNDS = 3
REVIEW_ROUND_FEES = {2: 25000, 3: 75000}
CONSTRUCTION_START_WINDOW_DAYS = 180
ELECTION_WINDOW_DAYS = 30
QUORUM_PCT = 20
MAX_CONCURRENT_TOURS = 3

ALL_ROLES = [
    "DeclarantExecutive", "DeclarantController", "BuilderRep",
    "AssociationDirector", "OwnerDirector", "DesignReviewer",
    "LifestyleCoordinator", "HomeownerResident", "PlatformAdmin",
]

DEFAULT_CLOCK_STR = "2026-05-01T00:00:00Z"

VENUE_TO_AMENITY = {
    "CLUBHOUSE": "CLUBHOUSE",
    "POOL_DECK": "POOL",
    "EVENT_LAWN": "EVENT_LAWN",
}

STAGE_ORDER = {
    "DECLARANT_CONTROL": 0,
    "OWNER_REPRESENTATION": 1,
    "PARITY": 2,
    "OWNER_MAJORITY": 3,
    "TURNOVER_COMPLETE": 4,
}

REQUIRED_OWNER_SEATS = {
    "DECLARANT_CONTROL": 0,
    "OWNER_REPRESENTATION": 1,
    "PARITY": 2,
    "OWNER_MAJORITY": 3,
    "TURNOVER_COMPLETE": 5,
}


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
    raise ApiError(error_id, http_status, message)


NOT_FOUND = {
    "community": ("ERR_COMMUNITY_NOT_FOUND", 404),
    "phase": ("ERR_PHASE_NOT_FOUND", 404),
    "amenity": ("ERR_AMENITY_NOT_FOUND", 404),
    "builder": ("ERR_BUILDER_NOT_FOUND", 404),
    "agreement": ("ERR_AGREEMENT_NOT_FOUND", 404),
    "tranche": ("ERR_TRANCHE_NOT_FOUND", 404),
    "lot": ("ERR_LOT_NOT_FOUND", 404),
    "closing": ("ERR_CLOSING_NOT_FOUND", 404),
    "budget": ("ERR_BUDGET_NOT_FOUND", 404),
    "line_item": ("ERR_LINE_ITEM_NOT_FOUND", 404),
    "rate": ("ERR_RATE_NOT_FOUND", 404),
    "district": ("ERR_DISTRICT_NOT_FOUND", 404),
    "advance": ("ERR_ADVANCE_NOT_FOUND", 404),
    "levy": ("ERR_LEVY_NOT_FOUND", 404),
    "payment": ("ERR_PAYMENT_NOT_FOUND", 404),
    "application": ("ERR_APPLICATION_NOT_FOUND", 404),
    "violation": ("ERR_VIOLATION_NOT_FOUND", 404),
    "event": ("ERR_EVENT_NOT_FOUND", 404),
    "rsvp": ("ERR_RSVP_NOT_FOUND", 404),
    "appointment": ("ERR_APPOINTMENT_NOT_FOUND", 404),
    "resident": ("ERR_RESIDENT_NOT_FOUND", 404),
    "notice": ("ERR_NOTICE_NOT_FOUND", 404),
    "board_seat": ("ERR_BOARD_SEAT_NOT_FOUND", 404),
}


def not_found(kind):
    eid, code = NOT_FOUND[kind]
    err(eid, code, f"{kind} not found")


def invalid_state(msg="Invalid state for requested transition"):
    err("ERR_INVALID_STATE", 409, msg)


def validation(msg="Request validation failed"):
    err("ERR_VALIDATION", 400, msg)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.communities = {}
        self.phases = {}
        self.amenities = {}
        self.builders = {}
        self.agreements = {}
        self.tranches = {}
        self.lots = {}
        self.closings = {}
        self.budgets = {}
        self.line_items = {}
        self.rates = {}
        self.districts = {}
        self.advances = {}
        self.levies = {}
        self.payments = {}
        self.applications = {}
        self.violations = {}
        self.events = {}
        self.rsvps = {}
        self.appointments = {}
        self.residents = {}
        self.notices = {}
        self.board_seats = {}
        # logical clock
        self.clock = None  # set below after _parse_dt is defined
        # wall-clock monotonic timestamp generator state
        self._last_wall_ms = 0

    # ---- wall-clock timestamps (created_at / updated_at / meta) ----
    def wall_now(self):
        """Strictly increasing wall-clock UTC datetime (millisecond precision)."""
        with self.lock:
            now = datetime.now(timezone.utc)
            ms = int(now.timestamp() * 1000)
            if ms <= self._last_wall_ms:
                ms = self._last_wall_ms + 1
            self._last_wall_ms = ms
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    def now(self):
        """The logical clock."""
        return self.clock


DB = Store()


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def _parse_dt(value):
    """Parse an ISO-8601 datetime; returns aware UTC datetime or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(value):
    dt = _parse_dt(value)
    if dt is None:
        validation(f"Malformed datetime: {value!r}")
    return dt


def iso(dt):
    """Serialize an aware UTC datetime with exactly 3 fractional digits and Z."""
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    s += f"{dt.microsecond // 1000:03d}Z"
    return s


def calendar_days(start, end):
    """Calendar days from start to end (date-based difference)."""
    return (end.date() - start.date()).days


def add_years(dt, k):
    try:
        return dt.replace(year=dt.year + k)
    except ValueError:
        # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + k, day=28)


# Logical clock initial value (now that _parse_dt is defined).
DB.clock = _parse_dt(DEFAULT_CLOCK_STR)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def dec_num(value):
    """Convert a Decimal to a plain int/float for JSON output."""
    d = Decimal(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": iso(DB.wall_now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def actor():
    """Authenticate the request; returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ALL_ROLES or not user_id:
        err("ERR_UNAUTHENTICATED", 401,
            "X-User-Role missing/unknown or X-User-ID missing")
    return user_id, role


def require_roles(role, roles):
    if role not in roles:
        err("ERR_FORBIDDEN_ROLE", 403,
            f"Role {role} is not authorized for this endpoint")


# ---------------------------------------------------------------------------
# Request-body helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        validation("Request body must be a JSON object")
    return data


def check_no_undeclared(data, allowed):
    for key in data:
        if key not in allowed:
            validation(f"Undeclared field: {key}")


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        validation(f"Field {field} is required and must be a non-empty string")
    return v


def opt_string(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        validation(f"Field {field} must be a string")
    return v


def req_int(data, field, minimum=None, gt=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        validation(f"Field {field} is required and must be an integer")
    if minimum is not None and v < minimum:
        validation(f"Field {field} must be >= {minimum}")
    if gt is not None and v <= gt:
        validation(f"Field {field} must be > {gt}")
    return v


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        validation(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        validation(f"Field {field} must be >= {minimum}")
    return v


def req_number(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        validation(f"Field {field} is required and must be a number")
    if minimum is not None and v < minimum:
        validation(f"Field {field} must be >= {minimum}")
    return v


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        validation(f"Field {field} must be a boolean")
    return v


def req_enum(data, field, members):
    v = data.get(field)
    if not isinstance(v, str) or v not in members:
        validation(f"Field {field} must be one of {sorted(members)}")
    return v


def req_datetime(data, field):
    v = data.get(field)
    if v is None:
        validation(f"Field {field} is required")
    return parse_dt(v)


def opt_datetime(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return parse_dt(data[field])


def opt_id(data, field):
    """Optional FK id: present-and-string -> value; absent/null -> None.
    Present-but-wrong-type -> validation error."""
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if not isinstance(v, str):
        validation(f"Field {field} must be a string id")
    return v


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------
def new_id():
    return uuid.uuid4().hex


def new_entity():
    now = DB.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = DB.now()


def get_or_404(kind, collection, rid):
    ent = collection.get(rid) if isinstance(rid, str) else None
    if ent is None:
        not_found(kind)
    return ent


def check_body_fk(kind, collection, value):
    """Body FK existence (only when a string id was supplied)."""
    if value is None:
        return None
    return get_or_404(kind, collection, value)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination_params():
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            validation("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            validation("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def filter_args(allowed):
    """Extract recognized filter query params; values are strings."""
    out = {}
    for name in allowed:
        v = request.args.get(name)
        if v is not None:
            out[name] = v
    return out


def paginate(items, sort_key=None):
    if sort_key is not None:
        items = sorted(items, key=sort_key)
    else:
        items = sorted(items, key=lambda e: e["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, total, limit, offset)
