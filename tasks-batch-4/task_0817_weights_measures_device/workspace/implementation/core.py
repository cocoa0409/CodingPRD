"""Core infrastructure: in-memory store, logical clock, errors, response
envelope, auth, pagination, and serialization helpers.

Everything structural (header names, envelope field names, pagination params,
error ids) is taken verbatim from PRD.md / SCAFFOLD.yaml.
"""

import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Logical clock + in-memory store (starts empty on every boot; NO seeding)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.establishments = {}
        self.inspectors = {}
        self.devices = {}
        self.inspections = {}
        self.test_readings = {}
        self.audit_items = {}
        self.complaints = {}
        self.seals = {}
        self.condemnations = {}
        self.penalties = {}
        self.fee_invoices = {}
        self._seq = 0
        self._seal_seq = 0
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_seal_number(self):
        self._seal_seq += 1
        return "SEAL-%06d" % self._seal_seq


store = Store()


def now():
    return store.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def new_id():
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO8601 UTC timestamp; raise ApiError(ERR_VALIDATION) on failure."""
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_VALIDATION", "invalid timestamp")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "invalid timestamp: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_SCHEDULE_WINDOW_INVALID": 400,
    "ERR_ESTABLISHMENT_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_PENALTY_NOT_FOUND": 404,
    "ERR_FEE_INVOICE_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_DEVICE_NOT_TESTABLE": 409,
    "ERR_DEVICE_RETIRED": 409,
    "ERR_INSPECTION_NOT_IN_PROGRESS": 409,
    "ERR_ESTABLISHMENT_SUSPENDED": 409,
    "ERR_PENALTY_NOT_PAYABLE": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_STALE_DEVICE_VERSION": 412,
    "ERR_COMPLAINT_REQUIRED": 409,
    "ERR_INSPECTOR_SCHEDULE_CONFLICT": 409,
    "ERR_DEVICE_RETEST_BUFFER": 409,
    "ERR_NO_READINGS": 422,
    "ERR_INSUFFICIENT_SAMPLE": 422,
    "ERR_DEVICE_HAS_ACTIVE_INSPECTION": 409,
    "ERR_SUSPEND_REQUIRES_BALANCE": 409,
    "ERR_OUTSTANDING_BALANCE": 409,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _make_meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": iso(now())}


def respond_object(data, status=200):
    body = {"meta": _make_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(items, limit, offset, total, status=200):
    meta = _make_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def respond_error(err):
    meta = _make_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

VALID_ROLES = {"ProgramAdmin", "Inspector", "Establishment"}


def authorize(allowed_roles):
    """Authenticate (both headers present, role valid) then authorize (role
    permitted for this operation). Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s not permitted for this operation" % role)
    return role, uid


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------

def get_body(optional=True):
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise ApiError("ERR_VALIDATION", "Malformed JSON body")
        if data is None:
            raise ApiError("ERR_VALIDATION", "Malformed JSON body")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", "Body must be a JSON object")
        return data
    if optional:
        return {}
    raise ApiError("ERR_VALIDATION", "Request body required")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % f)


def require_string(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    v = require_string(body, field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items already sorted; apply limit/offset. Returns (page, limit, offset, total)."""
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize(entity):
    if entity is None:
        return {}
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_many(entities):
    return [serialize(e) for e in entities]


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def base_common(kind):
    ts = iso(now())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
        "_type": kind,
    }


def base_line_item(kind):
    """TestReading / ScannerAuditItem carry only id + created_at."""
    return {
        "id": new_id(),
        "created_at": iso(now()),
        "_seq": store.next_seq(),
        "_type": kind,
    }


def touch(entity):
    entity["updated_at"] = iso(now())
    entity["version"] = entity.get("version", 1) + 1
