"""Foundation layer: logical clock, in-memory store, error catalogue, response
envelope, auth middleware and request-shape validation helpers.

Nothing in this module seeds or preloads any entity data.  The store starts
empty on every boot; every row is created through the declared API surface.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5) -- the system never reads the wall clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """In-memory storage.  Plain dicts keyed by id -- no disk, no cache."""

    COLLECTIONS = (
        "guests",
        "hosts",
        "jurisdiction_rules",
        "properties",
        "monitoring_devices",
        "identity_documents",
        "reservations",
        "incidents",
        "damage_claims",
        "claim_evidence",
        "coverage_layers",
        "settlement_allocations",
        "blocklist_entries",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.now = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.now


def set_now(value):
    db.now = value


# ---------------------------------------------------------------------------
# Timestamp helpers -- ISO 8601 UTC with exactly three fractional digits.
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_datetime(value):
    """Parse an ISO 8601 datetime string.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro,
                        tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc).date()
    except ValueError:
        return None


def at_time(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, 0,
                    tzinfo=timezone.utc)


def hours(n):
    return timedelta(hours=n)


# ---------------------------------------------------------------------------
# Money -- integers in cents, rounded HALF UP exactly once per PRD 2.6.
# ---------------------------------------------------------------------------

def round_half_up(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Error catalogue (PRD 5).
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    # auth / rbac
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_GUEST_NOT_FOUND": 404,
    "ERR_HOST_NOT_FOUND": 404,
    "ERR_JURISDICTION_RULE_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_EVIDENCE_NOT_FOUND": 404,
    "ERR_COVERAGE_LAYER_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_BLOCKLIST_ENTRY_NOT_FOUND": 404,
    # concurrency
    "ERR_PROPERTY_VERSION_STALE": 412,
    "ERR_RESERVATION_VERSION_STALE": 412,
    "ERR_GUEST_VERSION_STALE": 412,
    # state machine
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STAY_NOT_COMPLETED": 409,
    "ERR_EVIDENCE_ROUNDS_EXHAUSTED": 409,
    "ERR_APPEAL_ALREADY_FILED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_APPEAL_ROLE_MISMATCH": 403,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_GUEST_BLOCKLISTED": 409,
    # safety / privacy / compliance
    "ERR_SENSOR_PLACEMENT_PROHIBITED": 422,
    "ERR_SENSOR_JURISDICTION_PROHIBITED": 422,
    "ERR_SENSOR_AUDIO_PROHIBITED": 422,
    "ERR_SENSOR_COMPLIANCE_BLOCKED": 409,
    "ERR_PROPERTY_NOT_LISTED": 409,
    "ERR_REGISTRATION_REQUIRED": 422,
    "ERR_DISCLOSURE_TEXT_REQUIRED": 422,
    "ERR_ESCALATION_NOT_WARRANTED": 422,
    "ERR_NOISE_BELOW_THRESHOLD": 422,
    "ERR_OCCUPANCY_WITHIN_LIMIT": 422,
    "ERR_INCIDENT_HAS_LIVE_CLAIM": 409,
    "ERR_HOST_PAYOUT_HELD": 409,
    "ERR_COVERAGE_UNPROTECTED": 409,
    "ERR_DOCUMENT_EXPIRED": 409,
    # constraint / temporal / referential / uniqueness
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_CHECK_IN_IN_PAST": 422,
    "ERR_MIN_STAY_NOT_MET": 422,
    "ERR_OCCUPANCY_LIMIT_EXCEEDED": 422,
    "ERR_PROPERTY_CALENDAR_CONFLICT": 409,
    "ERR_GUEST_STAY_OVERLAP": 409,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_CLAIM_FOR_INCIDENT": 409,
    "ERR_SCOPE_TARGET_MISMATCH": 422,
    "ERR_BLOCKLIST_DUPLICATE_SCOPE": 409,
    "ERR_SUPERSEDE_NOT_BROADER": 422,
    "ERR_BLOCKLIST_GROUNDS_NOT_MET": 422,
    "ERR_LAYER_SCOPE_MISMATCH": 422,
    "ERR_LAYER_ORDER_CONFLICT": 409,
    "ERR_EMAIL_ALREADY_REGISTERED": 409,
    "ERR_JURISDICTION_CODE_TAKEN": 409,
    # fiscal
    "ERR_EVIDENCE_AMOUNT_REQUIRED": 422,
    "ERR_EVIDENCE_INCOMPLETE": 422,
    "ERR_PRODUCT_CONFIG_INVALID": 422,
    "ERR_CLAIM_CEILING_EXCEEDED": 422,
    "ERR_APPROVED_AMOUNT_INVALID": 422,
    # generic
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2).
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(now()),
    }


