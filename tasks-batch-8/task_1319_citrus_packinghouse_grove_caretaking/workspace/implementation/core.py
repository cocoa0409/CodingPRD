"""Core plumbing: logical clock, envelope, errors, in-memory store, helpers."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5): boots at 2026-08-01T00:00:00Z, never wall-clock.
# ---------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return CLOCK["now"]


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


# Error id constants
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_GROWER_OWNERSHIP_MISMATCH = "ERR_GROWER_OWNERSHIP_MISMATCH"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_GROVE_QUARANTINED = "ERR_GROVE_QUARANTINED"
ERR_GROVE_RETIRED = "ERR_GROVE_RETIRED"
ERR_DELIVERY_REGULATORY_HOLD = "ERR_DELIVERY_REGULATORY_HOLD"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_FRUIT_FLY_PROTOCOL_BLOCK = "ERR_FRUIT_FLY_PROTOCOL_BLOCK"
ERR_COLD_TREATMENT_INSUFFICIENT = "ERR_COLD_TREATMENT_INSUFFICIENT"
ERR_QUARANTINE_RELEASE_REQUIREMENTS = "ERR_QUARANTINE_RELEASE_REQUIREMENTS"
ERR_CERT_EXPIRED = "ERR_CERT_EXPIRED"
ERR_MATURITY_TEST_REQUIRED = "ERR_MATURITY_TEST_REQUIRED"
ERR_MATURITY_NOT_PASSING = "ERR_MATURITY_NOT_PASSING"
ERR_MATURITY_TEST_EXPIRED = "ERR_MATURITY_TEST_EXPIRED"
ERR_ASSIGNMENT_WINDOW_NOT_OPEN = "ERR_ASSIGNMENT_WINDOW_NOT_OPEN"
ERR_CREW_WINDOW_OVERLAP = "ERR_CREW_WINDOW_OVERLAP"
ERR_CREW_CAPACITY_EXCEEDED = "ERR_CREW_CAPACITY_EXCEEDED"
ERR_CREW_NOT_ACTIVE = "ERR_CREW_NOT_ACTIVE"
ERR_ROOM_CAPACITY_EXCEEDED = "ERR_ROOM_CAPACITY_EXCEEDED"
ERR_ROOM_NOT_AVAILABLE = "ERR_ROOM_NOT_AVAILABLE"
ERR_DEGREENING_DURATION_OUT_OF_BOUNDS = "ERR_DEGREENING_DURATION_OUT_OF_BOUNDS"
ERR_DEGREENING_REQUIRED = "ERR_DEGREENING_REQUIRED"
ERR_SORT_BOX_MISMATCH = "ERR_SORT_BOX_MISMATCH"
ERR_SORT_RUN_ALREADY_ACTIVE = "ERR_SORT_RUN_ALREADY_ACTIVE"
ERR_DUPLICATE_ENTITY = "ERR_DUPLICATE_ENTITY"
ERR_CHANNEL_CAPACITY_EXCEEDED = "ERR_CHANNEL_CAPACITY_EXCEEDED"
ERR_ACRES_EXCEED_GROVE = "ERR_ACRES_EXCEED_GROVE"
ERR_CHEMICAL_COST_NOT_ALLOWED = "ERR_CHEMICAL_COST_NOT_ALLOWED"
ERR_POOL_NOT_ACCEPTING = "ERR_POOL_NOT_ACCEPTING"
ERR_POOL_HAS_OPEN_DELIVERIES = "ERR_POOL_HAS_OPEN_DELIVERIES"
ERR_ADVANCE_CAP_EXCEEDED = "ERR_ADVANCE_CAP_EXCEEDED"
ERR_GROWER_NOT_ACTIVE = "ERR_GROWER_NOT_ACTIVE"
ERR_INVOICE_OVERPAYMENT = "ERR_INVOICE_OVERPAYMENT"
ERR_PAYMENT_AMOUNT_INVALID = "ERR_PAYMENT_AMOUNT_INVALID"
ERR_CHANNEL_MISMATCH = "ERR_CHANNEL_MISMATCH"
ERR_ASSIGNMENT_NOT_ACTIVE = "ERR_ASSIGNMENT_NOT_ACTIVE"
ERR_NO_JUICE_CHANNEL = "ERR_NO_JUICE_CHANNEL"
ERR_CARETAKING_NOT_ENROLLED = "ERR_CARETAKING_NOT_ENROLLED"


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": iso_ms(now()),
    }


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(page, pagination):
    m = _meta()
    m.update(pagination)
    return jsonify({"meta": m, "response_type": "array", "data": page}), 200


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; no seeding)
# ---------------------------------------------------------------------------
DB = {
    "growers": {},
    "groves": {},
    "maturity_tests": {},
    "crews": {},
    "assignments": {},
    "deliveries": {},
    "rooms": {},
    "sessions": {},
    "sort_runs": {},
    "channels": {},
    "pools": {},
    "advances": {},
    "ct_orders": {},
    "ct_invoices": {},
    "quarantines": {},
    "export_lots": {},
    "certs": {},
}
_SEQ = {"n": 0}


def new_entity():
    _SEQ["n"] += 1
    return {
        "id": str(uuid.uuid4()),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": _SEQ["n"],
    }


def touch(e):
    e["updated_at"] = now()
    e["version"] += 1


def get_or_404(collection, rid, label="Resource"):
    e = DB[collection].get(rid)
    if e is None:
        err(ERR_NOT_FOUND, 404, f"{label} not found: {rid}")
    return e


def sort_asc(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def sort_desc(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]), reverse=True)


# ---------------------------------------------------------------------------
# Roles / auth (PRD §2.1, scaffold validations pri 1-3)
# ---------------------------------------------------------------------------
ROLES = {
    "PackinghouseAdmin",
    "FieldSupervisor",
    "QualityInspector",
    "LineOperator",
    "PoolAccountant",
    "ComplianceOfficer",
    "Grower",
}
STAFF_ROLES = [
    "PackinghouseAdmin",
    "PoolAccountant",
    "FieldSupervisor",
    "QualityInspector",
    "LineOperator",
    "ComplianceOfficer",
]


def require_roles(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err(ERR_UNAUTHENTICATED, 401, "Missing or invalid authentication headers")
    if role not in allowed:
        err(ERR_FORBIDDEN_ROLE, 403, f"Role {role} is not authorized for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Request body / scalar validation (tier 5)
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def req_field(b, name):
    if name not in b or b[name] is None:
        err(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    return b[name]


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        err(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a number")
    return v


def as_str(v, name):
    if not isinstance(v, str):
        err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a string")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean")
    return v


def as_enum(v, name, members):
    if not isinstance(v, str) or v not in members:
        err(
            ERR_INVALID_REQUEST,
            400,
            f"Field {name} must be one of {sorted(members)}",
        )
    return v


def opt_int(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    return as_int(b[name], name)


def opt_bool(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    return as_bool(b[name], name)


def parse_dt(v, name):
    if not isinstance(v, str):
        err(ERR_INVALID_REQUEST, 400, f"Field {name} must be an ISO 8601 datetime string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        err(ERR_INVALID_REQUEST, 400, f"Field {name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(v, name):
    if not isinstance(v, str):
        err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except ValueError:
        err(ERR_INVALID_REQUEST, 400, f"Field {name} is not a valid YYYY-MM-DD date")


def opt_dt(b, name):
    if name not in b or b[name] is None:
        return None
    return parse_dt(b[name], name)


# ---------------------------------------------------------------------------
# Pagination (SCAFFOLD §1.0: limit/offset/total_count/has_more, defaults 10/0)
# ---------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if str(raw_limit).strip() != str(limit):
            err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if str(raw_offset).strip() != str(offset):
            err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        err(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        err(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def filters_from_query(allowed):
    out = {}
    for k in allowed:
        v = request.args.get(k)
        if v is not None:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Decimal helpers (PRD §2.7: integer cents, round half-up, 2dp for ratio/ge)
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def rhu(d, places):
    """Round half-up (ties away from zero) to the given number of places."""
    return D(d).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def cents(d):
    return int(rhu(d, 0))


def f2(d):
    """Serialize a 2-decimal Decimal as a JSON number."""
    return float(rhu(d, 2))
