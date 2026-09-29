"""Core infrastructure: in-memory store, response envelope, errors, auth, validation."""
import calendar
import functools
import random
import string
import uuid
from datetime import date, datetime, timezone

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1 / scaffold 1.7)
# ---------------------------------------------------------------------------
ROLE_PRODUCTION_ADMIN = "ProductionAdmin"
ROLE_ARCHIVE_RESEARCHER = "ArchiveResearcher"
ROLE_CLEARANCE_SUPERVISOR = "ClearanceSupervisor"
ROLE_RIGHTS_HOLDER_REP = "RightsHolderRep"
ROLE_LEGAL_COUNSEL = "LegalCounsel"

ALL_ROLES = (
    ROLE_PRODUCTION_ADMIN,
    ROLE_ARCHIVE_RESEARCHER,
    ROLE_CLEARANCE_SUPERVISOR,
    ROLE_RIGHTS_HOLDER_REP,
    ROLE_LEGAL_COUNSEL,
)

# ---------------------------------------------------------------------------
# Error catalog (scaffold 1.6 / PRD 5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ARCHIVE_OWNERSHIP_MISMATCH": 403,
    "ERR_PARTY_ROLE_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_REVIEW_TYPE_ROLE_MISMATCH": 403,
    # existence
    "ERR_PRODUCTION_NOT_FOUND": 404,
    "ERR_ARCHIVE_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_SOURCE_CANDIDATE_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_FAIR_USE_ANALYSIS_NOT_FOUND": 404,
    "ERR_OPINION_LETTER_NOT_FOUND": 404,
    "ERR_SUBJECT_RELEASE_NOT_FOUND": 404,
    "ERR_CLEARANCE_CHART_NOT_FOUND": 404,
    "ERR_EO_APPLICATION_NOT_FOUND": 404,
    "ERR_DELIVERY_PACKAGE_NOT_FOUND": 404,
    # payload
    "ERR_INVALID_REQUEST": 400,
    # occ
    "ERR_STALE_PRODUCTION_VERSION": 412,
    "ERR_STALE_LICENSE_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_PRODUCTION_NOT_IN_CLEARANCE": 409,
    "ERR_LICENSE_NOT_QUOTED": 409,
    "ERR_NO_SELECTED_SOURCE": 409,
    "ERR_NO_AVAILABLE_SOURCE": 409,
    "ERR_ARCHIVE_SUSPENDED": 409,
    "ERR_PRODUCTION_POSTURE_BLOCKED": 409,
    "ERR_PRODUCTION_POSTURE_RESTRICTED": 409,
    "ERR_CHART_STALE": 409,
    "ERR_CHART_SUPERSEDED": 409,
    "ERR_NO_ISSUED_OPINION_LETTER": 409,
    "ERR_REVIEW_ALREADY_RECORDED": 409,
    "ERR_REVIEWS_INCOMPLETE": 409,
    "ERR_EO_NOT_BOUND": 409,
    "ERR_NO_DELIVERED_PACKAGE": 409,
    "ERR_CUE_SHEET_INCOMPLETE": 409,
    "ERR_WINDOW_CLASS_INSUFFICIENT": 409,
    "ERR_NO_APPROVAL_RIGHTS": 409,
    "ERR_LICENSES_STILL_LIVE": 409,
    "ERR_NEGOTIATION_ROUND_LIMIT": 409,
    "ERR_RELEASE_REVISION_LIMIT": 409,
    "ERR_LICENSE_TERM_OVERLAP": 409,
    "ERR_DEPICTION_WINDOW_CONFLICT": 409,
    "ERR_OUTSIDE_RENEWAL_WINDOW": 409,
    # referential / semantic
    "ERR_ASSET_PRODUCTION_MISMATCH": 422,
    "ERR_CHART_PRODUCTION_MISMATCH": 422,
    "ERR_NO_ACTIVE_RATE_CARD": 422,
    "ERR_MUSIC_LEG_REQUIRED": 422,
    "ERR_TERM_DATES_INVALID": 422,
    "ERR_INVALID_RENEWAL_TERM": 422,
    "ERR_FAIR_USE_SCORE_INSUFFICIENT": 422,
    "ERR_COVERAGE_LIMIT_INVALID": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message="The request body or query is malformed."):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# In-memory store.  Starts completely empty on every boot; nothing is seeded.
