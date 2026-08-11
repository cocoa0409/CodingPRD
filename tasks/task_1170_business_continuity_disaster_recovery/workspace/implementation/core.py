"""Core infrastructure: in-memory store, logical clock, envelope, auth, validation.

PRD references: §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §2.4 (clock),
§2.5 (common fields), §2.7 (precision), §2.9 (not-found), §2.10 (precedence).
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, make_response, request

# --------------------------------------------------------------------------
# In-memory store (never persisted, never seeded)
# --------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.contacts = {}
        self.processes = {}
        self.bias = {}
        self.plans = {}
        self.sections = {}
        self.dependencies = {}
        self.third_parties = {}
        self.assessments = {}
        self.sites = {}
        self.reservations = {}
        self.exercises = {}
        self.findings = {}
        self.capabilities = {}
        self.runs = {}
        self.gaps = {}
        self.nodes = {}
        self.activations = {}
        self.notifications = {}
        self.attestations = {}
        self.seq = 0            # global insertion counter (stable ordering)
        self.tick_ms = 0        # monotonic ms offset applied to the clock
        # Logical program clock — fixed default per PRD §2.4.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-05-01T00:00:00Z"


DB = Store()
LOCK = threading.RLock()

ROLES = [
    "ResilienceAdmin", "BIAAnalyst", "PlanAuthor", "PlanApprover",
    "RiskCommittee", "ExerciseOfficer", "SiteCoordinator", "VendorManager",
    "CrisisOfficer", "AttestationSigner",
]
ALL_ROLES = list(ROLES)


# --------------------------------------------------------------------------
# Clock helpers
# --------------------------------------------------------------------------

def now_dt():
    """Current logical program time (never wall clock)."""
    return DB.clock


def tick_dt():
    """Logical time plus a monotonically increasing ms offset.

    Guarantees unique, creation-ordered created_at/updated_at values even
    though the logical clock is fixed between explicit sets.
    """
    DB.tick_ms += 1
    return DB.clock + timedelta(milliseconds=DB.tick_ms)


def next_seq():
    DB.seq += 1
    return DB.seq


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


# --------------------------------------------------------------------------
# Datetime parsing / formatting (ISO 8601 UTC, three fractional digits)
# --------------------------------------------------------------------------

def parse_dt(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar month addition (used for FRESHNESS_MONTHS = 12)."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, [31,
                       29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


# --------------------------------------------------------------------------
# Errors and response envelope
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(now_dt()),
    }


def ok(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return make_response(jsonify(body), status)


def err_response(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return make_response(jsonify(body), error.http_status)


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def not_found(error_id, what):
    fail(error_id, 404, f"{what} not found")


# --------------------------------------------------------------------------
# Auth (PRD §2.1)
# --------------------------------------------------------------------------

def actor(roles, sod_identity=False):
    """Authenticate + authorize the request.

    sod_identity: the endpoint performs an ownership / segregation-of-duties
    comparison, so an entity-backed role's X-User-ID must resolve to an
    existing Contact (ERR_UNAUTHORIZED otherwise).
    """
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        fail("ERR_UNAUTHENTICATED", 401,
             "Missing or unknown X-User-Role / X-User-ID headers")
    if role not in roles:
        fail("ERR_UNAUTHORIZED", 403,
             f"Role {role} is not permitted on this endpoint")
    if sod_identity and role != "ResilienceAdmin" and uid not in DB.contacts:
        fail("ERR_UNAUTHORIZED", 403,
             "Entity-backed identity does not resolve to an existing Contact")
    return {"role": role, "id": uid}


# --------------------------------------------------------------------------
# Body / field validation (PRD §2.10 layers 4-5)
# --------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req(body_dict, field):
    if field not in body_dict or body_dict[field] is None:
        fail("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return body_dict[field]


def validation(message, status=400):
    fail("ERR_VALIDATION", status, message)


def as_str(value, field):
    if not isinstance(value, str):
        validation(f"Field {field} must be a string")
    return value


def opt_str(body_dict, field):
    if field not in body_dict or body_dict[field] is None:
        return None
    return as_str(body_dict[field], field)


def as_int(value, field, minv=None, maxv=None):
    if isinstance(value, bool) or not isinstance(value, int):
        validation(f"Field {field} must be an integer")
    if minv is not None and value < minv:
        validation(f"Field {field} must be >= {minv}")
    if maxv is not None and value > maxv:
        validation(f"Field {field} must be <= {maxv}")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        validation(f"Field {field} must be a boolean")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        validation(f"Field {field} must be one of {', '.join(allowed)}")
    return value


def as_dt(value, field):
    dt = parse_dt(value)
    if dt is None:
        validation(f"Field {field} must be an ISO 8601 UTC timestamp")
    return dt


def as_num(value, field, minv=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        validation(f"Field {field} must be a number")
    dec = Decimal(str(value))
    if minv is not None and dec < Decimal(str(minv)):
        validation(f"Field {field} must be >= {minv}")
    return dec


def money2(value):
    """Round-half-up to exactly 2 decimal places (PRD §2.7)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit (default 10, 1..100), offset (default 0)
# --------------------------------------------------------------------------

def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


def apply_filters(items, filters):
    """filters: list of (query_param, entity_field) — exact match."""
    out = list(items)
    for param, field in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [e for e in out if str(e.get(field)) == raw]
    return out


# --------------------------------------------------------------------------
# Entity helpers
# --------------------------------------------------------------------------

def stamp_new(entity):
    ts = tick_dt()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def bump(entity):
    """Standard mutation: version +1 and updated_at refresh (PRD §2.5)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = tick_dt()
