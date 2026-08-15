"""Core infrastructure: in-memory store, logical clock, errors, response
envelope, auth middleware, datetime utilities, rounding, pagination.

Storage is in-memory only (plain dicts keyed by id). Every process boot
starts with an empty store — no seeding, no files, no external persistence.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import request

# ---------------------------------------------------------------------------
# Error catalog (error_id -> http status), from SCAFFOLD Table 6 / PRD §5
# ---------------------------------------------------------------------------
ERRORS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_DATE_RANGE": 400,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_EMPLOYER_ALREADY_EXISTS": 409,
    "ERR_DUPLICATE_AGENCY": 409,
    "ERR_AGREEMENT_OVERLAP": 409,
    "ERR_EMPLOYEE_NOT_ACTIVE": 409,
    "ERR_DUPLICATE_NEXUS_CASE": 409,
    "ERR_NEXUS_NOT_CONFIRMED": 409,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_REGISTRATION_NOT_SETTLED": 409,
    "ERR_ELECTION_OVERLAP": 409,
    "ERR_RECIPROCITY_NOT_AVAILABLE": 422,
    "ERR_REGISTRATION_NOT_ACTIVE": 409,
    "ERR_AGENCY_KIND_MISMATCH": 422,
    "ERR_VC_NOT_ALLOWED_NEW_EMPLOYER": 422,
    "ERR_NO_NET_SAVINGS": 422,
    "ERR_DEADLINE_PASSED": 409,
    "ERR_RATE_SUPERSEDED": 409,
    "ERR_LOCATION_CHANGE_PENDING": 409,
    "ERR_ABATEMENT_WINDOW_CLOSED": 409,
    "ERR_ABATEMENT_NOT_ELIGIBLE": 422,
    "ERR_ABATEMENT_PENDING": 409,
    "ERR_AMOUNT_EXCEEDS_PENALTY": 422,
    "ERR_COMPANY_POSTURE_DELINQUENT": 409,
}

ALL_ROLES = [
    "TaxDirector",
    "NexusAnalyst",
    "UISpecialist",
    "PayrollComplianceLead",
    "Employee",
    "Auditor",
]

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class APIError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERRORS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def err(error_id, message=None):
    raise APIError(error_id, message)


# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.clock = parse_dt(DEFAULT_CLOCK_ISO)
        self.seq = 0
        self.employers = {}
        self.employer_id = None
        self.agencies = {}
        self.agreements = {}
        self.locations = {}
        self.employees = {}
        self.nexus_cases = {}
        self.registrations = {}
        self.elections = {}
        self.assignments = {}
        self.ui_rates = {}
        self.vcs = {}
        self.location_changes = {}
        self.obligations = {}
        self.notices = {}
        self.abatements = {}


def next_seq():
    db.seq += 1
    return db.seq


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO-8601 date or datetime into an aware UTC datetime.
    Date-only inputs are carried at 00:00:00Z. Raises ValueError on junk."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if _ISO_DATE_RE.match(s):
            s = s + "T00:00:00Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError("not a datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def try_parse_dt(value):
    try:
        return parse_dt(value)
    except Exception:
        return None


def fmt_dt(dt):
    """Logical-clock / date fields: seconds precision, millis when needed."""
    if dt is None:
        return None
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(dt):
    """created_at / updated_at / request timestamps: three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding: round half up (toward +infinity on an exact .5), integer result
# ---------------------------------------------------------------------------
def rhu(numerator, denominator):
    """round_half_up(numerator / denominator) to an integer, exact arithmetic."""
    from fractions import Fraction

    f = Fraction(int(numerator), int(denominator))
    # floor(f + 1/2)
    return (2 * f.numerator + f.denominator) // (2 * f.denominator)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(store, fields):
    now = wall_now()
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = fmt_ts(now)
    rec["updated_at"] = fmt_ts(now)
    rec["version"] = 1
    rec["_seq"] = next_seq()
    store[rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = fmt_ts(wall_now())
    rec["version"] = int(rec.get("version", 1)) + 1


def ser_value(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, dict):
        return {k: ser_value(x) for k, x in v.items() if not str(k).startswith("_")}
    if isinstance(v, list):
        return [ser_value(x) for x in v]
    return v


def pub(rec):
    """Public serialization: strip internal '_' keys, format datetimes."""
    return {k: ser_value(v) for k, v in rec.items() if not str(k).startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope / PRD §2.2)
# ---------------------------------------------------------------------------
def meta_block():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(wall_now()),
    }


