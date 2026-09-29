"""Core infrastructure: in-memory store, logical clock, envelope, errors, auth, validation.

Every structural name in this module is taken from PRD.md / SCAFFOLD.yaml:
  * auth headers            : X-User-ID, X-User-Role            (PRD 2.1)
  * envelope                : meta / response_type / data       (PRD 2.2)
  * error body              : error_id / message                (PRD 2.2)
  * pagination              : limit / offset / total_count / has_more (PRD 2.3)
  * pagination defaults     : limit 10 (1..100), offset 0        (PRD 2.3)
  * optimistic concurrency  : expected_loan_version / expected_foreclosure_case_version (PRD 2.9)
  * common fields           : id / created_at / updated_at / version (PRD 2.7)
"""

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1 - the seven declared roles)
# ---------------------------------------------------------------------------
ROLE_BORROWER = "Borrower"
ROLE_CONTRACTOR = "Contractor"
ROLE_LOAN_OFFICER = "LoanOfficer"
ROLE_CREDIT_COMMITTEE = "CreditCommittee"
ROLE_LOAN_SERVICER = "LoanServicer"
ROLE_DRAW_INSPECTOR = "DrawInspector"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ROLES = (
    ROLE_BORROWER,
    ROLE_CONTRACTOR,
    ROLE_LOAN_OFFICER,
    ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_SERVICER,
    ROLE_DRAW_INSPECTOR,
    ROLE_PLATFORM_ADMIN,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-Role header is missing, empty or not one of the seven declared roles.",
    "ERR_FORBIDDEN_ROLE": "The caller's role is not permitted on this operation.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are malformed.",
}


def invalid(message="The request body or query parameters are malformed."):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def conflict(error_id, message=None):
    return ApiError(error_id, 409, message)


def not_found(error_id, message=None):
    return ApiError(error_id, 404, message)


# ---------------------------------------------------------------------------
# In-memory store. Starts completely EMPTY on every boot -- no seeding.
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.borrowers = {}
        self.properties = {}
        self.applications = {}
        self.rehab_line_items = {}
        self.contractors = {}
        self.loans = {}
        self.draw_requests = {}
        self.draw_line_items = {}
        self.inspection_visits = {}
        self.lien_waivers = {}
        self.ledger_entries = {}
        self.accrual_periods = {}
        self.exit_milestones = {}
        self.foreclosure_cases = {}
        # logical clock (SCAFFOLD logical_clock.default_current_utc)
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
def clock_now():
    return db.clock


def clock_date():
    return db.clock.date()


def iso_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.7)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000
    )


def clock_instant():
    return iso_instant(db.clock)


def iso_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_instant(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, pagination, status=200):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Common record fields (PRD 2.7)
# ---------------------------------------------------------------------------
def new_record(full=True):
    stamp = clock_instant()
    rec = {"id": str(uuid.uuid4()), "created_at": stamp, "_seq": db.next_seq()}
    if full:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """A recomputation of a derived field counts as a mutation (PRD 2.7)."""
    if rec is None:
        return
    rec["updated_at"] = clock_instant()
    rec["version"] = rec.get("version", 1) + 1


def sort_records(records):
    return sorted(records, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1, 2.12 steps 1-2)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    if role is None:
        role = request.headers.get("X-Role")
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403)
    g.role = role
    g.user_id = request.headers.get("X-User-ID") or ""
    return role, g.user_id


def caller_role():
    return getattr(g, "role", None)


def caller_id():
    return getattr(g, "user_id", "")


def bypasses_ownership():
    return caller_role() == ROLE_PLATFORM_ADMIN


def require_borrower_owner(borrower_id):
    """PRD 2.1 / 2.12 step 5 -- entity backed Borrower ownership."""
    if caller_role() == ROLE_BORROWER and caller_id() != borrower_id:
        raise ApiError("ERR_NOT_OWNER", 403)