def jsonable(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def object_response(payload):
    return {
        "meta": base_meta(),
        "response_type": "object",
        "data": jsonable(payload),
    }


def list_response(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": jsonable(list(rows)),
    }


def error_response(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth middleware (PRD 2.1).
# ---------------------------------------------------------------------------

ROLE_GUEST = "Guest"
ROLE_HOST = "Host"
ROLE_ADJUDICATOR = "TrustAdjudicator"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_ADMIN = "PlatformAdmin"

ALL_ROLES = (ROLE_GUEST, ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE,
             ROLE_ADMIN)


def require_auth(*allowed):
    """Priority 1 then priority 2 of PRD 2.8."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" \
            or role.strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS",
             "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHORIZED", "Unrecognised role '%s'" % role)
    if allowed and role not in allowed:
        fail("ERR_UNAUTHORIZED",
             "Role '%s' is not authorised for this endpoint" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_owner(actual_owner_id):
    if g.user_id != actual_owner_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Caller does not own this resource")


# ---------------------------------------------------------------------------
# Version / timestamp bookkeeping (PRD 2.4).
# ---------------------------------------------------------------------------

def touch(entity):
    """Refresh updated_at and bump version at most once per request."""
    if entity is None or "version" not in entity:
        return entity
    if not hasattr(g, "_bumped"):
        g._bumped = set()
    key = id(entity)
    entity["updated_at"] = now()
    if key not in g._bumped:
        g._bumped.add(key)
        entity["version"] += 1
    return entity


def new_row(with_version=True):
    row = {"id": str(uuid.uuid4()), "created_at": now()}
    if with_version:
        row["updated_at"] = now()
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def public(row, fields):
    out = {}
    for name in fields:
        out[name] = row.get(name)
    return out


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Request shape validation (priority 3 of PRD 2.8) -> ERR_INVALID_REQUEST.
# ---------------------------------------------------------------------------

def body_json():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return parsed


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s" % (name, detail))


def _require_present(b, name):
    if name not in b or b[name] is None:
        _bad(name, "is required")
    return b[name]


def req_string(b, name, allow_empty=False):
    value = _require_present(b, name)
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "must not be empty")
    return value


def opt_string(b, name, default=None, allow_empty=True):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, str):
        _bad(name, "must be a string or null")
    if not allow_empty and value.strip() == "":
        _bad(name, "must not be empty")
    return value


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def req_int(b, name, minimum=None, maximum=None):
    return _check_int(name, _require_present(b, name), minimum, maximum)


def opt_int(b, name, default=None, minimum=None, maximum=None):
    if name not in b or b[name] is None:
        return default
    return _check_int(name, b[name], minimum, maximum)


def req_bool(b, name):
    value = _require_present(b, name)
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], bool):
        _bad(name, "must be a boolean")
    return b[name]


def req_number(b, name, minimum=None):
    value = _require_present(b, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    return value


def opt_number(b, name, default=None, minimum=None):
    if name not in b or b[name] is None:
        return default
    return req_number(b, name, minimum)


def req_enum(b, name, values):
    value = _require_present(b, name)
    if not isinstance(value, str) or value not in values:
        _bad(name, "must be one of %s" % ", ".join(values))
    return value


def opt_enum(b, name, values, default=None):
    if name not in b or b[name] is None:
        return default
    return req_enum(b, name, values)


def req_dt(b, name):
    value = _require_present(b, name)
    parsed = parse_datetime(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC datetime")
    return parsed


def opt_dt(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    return req_dt(b, name)


def req_date(b, name):
    value = _require_present(b, name)
    parsed = parse_date(value)
    if parsed is None:
        _bad(name, "must be a YYYY-MM-DD calendar date")
    return parsed


def req_country_code(b, name):
    value = req_string(b, name)
    if not re.match(r"^[A-Z]{2}$", value):
        _bad(name, "must be exactly two uppercase letters")
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3).
# ---------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    ordered = sort_rows(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qs_bool(name):
    value = qs(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be true or false" % name)


def qs_int(name):
    value = qs(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
