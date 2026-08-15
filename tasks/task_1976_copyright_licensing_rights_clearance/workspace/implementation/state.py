"""Core state, envelope, auth, clock, and validation helpers.

In-memory only. The store starts empty on every boot — nothing is seeded.
Logical clock (PRD 2.5) defaults to exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time.
"""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta

from flask import Flask, request, g, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (empty at boot; no seeding)
# ---------------------------------------------------------------------------
rights_holders = {}          # id -> RightsHolder
assets = {}                  # id -> Asset
diligence_logs = {}          # id -> RightsDiligenceLog
clearance_requests = {}      # id -> ClearanceRequest
negotiation_rounds = {}      # id -> NegotiationRound
licenses = {}                # id -> License
usage_reservations = {}      # id -> UsageReservation
usage_events = {}            # id -> UsageEvent
license_payments = {}        # id -> LicensePayment
fair_use_assessments = {}    # id -> FairUseAssessment
takedown_notices = {}        # id -> TakedownNotice
renewal_alerts = {}          # id -> RenewalAlert

_seq = [0]

# Logical clock (PRD 2.5)
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

ROLES = {
    "Requester", "ClearanceOfficer", "Negotiator", "FinancePayer",
    "IngestionAgent", "LegalCertifier", "AssetCurator", "RightsHolderRep",
}
ENTITY_BACKED_ROLES = {"RightsHolderRep"}  # X-User-ID must equal a RightsHolder id

# --- Enum vocabularies -----------------------------------------------------
WORK_KINDS = {"MUSICAL_COMPOSITION", "SOUND_RECORDING", "FILM_CLIP",
              "STILL_IMAGE", "LITERARY_EXCERPT"}
MEDIA_KINDS = {"BROADCAST_TV", "STREAMING", "THEATRICAL", "RADIO",
               "SOCIAL", "PRINT"}
TERRITORIES = {"NA", "EMEA", "LATAM", "APAC", "WORLD"}
HOLDER_KINDS = {"PUBLISHER", "LABEL", "ESTATE", "COLLECTIVE", "INDIVIDUAL"}
SEARCH_CHANNELS = {"COPYRIGHT_OFFICE", "PERFORMING_RIGHTS_ORG", "UNION_GUILD",
                   "COMMERCIAL_DATABASE", "DIRECT_OUTREACH"}
DILIGENCE_OUTCOMES = {"HOLDER_FOUND", "NO_RESULT", "CONFLICTING_CLAIM"}

# --- Calculation constants (PRD 3 / scaffold §1.3) --------------------------
MEDIA_UNIT_RATE_CENTS = {
    "BROADCAST_TV": 50000, "STREAMING": 12000, "THEATRICAL": 80000,
    "RADIO": 8000, "SOCIAL": 3000, "PRINT": 5000,
}
TERRITORY_WEIGHT = {"NA": 1.0, "EMEA": 1.4, "LATAM": 0.8, "APAC": 1.2,
                    "WORLD": 3.0}
BULK_UNITS_MIN = 100
BULK_DISCOUNT = 0.10
MAX_NEGOTIATION_ROUNDS = 5
HOLD_TTL_HOURS = 720
RENEWAL_ALERT_LEAD_DAYS = 30
DMCA_COUNTER_WINDOW_DAYS = 10
EMBARGO_BUFFER_DAYS = 30
ORPHAN_MIN_CHANNELS = 3
ORPHAN_MIN_SPAN_DAYS = 30
FAIR_USE_CERTIFY_MIN = 13


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, msg):
    return ApiError(error_id, status, msg)


# ---------------------------------------------------------------------------
# Time helpers — all comparisons at second precision (PRD 2.5)
# ---------------------------------------------------------------------------
def now_dt():
    """The desk's logical clock (never wall-clock)."""
    return CLOCK["now"]


def wall_now_dt():
    return datetime.now(timezone.utc)


def ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits and Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO8601 string into an aware UTC datetime at second precision, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # truncate to second precision per PRD 2.5
    return dt.replace(microsecond=0)


