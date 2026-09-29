"""Core infrastructure: response envelope, errors, in-memory store, logical clock,
authentication/authorization, validation helpers and pagination.

Every structural name here is taken from SCAFFOLD.yaml `response_envelope` /
`validations` and from PRD sections 2.1-2.9.
"""

import itertools
import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role may not invoke this endpoint.",
    "ERR_NOT_LEASE_TENANT": "The acting tenant is not the tenant of record on this lease.",
    "ERR_SEGREGATION_OF_DUTIES": "The administrator who activated relief may not waive the kick-out right.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
}


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq_counter = itertools.count(1)
_last_record_dt = None
_record_lock = threading.Lock()


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_z(dt):
    """ISO 8601 UTC; fractional digits only when the instant carries them."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def record_now():
    """Monotonically increasing wall-clock record timestamp (ms resolution)."""
    global _last_record_dt
    with _record_lock:
        dt = datetime.now(timezone.utc)
        dt = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
        if _last_record_dt is not None and dt <= _last_record_dt:
            dt = _last_record_dt + timedelta(milliseconds=1)
        _last_record_dt = dt
        return iso_ms(dt)


def parse_dt(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Arithmetic (PRD 2.5)
# ---------------------------------------------------------------------------


def rhu(num, den):
    """round half up (away from zero) of num/den, both integers, den > 0."""
    num = int(num)
    den = int(den)
    if den == 0:
        return 0
    if den < 0:
        num, den = -num, -den
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def fdiv(num, den):
    """floor(num/den) toward negative infinity; den > 0."""
    num = int(num)
    den = int(den)
    if den == 0:
        return 0
    return num // den


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "centers",
    "tenants",
    "leases",
    "lease_years",
    "sales_reports",
    "sales_exclusions",
    "charges",
    "co_tenancy_clauses",
    "co_tenancy_events",
    "kick_out_clauses",
    "audits",
    "ledger_entries",
)

DB = {name: {} for name in COLLECTIONS}

CLOCK = {"now": DEFAULT_CLOCK}

request_lock = threading.RLock()


def clock_now():
    return CLOCK["now"]


def new_id():
    return str(uuid.uuid4())


def make_record(collection, fields, versioned=True):
    now = record_now()
    rec = {"id": new_id(), "created_at": now}
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = next(_seq_counter)
    DB[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Bump updated_at/version once per request for a mutated resource."""
    if rec is None or "version" not in rec:
        return rec
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if rec["id"] in touched:
        return rec
    touched.add(rec["id"])
    rec["version"] += 1
    rec["updated_at"] = record_now()
    return rec


def all_of(collection):
    return sorted(DB[collection].values(), key=lambda r: r["_seq"])


def find(collection, **kwargs):
    out = []
    for rec in all_of(collection):
        if all(rec.get(k) == v for k, v in kwargs.items()):
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso_z(value)
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, admission ladder steps 1-2)
# ---------------------------------------------------------------------------

ROLES = ("CenterAdmin", "LeaseAdministrator", "TenantUser", "Auditor", "OwnershipAnalyst")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed_roles):
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403)


def endpoint(*allowed_roles):
    """Decorator running admission steps 1 (auth) and 2 (role authorization)."""

    def wrapper(fn):
        def inner(*args, **kwargs):
            authenticate()
            authorize(*allowed_roles)
            return fn(*args, **kwargs)

        inner.__name__ = fn.__name__
        return inner

    return wrapper


# ---------------------------------------------------------------------------
# Body / query validation (admission ladder step 5)
# ---------------------------------------------------------------------------


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        raw = request.get_data(cache=True)
        if raw and raw.strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body is not valid JSON.")
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return payload


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def _present(payload, key):
    return key in payload and payload[key] is not None


def need_int(payload, key, minimum=None, maximum=None, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def need_str(payload, key, required=True, default=None, min_len=1, max_len=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % key)
    return value


def need_enum(payload, key, allowed, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def need_dt(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    parsed = parse_dt(payload[key])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed


# Pagination (PRD 2.3)


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("limit must be an integer.")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("offset must be an integer.")
        if offset < 0:
            bad("offset must be >= 0.")
    return limit, offset


def paginate(rows, serializer=serialize):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def qs_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def qs_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


# ---------------------------------------------------------------------------
# Existence helpers (admission ladder step 3)
# ---------------------------------------------------------------------------

_NOT_FOUND = {
    "centers": "ERR_CENTER_NOT_FOUND",
    "tenants": "ERR_TENANT_NOT_FOUND",
    "leases": "ERR_LEASE_NOT_FOUND",
    "lease_years": "ERR_LEASE_YEAR_NOT_FOUND",
    "sales_reports": "ERR_SALES_REPORT_NOT_FOUND",
    "charges": "ERR_CHARGE_NOT_FOUND",
    "co_tenancy_clauses": "ERR_CO_TENANCY_CLAUSE_NOT_FOUND",
    "co_tenancy_events": "ERR_CO_TENANCY_EVENT_NOT_FOUND",
    "kick_out_clauses": "ERR_KICK_OUT_CLAUSE_NOT_FOUND",
    "audits": "ERR_AUDIT_NOT_FOUND",
}


def must_get(collection, rid):
    if not isinstance(rid, str) or rid not in DB[collection]:
        raise ApiError(_NOT_FOUND[collection], 404)
    return DB[collection][rid]


def get_or_none(collection, rid):
    if not isinstance(rid, str):
        return None
    return DB[collection].get(rid)


def require_lease_tenant(lease):
    """Admission ladder step 4 - tenant ownership (PRD 2.1)."""
    if g.role != "TenantUser":
        return
    if lease is None or g.user_id != lease.get("tenant_id"):
        raise ApiError("ERR_NOT_LEASE_TENANT", 403)
