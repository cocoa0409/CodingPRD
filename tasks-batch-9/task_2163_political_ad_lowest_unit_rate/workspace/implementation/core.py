"""Core infrastructure: logical clock, in-memory store, errors, envelope, auth."""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": DEFAULT_CLOCK}


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt
    return _state["clock"]


def reset_clock():
    _state["clock"] = DEFAULT_CLOCK


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 UTC timestamp. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns None when unparseable."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def clock_date_str():
    return now().astimezone(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_ELECTION_NOT_FOUND": 404,
    "ERR_ADVERTISER_NOT_FOUND": 404,
    "ERR_RATE_CLASS_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SPOT_NOT_FOUND": 404,
    "ERR_FILE_ENTRY_NOT_FOUND": 404,
    "ERR_EO_REQUEST_NOT_FOUND": 404,
    "ERR_LUC_DETERMINATION_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_REBATE_NOT_FOUND": 404,
    "ERR_STALE_ELECTION_VERSION": 412,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_ADVERTISER_NOT_IN_REVIEW": 409,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_NOT_SUBMITTED": 409,
    "ERR_ORDER_NOT_ACCEPTED": 409,
    "ERR_ORDER_TERMINAL": 409,
    "ERR_SPOT_NOT_SCHEDULED": 409,
    "ERR_FILE_ENTRY_ALREADY_POSTED": 409,
    "ERR_EO_REQUEST_NOT_OPEN": 409,
    "ERR_COMPLAINT_NOT_OPEN": 409,
    "ERR_REFUND_NOT_DUE": 409,
    "ERR_STATION_POSTURE_FROZEN": 409,
    "ERR_STATION_POSTURE_RESTRICTED": 409,
    "ERR_ADVERTISER_NOT_CLASSIFIED": 409,
    "ERR_ADVERTISER_NOT_QUALIFIED_CANDIDATE": 409,
    "ERR_DISCLOSURE_NONCONFORMING": 422,
    "ERR_DISCLOSURE_AUTHORIZATION_MISSING": 422,
    "ERR_RATE_CLASS_NOT_PREEMPTIBLE": 409,
    "ERR_RATE_CLASS_STATION_MISMATCH": 422,
    "ERR_RATE_CLASS_WITHDRAWN": 409,
    "ERR_EO_NOT_OPPOSING_CANDIDATE": 422,
    "ERR_EO_TRIGGER_ORDER_NOT_AIRED": 409,
    "ERR_SPOT_AIR_DATE_IN_PAST": 422,
    "ERR_SPOT_AIR_DATE_NOT_REACHED": 409,
    "ERR_EO_REQUEST_WINDOW_CLOSED": 422,
    "ERR_EO_RESPONSE_DEADLINE_PASSED": 409,
    "ERR_ORDER_HAS_NO_SPOTS": 422,
    "ERR_SPOT_SLOT_COLLISION": 409,
    "ERR_CANDIDATE_SEPARATION_VIOLATION": 409,
    "ERR_STATION_DAILY_CAP_EXCEEDED": 409,
    "ERR_PAYMENT_TERMS_NOT_PERMITTED": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_ORDER_NOT_PAID": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

KINDS = [
    "station", "election", "advertiser", "rate_class", "order", "spot",
    "file_entry", "eo_request", "luc_determination", "complaint", "rebate",
]

NOT_FOUND_ERROR = {
    "station": "ERR_STATION_NOT_FOUND",
    "election": "ERR_ELECTION_NOT_FOUND",
    "advertiser": "ERR_ADVERTISER_NOT_FOUND",
    "rate_class": "ERR_RATE_CLASS_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "spot": "ERR_SPOT_NOT_FOUND",
    "file_entry": "ERR_FILE_ENTRY_NOT_FOUND",
    "eo_request": "ERR_EO_REQUEST_NOT_FOUND",
    "luc_determination": "ERR_LUC_DETERMINATION_NOT_FOUND",
    "complaint": "ERR_COMPLAINT_NOT_FOUND",
    "rebate": "ERR_REBATE_NOT_FOUND",
}


class Store(object):
    def __init__(self):
        self.tables = {kind: {} for kind in KINDS}
        self.seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def insert(self, kind, record, versioned=True):
        record["id"] = record.get("id") or self.new_id()
        record["_kind"] = kind
        record["_seq"] = self.next_seq()
        record["created_at"] = iso(now())
        if versioned:
            record["updated_at"] = record["created_at"]
            record["version"] = 1
        self.tables[kind][record["id"]] = record
        return record

    def get(self, kind, ident):
        if not isinstance(ident, str):
            return None
        return self.tables[kind].get(ident)

    def all(self, kind):
        rows = list(self.tables[kind].values())
        rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
        return rows


db = Store()


def touch(record):
    """Bump the concurrency field and refresh updated_at of a mutated record."""
    if record is None:
        return record
    record["updated_at"] = iso(now())
    record["version"] = record.get("version", 1) + 1
    return record


def touch_station_once(station):
    """Station counter cascades bump the station at most once per request."""
    if station is None:
        return
    marked = getattr(g, "_stations_touched", None)
    if marked is None:
        marked = set()
        g._stations_touched = marked
    if station["id"] in marked:
        return
    marked.add(station["id"])
    touch(station)


# ---------------------------------------------------------------------------
# Existence resolution (fixed resource-type order)
# ---------------------------------------------------------------------------

def resolve(refs):
    """refs: list of (kind, identifier). Validates in the fixed type order of
    PRD 2.7 and returns the resolved records in the caller's original order."""
    for kind in KINDS:
        for ref_kind, ident in refs:
            if ref_kind != kind:
                continue
            if db.get(kind, ident) is None:
                fail(NOT_FOUND_ERROR[kind], "%s %r does not exist" % (kind, ident))
    return [db.get(k, i) for k, i in refs]


def require(kind, ident):
    record = db.get(kind, ident)
    if record is None:
        fail(NOT_FOUND_ERROR[kind], "%s %r does not exist" % (kind, ident))
    return record


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = [
    "PlatformAdmin",
    "StationComplianceOfficer",
    "TrafficScheduler",
    "AdvertiserAgent",
    "PublicComplainant",
]

ALL_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Rung 1 of the rejection ladder: header presence, role validity, then
    endpoint role membership."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role %r is not a declared role" % role)
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def owner_check(expected_advertiser_id):
    """Rung 1: buy-side ownership. Only applies when acting as AdvertiserAgent."""
    if g.role != "AdvertiserAgent":
        return
    if expected_advertiser_id is None:
        return
    if g.user_id != expected_advertiser_id:
        fail("ERR_NOT_RESOURCE_OWNER", "acting agent does not own this resource")