def whole_days(a, b):
    """Whole-day length of window [a, b)."""
    delta = b - a
    return delta.days


# ---------------------------------------------------------------------------
# Identity / sequencing
# ---------------------------------------------------------------------------
def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Common audit triple for mutable resources (PRD 2.4)."""
    t = now_dt()
    entity["id"] = new_id()
    entity["created_at"] = t
    entity["updated_at"] = t
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def stamp_new_lean(entity):
    """Append-only ledger rows carry only id + created_at (PRD 2.4)."""
    t = now_dt()
    entity["id"] = new_id()
    entity["created_at"] = t
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Bump version + refresh updated_at on a mutable resource."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_dt()


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(20)),
        "api_request_timestamp": ts3(wall_now_dt()),
    }


def envelope_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def envelope_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def envelope_error(err_obj):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err_obj.error_id, "message": err_obj.message},
    }
    return jsonify(body), err_obj.http_status


@app.errorhandler(404)
def _nf(e):
    return envelope_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _mna(e):
    return envelope_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(500)
def _ise(e):
    return envelope_error(ApiError("ERR_INVALID_REQUEST", 500, "Internal error"))


# ---------------------------------------------------------------------------
# Auth (PRD 2.1) and route wrapper
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or undeclared X-User-Role header")
    if role in ENTITY_BACKED_ROLES:
        if not uid:
            raise ApiError("ERR_UNAUTHENTICATED", 401,
                           "X-User-ID required for entity-backed role")
    # For opaque roles X-User-ID is still required whenever the workflow
    # anchors an actor (requester_id / payer_id / etc.); require it universally
    # so ownership and segregation checks always have a value to compare.
    if not uid:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID header required")
    return uid, role


class _ListResult:
    def __init__(self, items, limit, offset, total):
        self.items = items
        self.limit = limit
        self.offset = offset
        self.total = total


def list_result(items, limit, offset, total):
    return _ListResult(items, limit, offset, total), 200


def endpoint(path, methods, roles):
    """Route wrapper: auth -> role -> handler -> envelope."""
    def deco(fn):
        def wrapper(**kwargs):
            try:
                uid, role = authenticate()
                if roles is not None and role not in roles:
                    raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                                   "Role %s may not perform this operation" % role)
                result, status = fn(user_id=uid, user_role=role, **kwargs)
                if isinstance(result, _ListResult):
                    return envelope_list(result.items, result.limit,
                                         result.offset, result.total)
                return envelope_object(result, status)
            except ApiError as e:
                return envelope_error(e)
        wrapper.__name__ = fn.__name__
        app.add_url_rule(path, fn.__name__, wrapper, methods=methods)
        return fn
    return deco


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return list_result(page, limit, offset, total)


def request_args_get(name):
    return request.args.get(name)


# ---------------------------------------------------------------------------
# Body validation (schema tier, PRD 2.8 rung 3)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True, force=False)
    if data is None:
        data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Request body must be a JSON object")
    return data


def is_intlike(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer()
    return False


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is required and must be a string" % name)
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a string" % name)
    return v


def req_enum(body, name, options):
    v = body.get(name)
    if not isinstance(v, str) or v not in options:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be one of %s" % (name, sorted(options)))
    return v


def req_int(body, name, min_v=None):
    v = body.get(name)
    if not is_intlike(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is required and must be an integer" % name)
    iv = int(v)
    if min_v is not None and iv < min_v:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be >= %d" % (name, min_v))
    return iv


def opt_int(body, name, min_v=None):
    v = body.get(name)
    if v is None:
        return None
    if not is_intlike(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an integer" % name)
    iv = int(v)
    if min_v is not None and iv < min_v:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be >= %d" % (name, min_v))
    return iv


def req_dt(body, name):
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a well-formed ISO8601 datetime" % name)
    return dt


def opt_dt(body, name):
    v = body.get(name)
    if v is None:
        return None
    dt = parse_dt(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a well-formed ISO8601 datetime" % name)
    return dt


def opt_bool(body, name, default=False):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be a boolean" % name)
    return v