def require_contractor_owner(contractor_id):
    if caller_role() == ROLE_CONTRACTOR and caller_id() != contractor_id:
        raise ApiError("ERR_NOT_OWNER", 403)


# ---------------------------------------------------------------------------
# Schema validation helpers (PRD 2.12 step 3 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
_MISSING = object()


def json_body():
    if request.content_length:
        data = request.get_json(silent=True)
    else:
        data = request.get_json(silent=True) if request.data else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object.")
    return data


def _get(body, name, required):
    if name not in body or body[name] is None:
        if required:
            raise invalid("Field '%s' is required." % name)
        return _MISSING
    return body[name]


def f_str(body, name, required=True, allow_empty=False):
    v = _get(body, name, required)
    if v is _MISSING:
        return None
    if not isinstance(v, str):
        raise invalid("Field '%s' must be a string." % name)
    if not allow_empty and v.strip() == "":
        raise invalid("Field '%s' must be a non-empty string." % name)
    return v


def f_int(body, name, required=True, minimum=None, maximum=None):
    v = _get(body, name, required)
    if v is _MISSING:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid("Field '%s' must be an integer." % name)
    if minimum is not None and v < minimum:
        raise invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and v > maximum:
        raise invalid("Field '%s' must be <= %s." % (name, maximum))
    return v


def f_bool(body, name, required=True, default=None):
    v = _get(body, name, required)
    if v is _MISSING:
        return default
    if not isinstance(v, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return v


def f_enum(body, name, allowed, required=True):
    v = _get(body, name, required)
    if v is _MISSING:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return v


def parse_date(value, name):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 date string." % name)
    try:
        return date.fromisoformat(value)
    except Exception:
        raise invalid("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)


def f_date(body, name, required=True):
    v = _get(body, name, required)
    if v is _MISSING:
        return None
    return parse_date(v, name)


def parse_datetime(value, name):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 datetime string." % name)
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        raise invalid("Field '%s' must be an ISO 8601 datetime." % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def f_datetime(body, name, required=True):
    v = _get(body, name, required)
    if v is _MISSING:
        return None
    return parse_datetime(v, name)


def to_decimal(value, name, places=2, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number." % name)
    d = Decimal(str(value))
    if -d.as_tuple().exponent > places:
        raise invalid("Field '%s' may carry at most %d decimal places." % (name, places))
    if minimum is not None and d < minimum:
        raise invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and d > maximum:
        raise invalid("Field '%s' must be <= %s." % (name, maximum))
    return d


def f_array(body, name, required=True):
    v = _get(body, name, required)
    if v is _MISSING:
        return None
    if not isinstance(v, list):
        raise invalid("Field '%s' must be an array." % name)
    if len(v) == 0:
        raise invalid("Field '%s' must not be empty." % name)
    for entry in v:
        if not isinstance(entry, dict):
            raise invalid("Every entry of '%s' must be an object." % name)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def pagination_params():
    args = request.args
    limit = DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except Exception:
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise invalid("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except Exception:
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' may not be negative.")
    return limit, offset


def q_enum(name, allowed):
    if name not in request.args:
        return None
    v = request.args.get(name)
    if v not in allowed:
        raise invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return v


def q_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def paginate(records, serializer):
    limit, offset = pagination_params()
    ordered = sort_records(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [serializer(r) for r in page], meta


# ---------------------------------------------------------------------------
# Money / decimal helpers (PRD 2.6)
# ---------------------------------------------------------------------------
ONE = Decimal(1)


def rhu(value):
    """Round half up to a whole cent."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def floor_cents(value):
    return int(Decimal(value).quantize(ONE, rounding=ROUND_FLOOR))


def quantize(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def dec_out(value, places):
    """Serialize a Decimal percentage/score as a JSON number."""
    if value is None:
        return None
    return float(quantize(value, places))


def add_months(base, months):
    """Advance a date by whole calendar months, clamped to the last day of the target month."""
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = base.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def days_between(start, end):
    return (end - start).days


__all__ = [n for n in dir() if not n.startswith("__")]
