"""Core infrastructure: logical clock, in-memory store, errors, envelope, auth,
validation helpers and shared calculation primitives.

Every structural name here is taken from PRD.md / SCAFFOLD.yaml:
  - auth headers          : X-User-ID, X-User-Role            (PRD 2.1)
  - envelope              : meta / response_type / data       (PRD 2.2)
  - error body            : data.error_id / data.message      (PRD 2.2)
  - pagination            : limit / offset / total_count / has_more (PRD 2.3)
  - OCC field             : expected_engagement_version       (PRD 2.7)
  - common fields         : id / created_at / updated_at / version (PRD 2.4)
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1 — the six roles)
# ---------------------------------------------------------------------------
ROLES = (
    "AccountManager",
    "DeliveryLead",
    "Engineer",
    "ClientContact",
    "FinanceOfficer",
    "PlatformAdmin",
)
ALL_ROLES = ROLES

# ---------------------------------------------------------------------------
# Error catalogue (PRD 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CLIENT_SCOPE_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_SPRINT_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_TIME_ENTRY_NOT_FOUND": 404,
    "ERR_CHANGE_REQUEST_NOT_FOUND": 404,
    "ERR_RELEASE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_RETAINER_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_STALE_ENGAGEMENT_VERSION": 412,
    "ERR_ENGAGEMENT_NOT_ACTIVE": 409,
    "ERR_SPRINT_NOT_ACTIVE": 409,
    "ERR_INVALID_TRANSITION": 409,
    "ERR_MILESTONE_NOT_COMPLETED": 409,
    "ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_NOT_TICKET_ASSIGNEE": 422,
    "ERR_TICKET_CYCLE": 422,
    "ERR_MILESTONE_ENGAGEMENT_MISMATCH": 422,
    "ERR_WORK_DATE_OUT_OF_SPRINT": 422,
    "ERR_SPRINT_OVERLAP": 409,
    "ERR_RETAINER_WINDOW_CONFLICT": 409,
    "ERR_RETAINER_WINDOW_INACTIVE": 422,
    "ERR_SPRINT_SPEND_FROZEN": 409,
    "ERR_TICKET_BLOCKED": 409,
    "ERR_CR_ROUND_LIMIT": 409,
    "ERR_INVOICE_KIND_MISMATCH": 422,
    "ERR_INVOICE_NO_LINES": 422,
    "ERR_DUPLICATE_MILESTONE_INVOICE": 409,
    "ERR_BUDGET_HOURS_EXCEEDED": 422,
    "ERR_DAILY_HOURS_EXCEEDED": 422,
    "ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message="Malformed request body."):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) — startup default is exactly 2026-05-01T00:00:00Z
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = CLOCK_DEFAULT

    def set(self, dt):
        self.now = dt

    def today(self):
        return self.now.date()


clock = Clock()


# ---------------------------------------------------------------------------
# In-memory store — starts EMPTY on every boot. Nothing is ever seeded.
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.clients = {}
        self.engagements = {}
        self.milestones = {}
        self.sprints = {}
        self.tickets = {}
        self.time_entries = {}
        self.change_requests = {}
        self.releases = {}
        self.invoices = {}
        self.retainers = {}
        self.incidents = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# ---------------------------------------------------------------------------
# Numeric discipline (PRD 2.8) — Decimal everywhere, round half up
# ---------------------------------------------------------------------------
ZERO = Decimal("0")


def D(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


def r2(v):
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r4(v):
    return D(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return iso3(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items() if not k.startswith("_")}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def iso3(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso3(clock.now),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": jsonable(data)}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(items) < total,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": jsonable(items)}), 200


def error_response(e):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": e.error_id, "message": e.message},
            }
        ),
        e.http_status,
    )


# ---------------------------------------------------------------------------
# Auth (PRD 2.1) — precedence 1 (authentication) then 2 (role authorisation)
# ---------------------------------------------------------------------------
def auth(*roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or unrecognised identity headers.")
    g.user_id = user_id
    g.role = role
    if roles and role not in roles:
        err("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


def is_client_contact():
    return getattr(g, "role", None) == "ClientContact"


def scope_client(client_id):
    """PRD 2.6 — a ClientContact is confined to its own client's data."""
    if is_client_contact() and g.user_id != client_id:
        err("ERR_CLIENT_SCOPE_VIOLATION", "Resource belongs to another client.")


