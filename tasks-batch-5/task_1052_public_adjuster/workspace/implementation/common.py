"""Cross-cutting helpers: error type, response envelope, auth, parsing, rounding.

Every structural name here is taken verbatim from SCAFFOLD.yaml / PRD.md:
  - auth headers: X-User-ID, X-User-Role  (PRD 2.1)
  - roles: PublicAdjuster, FirmPrincipal, Client, Carrier, System  (PRD 2.1)
  - envelope: meta{api_request_id, api_request_timestamp, [pagination]},
              response_type, data  (PRD 2.2)
  - error body: {error_id, message}  (PRD 2.2)
  - pagination: limit/offset/total_count/has_more, default 10 min 1 max 100 (PRD 2.3)
"""

import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, g, jsonify

from store import db

ROLES = {"PublicAdjuster", "FirmPrincipal", "Client", "Carrier", "System"}

# ---- Error catalogue (PRD section 5) -------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_LICENSE_NOT_VALID": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_LOSS_OUTSIDE_POLICY_PERIOD": 409,
    "ERR_SUPPLEMENT_WINDOW_CLOSED": 409,
    "ERR_RESCISSION_WINDOW_CLOSED": 409,
    "ERR_INSPECTION_OVERLAP": 409,
    "ERR_LICENSE_PERIOD_OVERLAP": 409,
    "ERR_APPRAISER_CONFLICT": 409,
    "ERR_UMPIRE_NOT_NEEDED": 409,
    "ERR_UMPIRE_REQUIRED": 409,
    "ERR_AWARD_OUT_OF_RANGE": 409,
    "ERR_FEE_EXCEEDS_STATUTORY_CAP": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_OPEN_DISPUTE_BLOCKS_RELEASE": 409,
    "ERR_DISBURSEMENT_RELEASED": 409,
    "ERR_CLAIM_NOT_SETTLED": 409,
    "ERR_POLICY_LIMIT_EXCEEDED": 409,
    "ERR_STALE_CLAIM_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---- Time helpers --------------------------------------------------------

def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 date or datetime into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # date-only form
        dt = datetime.fromisoformat(s + "T00:00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- Rounding (PRD 2.5: round half up, away from zero) -------------------

def round_half_up(cents_amount, fraction):
    """round_half_up(cents_amount * fraction) -> int cents."""
    result = (Decimal(int(cents_amount)) * Decimal(str(fraction))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(result)


# ---- Response envelope (PRD 2.2) -----------------------------------------

def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, pagination=None):
    is_array = isinstance(data, list)
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_STATUS.get(error_id, 400)


# ---- Auth (PRD 2.1 / validations priority 1-2) ---------------------------

def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and valid."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = uid
    g.role = role
    return uid, role


def require_role(*allowed):
    """Priority 2: role permitted for this endpoint."""
    if g.role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted for this operation")


# ---- Mutation bookkeeping (PRD 2.4 / 2.6) --------------------------------

def touch(entity):
    """Bump version + updated_at once per request for this entity."""
    if "_touched" not in g:
        g._touched = set()
    key = id(entity)
    if key in g._touched:
        return
    g._touched.add(key)
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = fmt_ts(db.now())


def stamp_new(entity):
    """Set common system fields on creation."""
    entity["created_at"] = fmt_ts(db.now())
    entity["updated_at"] = fmt_ts(db.now())
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def public(entity):
    """Strip internal-only fields for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---- Body / field validation (priority 12: ERR_VALIDATION) ---------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % n)


def as_int(body, name, positive=False, non_negative=True):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % name)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be positive" % name)
    if non_negative and v < 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be non-negative" % name)
    return v


def as_number(body, name, non_negative=True):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number" % name)
    if non_negative and v < 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be non-negative" % name)
    return v


def as_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def as_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string" % name)
    return v


# ---- Pagination (PRD 2.3) ------------------------------------------------

def paginate(items):
    """Sort by created_at asc (stable on insertion order) then window."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be non-negative")

    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [public(e) for e in window], pagination


def timedelta_days(days):
    return timedelta(days=days)
