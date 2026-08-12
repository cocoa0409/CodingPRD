"""Shared primitives: errors, envelope, auth, validation, decimal/time helpers."""
import functools
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

from mill.store import store

ALL_ROLES = [
    "SalesRep",
    "ProductionPlanner",
    "MaterialReceiver",
    "QualityInspector",
    "ComplianceOfficer",
    "ShippingCoordinator",
    "PlantAdmin",
]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_invalid(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------


def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _q(x, places):
    return D(x).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def r3(x):
    return float(_q(x, "0.001"))


def r2(x):
    return float(_q(x, "0.01"))


def r4(x):
    return float(_q(x, "0.0001"))


def r0c(x):
    """Round to integer cents, half up."""
    return int(_q(x, "1"))


def q3(x):
    """Decimal quantized to 3 places (for exact comparisons)."""
    return _q(x, "0.001")


# ---------------------------------------------------------------------------
# Time helpers (logical clock)
# ---------------------------------------------------------------------------


def now_dt():
    return store.clock


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(store.clock)


def parse_dt(s):
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        raise err_invalid(f"Invalid ISO8601 timestamp: {s!r}")
    st = s.strip()
    if st.endswith("Z"):
        st = st[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(st)
    except ValueError:
        raise err_invalid(f"Invalid ISO8601 timestamp: {s!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso(),
    }


def ok(data, code=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def ok_list(items, total_count, limit, offset):
    body = {
        "meta": {
            **_meta(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------


def new_rec():
    """Fresh record with common system fields; creation counts as version 1."""
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(store.seq),
    }


def touch(rec):
    """One mutation bump per entity per request: refresh updated_at, version += 1."""
    touched = g.setdefault("_touched", set())
    key = id(rec)
    if key in touched:
        return
    touched.add(key)
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def pub_list(recs):
    return [pub(r) for r in recs]


def by_seq(recs):
    return sorted(recs, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------


def endpoint(roles):
    """Decorator enforcing the auth-context (400) and RBAC (403) guards."""

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or role not in ALL_ROLES:
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    400,
                    "X-User-ID and X-User-Role headers are required and the role must be a declared role",
                )
            if role not in roles:
                raise ApiError(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    403,
                    f"Role {role} is not authorized for this endpoint",
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return inner

    return wrap


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------


def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_invalid("Request body must be a JSON object")
    return data


def req_field(body, name):
    v = body.get(name)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        raise err_invalid(f"Missing required field: {name}")
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if v not in allowed:
        raise err_invalid(f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default=None):
    v = body.get(name, default)
    if v is None:
        return v
    if v not in allowed:
        raise err_invalid(f"Field {name} must be one of {sorted(allowed)}")
    return v


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_num(body, name):
    v = req_field(body, name)
    if not _is_num(v):
        raise err_invalid(f"Field {name} must be a number")
    return v


def req_pos_num(body, name):
    v = req_num(body, name)
    if D(v) <= 0:
        raise err_invalid(f"Field {name} must be greater than zero")
    return v


def req_int(body, name, minimum=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid(f"Field {name} must be an integer")
    if isinstance(v, float):
        if not v.is_integer():
            raise err_invalid(f"Field {name} must be an integer")
        v = int(v)
    if minimum is not None and v < minimum:
        raise err_invalid(f"Field {name} must be >= {minimum}")
    return v


def opt_int(body, name, default=None, minimum=None):
    if body.get(name) is None:
        return default
    return req_int(body, name, minimum=minimum)


def opt_bool(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return None
    return bool(v)


def opt_num(body, name, default=None):
    if body.get(name) is None:
        return default
    return req_num(body, name)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


def list_response(recs):
    """recs: pre-filtered records; sorts by creation order and paginates."""
    limit, offset = pagination_params()
    ordered = by_seq(recs)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return ok_list(pub_list(page), total, limit, offset)
