"""Core infrastructure: logical clock, in-memory store, response envelope,
error catalog, request-scoped mutation tracking, auth and schema validation.

Storage is in-memory only.  Nothing is seeded at import time: every collection
starts empty and is populated exclusively through API calls.
"""

import calendar
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) -- default 2026-08-01T00:00:00Z, never wall clock.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK = {"now": DEFAULT_CLOCK}


def set_clock(dt):
    _CLOCK["now"] = dt.astimezone(timezone.utc)


def clock_now():
    return _CLOCK["now"]


def clock_date():
    return _CLOCK["now"].date()


def fmt_dt(d):
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def now_ts():
    return fmt_dt(_CLOCK["now"])


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat() if isinstance(d, (date, datetime)) else d


# ---------------------------------------------------------------------------
# Error catalog (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 403,
    "ERR_NOT_PRESIDING_OFFICER": 403,
    "ERR_NOT_ASSIGNED_INVESTIGATOR": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_TRADE_CLASSIFICATION_NOT_FOUND": 404,
    "ERR_RECOVERY_FUND_ACCOUNT_NOT_FOUND": 404,
    "ERR_LICENSEE_NOT_FOUND": 404,
    "ERR_QUALIFYING_INDIVIDUAL_NOT_FOUND": 404,
    "ERR_CONSUMER_NOT_FOUND": 404,
    "ERR_LICENSE_APPLICATION_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_COVERAGE_RECORD_NOT_FOUND": 404,
    "ERR_QUALIFIER_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_CITATION_NOT_FOUND": 404,
    "ERR_DISCIPLINARY_HEARING_NOT_FOUND": 404,
    "ERR_RECOVERY_FUND_CLAIM_NOT_FOUND": 404,
    "ERR_STALE_LICENSE_VERSION": 412,
    "ERR_STALE_FUND_ACCOUNT_VERSION": 412,
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_LICENSE_STATE_INVALID": 409,
    "ERR_COVERAGE_STATE_INVALID": 409,
    "ERR_ASSIGNMENT_STATE_INVALID": 409,
    "ERR_COMPLAINT_STATE_INVALID": 409,
    "ERR_INVESTIGATION_STATE_INVALID": 409,
    "ERR_CITATION_STATE_INVALID": 409,
    "ERR_HEARING_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_INVESTIGATION_NOT_SUBSTANTIATED": 409,
    "ERR_CLAIM_BASIS_NOT_ESTABLISHED": 409,
    "ERR_MEDIATION_ROUNDS_EXHAUSTED": 409,
    "ERR_LICENSE_NOT_COMPLIANT": 409,
    "ERR_OUTSTANDING_OBLIGATIONS": 409,
    "ERR_COVERAGE_CONTINUITY_GAP": 422,
    "ERR_BOND_COVERAGE_MISSING": 422,
    "ERR_CLASSIFICATION_MISMATCH": 422,
    "ERR_EXAM_REQUIREMENT_UNMET": 422,
    "ERR_QUALIFIER_CAPACITY_EXCEEDED": 422,
    "ERR_OWNERSHIP_PCT_INSUFFICIENT": 422,
    "ERR_UNLICENSED_SUBJECT_NOT_CLAIMABLE": 422,
    "ERR_INVESTIGATION_ORIGIN_MISMATCH": 422,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_PREDECESSOR_LICENSE_INVALID": 422,
    "ERR_JUDGMENT_FIELDS_MISMATCH": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_APPEAL_WINDOW_OPEN": 422,
    "ERR_ASSIGNMENT_EFFECTIVE_DATE_INVALID": 422,
    "ERR_COVERAGE_PERIOD_OVERLAP": 409,
    "ERR_HEARING_SLOT_CONFLICT": 409,
    "ERR_STATUTE_OF_LIMITATIONS_EXPIRED": 422,
    "ERR_CONTRACT_PREDATES_LICENSE": 422,
    "ERR_JUDGMENT_NOT_RIPE": 422,
    "ERR_RENEWAL_WINDOW_CLOSED": 422,
    "ERR_SUSPENSION_PERIOD_ACTIVE": 422,
    "ERR_HEARING_NOT_CONVENED": 422,
    "ERR_CE_HOURS_INSUFFICIENT": 422,
    "ERR_CE_HOURS_CEILING_EXCEEDED": 422,
    "ERR_EXPERIENCE_INSUFFICIENT": 422,
    "ERR_NET_WORTH_INSUFFICIENT": 422,
    "ERR_BOND_AMOUNT_INSUFFICIENT": 422,
    "ERR_LOSS_BELOW_JURISDICTIONAL_MINIMUM": 422,
    "ERR_PENALTY_EXCEEDS_STATUTORY_MAX": 422,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_FUND_BALANCE_EXHAUSTED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_REPAYMENT_EXCEEDS_OUTSTANDING": 422,
    "ERR_CLAIM_EXCEEDS_ALLEGED_LOSS": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
