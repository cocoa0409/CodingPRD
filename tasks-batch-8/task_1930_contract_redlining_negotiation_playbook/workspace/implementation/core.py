"""Core infrastructure: in-memory store, logical clock, envelope, auth, errors."""
import hashlib
import random
import string
import uuid
from datetime import datetime, timezone

from flask import request, jsonify

# --------------------------------------------------------------------------
# In-memory store (no persistence; fresh on every process boot)
# --------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.playbooks = {}
        self.clauses = {}
        self.contract_types = {}
        self.counterparties = {}
        self.users = {}
        self.intakes = {}
        self.triage_decisions = {}
        self.negotiations = {}
        self.rounds = {}
        self.deviations = {}
        self.decisions = {}
        self.packets = {}
        self.obligations = {}
        self.seq = 0


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_now = [CLOCK_START]


def now():
    return _now[0]


def set_now(dt):
    _now[0] = dt


# --------------------------------------------------------------------------
# Time utilities
# --------------------------------------------------------------------------


def parse_iso(s):
    """Parse an ISO-8601 string to an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_sec(dt):
    """ISO 8601 UTC at second precision, e.g. 2026-08-01T00:00:00Z"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds_between(a, b):
    return int((b - a).total_seconds())


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_"
        + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": fmt(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

ROLES = [
    "ContractAnalyst",
    "BusinessOwner",
    "LegalCounsel",
    "FinanceController",
    "ChiefCounsel",
    "Signatory",
    "OpsAdmin",
]

ALL_ROLES = list(ROLES)

# Approver authority ladder (low -> high)
LADDER = {
    "LEGAL_COUNSEL": 1,
    "BUSINESS_OWNER": 2,
    "FINANCE_CONTROLLER": 3,
    "CHIEF_COUNSEL": 4,
}


def authenticate(allowed_roles):
    """Validation pipeline steps 1-3: headers -> user resolution -> role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        uid is None
        or role is None
        or not isinstance(uid, str)
        or not isinstance(role, str)
        or uid.strip() == ""
        or role.strip() == ""
        or role not in ROLES
    ):
        err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and must be well-formed.",
        )
    user = None
    if role != "OpsAdmin":
        user = db.users.get(uid)
        if user is None or user.get("status") != "ACTIVE":
            err(
                "ERR_USER_NOT_FOUND",
                401,
                "X-User-ID does not resolve to an ACTIVE User.",
            )
    if role not in allowed_roles:
        err(
            "ERR_FORBIDDEN_FOR_ROLE",
            403,
            "Role %s is not permitted on this endpoint." % role,
        )
    return user, role


# --------------------------------------------------------------------------
# Body / path helpers
# --------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def get_or_404(coll, entity_id):
    ent = coll.get(entity_id)
    if ent is None:
        err("ERR_NOT_FOUND", 404, "Resource %s not found." % entity_id)
    return ent


def require_fields(b, fields):
    for f in fields:
        if f not in b or b[f] is None:
            err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % f)


# --------------------------------------------------------------------------
# Entity helpers
# --------------------------------------------------------------------------


def stamp_new(e):
    """Common system fields for mutable resources."""
    ts = fmt(now())
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def stamp_audit(e):
    """Immutable audit records carry only id + created_at."""
    e["created_at"] = fmt(now())
    e["_seq"] = next_seq()
    return e


def touch(e):
    e["updated_at"] = fmt(now())
    e["version"] = e.get("version", 1) + 1


def pub(e):
    """Strip internal fields (prefixed with _) before serialization."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


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
    items = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(items)
    page = items[offset : offset + limit]
    page_info = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [pub(e) for e in page], page_info


def apply_filters(items, filters):
    """filters: list of (query_param_name, entity_field_name)."""
    out = []
    for e in items:
        keep = True
        for param, field in filters:
            v = request.args.get(param)
            if v is None:
                continue
            ev = e.get(field)
            if ev is None or str(ev) != v:
                keep = False
                break
        if keep:
            out.append(e)
    return out
