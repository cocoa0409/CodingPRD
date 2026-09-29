"""Core primitives: error catalog, response envelope, logical clock, in-memory store.

Storage is in-memory only.  The store starts completely empty on every boot;
nothing is seeded, preloaded or hardcoded.  Every entity is created by an API
caller through the declared endpoint surface.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalog (PRD section 5 / SCAFFOLD section 1.6)
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INSPECTOR_NOT_ON_ENCOUNTER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_RIDER_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_ENCOUNTER_NOT_FOUND": 404,
    "ERR_CITATION_NOT_FOUND": 404,
    "ERR_HEARING_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_SERVICE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_STALE_CITATION_VERSION": 412,
    "ERR_INVALID_ZONE_STATE": 409,
    "ERR_INVALID_DEPLOYMENT_STATE": 409,
    "ERR_DEPLOYMENT_NOT_ACTIVE": 409,
    "ERR_ENCOUNTER_NOT_PENDING": 409,
    "ERR_OPEN_ENCOUNTERS_REMAIN": 409,
    "ERR_CITATION_STATUS_INVALID": 409,
    "ERR_SETTLEMENT_STATUS_INVALID": 409,
    "ERR_HEARING_NOT_SCHEDULED": 409,
    "ERR_HEARING_NOT_APPEALABLE": 409,
    "ERR_APPEAL_STATUS_INVALID": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_SERVICE_NOT_ACTIVE": 409,
    "ERR_ZONE_NOT_DESIGNATED": 409,
    "ERR_SIGNAGE_BELOW_THRESHOLD": 409,
    "ERR_INSPECTOR_SUSPENDED": 409,
    "ERR_INSPECTOR_CERT_EXPIRED": 409,
    "ERR_IDENTITY_NOT_ESTABLISHED": 422,
    "ERR_WARNING_REQUIRED_FIRST_OFFENSE": 409,
    "ERR_DISPOSITION_NOT_SUPPORTED": 409,
    "ERR_LINE_NOT_ASSIGNED_TO_ZONE": 422,
    "ERR_ASSIGNMENT_ALREADY_EXISTS": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_ENCOUNTER_ALREADY_CITED": 409,
    "ERR_HEARING_CITATION_MISMATCH": 422,
    "ERR_APPEAL_ALREADY_OPEN": 409,
    "ERR_ALTERNATIVE_ALREADY_ACTIVE": 409,
    "ERR_REISSUE_NOT_PERMITTED": 409,
    "ERR_ENCOUNTER_OUTSIDE_WINDOW": 422,
    "ERR_DEPLOYMENT_WINDOW_OVERLAP": 409,
    "ERR_ZONE_DEPLOYMENT_CAPACITY": 409,
    "ERR_CONTEST_WINDOW_CLOSED": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_SUPPLEMENT_WINDOW_CLOSED": 422,
    "ERR_REISSUE_WINDOW_CLOSED": 422,
    "ERR_APPEAL_ROUND_LIMIT": 409,
    "ERR_SAMPLE_SIZE_INADEQUATE": 409,
    "ERR_INSTALLMENT_COUNT_OUT_OF_RANGE": 422,
    "ERR_DECISION_FIELDS_INVALID": 422,
    "ERR_DIVERSION_NOT_ELIGIBLE": 422,
    "ERR_INVALID_SERVICE_HOURS": 422,
    "ERR_DOWN_PAYMENT_BELOW_MINIMUM": 422,
    "ERR_DOWN_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_REDUCTION_BELOW_FLOOR": 422,
    "ERR_PAYMENT_AMOUNT_INVALID": 422,
    "ERR_NOTHING_OUTSTANDING": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_ALPHANUM = string.ascii_uppercase + string.digits


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_UTC_SUFFIX = re.compile(r"(?:[Zz]|[+-]00:?00)$")


def parse_iso(value):
    """Parse an ISO-8601 UTC instant.  Returns None when unparseable / not UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    if parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def days(n):
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# Rounding helpers - money is always integer cents, rates integer basis points
# ---------------------------------------------------------------------------