COLLECTIONS = (
    "trade_classifications",
    "recovery_fund_accounts",
    "licensees",
    "qualifying_individuals",
    "exam_results",
    "license_applications",
    "licenses",
    "coverage_records",
    "qualifier_assignments",
    "consumers",
    "complaints",
    "investigations",
    "citations",
    "disciplinary_hearings",
    "recovery_fund_claims",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.seq = 0
        self.license_number_seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_license_number(self):
        self.license_number_seq += 1
        return "CSLB-%06d" % (self.license_number_seq + 100000)


db = Store()


# ---------------------------------------------------------------------------
# Request-scoped mutation tracking.  Any row touched during a request receives
# exactly one version bump and one updated_at refresh (PRD 2.8 / 2.9).
# ---------------------------------------------------------------------------
def tx_begin():
    g._dirty = {}
    g._fresh = set()


def _dirty():
    if not hasattr(g, "_dirty"):
        tx_begin()
    return g._dirty


def _fresh():
    if not hasattr(g, "_fresh"):
        tx_begin()
    return g._fresh


def touch(row):
    """Register a mutation of `row`, bumping version / updated_at exactly once
    per request no matter how many cascade hops reach the same row."""
    if row is None:
        return
    if id(row) in _fresh():
        return
    dirty = _dirty()
    if id(row) in dirty:
        return
    dirty[id(row)] = row
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now_ts()


def setf(row, key, value):
    """Assign a field, marking the row dirty only when the value changes."""
    if row.get(key, "\x00__missing__") != value:
        row[key] = value
        touch(row)


def commit():
    """Retained for symmetry; version bumps are applied eagerly by touch()."""
    g._dirty = {}


def new_row(common=True):
    row = {"id": str(uuid.uuid4()), "_seq": db.next_seq(), "created_at": now_ts()}
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    _fresh().add(id(row))
    return row


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_ts(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(items)) < total,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message, http_status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        http_status,
    )


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_ALL = [
    "BoardAdmin",
    "LicensingAnalyst",
    "Investigator",
    "HearingOfficer",
    "FundAdjudicator",
    "Licensee",
    "Consumer",
]


def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or str(uid).strip() == "" or role is None or str(role).strip() == "":
        err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in allowed_roles:
        err("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % role)
    g.user_id = uid
    g.role = role
    return uid, role


# ---------------------------------------------------------------------------
# Schema validation helpers (PRD 2.5 / 2.7 / 2.11)
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_str(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ValueError("bad date")
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def parse_dt_str(s):
    if not isinstance(s, str):
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    d = datetime.fromisoformat(t)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    try:
        b = request.get_json(force=True, silent=False)
    except Exception:
        err("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if b is None:
        return {}
    if not isinstance(b, dict):
        err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return b


_SENTINEL = object()


def _absent(b, k):
    return k not in b or b[k] is None


def v_str(b, k, required=True, default=None, allow_empty=False):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    v = b[k]
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", "%s must be a string" % k)
    if not allow_empty and v == "":
        err("ERR_INVALID_REQUEST", "%s must not be empty" % k)
    return v


def v_int(b, k, required=True, default=None, minv=None, maxv=None):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    v = b[k]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", "%s must be an integer" % k)
    if minv is not None and v < minv:
        err("ERR_INVALID_REQUEST", "%s must be >= %s" % (k, minv))
    if maxv is not None and v > maxv:
        err("ERR_INVALID_REQUEST", "%s must be <= %s" % (k, maxv))
    return v


def v_money(b, k, required=True, default=None):
    return v_int(b, k, required=required, default=default, minv=0)


def v_num(b, k, required=True, default=None, minv=None, maxv=None):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    v = b[k]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", "%s must be a number" % k)
    if minv is not None and v < minv:
        err("ERR_INVALID_REQUEST", "%s must be >= %s" % (k, minv))
    if maxv is not None and v > maxv:
        err("ERR_INVALID_REQUEST", "%s must be <= %s" % (k, maxv))
    return v


def v_bool(b, k, required=True, default=None):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    v = b[k]
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", "%s must be a boolean" % k)
    return v


def v_enum(b, k, allowed, required=True, default=None):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    v = b[k]
    if not isinstance(v, str) or v not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s" % (k, ", ".join(allowed)))
    return v


def v_date(b, k, required=True, default=None):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    try:
        return parse_date_str(b[k])
    except Exception:
        err("ERR_INVALID_REQUEST", "%s must be an ISO date (YYYY-MM-DD)" % k)


def v_datetime(b, k, required=True, default=None):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    try:
        return parse_dt_str(b[k])
    except Exception:
        err("ERR_INVALID_REQUEST", "%s must be an RFC3339 UTC datetime" % k)


def v_id(b, k, required=True, default=None):
    if _absent(b, k):
        if required:
            err("ERR_INVALID_REQUEST", "%s is required" % k)
        return default
    v = b[k]
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", "%s must be a string identifier" % k)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
INT_RE = re.compile(r"^-?\d+$")


def paging():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if not INT_RE.match(raw or ""):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = int(raw)
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        if not INT_RE.match(raw or ""):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = int(raw)
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def render_list(rows, serializer):
    limit, offset = paging()
    rows = sort_rows(rows)
    total = len(rows)
    page = rows[offset: offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def qfilter(rows, field, argname=None):
    argname = argname or field
    val = request.args.get(argname)
    if val is None:
        return rows
    return [r for r in rows if r.get(field) == val]


# ---------------------------------------------------------------------------
# Arithmetic helpers (PRD 2.5)
# ---------------------------------------------------------------------------
def rhu(value):
    """Round half up to a whole unit and return an int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(d, months):
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_days(d, days):
    return d + timedelta(days=days)


def norm_num(x):
    """Present whole numbers as ints so JSON stays clean for hour counts."""
    if isinstance(x, float) and float(x).is_integer():
        return int(x)
    return x
