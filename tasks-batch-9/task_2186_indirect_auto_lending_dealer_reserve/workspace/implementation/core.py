"""Core infrastructure: logical clock, in-memory store, response envelope,
errors, auth, validation helpers and exact-rational rounding."""
import re
import uuid
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fractions import Fraction

from flask import g, request, jsonify

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) - startup default 2026-08-01T00:00:00Z, never falls
# back to wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.current = CLOCK_DEFAULT

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


clock = Clock()

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Constants (PRD 3)
# ---------------------------------------------------------------------------
PROGRAM_MAX_MARKUP_BPS = 250
MAX_DTI_PCT = Decimal("45.00")
PARTICIPATION_FACTOR = Fraction(55, 100)
FLAT_FEE_BPS = 150
INCENTIVE_BPS = 25
INCENTIVE_CAP_CENTS = 15000
PROGRAM_RESERVE_CAP_CENTS = 250000
BUYBACK_ADMIN_FEE_CENTS = 25000
EARLY_PAYOFF_SEASONING_MONTHS = 12
PROBATION_MIN_FUNDED_COUNT = 2
PROBATION_EARLY_PAYOFF_RATE_BPS = 3000
AGREEMENT_NOTICE_BUFFER_DAYS = 30
FUNDING_WINDOW_DAYS = 30
MAX_RESUBMISSIONS = 2
MIN_REVIEW_POPULATION = 4
DISPARITY_THRESHOLD_BPS = 25
W_DEFAULT = Fraction(6)
W_EARLY = Fraction(2)
W_DOC = Fraction(3, 2)
W_MARKUP = Fraction(1)
MARKUP_BENCHMARK_BPS = 150

BASE_REQUIRED_DOC_TYPES = [
    "RETAIL_INSTALLMENT_CONTRACT",
    "TITLE_APPLICATION",
    "INSURANCE_BINDER",
]
DOC_TYPES = BASE_REQUIRED_DOC_TYPES + ["INCOME_VERIFICATION"]

ROLES = [
    "PortfolioAdmin",
    "CreditAnalyst",
    "FundingSpecialist",
    "DealerPrincipal",
    "ComplianceOfficer",
]
ALL_ROLES = list(ROLES)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_DEALER_SCOPE_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DEALER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_RATE_SHEET_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_BUYBACK_NOT_FOUND": 404,
    "ERR_SCORECARD_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_RESERVE_ENTRY_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DOCS_NOT_VERIFIED": 409,
    "ERR_APPLICATION_NOT_APPROVED": 409,
    "ERR_STALE_DEALER_VERSION": 412,
    "ERR_DEALER_COMPLIANCE_HOLD": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_DEALER_NOT_ACTIVE": 409,
    "ERR_NO_INFORCE_AGREEMENT": 422,
    "ERR_NO_EFFECTIVE_RATE_SHEET": 422,
    "ERR_RATE_SHEET_NO_TIERS": 422,
    "ERR_RATE_SHEET_WINDOW_OVERLAP": 409,
    "ERR_AGREEMENT_WINDOW_CONFLICT": 409,
    "ERR_FUNDING_WINDOW_EXPIRED": 422,
    "ERR_INVALID_EVENT_DATE": 422,
    "ERR_NO_ELIGIBLE_TIER": 422,
    "ERR_DTI_EXCEEDED": 422,
    "ERR_MARKUP_CAP_EXCEEDED": 422,
    "ERR_ADVANCE_LIMIT_EXCEEDED": 422,
    "ERR_RESUBMISSION_LIMIT": 409,
    "ERR_INSUFFICIENT_REVIEW_POPULATION": 422,
    "ERR_CONTRACT_NOT_FUNDED": 409,
    "ERR_DEALER_FUNDING_LINE_EXCEEDED": 409,
    "ERR_RESERVE_BALANCE_NEGATIVE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def parse_dt(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def stamp(rec, name, dt):
    """System-generated timestamp: canonical format + parsed shadow."""
    if dt is None:
        rec[name] = None
        rec["_" + name + "_dt"] = None
    else:
        rec[name] = fmt_dt(dt)
        rec["_" + name + "_dt"] = dt


def putdt(rec, name, raw, dt):
    """Client-supplied timestamp: echoed verbatim + parsed shadow."""
    rec[name] = raw
    rec["_" + name + "_dt"] = dt


def dtv(rec, name):
    return rec.get("_" + name + "_dt")


