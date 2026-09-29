"""Core plumbing: error catalogue, in-memory store, logical clock, response
envelope, authentication and request-shape validation.

Every structural name in this module is taken from PRD.md / SCAFFOLD.yaml:
  * identity headers        : X-User-ID / X-User-Role  (PRD 2.1)
  * success envelope        : meta / response_type / data  (PRD 2.2)
  * error envelope payload  : data.error_id / data.message  (PRD 2.2)
  * pagination fields       : limit / offset / total_count / has_more  (PRD 2.3)
  * OCC fields              : expected_title_version / expected_issue_version (PRD 2.9)
  * common system fields    : id / created_at / updated_at / version  (PRD 2.5)
"""

import copy
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_RESOURCE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CREATOR_NOT_FOUND": 404,
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_ISSUE_NOT_FOUND": 404,
    "ERR_STAGE_NOT_FOUND": 404,
    "ERR_CATALOG_NOT_FOUND": 404,
    "ERR_SOLICITATION_NOT_FOUND": 404,
    "ERR_VARIANT_COVER_NOT_FOUND": 404,
    "ERR_RETAILER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_PRINT_RUN_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_STALE_TITLE_VERSION": 412,
    "ERR_STALE_ISSUE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_RETURNS_NOT_PERMITTED": 409,
    "ERR_STATEMENT_ALREADY_PAID": 409,
    "ERR_TITLE_NOT_GREENLIT": 409,
    "ERR_ASSIGNMENT_NOT_ACCEPTED": 409,
    "ERR_CATALOG_NOT_LOCKED": 409,
    "ERR_ISSUE_NOT_SOLICITED": 409,
    "ERR_RETAILER_NOT_ACTIVE": 409,
    "ERR_NOT_CAMERA_READY": 409,
    "ERR_PRINT_NOT_COMPLETE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_NON_RETURNABLE_ACK_REQUIRED": 409,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 409,
    "ERR_SOLICITATION_WINDOW_CLOSED": 409,
    "ERR_CATALOG_DEADLINE_NOT_PASSED": 409,
    "ERR_FOC_NOT_REACHED": 409,
    "ERR_FOC_ALREADY_PASSED": 409,
    "ERR_ON_SALE_DATE_NOT_REACHED": 409,
    "ERR_DIGITAL_EMBARGO_VIOLATION": 422,
    "ERR_CANNIBALIZATION_WINDOW_CONFLICT": 409,
    "ERR_CREATOR_DOUBLE_BOOKED": 409,
    "ERR_ON_SALE_CADENCE_CONFLICT": 409,
    "ERR_COLLECTED_EDITION_CONFLICT": 409,
    "ERR_DUPLICATE_ISSUE_NUMBER": 409,
    "ERR_DUPLICATE_VARIANT_CODE": 409,
    "ERR_DUPLICATE_SOLICITATION": 409,
    "ERR_DUPLICATE_STATEMENT_PERIOD": 409,
    "ERR_CATALOG_SLOTS_EXHAUSTED": 409,
    "ERR_CRAFT_NOT_SUPPORTED": 422,
    "ERR_CRAFT_MISMATCH": 422,
    "ERR_TITLE_SCOPE_MISMATCH": 422,
    "ERR_VARIANT_RATIO_INVALID": 422,
    "ERR_VARIANT_NOT_AVAILABLE": 422,
    "ERR_NO_QUALIFYING_ORDERS": 409,
    "ERR_NO_ACCEPTED_SOLICITATIONS": 409,
    "ERR_STANDARD_COVER_REQUIRED": 409,
    "ERR_REQUIRED_CRAFT_STAGES_MISSING": 409,
    "ERR_NO_ASSIGNMENT_FOR_CREATOR": 409,
    "ERR_ROYALTY_SHARE_POOL_EXCEEDED": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_ZERO_PAYABLE_STATEMENT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# ---------------------------------------------------------------------------
# Domain vocabularies
# ---------------------------------------------------------------------------

ROLES = [
    "EditorInChief",
    "ManagingEditor",
    "SalesDirector",
    "RoyaltyAccountant",
    "Creator",
    "Retailer",
]

CRAFTS = ["SCRIPT", "PENCILS", "INKS", "COLORS", "LETTERS", "COVER"]
REQUIRED_CRAFTS = ["SCRIPT", "PENCILS", "INKS", "COLORS", "LETTERS"]

