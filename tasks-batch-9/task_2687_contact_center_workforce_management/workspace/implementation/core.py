"""Foundation: error catalog, response envelope, in-memory store, logical clock,
auth/RBAC, pagination and request-body validation helpers.

Storage is in-memory only. Nothing is seeded at import or startup time.
"""
import json
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING, getcontext

from flask import g, request, Response

getcontext().prec = 60

# ---------------------------------------------------------------------------
# Error catalog (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_PLANNING_CYCLE_NOT_FOUND": 404,
    "ERR_LABOR_AGREEMENT_NOT_FOUND": 404,
    "ERR_FORECAST_GROUP_NOT_FOUND": 404,
    "ERR_MARKETING_EVENT_NOT_FOUND": 404,
    "ERR_INTERVAL_PLAN_NOT_FOUND": 404,
    "ERR_AGENT_NOT_FOUND": 404,
    "ERR_SHIFT_TEMPLATE_NOT_FOUND": 404,
    "ERR_BID_ROUND_NOT_FOUND": 404,
    "ERR_SHIFT_BID_NOT_FOUND": 404,
    "ERR_SCHEDULE_SHIFT_NOT_FOUND": 404,
    "ERR_ADHERENCE_EXCEPTION_NOT_FOUND": 404,
    "ERR_INTRADAY_ACTION_NOT_FOUND": 404,
    "ERR_OUTSOURCE_PARTNER_NOT_FOUND": 404,
    "ERR_PARTNER_ALLOCATION_NOT_FOUND": 404,
    "ERR_HIRING_CLASS_NOT_FOUND": 404,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_STALE_PARTNER_VERSION": 412,
    "ERR_CYCLE_FROZEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_BID_ROUND_NOT_OPEN": 409,
    "ERR_ALLOCATION_NOT_COMMITTED": 409,
    "ERR_SHIFT_NOT_PUBLISHED": 409,
    "ERR_EXCEPTION_NOT_PENDING": 409,
    "ERR_ACTION_NOT_OFFERED": 409,
    "ERR_CYCLE_NOT_LOCKED": 409,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_REOPEN_LIMIT_REACHED": 409,
    "ERR_MIN_REST_VIOLATION": 422,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_MAX_WEEKLY_HOURS_EXCEEDED": 422,
    "ERR_MAX_CONSECUTIVE_DAYS_EXCEEDED": 422,
    "ERR_ACTION_EXPIRED": 409,
    "ERR_INTERVAL_OUTSIDE_HORIZON": 422,
    "ERR_EVENT_WINDOW_INVALID": 422,
    "ERR_VTO_NOTICE_TOO_SHORT": 422,
    "ERR_SKILL_MISMATCH": 422,
    "ERR_PARTNER_NOT_ELIGIBLE": 409,
    "ERR_TEMPLATE_SLOTS_EXHAUSTED": 409,
    "ERR_DUPLICATE_BID": 409,
    "ERR_DUPLICATE_INTERVALS": 409,
    "ERR_PREFERENCE_FLOOR_NOT_MET": 422,
    "ERR_VTO_WOULD_BREACH_COVERAGE": 409,
    "ERR_ROUTING_OUTFLOW_EXCEEDS_STAFFING": 422,
    "ERR_ALLOCATION_CAPACITY_EXCEEDED": 409,
    "ERR_PARTNER_VOLUME_OUT_OF_RANGE": 422,
    "ERR_OT_BUDGET_EXCEEDED": 402,
    "ERR_COMMITMENT_FLOOR_BREACH": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "CapacityPlanner",
    "WorkforceAnalyst",
    "SchedulingManager",
    "IntradayController",
    "Agent",
    "TeamCoach",
    "SourcingManager",
    "PartnerRep",
)
ALL_OPERATORS = [
    "CapacityPlanner",
    "WorkforceAnalyst",
    "SchedulingManager",
    "IntradayController",
    "TeamCoach",
    "SourcingManager",
]

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def require_auth(allowed_roles):
    """Priority 10 then 20: authentication then endpoint role authorisation."""
    uid = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint" % role)
    g.user_id = uid
    g.role = role
    return uid, role


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q(value, places):
    """Round half up to `places` decimals."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q0(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def clamp(value, lo, hi):
    v = D(value)
    if v < D(lo):
        return D(lo)
    if v > D(hi):
        return D(hi)
    return v


# ---------------------------------------------------------------------------
# Timestamps and the logical clock (PRD 2.4, 2.5)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

CLOCK = {"raw": DEFAULT_CLOCK_RAW, "dt": DEFAULT_CLOCK_DT}


def now_dt():
    return CLOCK["dt"]


def iso3(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso3(CLOCK["dt"])


def wall_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6})\d*)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        base = datetime(year, month, day, hh, mm, ss, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        base = base - sign * timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
    return base


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def date_to_dt(d, minute_offset=0):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=minute_offset)


def iso_date(d):
    return d.isoformat()


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
TABLES = (
    "planning_cycles",
    "labor_agreements",
    "forecast_groups",
    "marketing_events",
    "interval_plans",
    "agents",
    "shift_templates",
    "bid_rounds",
    "shift_bids",
    "schedule_shifts",
    "adherence_exceptions",
    "intraday_actions",
    "outsource_partners",
    "partner_allocations",
    "hiring_classes",
)

DB = {name: {} for name in TABLES}
_SEQ = {"n": 0}

NOT_FOUND = {
    "planning_cycles": "ERR_PLANNING_CYCLE_NOT_FOUND",
    "labor_agreements": "ERR_LABOR_AGREEMENT_NOT_FOUND",
    "forecast_groups": "ERR_FORECAST_GROUP_NOT_FOUND",
    "marketing_events": "ERR_MARKETING_EVENT_NOT_FOUND",
    "interval_plans": "ERR_INTERVAL_PLAN_NOT_FOUND",
    "agents": "ERR_AGENT_NOT_FOUND",
    "shift_templates": "ERR_SHIFT_TEMPLATE_NOT_FOUND",
    "bid_rounds": "ERR_BID_ROUND_NOT_FOUND",
    "shift_bids": "ERR_SHIFT_BID_NOT_FOUND",
    "schedule_shifts": "ERR_SCHEDULE_SHIFT_NOT_FOUND",
    "adherence_exceptions": "ERR_ADHERENCE_EXCEPTION_NOT_FOUND",
    "intraday_actions": "ERR_INTRADAY_ACTION_NOT_FOUND",
    "outsource_partners": "ERR_OUTSOURCE_PARTNER_NOT_FOUND",
    "partner_allocations": "ERR_PARTNER_ALLOCATION_NOT_FOUND",
    "hiring_classes": "ERR_HIRING_CLASS_NOT_FOUND",
}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_row(table, fields):
    """Insert a row with the four common fields (PRD 2.4)."""
    stamp = now_iso()
    row = {"id": str(uuid.uuid4()), "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    row["_seq"] = next_seq()
    row["_table"] = table
    DB[table][row["id"]] = row
    touched().add(id(row))
    return row


def touched():
    if not hasattr(g, "_touched"):
        g._touched = set()
    return g._touched


def touch(row):
    """Refresh updated_at and bump version -- at most once per row per request."""
    marker = id(row)
    seen = touched()
    if marker in seen:
        return row
    seen.add(marker)
    row["updated_at"] = now_iso()
    row["version"] = int(row["version"]) + 1
    return row


def get(table, row_id, error_id=None):
    row = DB[table].get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id or NOT_FOUND[table])
    return row


def maybe(table, row_id):
    return DB[table].get(row_id) if isinstance(row_id, str) else None


def rows(table):
    """All rows of a table in stable creation order."""
    return sorted(DB[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def json_safe(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value() and value.as_tuple().exponent >= 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def envelope(data, response_type, status, pagination=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_iso()}
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": json_safe(data)}
    return Response(
        json.dumps(body, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    return envelope(data, "object", status)


def created(data):
    return envelope(data, "object", 201)


def ok_list(items, pagination, status=200):
    return envelope(items, "array", status, pagination)


def error_response(error_id, message):
    return envelope(
        {"error_id": error_id, "message": message},
        "error",
        ERROR_HTTP.get(error_id, 400),
    )


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
_INT_RE = re.compile(r"^[+-]?\d+$")


def _page_int(raw, name):
    if raw is None:
        return None
    raw = raw.strip()
    if not _INT_RE.match(raw):
        fail("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    return int(raw)


def pagination_params():
    limit = _page_int(request.args.get("limit"), "limit")
    offset = _page_int(request.args.get("offset"), "offset")
    if limit is None:
        limit = 10
    elif limit < 1 or limit > 100:
        fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    elif offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset may not be negative")
    return limit, offset


def paginate(items, serializer=public):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok_list([serializer(r) for r in page], meta)


# ---------------------------------------------------------------------------
# Request body validation helpers (all raise ERR_VALIDATION, HTTP 422)
# ---------------------------------------------------------------------------
MISSING = object()


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        fail("ERR_VALIDATION", "Request body must be valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return parsed


def bad(name, detail):
    fail("ERR_VALIDATION", "%s %s" % (name, detail))


def present(b, name):
    return name in b and b[name] is not None


def v_string(b, name, required=True, minlen=1, maxlen=None, default=None, pattern=None):
    if not present(b, name):
        if required:
            bad(name, "is required")
        return default
    value = b[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if len(value) < minlen:
        bad(name, "must be at least %d characters" % minlen)
    if maxlen is not None and len(value) > maxlen:
        bad(name, "must be at most %d characters" % maxlen)
    if pattern is not None and not re.match(pattern, value):
        bad(name, "has an invalid format")
    return value


def v_int(b, name, required=True, minimum=None, maximum=None, default=None):
    if not present(b, name):
        if required:
            bad(name, "is required")
        return default
    value = b[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def v_num(b, name, required=True, minimum=None, maximum=None, default=None,
          exclusive_min=None, exclusive_max=None):
    if not present(b, name):
        if required:
            bad(name, "is required")
        return None if default is None else D(default)
    value = b[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    dec = D(value)
    if minimum is not None and dec < D(minimum):
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and dec > D(maximum):
        bad(name, "must be <= %s" % maximum)
    if exclusive_min is not None and dec <= D(exclusive_min):
        bad(name, "must be > %s" % exclusive_min)
    if exclusive_max is not None and dec >= D(exclusive_max):
        bad(name, "must be < %s" % exclusive_max)
    return dec


def v_enum(b, name, choices, required=True, default=None):
    if not present(b, name):
        if required:
            bad(name, "is required")
        return default
    value = b[name]
    if not isinstance(value, str) or value not in choices:
        bad(name, "must be one of %s" % ", ".join(choices))
    return value


def v_array(b, name, required=True, minlen=1, maxlen=None, default=None):
    if not present(b, name):
        if required:
            bad(name, "is required")
        return default
    value = b[name]
    if not isinstance(value, list):
        bad(name, "must be an array")
    if len(value) < minlen:
        bad(name, "must contain at least %d entries" % minlen)
    if maxlen is not None and len(value) > maxlen:
        bad(name, "must contain at most %d entries" % maxlen)
    return value


def v_date(b, name, required=True, default=None):
    if not present(b, name):
        if required:
            bad(name, "is required")
        return default
    value = b[name]
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        bad(name, "must be an ISO 8601 calendar date")
    return parsed


def v_datetime(b, name, required=True, default=None):
    """Returns (raw_string, datetime). Input datetimes are echoed back verbatim."""
    if not present(b, name):
        if required:
            bad(name, "is required")
        return default, None
    value = b[name]
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        bad(name, "must be an ISO 8601 UTC instant")
    return value, parsed


def v_id(b, name, required=True, default=None):
    if not present(b, name):
        if required:
            bad(name, "is required")
        return default
    value = b[name]
    if not isinstance(value, str) or value == "":
        bad(name, "must be a non-empty string identifier")
    return value


def v_forbidden(b, name, kind):
    if name in b and b[name] is not None:
        bad(name, "must be null for kind %s" % kind)


SKILL_RE = r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$"


def v_skill(b, name, required=True):
    return v_string(b, name, required=required, minlen=1, maxlen=30, pattern=SKILL_RE)


def v_skill_array(b, name, required=True):
    values = v_array(b, name, required=required, minlen=1)
    for item in values:
        if not isinstance(item, str) or not (1 <= len(item) <= 30) or not re.match(SKILL_RE, item):
            bad(name, "must contain uppercase snake-case skill codes")
    return values


def v_number_array(b, name, length=None, minimum=None, exclusive_min=None, required=True):
    values = v_array(b, name, required=required, minlen=1)
    if length is not None and len(values) != length:
        bad(name, "must contain exactly %d entries" % length)
    out = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            bad(name, "must contain numbers only")
        dec = D(item)
        if minimum is not None and dec < D(minimum):
            bad(name, "entries must be >= %s" % minimum)
        if exclusive_min is not None and dec <= D(exclusive_min):
            bad(name, "entries must be > %s" % exclusive_min)
        out.append(dec)
    return out


def filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