def days_between(start, end):
    """Whole days between two instants (floor)."""
    return int((end - start).total_seconds() // 86400)


def months_from_days(start, end):
    return days_between(start, end) // 30


# ---------------------------------------------------------------------------
# Exact rounding helpers (round half up, away from zero)
# ---------------------------------------------------------------------------
def F(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    return Fraction(value)


def rhu(value):
    """round_half_up to a whole number; ties away from zero."""
    x = F(value)
    n, d = x.numerator, x.denominator
    if n >= 0:
        return (2 * n + d) // (2 * d)
    return -((-2 * n + d) // (2 * d))


def rhu2(value):
    """round_half_up to 2 decimal places, returned as Decimal."""
    return Decimal(rhu(F(value) * 100)) / Decimal(100)


def dec2float(value):
    return float(value)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.dealers = {}
        self.agreements = {}
        self.sheets = {}
        self.tiers = {}
        self.applications = {}
        self.contracts = {}
        self.documents = {}
        self.entries = {}
        self.events = {}
        self.scorecards = {}
        self.reviews = {}
        self.demands = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_rec(versioned=True):
    rec = {"id": str(uuid.uuid4())}
    now = clock.now()
    stamp(rec, "created_at", now)
    rec["_seq"] = store.next_seq()
    if versioned:
        stamp(rec, "updated_at", now)
        rec["version"] = 1
    return rec


def bump(rec):
    if rec is None:
        return
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        stamp(rec, "updated_at", clock.now())


def serialize(rec):
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, Fraction):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def sort_key(rec):
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


def by_created(records):
    return sorted(records, key=sort_key)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_meta():
    rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
    return {"api_request_id": rid, "api_request_timestamp": fmt_dt(clock.now())}


def ok(data, code=200):
    body = {"meta": request_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_list(items, pagination):
    meta = request_meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_STATUS.get(error_id, 400)


# ---------------------------------------------------------------------------
# Auth / RBAC / dealer scope (PRD 2.1, 2.7)
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "Missing authentication headers.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "Empty authentication headers.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    if g.role not in roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % g.role)


def is_dealer_principal():
    return g.role == "DealerPrincipal"


def scope_dealer_id(dealer_id):
    """Ownership check against an identifier we already hold."""
    if is_dealer_principal() and dealer_id is not None and dealer_id != g.user_id:
        fail("ERR_DEALER_SCOPE_VIOLATION", "Dealer principal may only act for its own dealership.")


def scope_body_dealer_id(body):
    if not is_dealer_principal():
        return
    value = body.get("dealer_id")
    if isinstance(value, str) and value.strip() and value != g.user_id:
        fail("ERR_DEALER_SCOPE_VIOLATION", "Dealer principal may only name its own dealership.")


# ---------------------------------------------------------------------------
# Body access + field validation (ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        if request.data.strip():
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


_MISSING = object()


def _present(body, name):
    return name in body and body[name] is not None


def v_str(body, name, required=True, min_len=1, max_len=None, default=None, pattern=None, nonblank=True):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if nonblank and not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % name)
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "Field '%s' has an invalid format." % name)
    return value


def v_int(body, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below the permitted minimum." % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above the permitted maximum." % name)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def v_dt(body, name, required=True, default=None):
    """Returns (raw_string, parsed_datetime)."""
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return (default, None)
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 string." % name)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 instant." % name)
    return (value, parsed)


def v_id(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
_INT_RE = re.compile(r"^[+-]?\d+$")


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not _INT_RE.match(raw.strip()):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(raw.strip())
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def paginate(records):
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def list_response(records):
    page, meta = paginate(records)
    return ok_list([serialize(r) for r in page], meta)


def qfilter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# ---------------------------------------------------------------------------
# Path-parameter resolution (left to right)
# ---------------------------------------------------------------------------
def get_dealer(dealer_id):
    rec = store.dealers.get(dealer_id)
    if rec is None:
        fail("ERR_DEALER_NOT_FOUND", "No dealer with id %s." % dealer_id)
    return rec


def get_agreement(agreement_id):
    rec = store.agreements.get(agreement_id)
    if rec is None:
        fail("ERR_AGREEMENT_NOT_FOUND", "No dealer agreement with id %s." % agreement_id)
    return rec


def get_sheet(sheet_id):
    rec = store.sheets.get(sheet_id)
    if rec is None:
        fail("ERR_RATE_SHEET_NOT_FOUND", "No rate sheet with id %s." % sheet_id)
    return rec


def get_application(app_id):
    rec = store.applications.get(app_id)
    if rec is None:
        fail("ERR_APPLICATION_NOT_FOUND", "No credit application with id %s." % app_id)
    return rec


def get_contract(contract_id):
    rec = store.contracts.get(contract_id)
    if rec is None:
        fail("ERR_CONTRACT_NOT_FOUND", "No retail contract with id %s." % contract_id)
    return rec


def get_document(document_id):
    rec = store.documents.get(document_id)
    if rec is None:
        fail("ERR_DOCUMENT_NOT_FOUND", "No contract document with id %s." % document_id)
    return rec


def get_demand(demand_id):
    rec = store.demands.get(demand_id)
    if rec is None:
        fail("ERR_BUYBACK_NOT_FOUND", "No buyback demand with id %s." % demand_id)
    return rec


def get_scorecard(scorecard_id):
    rec = store.scorecards.get(scorecard_id)
    if rec is None:
        fail("ERR_SCORECARD_NOT_FOUND", "No dealer scorecard with id %s." % scorecard_id)
    return rec


def get_review(review_id):
    rec = store.reviews.get(review_id)
    if rec is None:
        fail("ERR_REVIEW_NOT_FOUND", "No fair lending review with id %s." % review_id)
    return rec


def get_entry(entry_id):
    rec = store.entries.get(entry_id)
    if rec is None:
        fail("ERR_RESERVE_ENTRY_NOT_FOUND", "No reserve entry with id %s." % entry_id)
    return rec
