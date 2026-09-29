"""Foundation layer: in-memory store, logical clock, money helpers,
response envelope, error catalog, auth extraction and request-schema
validation for the Qualified Opportunity Fund Compliance API.

Structural names below are taken verbatim from PRD.md / SCAFFOLD.yaml:
  api_prefix                -> /qof
  success envelope          -> meta / response_type / data
  error body                -> error_id / message
  meta request fields       -> api_request_id ("req_" prefix), api_request_timestamp
  pagination fields         -> limit / offset / total_count / has_more (inside meta)
  auth headers              -> X-User-ID, X-User-Role
  common entity fields      -> id, created_at, updated_at, version
"""

import calendar
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

API_PREFIX = "/qof"

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ROLE_FUND_MANAGER = "FundManager"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_INVESTOR = "Investor"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ALL_ROLES = (
    ROLE_FUND_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INVESTOR,
    ROLE_PLATFORM_ADMIN,
)

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalog (PRD section 5) -- error_id -> http_status
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVESTOR_NOT_FOUND": 404,
    "ERR_FUND_NOT_FOUND": 404,
    "ERR_ELIGIBLE_GAIN_NOT_FOUND": 404,
    "ERR_DEFERRAL_ELECTION_NOT_FOUND": 404,
    "ERR_FUND_ASSET_NOT_FOUND": 404,
    "ERR_QOZ_BUSINESS_NOT_FOUND": 404,
    "ERR_BUSINESS_TEST_NOT_FOUND": 404,
    "ERR_ASSET_TEST_NOT_FOUND": 404,
    "ERR_IMPROVEMENT_PROJECT_NOT_FOUND": 404,
    "ERR_WCSH_PLAN_NOT_FOUND": 404,
    "ERR_CAPITAL_EXPENDITURE_NOT_FOUND": 404,
    "ERR_PENALTY_ASSESSMENT_NOT_FOUND": 404,
    "ERR_INCLUSION_EVENT_NOT_FOUND": 404,
    "ERR_STEP_UP_ELECTION_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_INVESTOR_SCOPE_VIOLATION": 403,
    "ERR_FUND_MANAGER_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_FUND_VERSION": 412,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_FUND_NOT_CERTIFIED": 409,
    "ERR_FUND_DECERTIFIED": 409,
    "ERR_INVESTOR_NOT_ATTESTED": 422,
    "ERR_GAIN_NOT_ELIGIBLE": 422,
    "ERR_ELECTED_AMOUNT_EXCEEDS_GAIN": 422,
    "ERR_180_DAY_WINDOW_CLOSED": 422,
    "ERR_180_DAY_WINDOW_NOT_OPEN": 422,
    "ERR_RELATED_PARTY_ACQUISITION": 422,
    "ERR_TESTING_PERIOD_OVERLAP": 409,
    "ERR_IMPROVEMENT_WINDOW_OVERLAP": 409,
    "ERR_EXPENDITURE_OUTSIDE_WINDOW": 422,
    "ERR_WCSH_WINDOW_CLOSED": 422,
    "ERR_WCSH_PLAN_INCOMPLETE": 422,
    "ERR_WCSH_SCHEDULE_MISMATCH": 422,
    "ERR_WCSH_AGGREGATE_CAP_EXCEEDED": 422,
    "ERR_CHECKPOINT_INDEX_INVALID": 422,
    "ERR_SAFE_HARBOR_INPUT_MISSING": 422,
    "ERR_QOZB_LINK_REQUIRED": 422,
    "ERR_AGGREGATION_GROUP_INVALID": 422,
    "ERR_TEN_YEAR_HOLD_NOT_MET": 422,
    "ERR_DISPOSITION_SEQUENCE_INVALID": 422,
    "ERR_DISPOSITION_ORDER_VIOLATION": 409,
    "ERR_INCLUSION_FRACTION_EXCEEDS_REMAINING": 422,
    "ERR_ELECTION_REVOKED": 409,
    "ERR_CURE_ATTEMPTS_EXHAUSTED": 409,
    "ERR_CURE_BASIS_NOT_APPROVABLE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize()


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Money / percentage precision (PRD section 2.7)
# ---------------------------------------------------------------------------

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")
ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")


def q2(value):
    """Money: exactly 2 decimal places, ROUND_HALF_UP."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def q4(value):
    """Percentages / fractions: exactly 4 decimal places, ROUND_HALF_UP."""
    return Decimal(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def dec(value):
    """Lossless Decimal from a JSON number (via repr) or string."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def num(value):
    """Serialize a Decimal as a JSON number (never a string)."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_last_stamp = [None]


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    """Strictly increasing millisecond-resolution wall stamp.

    PRD section 2.4 pins every *domain* instant to the logical clock; the row
    bookkeeping stamps created_at / updated_at are not in that list, and the
    PRD's default list ordering ("creation timestamp ascending") requires them
    to be distinct and to follow insertion order.
    """
    t = datetime.now(UTC).replace(tzinfo=UTC)
    t = t.replace(microsecond=(t.microsecond // 1000) * 1000)
    prev = _last_stamp[0]
    if prev is not None and t <= prev:
        t = prev + timedelta(milliseconds=1)
    _last_stamp[0] = t
    return t


def parse_dt(value):
    """Parse an ISO 8601 timestamp; raise ERR_INVALID_REQUEST when malformed."""
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp")
    raw = value.strip()
    text = raw
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            fail("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp: %s" % raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def whole_days(later, earlier):
    """Whole elapsed days; any partial day is discarded (floor)."""
    return (later - earlier) // timedelta(days=1)


def add_months(dt, months):
    """Add whole calendar months, clamping the day to the target month length."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def month_key(dt):
    return dt.year * 12 + (dt.month - 1)


# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot -- nothing is ever seeded)
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "investors",
    "funds",
    "eligible_gains",
    "deferral_elections",
    "fund_assets",
    "qoz_businesses",
    "business_tests",
    "asset_tests",
    "improvement_projects",
    "wcsh_plans",
    "capital_expenditures",
    "penalty_assessments",
    "inclusion_events",
    "step_up_elections",
)

DB = {name: {} for name in COLLECTIONS}

NOT_FOUND_ERROR = {
    "investors": "ERR_INVESTOR_NOT_FOUND",
    "funds": "ERR_FUND_NOT_FOUND",
    "eligible_gains": "ERR_ELIGIBLE_GAIN_NOT_FOUND",
    "deferral_elections": "ERR_DEFERRAL_ELECTION_NOT_FOUND",
    "fund_assets": "ERR_FUND_ASSET_NOT_FOUND",
    "qoz_businesses": "ERR_QOZ_BUSINESS_NOT_FOUND",
    "business_tests": "ERR_BUSINESS_TEST_NOT_FOUND",
    "asset_tests": "ERR_ASSET_TEST_NOT_FOUND",
    "improvement_projects": "ERR_IMPROVEMENT_PROJECT_NOT_FOUND",
    "wcsh_plans": "ERR_WCSH_PLAN_NOT_FOUND",
    "capital_expenditures": "ERR_CAPITAL_EXPENDITURE_NOT_FOUND",
    "penalty_assessments": "ERR_PENALTY_ASSESSMENT_NOT_FOUND",
    "inclusion_events": "ERR_INCLUSION_EVENT_NOT_FOUND",
    "step_up_elections": "ERR_STEP_UP_ELECTION_NOT_FOUND",
}

_seq = [0]

# Logical clock (PRD section 2.4). Default 2026-08-01T00:00:00Z.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
CLOCK = {"current_utc": CLOCK_DEFAULT}


def now_logical():
    return CLOCK["current_utc"]


def set_clock(value):
    previous = CLOCK["current_utc"]
    CLOCK["current_utc"] = value
    return previous


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields, common=True):
    row = dict(fields)
    row["id"] = new_id()
    row["_kind"] = collection
    row["_seq"] = next_seq()
    stamp = wall_now()
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    DB[collection][row["id"]] = row
    # A freshly created row is already at its final version for this request;
    # any recompute that follows must not bump it past 1.
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    seen.add(row["id"])
    return row


def touch(row):
    """Refresh updated_at and bump version -- at most once per HTTP request."""
    if row is None or "version" not in row:
        return row
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    if row["id"] in seen:
        return row
    seen.add(row["id"])
    row["version"] += 1
    row["updated_at"] = wall_now()
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


def must_get(collection, row_id, error_id=None):
    row = get(collection, row_id)
    if row is None:
        fail(error_id or NOT_FOUND_ERROR[collection])
    return row


def must_ref(collection, row_id):
    """Body-level foreign key resolution (validation priority 7)."""
    row = get(collection, row_id)
    if row is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND",
             "Referenced %s '%s' does not exist" % (collection, row_id))
    return row


def rows(collection, predicate=None):
    out = [r for r in DB[collection].values() if predicate is None or predicate(r)]
    out.sort(key=lambda r: r["_seq"])
    return out


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(UTC)),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(items, page):
    total = len(items)
    limit = page["limit"]
    offset = page["offset"]
    window = items[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": window}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth (validation priorities 1-3) and pagination (priority 5)
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or not str(user_id).strip():
        fail("ERR_MISSING_AUTH_HEADER", "%s header is required" % HEADER_USER_ID)
    if role is None or not str(role).strip():
        fail("ERR_MISSING_AUTH_HEADER", "%s header is required" % HEADER_USER_ROLE)
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ALL_ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unrecognized role '%s'" % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED",
             "Role '%s' may not perform this operation" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None:
        limit = _page_int(raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail("ERR_INVALID_PAGINATION",
                 "limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if raw_offset is not None:
        offset = _page_int(raw_offset)
        if offset < PAGE_OFFSET_DEFAULT:
            fail("ERR_INVALID_PAGINATION", "offset must be greater than or equal to 0")
    return {"limit": limit, "offset": offset}


def _page_int(raw):
    text = str(raw).strip()
    try:
        return int(text)
    except ValueError:
        fail("ERR_INVALID_PAGINATION", "Pagination parameters must be integers")
