"""Shared helpers: response envelope, validation coercion, pagination, domain utilities."""

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

import errors
from store import STORE, now_dt, now_iso

ROLES = {"HRAdmin", "HRReviewer", "DepartmentChair", "Dean", "PayrollOfficer"}

EDUCATION_TIERS = ["BACHELORS", "MASTERS", "DOCTORATE"]
TIER_RANK = {t: i for i, t in enumerate(EDUCATION_TIERS)}

MAX_REVISIONS = 3

# cancellation_partial_pay constants
PRE_CENSUS_PCT = 0.10
LATE_FLOOR_PCT = 0.25
ONBOARDING_STIPEND_CENTS = 5000

# contract issuance overage allowance (load units)
OVERAGE_ALLOWANCE = 1.00

# retention_composite_score weights
W_TEACHING = 0.60
W_SERVICE = 0.25
W_COMPLIANCE = 0.15

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope / PRD 2.2)
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_uppercase + string.digits, k=20)
        ),
        "api_request_timestamp": now_iso(),
    }


def success_obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def success_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message},
            }
        ),
        err.http_status,
    )


# ---------------------------------------------------------------------------
# Auth (PRD 2.1)
# ---------------------------------------------------------------------------

def get_actor():
    """Validate the auth headers; return (user_id, role) or raise ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.unauthenticated()
    if not role or not isinstance(role, str) or not role.strip():
        raise errors.unauthenticated()
    if role not in ROLES:
        raise errors.unauthenticated("X-User-Role is not a declared role")
    return user_id.strip(), role


def require_roles(roles):
    user_id, role = get_actor()
    if role not in roles:
        raise errors.unauthorized_role()
    return user_id, role


# ---------------------------------------------------------------------------
# Request body access & coercion (priority 19, ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body():
    """Return the request JSON body as a dict; never raises."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def is_valid_date_str(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def parse_date(s):
    return date.fromisoformat(s)


def parse_instant(value):
    """Parse an ISO 8601 instant; return aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or not v.strip():
        raise errors.invalid_request("Field '%s' is required and must be a non-empty string" % name)
    return v


def opt_str(data, name):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if not isinstance(v, str) or not v.strip():
        raise errors.invalid_request("Field '%s' must be a non-empty string" % name)
    return v


def req_enum(data, name, members):
    v = data.get(name)
    if v not in members:
        raise errors.invalid_request(
            "Field '%s' must be one of %s" % (name, ", ".join(members))
        )
    return v


def opt_enum(data, name, members):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if v not in members:
        raise errors.invalid_request(
            "Field '%s' must be one of %s" % (name, ", ".join(members))
        )
    return v


def req_int(data, name, min_value=None):
    v = data.get(name)
    if not is_int(v):
        raise errors.invalid_request("Field '%s' is required and must be an integer" % name)
    if min_value is not None and v < min_value:
        raise errors.invalid_request("Field '%s' must be >= %d" % (name, min_value))
    return v


def opt_int(data, name, min_value=None):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if not is_int(v):
        raise errors.invalid_request("Field '%s' must be an integer" % name)
    if min_value is not None and v < min_value:
        raise errors.invalid_request("Field '%s' must be >= %d" % (name, min_value))
    return v


def _two_decimal_ok(v):
    scaled = abs(v) * 100
    return abs(scaled - round(scaled)) < 1e-6


def req_number(data, name, gt=None, min_value=None, max_value=None, max_decimals=None):
    v = data.get(name)
    if not is_number(v):
        raise errors.invalid_request("Field '%s' is required and must be a number" % name)
    v = float(v)
    if gt is not None and not v > gt:
        raise errors.invalid_request("Field '%s' must be > %s" % (name, gt))
    if min_value is not None and v < min_value:
        raise errors.invalid_request("Field '%s' must be >= %s" % (name, min_value))
    if max_value is not None and v > max_value:
        raise errors.invalid_request("Field '%s' must be <= %s" % (name, max_value))
    if max_decimals == 2 and not _two_decimal_ok(v):
        raise errors.invalid_request("Field '%s' allows at most 2 decimal places" % name)
    return v


def req_date(data, name):
    v = data.get(name)
    if not is_valid_date_str(v):
        raise errors.invalid_request("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % name)
    return v


def opt_bool(data, name):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if not isinstance(v, bool):
        raise errors.invalid_request("Field '%s' must be a boolean" % name)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0
# ---------------------------------------------------------------------------

def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw, 10)
        except (TypeError, ValueError):
            raise errors.invalid_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("Query parameter 'limit' must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw, 10)
        except (TypeError, ValueError):
            raise errors.invalid_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise errors.invalid_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def list_response(rows, filters):
    """Filter by query-param equality filters, sort by created_at asc, paginate.

    Records are copied before the internal _seq marker is stripped so the
    store's own dicts are never mutated by a read.
    """
    items = list(rows)
    for key, wanted in filters.items():
        if wanted is None:
            continue
        items = [it for it in items if _matches(it, key, wanted)]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(items)
    limit, offset = pagination_params()
    page = []
    for it in items[offset:offset + limit]:
        clean = dict(it)
        clean.pop("_seq", None)
        page.append(clean)
    return success_list(page, limit, offset, total)


def _matches(record, key, wanted):
    value = record.get(key)
    if isinstance(value, bool):
        w = wanted.strip().lower()
        if w == "true":
            return value is True
        if w == "false":
            return value is False
        return False
    return str(value) == wanted


# ---------------------------------------------------------------------------
# Record factory
# ---------------------------------------------------------------------------

_SEQ = [0]


def new_record(common=True):
    _SEQ[0] += 1
    rec = {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": _SEQ[0]}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version (common-field entities only)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lookups (404 ERR_NOT_FOUND, left-to-right: path before body)
# ---------------------------------------------------------------------------

def find_or_404(table, rid, label="Resource"):
    rec = STORE[table].get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise errors.not_found("%s '%s' not found" % (label, rid))
    return rec


# ---------------------------------------------------------------------------
# Domain utilities
# ---------------------------------------------------------------------------

def today():
    return now_dt().date()


def term_by_code(code):
    for t in STORE["terms"].values():
        if t["code"] == code:
            return t
    return None


def current_term():
    """The term whose window contains the current logical date; otherwise the
    chronologically next term by start_date (ties: earliest created_at)."""
    today_d = today()
    terms = list(STORE["terms"].values())
    containing = [
        t for t in terms
        if parse_date(t["start_date"]) <= today_d <= parse_date(t["end_date"])
    ]
    if containing:
        containing.sort(key=lambda t: (t["start_date"], t["_seq"]))
        return containing[0]
    future = [t for t in terms if parse_date(t["start_date"]) > today_d]
    if not future:
        return None
    future.sort(key=lambda t: (parse_date(t["start_date"]), t["_seq"]))
    return future[0]


def overlap_days(p_start, p_end, t_start, t_end):
    lo = max(p_start, t_start)
    hi = min(p_end, t_end)
    if hi < lo:
        return 0
    return (hi - lo).days + 1
