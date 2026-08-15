import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext
from functools import wraps

from flask import g, jsonify, request

getcontext().prec = 60

ROLES = (
    "PanelManager",
    "SurveyDesigner",
    "DataAnalyst",
    "IncentiveClerk",
    "PrivacyOfficer",
    "DepartmentLiaison",
)
AGE_BANDS = ("AGE_18_29", "AGE_30_44", "AGE_45_64", "AGE_65_PLUS")
TENURES = ("RENTER", "OWNER")

ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# The logical clock starts exactly at 2026-08-01T00:00:00Z and never reads
# wall-clock time; it advances only via POST /_clock/set_current_utc.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


class Store:
    """Pure in-memory store. Starts empty on every boot; no seeding."""

    def __init__(self):
        self.cells = {}
        self.panelists = {}
        self.instruments = {}
        self.translations = {}
        self.waves = {}
        self.invitations = {}
        self.responses = {}
        self.awards = {}
        self.snapshots = {}
        self.publications = {}
        self.commitments = {}
        self.holds = {}
        self.runs = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


db = Store()


def now():
    return db.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an ISO 8601 timestamp string" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_req_id():
    return "req_" + uuid.uuid4().hex[:24]


def meta():
    return {"api_request_id": new_req_id(), "api_request_timestamp": iso(now())}


def ok(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def ok_list(items, total, limit, offset):
    m = meta()
    m.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    })
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_response(exc):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "X-User-ID and X-User-Role headers are required")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                               "Role %s is not permitted for this endpoint" % role)
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def _present(data, name):
    if name not in data or data[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: %s" % name)
    return data[name]


def req_str(data, name):
    v = _present(data, name)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be a string" % name)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_str(data, name)


def req_int(data, name, min_value=None):
    v = _present(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be >= %d" % (name, min_value))
    return v


def opt_int(data, name, default=None, min_value=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, min_value)


def req_num(data, name):
    v = _present(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be a number" % name)
    return v


def req_enum(data, name, allowed):
    v = _present(data, name)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be one of %s" % (name, list(allowed)))
    return v


def req_list_str(data, name):
    v = _present(data, name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an array of strings" % name)
    return v


# ---------------------------------------------------------------------------
# Resource spine, sorting, pagination
# ---------------------------------------------------------------------------

def new_resource():
    db.seq += 1
    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.seq,
    }


def touch(res):
    res["updated_at"] = now()
    res["version"] += 1


def sorted_items(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    return items[offset:offset + limit], total, limit, offset


def list_response(items, serializer):
    ordered = sorted_items(items)
    page, total, limit, offset = paginate(ordered)
    return ok_list([serializer(r) for r in page], total, limit, offset)


def round6(d):
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def round6f(d):
    return float(round6(d))
