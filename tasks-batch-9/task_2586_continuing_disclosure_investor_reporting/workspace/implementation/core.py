"""Core infrastructure: in-memory store, logical clock, response envelope,
error catalog, auth guard, request-shape validation helpers.

Storage is in-memory only. The store starts empty on every boot; no seeding.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, request

# ---------------------------------------------------------------- roles / auth
ROLE_FINANCE_DIRECTOR = "FinanceDirector"
ROLE_DISCLOSURE_OFFICER = "DisclosureOfficer"
ROLE_COMPLIANCE_REVIEWER = "ComplianceReviewer"
ROLE_DISSEMINATION_AGENT = "DisseminationAgent"
ALL_ROLES = (
    ROLE_FINANCE_DIRECTOR,
    ROLE_DISCLOSURE_OFFICER,
    ROLE_COMPLIANCE_REVIEWER,
    ROLE_DISSEMINATION_AGENT,
)
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ------------------------------------------------------------- error catalogue
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_AGENT_NOT_ENGAGED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ISSUE_NOT_FOUND": 404,
    "ERR_UNDERTAKING_NOT_FOUND": 404,
    "ERR_REQUIREMENT_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_CONTENT_ITEM_NOT_FOUND": 404,
    "ERR_EVENT_NOTICE_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_FAILURE_EVENT_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_OFFICIAL_STATEMENT_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_ISSUE_VERSION_STALE": 412,
    "ERR_UNDERTAKING_VERSION_STALE": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ISSUE_NOT_OUTSTANDING": 409,
    "ERR_UNDERTAKING_NOT_ACTIVE": 409,
    "ERR_ENGAGEMENT_NOT_ACTIVE": 409,
    "ERR_CYCLE_NOT_EDITABLE": 409,
    "ERR_CYCLE_HAS_LIVE_FILING": 409,
    "ERR_ENGAGEMENT_HAS_LIVE_FILING": 409,
    "ERR_UNDERTAKING_ALREADY_EXISTS": 409,
    "ERR_DUPLICATE_REQUIREMENT": 409,
    "ERR_DUPLICATE_EVENT_NOTICE": 409,
    "ERR_SUBJECT_ALREADY_FILED": 409,
    "ERR_RECEIPT_ID_DUPLICATE": 409,
    "ERR_NO_CONTENT_REQUIREMENTS": 409,
    "ERR_CONTENT_WEIGHTS_UNBALANCED": 422,
    "ERR_CONTENT_NOT_READY": 409,
    "ERR_NO_FILEABLE_CONTENT": 409,
    "ERR_CONTENT_DATA_AS_OF_REQUIRED": 409,
    "ERR_AUDIT_OPINION_REQUIRED": 409,
    "ERR_REQUIREMENT_NOT_WAIVABLE": 409,
    "ERR_WAIVER_REASON_REQUIRED": 422,
    "ERR_REPORTING_PERIOD_OVERLAP": 409,
    "ERR_OCCURRENCE_DATE_STALE": 422,
    "ERR_OCCURRENCE_DATE_IN_FUTURE": 422,
    "ERR_PLACEMENT_REVIEW_CAPACITY_EXCEEDED": 409,
    "ERR_ACK_DATE_OUT_OF_RANGE": 422,
    "ERR_FILING_SUBJECT_MISMATCH": 422,
    "ERR_SUPERSEDE_TARGET_INVALID": 409,
    "ERR_CORRECTION_REASON_REQUIRED": 422,
    "ERR_SUBMISSION_ATTEMPTS_EXHAUSTED": 409,
    "ERR_REMEDIATION_FILING_INVALID": 409,
    "ERR_DISCLOSURE_INADEQUATE": 409,
    "ERR_PER_SE_EVENT_IS_MATERIAL": 422,
    "ERR_ESCROW_INSUFFICIENT": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 422)
        self.message = message or error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ------------------------------------------------------------------- the store
class Store(object):
    """Flat in-memory tables keyed by id."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.bond_issues = {}
        self.undertakings = {}
        self.content_requirements = {}
        self.cycles = {}
        self.content_items = {}
        self.notices = {}
        self.filings = {}
        self.failure_events = {}
        self.placements = {}
        self.official_statements = {}
        self.engagements = {}
        self.seq = 0


DB = Store()

# ---------------------------------------------------------------- logical clock
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.current = CLOCK_START


class RequestCounter(object):
    """Monotonic per-request token, used to recognise rows minted right now."""

    def __init__(self):
        self.n = 0

    def next(self):
        self.n += 1
        return self.n


CLOCK = Clock()
REQUESTS = RequestCounter()


def clock_now():
    return CLOCK.current


def clock_date():
    return CLOCK.current.date()


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def clock_stamp():
    """Timestamp for every business `*_at` field: always the logical clock."""
    return fmt_ts(CLOCK.current)


