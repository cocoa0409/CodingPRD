"""Core infrastructure: in-memory store, envelope helpers, errors, auth,
datetime utilities, pagination.

All storage is process-local module state. Nothing is persisted to disk, so
every fresh `start.sh` invocation boots with a completely empty store.
"""

import itertools
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request


# ---------------------------------------------------------------------------
# In-memory data store (fresh per process)
# ---------------------------------------------------------------------------

class _Store:
    def __init__(self):
        self.org_units = {}          # id -> HROrgUnit
        self.employees = {}          # id -> Employee
        self.coaching_entries = {}   # id -> ManagerCoachingLogEntry
        self.concerns = {}           # id -> PerformanceConcern
        self.templates = {}          # id -> PIPTemplate
        self.pips = {}               # id -> PerformanceImprovementPlan
        self.goals = {}              # id -> PIPGoal
        self.checkins = {}           # id -> CheckIn
        self.evidence = {}           # id -> EvidenceItem
        self.legal_reviews = {}      # id -> LegalReview
        self.decisions = {}          # id -> OutcomeDecision
        self.rebuttals = {}          # id -> EmployeeRebuttal
        self.cycles = {}             # id -> RatingCycle
        self.consistency = {}        # id -> ConsistencyReview
        self.links = {}              # id -> RatingCycleOutcomeLink
        self.seq = itertools.count(1)  # global creation ordering tiebreak


db = _Store()


def next_seq():
    return next(db.seq)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ids (from the PRD error catalogue)