# ---------------------------------------------------------------------------
# Body / query validation (PRD 2.5 step 5)
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        invalid("Body must be a JSON object.")
    return b


def req_str(b, key):
    v = b.get(key)
    if not isinstance(v, str) or v.strip() == "":
        invalid("Field '%s' is required and must be a non-empty string." % key)
    return v


def opt_str(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str):
        invalid("Field '%s' must be a string." % key)
    return v


def req_enum(b, key, allowed):
    v = b.get(key)
    if not isinstance(v, str) or v not in allowed:
        invalid("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _decimals(v):
    exp = D(v).as_tuple().exponent
    return -exp if exp < 0 else 0


def req_number(b, key, positive=False, non_negative=False, max_dp=None,
               min_value=None, max_value=None):
    v = b.get(key)
    if not _is_number(v):
        invalid("Field '%s' must be a number." % key)
    d = D(v)
    if positive and d <= 0:
        invalid("Field '%s' must be strictly greater than 0." % key)
    if non_negative and d < 0:
        invalid("Field '%s' must not be negative." % key)
    if max_dp is not None and _decimals(v) > max_dp:
        invalid("Field '%s' must carry at most %d decimal places." % (key, max_dp))
    if min_value is not None and d < D(min_value):
        invalid("Field '%s' is below the permitted minimum." % key)
    if max_value is not None and d > D(max_value):
        invalid("Field '%s' is above the permitted maximum." % key)
    return d


def req_int(b, key, minimum=None):
    v = b.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        invalid("Field '%s' must be an integer." % key)
    if minimum is not None and v < minimum:
        invalid("Field '%s' must be at least %d." % (key, minimum))
    return v


def opt_bool(b, key, default):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, bool):
        invalid("Field '%s' must be a boolean." % key)
    return v


def req_date(b, key):
    v = b.get(key)
    if not isinstance(v, str):
        invalid("Field '%s' must be a YYYY-MM-DD date string." % key)
    return parse_date(v, key)


def parse_date(v, key="date"):
    try:
        d = datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        invalid("Field '%s' must be a YYYY-MM-DD date string." % key)
    return d


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            invalid("limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            invalid("offset must be an integer >= 0.")
        if offset < 0:
            invalid("offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    """PRD 2.3 — sorted by created_at ascending (oldest first)."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Entity lifecycle helpers (PRD 2.4)
# ---------------------------------------------------------------------------
def new_entity(fields):
    now = clock.now
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    row["updated_at"] = clock.now
    row["version"] += 1


# ---------------------------------------------------------------------------
# Existence resolution (PRD 2.5 steps 3 & 4)
# ---------------------------------------------------------------------------
_COLLECTIONS = {
    "client": ("clients", "ERR_CLIENT_NOT_FOUND"),
    "engagement": ("engagements", "ERR_ENGAGEMENT_NOT_FOUND"),
    "milestone": ("milestones", "ERR_MILESTONE_NOT_FOUND"),
    "sprint": ("sprints", "ERR_SPRINT_NOT_FOUND"),
    "ticket": ("tickets", "ERR_TICKET_NOT_FOUND"),
    "time_entry": ("time_entries", "ERR_TIME_ENTRY_NOT_FOUND"),
    "change_request": ("change_requests", "ERR_CHANGE_REQUEST_NOT_FOUND"),
    "release": ("releases", "ERR_RELEASE_NOT_FOUND"),
    "invoice": ("invoices", "ERR_INVOICE_NOT_FOUND"),
    "retainer": ("retainers", "ERR_RETAINER_NOT_FOUND"),
    "incident": ("incidents", "ERR_INCIDENT_NOT_FOUND"),
}


def must_get(kind, ident):
    coll_name, error_id = _COLLECTIONS[kind]
    coll = getattr(store, coll_name)
    if not isinstance(ident, str) or ident not in coll:
        err(error_id, "%s not found." % kind.replace("_", " ").title())
    return coll[ident]


def fk(b, key, kind, required=True):
    """Body foreign key existence — precedence step 4, ahead of well-formedness."""
    v = b.get(key)
    if v is None:
        if required:
            return None  # missing-ness is reported later by well-formedness
        return None
    return must_get(kind, v)