def wall_stamp():
    return fmt_ts(datetime.now(timezone.utc))


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_str(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_dt_str(value):
    if not isinstance(value, str):
        return None
    txt = value.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def date_part(ts_string):
    parsed = parse_dt_str(ts_string)
    return parsed.date() if parsed else None


def day_diff(later, earlier):
    """Whole calendar days between two dates, floored at 0."""
    if later is None or earlier is None:
        return 0
    return max(0, (later - earlier).days)


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    return int(round_half_up(value, 0))


def num2(value):
    """2-decimal Decimal rendered as a JSON number."""
    return float(round_half_up(value, 2))


# --------------------------------------------------------------- row lifecycle
def new_row(fields, versioned=True):
    """Create a row. `created_at`/`updated_at` are stamped from the logical clock."""
    DB.seq += 1
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    stamp = clock_stamp()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = DB.seq
    # the request that minted the row; a brand new row never version-bumps
    row["_born"] = getattr(g, "_req", None)
    return row


_SKIP_ON_DIFF = ("updated_at", "version")


def _snapshot(row):
    snap = {}
    for key, value in row.items():
        if key.startswith("_") or key in _SKIP_ON_DIFF:
            continue
        snap[key] = list(value) if isinstance(value, list) else value
    return snap


def touch(row):
    """Register a row as possibly mutated by this request.

    At the end of the request every registered row whose persisted fields
    actually changed gets exactly one `version` bump and a fresh `updated_at`.
    """
    if row is None:
        return row
    registry = g.setdefault("_touched", {})
    key = id(row)
    if key not in registry:
        registry[key] = (row, _snapshot(row))
    return row


def bump(row):
    """Force a version advance even when no other field of the row changes
    (a filing draft advances its parent issue; an engagement its undertaking)."""
    touch(row)
    forced = g.setdefault("_forced", set())
    forced.add(id(row))
    return row


def finalize_mutations():
    registry = getattr(g, "_touched", None) or {}
    forced = getattr(g, "_forced", None) or set()
    stamp = clock_stamp()
    token = getattr(g, "_req", None)
    for row, snap in registry.values():
        if row.get("_born") == token:  # minted by this very request
            continue
        if "version" not in row:  # ContentRequirement: immutable, unversioned
            continue
        if id(row) in forced or _snapshot(row) != snap:
            row["version"] += 1
            row["updated_at"] = stamp


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


# -------------------------------------------------------------------- envelope
_ALNUM = string.ascii_uppercase + string.digits


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": wall_stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


class Obj(object):
    def __init__(self, row, status=200):
        self.row = row
        self.status = status


class Arr(object):
    def __init__(self, rows, pagination, status=200):
        self.rows = rows
        self.pagination = pagination
        self.status = status


class Raw(object):
    def __init__(self, data, status=200):
        self.data = data
        self.status = status


def render(result):
    if isinstance(result, Obj):
        return {"meta": _meta(), "response_type": "object",
                "data": public(result.row)}, result.status
    if isinstance(result, Arr):
        return {"meta": _meta(result.pagination), "response_type": "array",
                "data": [public(r) for r in result.rows]}, result.status
    if isinstance(result, Raw):
        return {"meta": _meta(), "response_type": "object",
                "data": result.data}, result.status
    raise RuntimeError("unsupported handler result")


def render_error(exc):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": exc.error_id, "message": exc.message}}, exc.http_status


# ------------------------------------------------------------------ auth ladder
def check_auth(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_id == "" or role is None or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "valid %s and %s headers are required"
             % (HEADER_USER_ID, HEADER_USER_ROLE))
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    g.user_id = user_id
    g.role = role


def endpoint(roles):
    """Wrap a handler: auth ladder rules 1-2, version bookkeeping, envelope."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            g._req = REQUESTS.next()
            g._touched = {}
            g._forced = set()
            try:
                check_auth(roles)
                result = fn(*args, **kwargs)
            except ApiError as exc:
                return render_error(exc)
            finalize_mutations()
            return render(result)
        return wrapper
    return decorator


# ------------------------------------------------------- request shape helpers
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def _missing(data, field):
    return field not in data or data[field] is None


def vstr(data, field, required=True, min_len=1, max_len=None, pattern=None,
         default=None):
    if _missing(data, field):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % field)
        return default
    value = data[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % field)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s is too short" % field)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s is too long" % field)
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "%s is malformed" % field)
    return value


def venum(data, field, allowed, required=True, default=None):
    if _missing(data, field):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % field)
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def vint(data, field, required=True, minimum=None, maximum=None, default=None):
    if _missing(data, field):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % field)
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s is below the permitted minimum" % field)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s is above the permitted maximum" % field)
    return value


def vbool(data, field, default=False):
    if _missing(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return value


def vdate(data, field, required=True, default=None):
    if _missing(data, field):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % field)
        return default
    parsed = parse_date_str(data[field])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 date (YYYY-MM-DD)" % field)
    return parsed


def vdatetime(data, field, required=True):
    if _missing(data, field):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % field)
        return None
    parsed = parse_dt_str(data[field])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % field)
    return parsed


def vid_list(data, field, default=None):
    if _missing(data, field):
        return default
    value = data[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % field)
    for element in value:
        if not isinstance(element, str) or element == "":
            fail("ERR_INVALID_REQUEST", "%s must contain identifier strings" % field)
    if len(set(value)) != len(value):
        fail("ERR_INVALID_REQUEST", "%s must not contain duplicates" % field)
    return list(value)


# ------------------------------------------------------------------- pagination
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def _int_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_PAGINATION", "%s must be an integer" % name)


def pagination():
    limit = _int_param("limit")
    offset = _int_param("offset")
    if limit is None:
        limit = PAGINATION_LIMIT_DEFAULT
    if offset is None:
        offset = PAGINATION_OFFSET_DEFAULT
    if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
        fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset must be zero or greater")
    return limit, offset


def listing(rows, filters=None):
    """Apply query filters, ordering (created_at ASC), then limit/offset."""
    limit, offset = pagination()
    selected = by_seq(rows)
    for param, field in (filters or {}).items():
        wanted = request.args.get(param)
        if wanted is None:
            continue
        selected = [r for r in selected if r.get(field) == wanted]
    total = len(selected)
    window = selected[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return Arr(window, meta)


# ------------------------------------------------------------ lookups (rule 3/4)
_TABLE_ERRORS = {
    "bond_issues": "ERR_ISSUE_NOT_FOUND",
    "undertakings": "ERR_UNDERTAKING_NOT_FOUND",
    "content_requirements": "ERR_REQUIREMENT_NOT_FOUND",
    "cycles": "ERR_CYCLE_NOT_FOUND",
    "content_items": "ERR_CONTENT_ITEM_NOT_FOUND",
    "notices": "ERR_EVENT_NOTICE_NOT_FOUND",
    "filings": "ERR_FILING_NOT_FOUND",
    "failure_events": "ERR_FAILURE_EVENT_NOT_FOUND",
    "placements": "ERR_PLACEMENT_NOT_FOUND",
    "official_statements": "ERR_OFFICIAL_STATEMENT_NOT_FOUND",
    "engagements": "ERR_ENGAGEMENT_NOT_FOUND",
}


def must_get(table, row_id):
    """Path/body reference resolution. Missing rows raise the table's 404."""
    rows = getattr(DB, table)
    if not isinstance(row_id, str) or row_id not in rows:
        fail(_TABLE_ERRORS[table], "%s %r does not exist" % (table, row_id))
    return rows[row_id]


def fk(table, data, field):
    """Resolve an optional body foreign key; absent/null values are deferred
    to the request-shape rule, present-but-unknown values raise the 404."""
    if _missing(data, field):
        return None
    return must_get(table, data[field])


def issue_of(row_id):
    return DB.bond_issues.get(row_id)


def undertaking_for_issue(issue_id):
    for row in by_seq(DB.undertakings.values()):
        if row["issue_id"] == issue_id:
            return row
    return None


def requirements_of(undertaking_id):
    return by_seq([r for r in DB.content_requirements.values()
                   if r["undertaking_id"] == undertaking_id])


def cycles_of(undertaking_id):
    return by_seq([r for r in DB.cycles.values()
                   if r["undertaking_id"] == undertaking_id])


def items_of(cycle_id):
    return by_seq([r for r in DB.content_items.values() if r["cycle_id"] == cycle_id])


def notices_of_issue(issue_id):
    return by_seq([r for r in DB.notices.values() if r["issue_id"] == issue_id])


def placements_of_issue(issue_id):
    return by_seq([r for r in DB.placements.values() if r["issue_id"] == issue_id])


def engagements_of(undertaking_id):
    return by_seq([r for r in DB.engagements.values()
                   if r["undertaking_id"] == undertaking_id])


def failure_events_of(undertaking_id):
    return by_seq([r for r in DB.failure_events.values()
                   if r["undertaking_id"] == undertaking_id])


def failure_events_of_cycle(cycle_id):
    return by_seq([r for r in DB.failure_events.values() if r["cycle_id"] == cycle_id])


def statements_of_issue(issue_id):
    return by_seq([r for r in DB.official_statements.values()
                   if r["issue_id"] == issue_id])


def filings_of_engagement(engagement_id):
    return by_seq([r for r in DB.filings.values()
                   if r["submitting_engagement_id"] == engagement_id])


def undertaking_of_cycle(cycle):
    return DB.undertakings.get(cycle["undertaking_id"]) if cycle else None
