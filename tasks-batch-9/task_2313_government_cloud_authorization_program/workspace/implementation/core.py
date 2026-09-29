"""Foundation layer: in-memory store, logical clock, errors, envelope, auth, validators."""
import itertools
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import g, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Instant: a datetime subclass that remembers the exact string a client sent.
# ---------------------------------------------------------------------------


class Instant(datetime):
    __slots__ = ("raw",)


def make_instant(dt, raw=None):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    inst = Instant(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond,
        tzinfo=UTC,
    )
    inst.raw = raw
    return inst


def iso(dt):
    """Canonical ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def real_now():
    return datetime.now(UTC)


def real_now_iso():
    return iso(real_now())


# ---------------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ACTION_ROLE_MISMATCH": 403,
    "ERR_WRONG_REVIEW_QUEUE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_OFFERING_NOT_FOUND": 404,
    "ERR_DATA_CATEGORY_NOT_FOUND": 404,
    "ERR_BASELINE_NOT_FOUND": 404,
    "ERR_CONTROL_IMPLEMENTATION_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_TEST_SLOT_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_POAM_ITEM_NOT_FOUND": 404,
    "ERR_DEVIATION_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_MONITORING_PERIOD_NOT_FOUND": 404,
    "ERR_CHANGE_REQUEST_NOT_FOUND": 404,
    "ERR_REUSE_GRANT_NOT_FOUND": 404,
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_PACKAGE_ACCESS_DENIED": 403,
    "ERR_STALE_OFFERING_VERSION": 412,
    "ERR_STALE_AUTHORIZATION_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ENGAGEMENT_REPORT_NOT_DELIVERED": 409,
    "ERR_AUTHORIZATION_NOT_ACTIVE": 409,
    "ERR_DEVIATION_PENDING_ON_ITEM": 409,
    "ERR_INHERITED_OFFERING_NOT_AUTHORIZED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_NO_CONFIRMED_DATA_CATEGORY": 422,
    "ERR_BASELINE_NOT_AVAILABLE": 422,
    "ERR_CRM_TEXT_REQUIRED": 422,
    "ERR_INCOMPLETE_SCAN_SET": 422,
    "ERR_WINDOW_INVALID": 422,
    "ERR_DETECTION_DATE_IN_FUTURE": 422,
    "ERR_SCAN_WINDOW_NOT_OPEN": 422,
    "ERR_PERIOD_NOT_ENDED": 409,
    "ERR_TEST_SLOT_OVERLAP": 409,
    "ERR_CHANGE_WINDOW_BUFFER_VIOLATION": 409,
    "ERR_DUPLICATE_MONITORING_PERIOD": 409,
    "ERR_DUPLICATE_REUSE_GRANT": 409,
    "ERR_DUPLICATE_CONTROL_IMPLEMENTATION": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_ENGAGEMENT_OFFERING_MISMATCH": 409,
    "ERR_POAM_OFFERING_MISMATCH": 409,
    "ERR_SPONSOR_AGENCY_MISMATCH": 403,
    "ERR_SUPERSEDED_ITEM_MISMATCH": 409,
    "ERR_CRM_COVERAGE_INSUFFICIENT": 422,
    "ERR_RESIDUAL_RISK_TOO_HIGH": 422,
    "ERR_OVERDUE_HIGH_FINDINGS": 422,
    "ERR_ENGAGEMENT_HOURS_EXHAUSTED": 422,
    "ERR_REUSE_SEATS_EXHAUSTED": 422,
    "ERR_SPONSORSHIP_CAPACITY_EXCEEDED": 422,
    "ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE": 422,
    "ERR_ASSESSMENT_BUDGET_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "agencies",
    "baselines",
    "offerings",
    "data_categories",
    "control_implementations",
    "engagements",
    "test_slots",
    "packages",
    "poam_items",
    "deviations",
    "authorizations",
    "monitoring_periods",
    "scan_submissions",
    "change_requests",
    "reuse_grants",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = make_instant(DEFAULT_CLOCK, iso(DEFAULT_CLOCK))

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_record(audit=True):
    # PRD 2.5: "the server never falls back to real time" — audit stamps are
    # taken from the logical clock, formatted per 2.4 with three fractional digits.
    rec = {"id": new_id(), "created_at": iso(now())}
    if audit:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = iso(now())
    rec["version"] = int(rec.get("version", 0)) + 1


def ordered(rows):
    return sorted(rows, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": real_now_iso(),
    }


def public(rec):
    if rec is None:
        return None
    return {k: encode(v) for k, v in rec.items() if not k.startswith("_")}


def encode(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        raw = getattr(value, "raw", None)
        return raw if raw else iso(value)
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": encode(data) if data is not None else {}}
    return body, status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return {"meta": meta, "response_type": "array", "data": [encode(r) for r in rows]}, 200


def error_body(err):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }


# ---------------------------------------------------------------------------
# Auth (validation tiers 1 and 2)
# ---------------------------------------------------------------------------

ROLES = ("CspComplianceLead", "ThirdPartyAssessor", "AgencyAuthorizingOfficial", "ProgramBoardReviewer")
LEAD = "CspComplianceLead"
ASSESSOR = "ThirdPartyAssessor"
AGENCY_OFFICIAL = "AgencyAuthorizingOfficial"
BOARD = "ProgramBoardReviewer"
ANY_ROLE = ROLES


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s is not permitted on this endpoint." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def uid():
    return g.user_id


def role():
    return g.role


# ---------------------------------------------------------------------------
# Request body / query validators (validation tier 5)
# ---------------------------------------------------------------------------


def body():
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
        if data is None:
            if not request.data or request.data.strip() == b"":
                return {}
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        if not isinstance(data, dict):
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return data
    return {}


MISSING = object()


def req_str(b, key, allow_empty=False):
    v = b.get(key, MISSING)
    if v is MISSING or v is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if not allow_empty and v.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % key)
    return v


def opt_str(b, key, default=None, allow_empty=True, allow_null=True):
    if key not in b:
        return default
    v = b.get(key)
    if v is None:
        if allow_null:
            return None
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be null." % key)
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if not allow_empty and v.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % key)
    return v


def req_enum(b, key, allowed):
    v = req_str(b, key)
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return v


def opt_enum(b, key, allowed, default=None):
    if key not in b or b.get(key) is None:
        return default
    v = b.get(key)
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return v


def _as_int(v, key):
    if isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and float(v).is_integer():
        return int(v)
    fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)


def req_int(b, key, minimum=None, maximum=None):
    if key not in b or b.get(key) is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    n = _as_int(b.get(key), key)
    _range_check(n, key, minimum, maximum)
    return n


def opt_int(b, key, default=None, minimum=None, maximum=None):
    if key not in b or b.get(key) is None:
        return default
    n = _as_int(b.get(key), key)
    _range_check(n, key, minimum, maximum)
    return n


def _range_check(n, key, minimum, maximum):
    if minimum is not None and n < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and n > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))


def req_bool(b, key):
    v = b.get(key)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return v


def opt_bool(b, key, default=None):
    if key not in b or b.get(key) is None:
        return default
    return req_bool(b, key)


TWO = Decimal("0.01")


def r2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def _as_decimal(v, key):
    if isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if isinstance(v, str):
        try:
            return Decimal(v.strip())
        except InvalidOperation:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)


def req_money(b, key, positive=True):
    if key not in b or b.get(key) is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    d = _as_decimal(b.get(key), key)
    if positive and d <= 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than zero." % key)
    return r2(d)


def req_instant(b, key):
    v = b.get(key, MISSING)
    if v is MISSING or v is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    return parse_instant(v, key)


def opt_instant(b, key, default=None):
    if key not in b or b.get(key) is None:
        return default
    return parse_instant(b.get(key), key)


def parse_instant(v, key="timestamp"):
    if not isinstance(v, str) or not v.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 datetime string." % key)
    text = v.strip()
    normalized = text
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 datetime string." % key)
    return make_instant(dt, text)


def req_str_array(b, key, allowed=None, allow_empty=False):
    v = b.get(key, MISSING)
    if v is MISSING or v is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    if not v and not allow_empty:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % key)
    out = []
    for item in v:
        if not isinstance(item, str) or not item.strip():
            fail("ERR_INVALID_REQUEST", "Field '%s' contains an invalid element." % key)
        if allowed is not None and item not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains an illegal member." % key)
        if item in out:
            fail("ERR_INVALID_REQUEST", "Field '%s' must not contain duplicates." % key)
        out.append(item)
    return out


PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
AGENCY_CODE_RE = re.compile(r"^[A-Z]{2,8}$")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_enum(key, allowed):
    v = request.args.get(key)
    if v is None or v == "":
        return None
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (key, ", ".join(allowed)))
    return v


def query_bool(key):
    v = request.args.get(key)
    if v is None or v == "":
        return None
    low = v.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % key)


def query_str(key):
    v = request.args.get(key)
    if v is None or v == "":
        return None
    return v


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Lookup helpers (validation tiers 6 and 7)
# ---------------------------------------------------------------------------

_NOT_FOUND = {
    "agencies": "ERR_AGENCY_NOT_FOUND",
    "baselines": "ERR_BASELINE_NOT_FOUND",
    "offerings": "ERR_OFFERING_NOT_FOUND",
    "data_categories": "ERR_DATA_CATEGORY_NOT_FOUND",
    "control_implementations": "ERR_CONTROL_IMPLEMENTATION_NOT_FOUND",
    "engagements": "ERR_ENGAGEMENT_NOT_FOUND",
    "test_slots": "ERR_TEST_SLOT_NOT_FOUND",
    "packages": "ERR_PACKAGE_NOT_FOUND",
    "poam_items": "ERR_POAM_ITEM_NOT_FOUND",
    "deviations": "ERR_DEVIATION_NOT_FOUND",
    "authorizations": "ERR_AUTHORIZATION_NOT_FOUND",
    "monitoring_periods": "ERR_MONITORING_PERIOD_NOT_FOUND",
    "change_requests": "ERR_CHANGE_REQUEST_NOT_FOUND",
    "reuse_grants": "ERR_REUSE_GRANT_NOT_FOUND",
}


def lookup(collection, ident):
    table = getattr(db, collection)
    if not isinstance(ident, str) or ident not in table:
        fail(_NOT_FOUND[collection])
    return table[ident]


def rows(collection):
    return ordered(getattr(db, collection).values())


def timedelta_days(n):
    return timedelta(days=int(n))