def ok_object(rec, status=200):
    body = {"meta": meta_block(), "response_type": "object", "data": pub(rec)}
    return body, status


def ok_data(data, status=200):
    body = {"meta": meta_block(), "response_type": "object", "data": data}
    return body, status


def ok_list(recs, total, limit, offset):
    has_more = (offset + len(recs)) < total
    meta = meta_block()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        }
    )
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [pub(r) for r in recs],
    }
    return body, 200


def error_body(error_id, message):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, ERRORS[error_id]


# ---------------------------------------------------------------------------
# Auth (validation priorities 1-2-4): headers, role, employee ownership
# ---------------------------------------------------------------------------
def get_context():
    """Returns (user_id, role). Enforces header presence (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip() or not role or not str(role).strip():
        err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return str(user_id), str(role)


def require_roles(*roles):
    """Priority 1 then priority 2."""
    user_id, role = get_context()
    if role not in roles:
        err("ERR_FORBIDDEN_FOR_ROLE", f"Role {role} is not authorized for this endpoint")
    return user_id, role


def require_owner(user_id, employee_id):
    """Priority 4: Employee-role callers may only act on their own resources."""
    if employee_id != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Employee-role caller does not own this resource")


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def missing(b, field):
    return field not in b or b[field] is None


def require_field(b, field):
    if missing(b, field):
        err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return b[field]


def get_int(b, field, required=False, minimum=None):
    if missing(b, field):
        if required:
            err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return None
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def get_str(b, field, required=False):
    if missing(b, field):
        if required:
            err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return None
    v = b[field]
    if not isinstance(v, str) or not v.strip():
        err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def get_enum(b, field, values, required=False):
    v = get_str(b, field, required=required)
    if v is None:
        return None
    if v not in values:
        err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(values)}")
    return v


def get_bool(b, field, default=None):
    if missing(b, field):
        return default
    v = b[field]
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def get_dt(b, field, required=False):
    """Datetime body field; unparseable -> ERR_INVALID_REQUEST (general sanity)."""
    if missing(b, field):
        if required:
            err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return None
    dt = try_parse_dt(b[field])
    if dt is None:
        err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO-8601 date/datetime")
    return dt


def lookup(store, rid):
    rec = store.get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", f"Resource not found: {rid}")
    return rec


def check_occ(b, field, current_version):
    """Priority 7 optimistic concurrency. Field is non-optional on OCC endpoints."""
    if missing(b, field):
        err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if v != current_version:
        err(
            "ERR_STALE_VERSION",
            f"{field}={v} does not match current version {current_version}",
        )


# ---------------------------------------------------------------------------
# Pagination (limit/offset; defaults 10/0, min 1, max 100; sort created_at asc)
# ---------------------------------------------------------------------------
def paginate(recs):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    ordered = sorted(recs, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total, limit, offset


def parse_bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    err("ERR_INVALID_REQUEST", f"{name} must be true or false")


def filter_records(store, filters):
    """filters: list of (field_name, raw_value); None raw -> skip. Exact match."""
    out = []
    for rec in store.values():
        ok = True
        for field, raw in filters:
            if raw is None:
                continue
            cur = rec.get(field)
            if isinstance(cur, bool):
                if parse_query_bool(field, raw) != cur:
                    ok = False
                    break
            elif isinstance(cur, int) and not isinstance(cur, bool):
                try:
                    if int(raw) != cur:
                        ok = False
                        break
                except (TypeError, ValueError):
                    err("ERR_INVALID_REQUEST", f"{field} filter must be an integer")
            else:
                if str(raw) != ("" if cur is None else str(cur)):
                    ok = False
                    break
        if ok:
            out.append(rec)
    return out


def parse_query_bool(field, raw):
    if str(raw).lower() == "true":
        return True
    if str(raw).lower() == "false":
        return False
    err("ERR_INVALID_REQUEST", f"{field} filter must be true or false")


# The singleton store. Instantiated last so DB.__init__ can use parse_dt.
db = DB()