# ---------------------------------------------------------------------------
# Body + query helpers
# ---------------------------------------------------------------------------

def body():
    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")


def pagination():
    """Rung 2 of the ladder."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        limit = _as_int_param(raw_limit, "limit")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be within [1, 100]")
    if raw_offset is not None:
        offset = _as_int_param(raw_offset, "offset")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be zero or greater")
    return limit, offset


_INT_PARAM = re.compile(r"^[+-]?[0-9]+$")


def _as_int_param(raw, name):
    text = str(raw).strip()
    if not _INT_PARAM.match(text):
        fail("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    return int(text)


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def filter_rows(rows, spec):
    """spec: mapping of query-parameter name -> record field name."""
    out = rows
    for param, field in spec.items():
        value = request.args.get(param)
        if value is None:
            continue
        out = [r for r in out if _as_query_str(r.get(field)) == value]
    return out


def _as_query_str(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# Payload shape validation (rung 4)
# ---------------------------------------------------------------------------

def need_string(payload, field, allow_empty=False, allow_null=False):
    if field not in payload:
        fail("ERR_INVALID_REQUEST", "%s is required" % field)
    value = payload[field]
    if value is None:
        if allow_null:
            return None
        fail("ERR_INVALID_REQUEST", "%s must be a string" % field)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % field)
    if not allow_empty and not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return value


def opt_string(payload, field, default=None, allow_empty=True):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % field)
    if not allow_empty and not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return value


def need_enum(payload, field, members):
    value = need_string(payload, field, allow_empty=True)
    if value not in members:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, ", ".join(members)))
    return value


def opt_enum(payload, field, members, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, ", ".join(members)))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def need_int(payload, field, minimum=None, maximum=None, choices=None):
    if field not in payload or payload[field] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % field)
    value = payload[field]
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if choices is not None and value not in choices:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, choices))
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (field, maximum))
    return value


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (field, maximum))
    return value


def opt_bool(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return value


def need_bool(payload, field):
    if field not in payload or payload[field] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % field)
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return value


def need_date(payload, field):
    value = need_string(payload, field, allow_empty=True)
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD calendar date" % field)
    return value


def opt_id(payload, field):
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a string identifier" % field)
    return value


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_days(dt, days):
    return dt + timedelta(days=days)
