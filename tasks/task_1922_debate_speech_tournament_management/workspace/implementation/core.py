"""Core plumbing: in-memory store, logical clock, timestamps, envelope, auth."""
import math
import secrets
import string
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------------------
# In-memory store. Starts empty on every boot; never seeded.
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.tournaments = {}
        self.schools = {}
        self.divisions = {}
        self.entries = {}
        self.judges = {}
        self.judge_conflicts = {}
        self.rooms = {}
        self.rounds = {}
        self.pairings = {}
        self.pairing_entries = {}
        self.ballots = {}
        self.contracts = {}
        self.orders = {}
        self.lock = threading.RLock()


db = Store()

# ---------------------------------------------------------------------------
# Logical UTC clock. Default exactly 2026-08-01T00:00:00Z; never wall clock.
# ---------------------------------------------------------------------------


class LogicalClock:
    def __init__(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


clock = LogicalClock()

# ---------------------------------------------------------------------------
# Wall-clock timestamps for created_at / updated_at / request meta.
# Strictly increasing so created_at ASC ordering is deterministic.
# ---------------------------------------------------------------------------

_ts_lock = threading.Lock()
_last_ts_ms = [0]


def now_ts():
    with _ts_lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ts_ms[0]:
            ms = _last_ts_ms[0] + 1
        _last_ts_ms[0] = ms
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    """Canonical ISO-8601 UTC rendering; seconds precision when exact."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = dt.microsecond // 1000
    if dt.microsecond % 1000 == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % ms
    return dt.isoformat().replace("+00:00", "Z")


def parse_dt(value):
    """Parse an ISO-8601 datetime string (accepts trailing Z). Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def req_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(24))


# ---------------------------------------------------------------------------
# Errors and response envelope.
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def make_meta(pagination=None):
    meta = {"api_request_id": req_id(), "api_request_timestamp": now_ts()}
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, code=200, pagination=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": make_meta(pagination), "response_type": rtype, "data": data}
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / roles.
# ---------------------------------------------------------------------------

ROLES = {"TournamentDirector", "TabStaff", "SchoolCoach", "Judge"}


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and role must be recognized",
        )
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role %s is not authorized for this endpoint" % role)


def get_body():
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_VALIDATION", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
        return data
    return {}


def validation_error(message):
    return ApiError("ERR_VALIDATION", 400, message)


# ---------------------------------------------------------------------------
# Pagination.
# ---------------------------------------------------------------------------


def parse_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, serializer):
    """items: full sorted list. Returns (data, pagination-meta-dict)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [serializer(x) for x in page], meta


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(obj):
    obj["version"] = obj.get("version", 0) + 1
    obj["updated_at"] = now_ts()


def touch_if_changed(obj, changed):
    if changed:
        touch(obj)
