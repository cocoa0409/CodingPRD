"""Core plumbing: logical clock, errors, response envelope, parsing, auth.

PRD §2: envelope, pagination, logical clock, common fields, validation ladder.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4) — default 2026-05-01T00:00:00Z, never wall clock.
# ---------------------------------------------------------------------------
CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_TICK = 0   # monotonic microsecond offset so stamps order strictly
_SEQ = 0    # global creation sequence (created_at ordering tie-breaks)


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


def set_clock(dt):
    global CLOCK
    CLOCK = dt


def now():
    return CLOCK


def today():
    return CLOCK.date()


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def fmt_instant(dt):
    """ISO 8601 UTC; fractional digits omitted when zero (clock echo)."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return base + ".{:03d}Z".format(dt.microsecond // 1000)
    return base + "Z"


def stamp():
    """Logical timestamp for created_at/updated_at/*_at fields."""
    global _TICK
    _TICK += 1
    return fmt_dt(CLOCK + timedelta(microseconds=_TICK))


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Errors (PRD §5 catalogue)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def fail(error_id, status, message):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(20)
        ),
        "api_request_timestamp": stamp(),
    }


def ok(data, code=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Parsing helpers (dates YYYY-MM-DD, times HH:MM, instants ISO 8601)
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse_date_str(v, field="date"):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be a YYYY-MM-DD date" % field)
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' is not a valid calendar date" % field)


def parse_time_str(v, field="time"):
    if not isinstance(v, str) or not _TIME_RE.match(v):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be an HH:MM 24h time" % field)
    return v


def parse_dt_str(v, field="datetime"):
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be an ISO 8601 datetime" % field)
    t = v.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be an ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def combine(d, hm):
    """Combine a date and an 'HH:MM' string into a UTC datetime."""
    return datetime(d.year, d.month, d.day, int(hm[:2]), int(hm[3:]), tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Request-body schema validation (PRD §2.6 rung 3)
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None or not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def reject_unknown(data, allowed):
    unknown = set(data) - set(allowed)
    if unknown:
        fail("ERR_INVALID_REQUEST", 400,
             "Unknown field(s): " + ", ".join(sorted(unknown)))


def need(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", 400, "Missing required field: " + name)
    return data[name]


def as_str(v, name):
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % name)
    return v


def as_int(v, name, minimum=None):
    if not isinstance(v, int) or isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", 400,
             "Field '%s' must be >= %d" % (name, minimum))
    return v


def as_enum(v, name, values):
    if not isinstance(v, str) or v not in values:
        fail("ERR_INVALID_REQUEST", 400,
             "Field '%s' must be one of %s" % (name, sorted(values)))
    return v


PRODUCT_FORMS = {"BLOCK", "CUBE", "DRY_ICE"}
PACKAGINGS = {"BAG", "PALLET"}


def parse_lines(data, key):
    """Validate a non-empty lines/standing_lines array (rung 3).

    quantity_units >= 1 is NOT checked here — that is the business rule
    ERR_LINE_QUANTITY_INVALID (validation priority 16).
    """
    lines = need(data, key)
    if not isinstance(lines, list) or len(lines) == 0:
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be a non-empty array" % key)
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            fail("ERR_INVALID_REQUEST", 400, "Each line must be an object")
        reject_unknown(ln, {"product_form", "packaging", "quantity_units"})
        pf = as_enum(need(ln, "product_form"), "product_form", PRODUCT_FORMS)
        pk = as_enum(need(ln, "packaging"), "packaging", PACKAGINGS)
        q = need(ln, "quantity_units")
        if not isinstance(q, int) or isinstance(q, bool):
            fail("ERR_INVALID_REQUEST", 400, "Field 'quantity_units' must be an integer")
        out.append({"product_form": pf, "packaging": pk, "quantity_units": q})
    return out


def check_line_quantities(lines):
    for ln in lines:
        if ln["quantity_units"] < 1:
            fail("ERR_LINE_QUANTITY_INVALID", 400, "Line quantity_units must be >= 1")


# ---------------------------------------------------------------------------
# Pagination (SCAFFOLD §1.0 / PRD §2.3): limit/offset, defaults 10/0, 1..100
# ---------------------------------------------------------------------------
def paginate(items, view):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "Query parameter 'limit' must be an integer")
        if str(limit) != raw_limit.strip() or limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", 400,
                 "Query parameter 'limit' must be an integer between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "Query parameter 'offset' must be an integer")
        if str(offset) != raw_offset.strip() or offset < 0:
            fail("ERR_INVALID_REQUEST", 400,
                 "Query parameter 'offset' must be a non-negative integer")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok([view(x) for x in page], 200, pagination)


# ---------------------------------------------------------------------------
# Authentication / authorization (PRD §2.1, §2.6 rungs 1-2)
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "DepotManager", "Dispatcher",
         "BillingClerk", "SafetyOfficer", "CustomerAgent"}
ALL_ROLES = ROLES


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", 401,
             "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        fail("ERR_FORBIDDEN", 403, "Role %s is not permitted for this endpoint" % role)


def agent_owns(uid, role, customer_id):
    """Entity-backed ownership: CustomerAgent may only touch their own resources."""
    if role == "CustomerAgent" and uid != customer_id:
        fail("ERR_FORBIDDEN", 403, "CustomerAgent does not own this resource")
