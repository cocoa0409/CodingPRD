"""Core infrastructure for the Outdoor Gear Repair & Warranty Program API.

Holds: the in-memory store, the logical service clock, the response envelope
helpers, the error catalogue, authentication/authorisation and the request-shape
validation primitives.  Storage is in-memory only and starts completely empty on
every boot -- nothing is seeded here or anywhere else.
"""

import json
import random
import re
import string
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

UTC = timezone.utc

# The logical clock's startup value (PRD Sec. 2.4).
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

ROLES = ("Customer", "ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")

# --------------------------------------------------------------------------- #
# Error catalogue (PRD Sec. 5)
# --------------------------------------------------------------------------- #

ERROR_HTTP = {
    # auth / authz
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_UNKNOWN_ACTOR": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # existence
    "ERR_SERVICE_CENTER_NOT_FOUND": 404,
    "ERR_GEAR_MODEL_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_GEAR_ITEM_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_REPAIR_ORDER_NOT_FOUND": 404,
    "ERR_ESTIMATE_NOT_FOUND": 404,
    "ERR_PART_LOT_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_WORK_BLOCK_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    # state
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_WORK_STATE": 409,
    "ERR_INVALID_BILLING_STATE": 409,
    "ERR_INVALID_ESTIMATE_STATE": 409,
    "ERR_RESERVATION_NOT_RESERVED": 409,
    "ERR_INVALID_DISPOSITION_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_REPAIR_ORDER_VERSION": 412,
    # business safety
    "ERR_TECHNICIAN_NOT_ACTIVE": 422,
    "ERR_TECHNICIAN_NOT_CERTIFIED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CENTER_LIABILITY_FROZEN": 409,
    "ERR_REPLACEMENT_REQUIRES_OVERRIDE": 403,
    # business referential
    "ERR_TECHNICIAN_CENTER_MISMATCH": 422,
    "ERR_PART_MODEL_MISMATCH": 422,
    "ERR_SUBSTITUTION_NOT_PERMITTED": 422,
    "ERR_WORK_BLOCK_NOT_ON_ORDER": 422,
    "ERR_SUCCESSOR_CYCLE": 422,
    # business temporal
    "ERR_PURCHASE_DATE_IN_FUTURE": 422,
    "ERR_WARRANTY_EXPIRED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_SURGE_WINDOW_OVERLAP": 409,
    "ERR_TECHNICIAN_WINDOW_CONFLICT": 409,
    "ERR_ESTIMATE_EXPIRED": 409,
    # business constraint
    "ERR_PROOF_OF_PURCHASE_MISSING": 422,
    "ERR_INFO_REQUEST_LIMIT": 409,
    "ERR_ASSESSMENT_INCONCLUSIVE": 409,
    "ERR_ORDER_ALREADY_OPEN": 409,
    "ERR_ESTIMATE_ALREADY_APPROVED": 409,
    "ERR_BENCH_CAPACITY_EXCEEDED": 409,
    "ERR_INVALID_UNITS": 422,
    "ERR_INSUFFICIENT_PART_UNITS": 409,
    "ERR_INSUFFICIENT_STOCK_ADJUSTMENT": 422,
    "ERR_MODEL_CODE_TAKEN": 409,
    "ERR_EMAIL_TAKEN": 409,
    "ERR_EMPLOYEE_CODE_TAKEN": 409,
    "ERR_SERIAL_ALREADY_REGISTERED": 409,
    "ERR_PART_CODE_TAKEN": 409,
    "ERR_WORK_TYPES_INCOMPLETE": 409,
    "ERR_PARTS_NOT_SETTLED": 409,
    "ERR_NO_ELIGIBLE_TECHNICIAN": 422,
    "ERR_ITEM_NOT_IRREPARABLE": 409,
    # business fiscal
    "ERR_ESTIMATE_NOT_APPROVED": 402,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 402,
    "ERR_BALANCE_OUTSTANDING": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 400)
        self.message = message or _humanise(error_id)


def _humanise(error_id):
    txt = error_id[4:] if error_id.startswith("ERR_") else error_id
    return txt.replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #

