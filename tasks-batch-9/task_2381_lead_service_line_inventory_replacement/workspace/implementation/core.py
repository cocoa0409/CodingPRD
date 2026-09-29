"""Core infrastructure: in-memory store, logical clock, response envelope,
error vocabulary, authentication/authorization and request validation.

Every structural name in this module (header names, envelope field names,
pagination parameter names, error identifiers) is taken verbatim from
PRD.md sections 2.1 - 2.10 and SCOPE/SCAFFOLD section 1.0 / 1.4 / 1.6.
"""

import functools
import itertools
import random
import re
import string
import threading
import uuid
from datetime import datetime, timezone, date as date_cls, time as time_cls
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Logical clock default (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store.  Starts completely empty on every boot -- nothing is ever
# seeded, preloaded or hardcoded.
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.water_systems = {}
        self.service_lines = {}
        self.evidence_items = {}
        self.crews = {}
        self.appointments = {}
        self.batches = {}
        self.publications = {}
        self.notifications = {}
        self.orders = {}
        self.street_projects = {}
        self.funding_sources = {}
        self.progress_reports = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()
_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Timestamps / identifiers (PRD 2.4)
# ---------------------------------------------------------------------------
def wall_now():
    return datetime.now(timezone.utc)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def new_id():
    return str(uuid.uuid4())


def new_row():
    stamp = iso_ms(wall_now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """A mutation of the row: refresh updated_at and advance version by one."""
    row["updated_at"] = iso_ms(wall_now())
    if "version" in row:
        row["version"] = row["version"] + 1


def by_created_at(rows):
    """created_at ascending, with insertion sequence as the stable ordering key."""
    return sorted(rows, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Errors (PRD 5 / scaffold 1.6)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CREW_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_WATER_SYSTEM_NOT_FOUND": 404,
    "ERR_SERVICE_LINE_NOT_FOUND": 404,
    "ERR_EVIDENCE_ITEM_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_SAMPLING_BATCH_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_PUBLICATION_NOT_FOUND": 404,
    "ERR_NOTIFICATION_NOT_FOUND": 404,
    "ERR_REPLACEMENT_ORDER_NOT_FOUND": 404,
    "ERR_STREET_PROJECT_NOT_FOUND": 404,
    "ERR_FUNDING_SOURCE_NOT_FOUND": 404,
    "ERR_PROGRESS_REPORT_NOT_FOUND": 404,
    "ERR_STALE_WATER_SYSTEM_VERSION": 412,
    "ERR_STALE_SERVICE_LINE_VERSION": 412,
    "ERR_INVENTORY_STATE_INVALID": 409,
    "ERR_APPOINTMENT_STATE_INVALID": 409,
    "ERR_BATCH_STATE_INVALID": 409,
    "ERR_PUBLICATION_STATE_INVALID": 409,
    "ERR_NOTIFICATION_STATE_INVALID": 409,
    "ERR_ORDER_STATE_INVALID": 409,
    "ERR_LINE_NOT_ELIGIBLE": 409,
    "ERR_EVIDENCE_ALREADY_RETRACTED": 409,
    "ERR_PROGRAM_POSTURE_FROZEN": 409,
    "ERR_PROGRAM_POSTURE_RESTRICTED": 409,
    "ERR_INVENTORY_NOT_PUBLISHED": 409,
    "ERR_UNVALIDATED_SAMPLING_STRATUM": 409,
    "ERR_CONSENT_NOT_RESOLVED": 409,
    "ERR_CREW_INACTIVE": 409,
    "ERR_PINNED_SNAPSHOT_STALE": 409,
    "ERR_CCT_NOT_OPTIMIZED": 422,
    "ERR_NOTIFICATION_OVERDUE_BLOCK": 409,
    "ERR_DUPLICATE_PWSID": 409,
    "ERR_DUPLICATE_ADDRESS_LABEL": 409,
    "ERR_DUPLICATE_STRATUM_CODE": 409,
    "ERR_CREW_METHOD_NOT_CERTIFIED": 422,
    "ERR_CREW_OUTSIDE_SHIFT": 422,
    "ERR_EVIDENCE_SIDE_MISMATCH": 422,
    "ERR_REPLACED_SIDES_MISMATCH": 422,
    "ERR_SAMPLE_COUNT_INSUFFICIENT": 422,
    "ERR_CREW_WINDOW_CONFLICT": 409,
    "ERR_MORATORIUM_CONFLICT": 409,
    "ERR_COMPLIANCE_DEADLINE_PASSED": 409,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    "ERR_CREW_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_EXCAVATION_CAPACITY_EXCEEDED": 409,
    "ERR_EQUITY_REQUIREMENT_BREACH": 422,
    "ERR_FUNDING_INSUFFICIENT": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        Exception.__init__(self, message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso_ms(wall_now()),
    }
    if extra:
        m.update(extra)
    return m


def respond_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Authentication / authorization (PRD 2.1, ladder rungs 1-2)
# ---------------------------------------------------------------------------
ROLES = (
    "ProgramAdministrator",
    "InventoryAnalyst",
    "ComplianceOfficer",
    "FieldTechnician",
    "CustomerRepresentative",
    "ReplacementContractor",
)
ANY_ROLE = ROLES


def endpoint(roles):
    """Wrap a route: serialize access, authenticate, then authorize."""
    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with _lock:
                user_id = request.headers.get("X-User-ID")
                user_role = request.headers.get("X-User-Role")
                if not user_id or not user_role or user_role not in ROLES:
                    fail("ERR_UNAUTHENTICATED",
                         "X-User-ID and X-User-Role headers are required and the "
                         "role must be one of the six declared roles.")
                if user_role not in allowed:
                    fail("ERR_UNAUTHORIZED",
                         "Role %s is not authorized for this operation." % user_role)
                g.user_id = user_id
                g.user_role = user_role
                return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_datetime(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date_cls.fromisoformat(value.strip())
    except ValueError:
        return None


def parse_hhmm(value):
    if not isinstance(value, str):
        return None
    m = _HHMM_RE.match(value.strip())
    if not m:
        return None
    return time_cls(int(m.group(1)), int(m.group(2)))


# ---------------------------------------------------------------------------
# Numeric helpers (PRD 2.6)
# ---------------------------------------------------------------------------
def dec(value):
    return Decimal(str(value))


def round2(value):
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round4(value):
    return float(dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def dec_round2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def round_half_up_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body validation (ladder rungs 3-5)
# ---------------------------------------------------------------------------
MISSING = object()


def body_json():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_ok(spec, value):
    kind = spec["type"]
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return _is_int(value)
    if kind == "number":
        return _is_num(value)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "datetime":
        return parse_datetime(value) is not None
    if kind == "date":
        return parse_date(value) is not None
    if kind == "hhmm":
        return parse_hhmm(value) is not None
    return True


def validate_body(payload, specs):
    """Three ordered passes over the declared input schema:

    pass 1 -- presence and JSON type      -> ERR_INVALID_REQUEST   (400)
    pass 2 -- enum membership             -> ERR_INVALID_ENUM_VALUE (422)
    pass 3 -- declared value constraints  -> ERR_INVALID_REQUEST   (400)
    """
    out = {}

    # pass 1: presence + declared JSON type
    for spec in specs:
        name = spec["name"]
        present = name in payload
        raw = payload.get(name, MISSING)
        if not present or raw is None:
            if spec.get("required"):
                if not present:
                    fail("ERR_INVALID_REQUEST",
                         "Required field '%s' is missing." % name)
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must not be null." % name)
            out[name] = spec.get("default", None)
            continue
        if not _type_ok(spec, raw):
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' has an invalid type or format." % name)
        if spec["type"] == "array":
            item_type = spec.get("item_type")
            if item_type:
                for item in raw:
                    if not _type_ok({"type": item_type}, item):
                        fail("ERR_INVALID_REQUEST",
                             "Field '%s' contains an entry of the wrong type." % name)
        out[name] = raw

    # pass 2: enum membership
    for spec in specs:
        name = spec["name"]
        value = out.get(name)
        if value is None:
            continue
        choices = spec.get("enum")
        if choices and value not in choices:
            fail("ERR_INVALID_ENUM_VALUE",
                 "Field '%s' must be one of %s." % (name, ", ".join(choices)))
        item_choices = spec.get("item_enum")
        if item_choices and isinstance(value, list):
            for item in value:
                if item not in item_choices:
                    fail("ERR_INVALID_ENUM_VALUE",
                         "Field '%s' contains a value outside %s."
                         % (name, ", ".join(item_choices)))

    # pass 3: declared value constraints
    for spec in specs:
        name = spec["name"]
        value = out.get(name)
        if value is None:
            continue
        if spec.get("nonempty") and isinstance(value, (list, str)) and len(value) == 0:
            fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
        if "min" in spec and _is_num(value) and dec(value) < dec(spec["min"]):
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must be greater than or equal to %s." % (name, spec["min"]))
        if "max" in spec and _is_num(value) and dec(value) > dec(spec["max"]):
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must be less than or equal to %s." % (name, spec["max"]))
        if "gt" in spec and _is_num(value) and dec(value) <= dec(spec["gt"]):
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must be strictly greater than %s." % (name, spec["gt"]))
    return out


def field(name, type_, required=False, default=None, enum=None, item_type=None,
          item_enum=None, **extra):
    spec = {"name": name, "type": type_, "required": required, "default": default}
    if enum is not None:
        spec["enum"] = list(enum)
    if item_type is not None:
        spec["item_type"] = item_type
    if item_enum is not None:
        spec["item_enum"] = list(item_enum)
    spec.update(extra)
    return spec


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3, ladder rung 6)
# ---------------------------------------------------------------------------
def read_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer in [1,100].")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer in [1,100].")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return "__nomatch__"
