"""Shared helpers: decimals, dates, envelope, pagination, auth, validators."""
import calendar
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from .errors import ApiError, bad_request
from .store import new_req_id, now, store

ROLES = (
    "PlantManager",
    "LabTechnician",
    "ProductionOperator",
    "QCInspector",
    "RegulatoryClerk",
    "Dealer",
)

# ---------------------------------------------------------------------------
# Decimal helpers (money in integer cents; VOC at 2dp; round half up)
# ---------------------------------------------------------------------------
from decimal import Decimal, ROUND_HALF_UP  # noqa: E402


def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round0(x):
    """Round half up to integer."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(x):
    """Round half up to 2 decimal places, returned as Decimal."""
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime_value(s, field):
    if not isinstance(s, str):
        raise bad_request("%s must be an ISO 8601 string" % field)
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise bad_request("%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def success(data, status=200, response_type="object", page=None):
    m = {"api_request_id": new_req_id(), "api_request_timestamp": fmt_ts(now())}
    if page:
        m.update(page)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), status


def error_body(error_id, message):
    return {
        "meta": {"api_request_id": new_req_id(), "api_request_timestamp": fmt_ts(now())},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def list_response(recs, serialize):
    recs = sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
    limit = q_int("limit", 10)
    offset = q_int("offset", 0)
    if limit < 1 or limit > 100:
        raise bad_request("limit must be between 1 and 100")
    if offset < 0:
        raise bad_request("offset must be >= 0")
    total = len(recs)
    page_items = recs[offset : offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page_items) < total,
    }
    return success([serialize(r) for r in page_items], 200, "array", page)


def q_int(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad_request("%s must be an integer" % name)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(allowed):
    """Gate 1 (401) then gate 2 (403 role). Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError(401, "ERR_UNAUTHENTICATED", "X-User-Role header missing or not a declared role")
    if role not in allowed:
        raise ApiError(403, "ERR_FORBIDDEN", "Role %s is not permitted for this endpoint" % role)
    return request.headers.get("X-User-ID"), role


# ---------------------------------------------------------------------------
# Body + field validators (gate 3)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def _present(b, k):
    return k in b and b[k] is not None


def v_str(b, k, required=True):
    if not _present(b, k):
        if required:
            raise bad_request("Missing required field: %s" % k)
        return None
    if not isinstance(b[k], str):
        raise bad_request("%s must be a string" % k)
    return b[k]


def v_state_code(b, k, required=True, allow_wildcard=False):
    v = v_str(b, k, required)
    if v is None:
        return None
    if allow_wildcard and v == "*":
        return v
    if len(v) != 2:
        raise bad_request("%s must be a two-letter state code" % k)
    return v


def v_int(b, k, required=True, minv=None):
    if not _present(b, k):
        if required:
            raise bad_request("Missing required field: %s" % k)
        return None
    v = b[k]
    if isinstance(v, bool):
        raise bad_request("%s must be an integer" % k)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not isinstance(v, int):
        raise bad_request("%s must be an integer" % k)
    if minv is not None and v < minv:
        raise bad_request("%s must be >= %s" % (k, minv))
    return v


def v_num(b, k, required=True, minv=None, gt=None):
    if not _present(b, k):
        if required:
            raise bad_request("Missing required field: %s" % k)
        return None
    v = b[k]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request("%s must be a number" % k)
    if minv is not None and v < minv:
        raise bad_request("%s must be >= %s" % (k, minv))
    if gt is not None and v <= gt:
        raise bad_request("%s must be > %s" % (k, gt))
    return v


def v_bool(b, k, required=True):
    if not _present(b, k):
        if required:
            raise bad_request("Missing required field: %s" % k)
        return None
    if not isinstance(b[k], bool):
        raise bad_request("%s must be a boolean" % k)
    return b[k]


def v_enum(b, k, values, required=True):
    v = v_str(b, k, required)
    if v is None:
        return None
    if v not in values:
        raise bad_request("%s must be one of %s" % (k, ", ".join(values)))
    return v


def v_arr(b, k, required=True):
    if not _present(b, k):
        if required:
            raise bad_request("Missing required field: %s" % k)
        return None
    if not isinstance(b[k], list):
        raise bad_request("%s must be an array" % k)
    return b[k]


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record():
    """Primary-resource record: id, created_at, updated_at, version."""
    import uuid

    from .store import next_seq

    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_light_record():
    """Sub-record (FormulaLine / BatchAdjustment): id and created_at only."""
    import uuid

    from .store import next_seq

    return {"id": str(uuid.uuid4()), "created_at": now(), "_seq": next_seq()}


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