def rhu_int(numerator, denominator):
    """round_half_up(numerator / denominator) -> int"""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(numerator, denominator):
    """round_half_up(numerator / denominator) -> Decimal with 4 decimals"""
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec4_str(value):
    """Render a ratio as a decimal string with exactly 4 decimal places."""
    return format(q4(value), "f")


def dec4_num(value):
    return float(q4(value))


# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    """Plain dict storage keyed by id.  Empty at process start, always."""

    def __init__(self):
        self.zones = {}
        self.lines = {}
        self.assignments = {}
        self.audits = {}
        self.inspectors = {}
        self.riders = {}
        self.deployments = {}
        self.encounters = {}
        self.citations = {}
        self.hearings = {}
        self.appeals = {}
        self.plans = {}
        self.services = {}
        self.payments = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """id + created_at (+ updated_at/version for mutable record kinds)."""
    now = db.now()
    rec = {"id": new_id(), "created_at": now, "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: bump version, refresh updated_at."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = db.now()
    return rec


def ordered(records):
    """Default collection ordering: ascending created_at (oldest first)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20)),
        "api_request_timestamp": iso3(datetime.now(UTC)),
    }


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Authentication / RBAC (PRD 2.1)
# ---------------------------------------------------------------------------

ROLES = (
    "EnforcementPlanner",
    "FareInspector",
    "Rider",
    "HearingOfficer",
    "AppealsBoardMember",
    "EquityAnalyst",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_rider(self):
        return self.role == "Rider"

    @property
    def is_inspector(self):
        return self.role == "FareInspector"


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    return Actor(user_id, role)


def authorize(*allowed_roles):
    actor = authenticate()
    if actor.role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Role %s may not call this endpoint." % actor.role)
    return actor


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s must be <= %d." % (name, maximum))
    return value


def page(items, limit, offset, serializer):
    total = len(items)
    window = items[offset:offset + limit]
    return respond_list([serializer(item) for item in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Request-body schema validation (precedence step 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

_MISSING = object()


def body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name, min_len=1, max_len=None):
    if not _present(payload, name):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def req_int(payload, name, minimum=None, maximum=None, error_id="ERR_INVALID_REQUEST"):
    if not _present(payload, name):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    _range_check(name, value, minimum, maximum, error_id)
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None,
            error_id="ERR_INVALID_REQUEST"):
    if not _present(payload, name):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    _range_check(name, value, minimum, maximum, error_id)
    return value


def _range_check(name, value, minimum, maximum, error_id):
    if minimum is not None and value < minimum:
        raise ApiError(error_id, "Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(error_id, "Field '%s' must be <= %d." % (name, maximum))


def req_enum(payload, name, allowed):
    value = req_str(payload, name, min_len=1)
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not _present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def opt_bool(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_dt(payload, name, error_id="ERR_INVALID_REQUEST"):
    if not _present(payload, name):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 string." % name)
    parsed = parse_iso(value)
    if parsed is None:
        raise ApiError(error_id, "Field '%s' must be a UTC ISO-8601 instant." % name)
    return parsed


def opt_dt(payload, name, default=None, error_id="ERR_INVALID_REQUEST"):
    if not _present(payload, name):
        return default
    return req_dt(payload, name, error_id=error_id)


def query_dt(name, error_id="ERR_INVALID_TIME_WINDOW"):
    raw = request.args.get(name)
    if raw is None or raw == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
    parsed = parse_iso(raw)
    if parsed is None:
        raise ApiError(error_id, "Query parameter '%s' must be a UTC ISO-8601 instant." % name)
    return parsed


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def query_filter(name, allowed=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if allowed is not None and raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def lookup(table, key, error_id):
    record = table.get(key) if isinstance(key, str) else None
    if record is None:
        raise ApiError(error_id, "No such record: %s." % key)
    return record


def fk(payload, name, table, error_id, required=True):
    """Resolve a body foreign key in declared field order."""
    if not _present(payload, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return lookup(table, value, error_id)