TITLE_STATUSES = ["PITCHED", "GREENLIT", "IN_PRODUCTION", "PUBLISHING", "COMPLETED", "CANCELLED"]
ASSIGNMENT_STATUSES = ["PROPOSED", "COUNTERED", "ACCEPTED", "ACTIVE", "COMPLETED", "TERMINATED"]
PRODUCTION_STATUSES = ["PLANNED", "SCRIPTING", "ART", "PREPRESS", "CAMERA_READY", "CANCELLED"]
COMMERCIAL_STATUSES = ["UNSOLICITED", "SOLICITED", "FOC_LOCKED", "PRINTED", "ON_SALE", "CANCELLED"]
SCHEDULE_HEALTHS = ["ON_TRACK", "AT_RISK", "SLIPPED"]
STAGE_STATUSES = ["NOT_STARTED", "IN_PROGRESS", "DELIVERED", "KICKED_BACK", "APPROVED", "CANCELLED"]
CATALOG_STATUSES = ["OPEN", "LOCKED", "PUBLISHED"]
SOLICITATION_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "WITHDRAWN"]
COVER_KINDS = ["STANDARD", "RATIO_INCENTIVE", "RETAILER_EXCLUSIVE"]
RETAILER_STATUSES = ["ACTIVE", "SUSPENDED"]
DISCOUNT_TIERS = ["ENTRY", "BASIC", "CORE", "PREMIER"]
ORDER_STATUSES = ["DRAFT", "SUBMITTED", "FOC_LOCKED", "INVOICED", "SHIPPED", "CANCELLED"]
PRINT_RUN_STATUSES = ["PLANNED", "PRINTED", "CANCELLED"]
PRINT_BASES = ["ORDER_DRIVEN", "DEMAND_FORECAST"]
RELEASE_CHANNELS = ["DIGITAL", "COLLECTED"]
REVENUE_CHANNELS = ["PRINT_DM", "DIGITAL", "COLLECTED", "SUBSIDIARY"]
BASIS_STATUSES = ["ESTIMATED", "ACTUAL"]
STATEMENT_BASES = ["ESTIMATED", "SETTLED"]
STATEMENT_STATUSES = ["DRAFT", "ISSUED", "PAID", "REVERSED"]

# Domain constants (SCAFFOLD calculations / PRD section 3)
FOC_LEAD_DAYS = 21
ON_SALE_CADENCE_DAYS = 21
MAX_NEGOTIATION_ROUNDS = 3
SLIP_AT_RISK_DAYS = 7
SLIP_BREACH_DAYS = 21
DIGITAL_EMBARGO_DAYS = 30
COLLECTED_BLACKOUT_DAYS = 90
REPRINT_COLLECTED_GUARD_DAYS = 60
EXCLUSIVE_ELIGIBILITY_UNITS = 10000
EXCLUSIVE_MIN_RATIO = 50
TIER_BASIC_UNITS = 2500
TIER_CORE_UNITS = 10000
TIER_PREMIER_UNITS = 25000
FREE_HANDLING_THRESHOLD_CENTS = 50000
HANDLING_FEE_CENTS = 995
OVERPRINT_PCT_NUM = 8
OVERPRINT_PCT_DEN = 100
RESERVE_COPIES = 150
CARTON_MULTIPLE = 250
MIN_FIRST_PRINTING = 500
MIN_REPRINT = 250
RETURNS_RESERVE_PCT = 20
CHANNEL_MULTIPLIER_BPS = {
    "PRINT_DM": 10000,
    "DIGITAL": 20000,
    "COLLECTED": 12500,
    "SUBSIDIARY": 40000,
}
POOL_DENOMINATOR = 100000000
INCENTIVE_RATIOS = [10, 25, 50, 100]

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Timestamps / date handling (PRD 2.4, 2.5)
# ---------------------------------------------------------------------------

MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_dt(stored):
    """Parse a stored ISO string back into a datetime (None-safe)."""
    if stored is None:
        return None
    return parse_dt(stored)


def date_of(value):
    """UTC calendar date of a stored ISO string or datetime."""
    if value is None:
        return None
    dt = value if isinstance(value, datetime) else parse_dt(value)
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).date()


def day_diff(later, earlier):
    """Whole calendar days between two instants/strings (later - earlier)."""
    return (date_of(later) - date_of(earlier)).days


def shift_days(value, days):
    """Return an ISO string for value shifted by `days` calendar days."""
    dt = value if isinstance(value, datetime) else parse_dt(value)
    return fmt_dt(dt + timedelta(days=days))


def wall_now():
    return datetime.now(timezone.utc)


def now_iso():
    return fmt_dt(wall_now())


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class Store(object):
    """Process-local, in-memory data store. Starts completely empty on boot:
    nothing is seeded, preloaded or hardcoded."""

    def __init__(self):
        self.creators = {}
        self.titles = {}
        self.assignments = {}
        self.issues = {}
        self.stages = {}
        self.catalogs = {}
        self.solicitations = {}
        self.variant_covers = {}
        self.retailers = {}
        self.orders = {}
        self.print_runs = {}
        self.release_windows = {}
        self.revenue_events = {}
        self.statements = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK

    # -- clock ------------------------------------------------------------
    def now(self):
        """Current logical clock as an ISO string."""
        return self.clock

    def now_dt(self):
        return parse_dt(self.clock)

    def set_clock(self, dt):
        self.clock = fmt_dt(dt)

    # -- row helpers ------------------------------------------------------
    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_row(self, versioned=True, **fields):
        row = {
            "id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "_seq": self.next_seq(),
        }
        if versioned:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        row.update(fields)
        return row