# ---------------------------------------------------------------------------
CLOCK_STARTUP_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.productions = {}
        self.archives = {}
        self.rate_cards = {}
        self.assets = {}
        self.source_candidates = {}
        self.licenses = {}
        self.negotiation_rounds = {}
        self.fair_use_analyses = {}
        self.opinion_letters = {}
        self.subject_releases = {}
        self.clearance_charts = {}
        self.eo_applications = {}
        self.delivery_packages = {}
        self._seq = 0
        self.clock = CLOCK_STARTUP_DEFAULT

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def clock_now():
    return db.clock


def clock_date():
    return db.clock.date()


# ---------------------------------------------------------------------------
# Timestamps / ids / row helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def new_row(with_version=True):
    row = {"id": new_id(), "created_at": now_iso()}
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    return jsonify({"meta": meta, "response_type": "array", "data": window}), 200


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, ladder rungs 1-3)
# ---------------------------------------------------------------------------
def guard(*allowed_roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or not str(user_id).strip():
                fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
            if role is None or not str(role).strip():
                fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
            if role not in ALL_ROLES:
                fail("ERR_UNAUTHENTICATED", "X-User-Role names an unknown role.")
            g.user_id = user_id
            g.role = role
            if role not in allowed_roles:
                fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_role(*roles):
    if g.role not in roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % g.role)


# ---------------------------------------------------------------------------
# Body / query helpers (ladder rung 7)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            invalid("limit must be an integer.")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            invalid("offset must be an integer.")
        if offset < 0:
            invalid("offset must be 0 or greater.")
    return limit, offset


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        invalid("Field '%s' is required and must be a non-empty string." % key)
    return value


def opt_str(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    return value


def req_enum(data, key, domain):
    value = data.get(key)
    if not isinstance(value, str) or value not in domain:
        invalid("Field '%s' must be one of %s." % (key, sorted(domain)))
    return value


def opt_enum(data, key, domain, default=None):
    if key not in data or data[key] is None:
        return default
    return req_enum(data, key, domain)


def req_int(data, key, minimum=0, maximum=None):
    value = data.get(key)
    if not is_int(value):
        invalid("Field '%s' is required and must be an integer." % key)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(data, key, default=None, minimum=0, maximum=None):
    if key not in data or data[key] is None:
        return default
    return req_int(data, key, minimum, maximum)


def req_num(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % key)
    if value < 0:
        invalid("Field '%s' must be non-negative." % key)
    return value


def parse_date(value, key="date"):
    if not isinstance(value, str):
        invalid("Field '%s' must be an ISO date (YYYY-MM-DD)." % key)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        invalid("Field '%s' must be an ISO date (YYYY-MM-DD)." % key)


def req_date(data, key):
    if key not in data or data[key] is None:
        invalid("Field '%s' is required." % key)
    return parse_date(data[key], key)


def opt_date(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return parse_date(data[key], key)


def iso_date(d):
    return d.isoformat()


# ---------------------------------------------------------------------------
# Date arithmetic (PRD 2.11)
# ---------------------------------------------------------------------------
def add_months(d, n):
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def whole_month_span(start, end):
    months = (end.year - start.year) * 12 + (end.month - start.month)
    while months > 0 and add_months(start, months) > end:
        months -= 1
    while add_months(start, months + 1) <= end:
        months += 1
    return months


def term_months_consistent(start, end, term_months):
    span = whole_month_span(start, end)
    if term_months == span:
        return True
    remainder = (end - add_months(start, span)).days
    return remainder > 0 and term_months == span + 1


def days_between(a, b):
    return (b - a).days
