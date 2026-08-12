"""Core infrastructure: in-memory store, logical clock, response envelope,
errors, auth, validation helpers, serialization, pagination."""

import random
import string
import uuid
from datetime import datetime, timezone

from flask import request, jsonify

# ---------------------------------------------------------------- errors ---

ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_FORBIDDEN = "ERR_FORBIDDEN_FOR_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE_TRANSITION"
ERR_GAS_FREE_LIMITS = "ERR_GAS_FREE_LIMITS_EXCEEDED"
ERR_NO_VALID_CERT = "ERR_NO_VALID_GAS_FREE_CERT"
ERR_CERT_EXPIRED = "ERR_CERT_EXPIRED"
ERR_CERT_ALREADY_REVALIDATED = "ERR_CERT_ALREADY_REVALIDATED"
ERR_SOD = "ERR_SEGREGATION_OF_DUTIES"
ERR_CONTRACTOR_NOT_QUALIFIED = "ERR_CONTRACTOR_NOT_QUALIFIED"
ERR_INCOMPATIBLE_CHANGEOVER = "ERR_INCOMPATIBLE_CHANGEOVER"
ERR_WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"
ERR_WINDOW_BUFFER = "ERR_WINDOW_BUFFER_VIOLATION"
ERR_WINDOW_NOT_ACTIVE = "ERR_WINDOW_NOT_ACTIVE"
ERR_WINDOW_UNAVAILABLE = "ERR_WINDOW_UNAVAILABLE"
ERR_WINDOW_LINKED = "ERR_WINDOW_LINKED"
ERR_TANK_NOT_IN_SERVICE = "ERR_TANK_NOT_IN_SERVICE"
ERR_WASTE_PROFILE_NOT_APPROVED = "ERR_WASTE_PROFILE_NOT_APPROVED"
ERR_PROFILE_ALREADY_APPROVED = "ERR_PROFILE_ALREADY_APPROVED"
ERR_SHIPMENT_PROFILE_MISMATCH = "ERR_SHIPMENT_PROFILE_MISMATCH"
ERR_NO_DELIVERED_SHIPMENT = "ERR_NO_DELIVERED_SHIPMENT"
ERR_NO_VALID_ENTRY_PERMIT = "ERR_NO_VALID_ENTRY_PERMIT"
ERR_ATMOSPHERE_NOT_CLEAR = "ERR_ATMOSPHERE_NOT_CLEAR"
ERR_PERMITS_NOT_CLOSED = "ERR_PERMITS_NOT_CLOSED"
ERR_JOB_HAS_ACTIVE_PERMIT = "ERR_JOB_HAS_ACTIVE_PERMIT"
ERR_INSPECTOR_UNAVAILABLE = "ERR_INSPECTOR_UNAVAILABLE"
ERR_CRITICAL_FINDINGS_OPEN = "ERR_CRITICAL_FINDINGS_OPEN"
ERR_FINDING_NOT_RISK_ACCEPTABLE = "ERR_FINDING_NOT_RISK_ACCEPTABLE"
ERR_NO_REWORKABLE_FINDINGS = "ERR_NO_REWORKABLE_FINDINGS"
ERR_FLUSH_VOLUME_INSUFFICIENT = "ERR_FLUSH_VOLUME_INSUFFICIENT"
ERR_MASS_BALANCE = "ERR_MASS_BALANCE_OUT_OF_TOLERANCE"
ERR_DISCHARGE_LIMITS = "ERR_DISCHARGE_LIMITS_EXCEEDED"
ERR_DISCHARGE_CAPACITY = "ERR_DISCHARGE_CAPACITY_EXCEEDED"


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ----------------------------------------------------------------- store ---


class Store:
    """Purely in-memory store. A fresh process starts completely empty."""

    def __init__(self):
        self.terminals = {}
        self.products = {}
        self.tanks = {}
        self.contractors = {}
        self.safety_events = {}
        self.cleaning_jobs = {}
        self.service_windows = {}
        self.waste_profiles = {}
        self.waste_shipments = {}
        self.gas_free_certs = {}
        self.entry_permits = {}
        self.inspectors = {}
        self.inspections = {}
        self.findings = {}
        self.repair_orders = {}
        self.wastewater_batches = {}
        self.seq = 0
        # Logical clock: exactly 2026-05-01T00:00:00Z before any clock call.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def now():
    return db.clock


def next_seq():
    db.seq += 1
    return db.seq


# ------------------------------------------------------------------ time ---


def iso(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(v, field):
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"{field} must be an ISO 8601 datetime string")
    s = v.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# -------------------------------------------------------------- entities ---


def create_entity(fields, common=True):
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    e["created_at"] = now()
    if common:
        e["updated_at"] = now()
        e["version"] = 1
    e["_seq"] = next_seq()
    return e


def touch(e):
    """Every mutation refreshes updated_at and advances version by exactly one."""
    if "version" in e:
        e["version"] += 1
        e["updated_at"] = now()


def _ser_val(v):
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, list):
        return [_ser_val(x) for x in v]
    if isinstance(v, dict):
        return {k: _ser_val(x) for k, x in v.items()}
    return v


def ser(e):
    return {k: _ser_val(v) for k, v in e.items() if not k.startswith("_")}


def get_or_404(collection, entity_id, label="resource"):
    e = collection.get(entity_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{label} not found: {entity_id}")
    return e


# -------------------------------------------------------------- envelope ---


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=16)),
        "api_request_timestamp": iso(now()),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


# ------------------------------------------------------------ pagination ---


def paginate(items):
    """items: full sorted list. Applies limit/offset from the query string."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def sorted_all(collection):
    return sorted(collection.values(),
                  key=lambda e: (e["created_at"], e["_seq"]))


def apply_filters(items, filters):
    """filters: list of (query_param, field_name). Exact string match."""
    for param, field in filters:
        val = request.args.get(param)
        if val is not None:
            items = [e for e in items if e.get(field) is not None
                     and str(e.get(field)) == val]
    return items


# ------------------------------------------------------------------ auth ---

ROLES = {
    "TerminalAdmin",
    "TerminalOperator",
    "ContractorSupervisor",
    "MarineChemist",
    "EHSOfficer",
    "API653Inspector",
    "LabTechnician",
}

ALL_ROLES = tuple(sorted(ROLES))


def auth():
    """Priority 1: headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_AUTH, 400,
                       "X-User-ID and a valid X-User-Role header are required")
    return uid, role


def require_role(role, allowed):
    """Priority 2: role admission."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403,
                       f"role {role} is not permitted for this endpoint")


def forbid(msg="ownership check failed"):
    raise ApiError(ERR_FORBIDDEN, 403, msg)


# ------------------------------------------------------------- body utils ---


def body_json():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return b


def need(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {name}")
    return body[name]


def as_int(v, name):
    if isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a number")
    return float(v)


def as_str(v, name):
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a boolean")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"{name} must be one of {sorted(allowed)}")
    return v


def req_int(body, name):
    return as_int(need(body, name), name)


def req_num(body, name):
    return as_num(need(body, name), name)


def req_str(body, name):
    return as_str(need(body, name), name)


def req_enum(body, name, allowed):
    return as_enum(need(body, name), name, allowed)


def req_dt(body, name):
    return parse_dt(need(body, name), name)