E_AUTH = ("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
E_FORBIDDEN = ("ERR_FORBIDDEN", 403)
E_NOT_FOUND = ("ERR_NOT_FOUND", 404)
E_PARENT_MISMATCH = ("ERR_PARENT_MISMATCH", 404)
E_STALE_VERSION = ("ERR_STALE_VERSION", 412)
E_INVALID_STATE = ("ERR_INVALID_STATE", 409)
E_SOD = ("ERR_SEGREGATION_OF_DUTIES", 403)
E_EMPLOYEE_NOT_ACTIVE = ("ERR_EMPLOYEE_NOT_ACTIVE", 409)
E_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
E_COACHING_MISMATCH = ("ERR_COACHING_ENTRY_MISMATCH", 422)
E_COACHING_NOT_FORMAL = ("ERR_COACHING_ENTRY_NOT_FORMAL", 422)
E_INSUFFICIENT_COACHING = ("ERR_INSUFFICIENT_COACHING_HISTORY", 422)
E_CONCERN_NOT_ACCEPTED = ("ERR_CONCERN_NOT_ACCEPTED", 409)
E_TEMPLATE_WEIGHT_SUM = ("ERR_TEMPLATE_WEIGHT_SUM", 422)
E_TEMPLATE_CADENCE = ("ERR_TEMPLATE_CADENCE_MISMATCH", 422)
E_TEMPLATE_IN_USE = ("ERR_TEMPLATE_IN_USE", 409)
E_TEMPLATE_NOT_PUBLISHED = ("ERR_TEMPLATE_NOT_PUBLISHED", 409)
E_ACTIVE_PIP_EXISTS = ("ERR_ACTIVE_PIP_EXISTS", 409)
E_PIP_NOT_ACTIVE = ("ERR_PIP_NOT_ACTIVE", 409)
E_OUTCOME_ALREADY_PROPOSED = ("ERR_OUTCOME_ALREADY_PROPOSED", 409)
E_CHECKIN_TOO_EARLY = ("ERR_CHECKIN_TOO_EARLY", 409)
E_CHECKIN_QUORUM = ("ERR_CHECKIN_QUORUM", 422)
E_CHECKIN_ALREADY_HELD = ("ERR_CHECKIN_ALREADY_HELD", 409)
E_CHECKIN_CADENCE = ("ERR_CHECKIN_CADENCE_VIOLATION", 422)
E_REFERENTIAL = ("ERR_REFERENTIAL_INTEGRITY", 422)
E_PLAN_STILL_RUNNING = ("ERR_PLAN_STILL_RUNNING", 409)
E_ATTAINMENT_BELOW = ("ERR_ATTAINMENT_BELOW_THRESHOLD", 422)
E_EXTENSION_LIMIT = ("ERR_EXTENSION_LIMIT_EXCEEDED", 409)
E_LEGAL_REVIEW_REQUIRED = ("ERR_LEGAL_REVIEW_REQUIRED", 409)
E_LEGAL_OVERRIDE_NOT_ALLOWED = ("ERR_LEGAL_OVERRIDE_NOT_ALLOWED", 409)
E_REBUTTAL_WINDOW_CLOSED = ("ERR_REBUTTAL_WINDOW_CLOSED", 409)
E_REBUTTAL_NOT_SUBJECT = ("ERR_REBUTTAL_NOT_SUBJECT", 403)
E_COHORT_TOO_SMALL = ("ERR_COHORT_TOO_SMALL", 422)
E_CYCLE_STILL_OPEN = ("ERR_CYCLE_STILL_OPEN", 409)
E_CYCLE_TOO_RECENT = ("ERR_CYCLE_TOO_RECENT", 409)


def err(spec, message=None):
    raise ApiError(spec[0], spec[1], message or spec[0])


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def now_iso():
    """Wall-clock UTC timestamp with exactly three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return body, status


def ok_list(items, limit, offset, total):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return body, 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLES = {
    "HRSystemAdmin", "Manager", "HRBusinessPartner",
    "LegalCounsel", "HRDirector", "Employee",
}
ALL_ROLES = ["HRSystemAdmin", "HRBusinessPartner", "HRDirector",
             "LegalCounsel", "Manager", "Employee"]


def auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        err(E_AUTH, "X-User-ID and X-User-Role headers are required")
    if not isinstance(uid, str) or not uid.strip():
        err(E_AUTH, "X-User-ID header is malformed")
    if role not in ROLES:
        err(E_AUTH, "X-User-Role header is malformed")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err(E_FORBIDDEN, "Role %s is not permitted for this endpoint" % role)


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. None on failure."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    s = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    # Normalize offsets without colon (+0000 -> +00:00)
    if re.search(r"[+-]\d{4}$", s):
        s = s[:-5] + s[-5:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def frac_digits(ref):
    """Number of fractional second digits in a reference ISO string."""
    if isinstance(ref, str):
        m = _ISO_RE.match(ref.strip())
        if m and m.group(3):
            return len(m.group(3)) - 1
    return 0


def fmt_like(dt, ref):
    """Format dt (UTC) in the same second-fraction style as ref string."""
    digits = frac_digits(ref)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if digits > 0:
        frac = f"{dt.microsecond:06d}"
        if digits <= 6:
            frac = frac[:digits]
        else:
            frac = frac + "0" * (digits - 6)
        return base + "." + frac + "Z"
    return base + "Z"


DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def clock_of(ou):
    """Parsed logical clock of an org unit."""
    return parse_dt(ou["current_utc"])


def days(n):
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# Decimal / rounding helpers
# ---------------------------------------------------------------------------

def dec(v):
    """Exact Decimal from an int/float/str JSON number."""
    return Decimal(str(v))


def round4(d):
    """Round half-up to exactly 4 decimal places; returned as float."""
    q = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------

def new_record():
    """Common system fields for mutable resources."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_append_record():
    """System fields for append-only resources (no updated_at/version)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal underscore-prefixed keys for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err(E_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            err(E_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err(E_INVALID_REQUEST, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            err(E_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(records, filters=None):
    """Sort by created_at asc (tie: creation seq), apply filters, paginate."""
    items = list(records)
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            items = [r for r in items if str(r.get(key)) == str(val)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return ok_list([public(r) for r in page], limit, offset, total)


def body():
    """Request JSON body as dict; empty/absent body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err(E_INVALID_REQUEST, "request body must be a JSON object")
    return data


def require_field(b, name):
    if name not in b or b[name] is None:
        err(E_INVALID_REQUEST, "field '%s' is required" % name)
    return b[name]


def min_len(value, n, field):
    if not isinstance(value, str) or len(value) < n:
        err(E_INVALID_REQUEST, "field '%s' must be at least %d characters" % (field, n))
    return value


def enum_field(value, allowed, field):
    if value not in allowed:
        err(E_INVALID_REQUEST, "field '%s' must be one of %s" % (field, sorted(allowed)))
    return value