db = Store()


def ordered(table_or_rows):
    rows = table_or_rows.values() if isinstance(table_or_rows, dict) else table_or_rows
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Mutation tracking: one version bump per row per request (PRD 2.5 / 2.6)
# ---------------------------------------------------------------------------

_IGNORED_ON_DIFF = ("updated_at", "version")


def track(row):
    """Snapshot a pre-existing row so that a real change bumps version once."""
    if row is None or "version" not in row:
        return row
    if not hasattr(g, "_tracked"):
        g._tracked = {}
    key = id(row)
    if key not in g._tracked:
        snapshot = {k: copy.deepcopy(v) for k, v in row.items() if k not in _IGNORED_ON_DIFF}
        g._tracked[key] = (row, snapshot)
    return row


def apply_fields(row, **updates):
    """Track then update; version/updated_at are settled at commit time."""
    track(row)
    row.update(updates)
    return row


def touch(row):
    """Force a version bump on a row that the spec bumps without changing any
    field - the optimistic-concurrency parent bumps of PRD 2.9."""
    if row is None or "version" not in row:
        return row
    track(row)
    if not hasattr(g, "_forced"):
        g._forced = set()
    g._forced.add(id(row))
    return row


def commit():
    """Bump updated_at/version once for every row whose content really moved."""
    tracked = getattr(g, "_tracked", None)
    forced = getattr(g, "_forced", set())
    if not tracked:
        return
    stamp = now_iso()
    for key, (row, snapshot) in tracked.items():
        current = {k: v for k, v in row.items() if k not in _IGNORED_ON_DIFF}
        if current != snapshot or key in forced:
            row["updated_at"] = stamp
            row["version"] = row.get("version", 1) + 1
    g._tracked = {}
    g._forced = set()


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def _envelope(response_type, data, status, extra_meta=None):
    meta = _meta()
    if extra_meta:
        meta.update(extra_meta)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_data(data, status=200):
    commit()
    return _envelope("object", data, status)


def ok_row(serializer, row, status=200):
    commit()
    return _envelope("object", serializer(row), status)


def created_row(serializer, row):
    return ok_row(serializer, row, 201)


def ok_list(serializer, rows, page_meta):
    commit()
    return _envelope("array", [serializer(r) for r in rows], 200, page_meta)


def error_response(error_id, message, status):
    return _envelope("error", {"error_id": error_id, "message": message}, status)


# ---------------------------------------------------------------------------
# Authentication / authorization (PRD 2.1, 2.10 steps 1-2)
# ---------------------------------------------------------------------------


def auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Request shape validation (PRD 2.10 step 3 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True, force=True)
    if body is None:
        bad("Request body must be a JSON object.")
    if not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    return body


def _present(body, key):
    return key in body and body[key] is not None


def v_str(body, key, required=False, min_len=None, max_len=None, default=None):
    if not _present(body, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def v_int(body, key, required=False, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %d." % (key, maximum))
    return value


def v_bool(body, key, required=False, default=None):
    if not _present(body, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def v_enum(body, key, allowed, required=False, default=None):
    if not _present(body, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def v_datetime(body, key, required=False, default=None):
    if not _present(body, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = body[key]
    dt = parse_dt(value) if isinstance(value, str) else None
    if dt is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    return dt


def v_month(body, key, required=False, default=None):
    if not _present(body, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or not MONTH_RE.match(value):
        bad("Field '%s' must be a YYYY-MM month string." % key)
    return value


def v_id_list(body, key, default=None):
    if not _present(body, key):
        return list(default) if default is not None else []
    value = body[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    for member in value:
        if not isinstance(member, str) or not member:
            bad("Field '%s' must contain identifier strings." % key)
    return value


def v_craft_list(body, key, required=False):
    if not _present(body, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    value = body[key]
    if not isinstance(value, list) or not value:
        bad("Field '%s' must be a non-empty array." % key)
    seen = set()
    for member in value:
        if not isinstance(member, str) or member not in CRAFTS:
            bad("Field '%s' members must be valid crafts." % key)
        if member in seen:
            bad("Field '%s' members must be distinct." % key)
        seen.add(member)
    return value


# ---------------------------------------------------------------------------
# Pagination + query filters (PRD 2.3)
# ---------------------------------------------------------------------------


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        if not re.match(r"^-?\d+$", limit_raw.strip()):
            bad("Query parameter 'limit' must be an integer.")
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None:
        if not re.match(r"^-?\d+$", offset_raw.strip()):
            bad("Query parameter 'offset' must be an integer.")
        offset = int(offset_raw)
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def q_month(name):
    value = request.args.get(name)
    if value is None:
        return None
    if not MONTH_RE.match(value):
        bad("Query parameter '%s' must be a YYYY-MM month string." % name)
    return value


def q_str(name):
    return request.args.get(name)


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def page(rows):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, meta