COLLECTIONS = (
    "service_centers",
    "gear_models",
    "customers",
    "gear_items",
    "warranty_claims",
    "claim_assessments",
    "technicians",
    "work_blocks",
    "surge_windows",
    "repair_orders",
    "repair_estimates",
    "part_lots",
    "parts_reservations",
    "liability_entries",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #

def now():
    return db.clock


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_iso():
    return iso(db.clock)


_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?([Zz]|[+-]\d{2}:?\d{2})?$")


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if not _DT_RE.match(raw):
        return None
    txt = raw.replace(" ", "T").replace("t", "T")
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    # normalise +HHMM -> +HH:MM
    m = re.search(r"([+-]\d{2})(\d{2})$", txt)
    if m:
        txt = txt[: m.start()] + m.group(1) + ":" + m.group(2)
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def dt_of(stored):
    """Parse a stored ISO string back into a datetime."""
    if stored is None:
        return None
    if isinstance(stored, datetime):
        return stored
    return parse_instant(stored)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # 29 Feb -> 28 Feb
        return dt.replace(year=dt.year + years, day=28)


def end_of_day(d, extra_days=0):
    base = d + timedelta(days=extra_days)
    return datetime(base.year, base.month, base.day, 23, 59, 59, 999000, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Rounding helpers
# --------------------------------------------------------------------------- #

def rhu(value):
    """Round half up to a whole (integer) cent."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places, returned as a float."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #

def new_row(common=True):
    stamp = now_iso()
    row = {"id": str(uuid.uuid4()), "created_at": stamp, "_seq": db.next_seq()}
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] = row["version"] + 1


def set_fields(row, **kwargs):
    """Assign fields; when anything actually changed, refresh audit fields once."""
    changed = False
    for key, value in kwargs.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def ordered(collection):
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }


def respond(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def respond_list(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


# --------------------------------------------------------------------------- #
# Auth (checks 1-4)
# --------------------------------------------------------------------------- #

class Ctx(object):
    __slots__ = ("user_id", "role", "actor")

    def __init__(self, user_id, role, actor):
        self.user_id = user_id
        self.role = role
        self.actor = actor

    @property
    def is_customer(self):
        return self.role == "Customer"

    @property
    def is_tech(self):
        return self.role == "RepairTechnician"


def require(*allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip() or role is None or not str(role).strip():
        fail("ERR_MISSING_AUTH_HEADERS")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES:
        fail("ERR_INVALID_ROLE")
    actor = None
    if role == "Customer":
        actor = db.customers.get(user_id)
        if actor is None:
            fail("ERR_UNKNOWN_ACTOR")
    elif role == "RepairTechnician":
        actor = db.technicians.get(user_id)
        if actor is None:
            fail("ERR_UNKNOWN_ACTOR")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    return Ctx(user_id, role, actor)


# --------------------------------------------------------------------------- #
# Body / query validation (check 9 / 10)
# --------------------------------------------------------------------------- #

_MISSING = object()


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        body = json.loads(raw)
    except Exception:
        body = None
    if body is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def present(body, key):
    return key in body and body[key] is not None


def v_string(body, key, required=False, min_len=None, max_len=None, pattern=None,
             default=None, allow_null=False, non_blank=True):
    if key not in body or body[key] is None:
        if required and not (allow_null and key in body):
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if non_blank and not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "Field '%s' is malformed." % key)
    return value


def v_int(body, key, required=False, min_value=None, max_value=None, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if min_value is not None and value < min_value:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % key)
    if max_value is not None and value > max_value:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % key)
    return value


def v_number(body, key, required=False, min_value=None, max_value=None, default=None,
             max_decimals=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    number = Decimal(str(value))
    if min_value is not None and number < Decimal(str(min_value)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % key)
    if max_value is not None and number > Decimal(str(max_value)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % key)
    if max_decimals is not None and -number.as_tuple().exponent > max_decimals:
        fail("ERR_INVALID_REQUEST", "Field '%s' has too many decimal places." % key)
    return float(number)


def v_bool(body, key, required=False, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def v_enum(body, key, allowed, required=False, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def v_instant(body, key, required=False, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    parsed = parse_instant(body[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 timestamp." % key)
    return parsed


def v_list(body, key, required=False, min_items=None, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    if min_items is not None and len(value) < min_items:
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % key)
    return value


# ---- query params ---------------------------------------------------------- #

def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not a recognised value." % name)
    return raw


def q_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def pagination():
    """Check 10 -- limit/offset window."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset: offset + limit], len(rows)
