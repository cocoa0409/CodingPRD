"""Core plumbing: in-memory store, logical clock, response envelope, auth, validation.

Every structural name in this module is taken from SCAFFOLD.yaml (`response_envelope`,
`validations`, `entities`) and PRD.md sections 2.1 - 2.9.
"""

import functools
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext

from flask import g, jsonify, request

getcontext().prec = 60

D = Decimal

# ---------------------------------------------------------------------------
# rounding helpers -- PRD 2.9: rounding is always half up, applied at the step
# where it is specified.
# ---------------------------------------------------------------------------


def q(value, places):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def q0(value):
    return int(q(value, 0))


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


# ---------------------------------------------------------------------------
# timestamps -- ISO 8601 UTC with exactly three fractional digits (PRD 2.4)
# ---------------------------------------------------------------------------


def fmt_dt(dt):
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


def parse_dt(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


CLOCK_DEFAULT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# in-memory store -- starts empty on every boot, nothing is ever seeded
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "facilities",
    "suppliers",
    "prices",
    "intakes",
    "manifests",
    "modules",
    "decisions",
    "lines",
    "campaigns",
    "lots",
    "outputs",
    "settlements",
    "allotments",
    "events",
    "passports",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT_UTC
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._counter = itertools.count(1)

    def now(self):
        return self.clock

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(fields, common_fields=True):
    """Create a row carrying the system fields declared in PRD 2.4."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = db.now()
    if common_fields:
        row["updated_at"] = db.now()
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Advance version by exactly 1 and refresh updated_at, once per request."""
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = id(row)
    if key in touched:
        return
    touched.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.now()


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# errors -- catalogue from PRD 5 / SCAFFOLD `errors`
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_INTAKE_NOT_FOUND": 404,
    "ERR_MANIFEST_NOT_FOUND": 404,
    "ERR_MODULE_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_DISCHARGE_EVENT_NOT_FOUND": 404,
    "ERR_PASSPORT_NOT_FOUND": 404,
    "ERR_STALE_INTAKE_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_INVALID_CUSTODY_STATE": 409,
    "ERR_INVALID_COMPLIANCE_STATE": 409,
    "ERR_MANIFEST_NOT_SUBMITTED": 409,
    "ERR_MODULE_NOT_TRIAGEABLE": 409,
    "ERR_MODULE_NOT_IN_RECOVERY_QUEUE": 409,
    "ERR_MODULE_NOT_SHIPPABLE": 409,
    "ERR_LOT_NOT_OPEN": 409,
    "ERR_LOT_NOT_CHARGED": 409,
    "ERR_CAMPAIGN_NOT_RUNNING": 409,
    "ERR_CAMPAIGN_NOT_SCHEDULED": 409,
    "ERR_SETTLEMENT_NOT_DRAFT": 409,
    "ERR_SETTLEMENT_NOT_POSTED": 409,
    "ERR_SETTLEMENT_NOT_DISPUTED": 409,
    "ERR_SETTLEMENT_NOT_IN_UMPIRE_ROUND": 409,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_DISCHARGE_EVENT_NOT_POSTED": 409,
    "ERR_PASSPORT_NOT_ISSUED": 409,
    "ERR_PASSPORT_ALREADY_ISSUED": 409,
    "ERR_MODULES_ALREADY_COMMITTED": 409,
    "ERR_LINE_HAS_RUNNING_CAMPAIGN": 409,
    "ERR_CAMPAIGN_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_INDEX_PRICE": 409,
    "ERR_FACILITY_SUSPENDED": 422,
    "ERR_SOC_ABOVE_PACKAGING_LIMIT": 422,
    "ERR_PERMIT_NOT_ACTIVE": 422,
    "ERR_LINE_NOT_AVAILABLE": 422,
    "ERR_CHANGEOVER_BUFFER_VIOLATION": 422,
    "ERR_CAMPAIGN_WINDOW_CLOSED": 422,
    "ERR_PERMIT_WINDOW_EXCLUDED": 422,
    "ERR_CAMPAIGN_CAPACITY_EXCEEDED": 422,
    "ERR_LOT_CHARGE_EXCEEDS_PLAN": 422,
    "ERR_DISCHARGE_DAILY_CAP_EXCEEDED": 422,
    "ERR_MASS_BALANCE_OUT_OF_TOLERANCE": 422,
    "ERR_NO_RECOVERY_OUTPUTS": 422,
    "ERR_RECYCLED_CONTENT_BELOW_MINIMUM": 422,
    "ERR_DISPOSITION_OVERRIDE_NOT_PERMITTED": 422,
    "ERR_VARIANCE_WITHIN_TOLERANCE": 422,
    "ERR_MODULE_CHEMISTRY_MISMATCH": 422,
    "ERR_METAL_NOT_RECOVERABLE_ON_LINE": 422,
    "ERR_INTAKE_NOT_RELEASED": 422,
    "ERR_CAMPAIGN_FAMILY_MISMATCH": 422,
    "ERR_INDEX_PRICE_UNAVAILABLE": 422,
    "ERR_SUPPLIER_CREDIT_HOLD": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# ---------------------------------------------------------------------------
# response envelope -- SCAFFOLD response_envelope / PRD 2.2
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def serialize(value):
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_dt(value)
    return value


def object_response(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data or {})}
    return jsonify(body), code


class Page:
    def __init__(self, items, limit, offset, total):
        self.items = items
        self.limit = limit
        self.offset = offset
        self.total = total


def array_response(page):
    meta = _meta()
    meta["limit"] = page.limit
    meta["offset"] = page.offset
    meta["total_count"] = page.total
    meta["has_more"] = (page.offset + len(page.items)) < page.total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(row) for row in page.items],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# auth -- PRD 2.1 / validations priority 1 and 2
# ---------------------------------------------------------------------------

ROLES = (
    "PlatformAdmin",
    "MarketAnalyst",
    "IntakeClerk",
    "PlantOperator",
    "ComplianceOfficer",
    "TriageEngineer",
    "AssayTechnician",
    "SettlementAccountant",
    "CertificationOfficer",
    "SupplierRep",
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def require_auth(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(bp, rule, methods, roles, code=200):
    """Register a route: auth (tier 1/2) then the handler, wrapped in the envelope."""

    def decorator(fn):
        @bp.route(rule, methods=methods, endpoint=fn.__name__)
        @functools.wraps(fn)
        def wrapper(**kwargs):
            g.touched = set()
            require_auth(roles)
            result = fn(**kwargs)
            if isinstance(result, Page):
                return array_response(result)
            return object_response(result, code)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# request input -- body for writes, query string for reads
# ---------------------------------------------------------------------------

MISSING = object()


def payload():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    args = {k: v for k, v in request.args.items()}
    if request.method == "GET":
        merged = dict(body)
        merged.update(args)
    else:
        merged = dict(args)
        merged.update(body)
    return merged


def _bad(field, why="is invalid"):
    return ApiError("ERR_INVALID_REQUEST", "'%s' %s." % (field, why))


def f_str(data, key, required=True, default=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise _bad(key, "is required")
        return default
    if not isinstance(value, str) or not value.strip():
        raise _bad(key, "must be a non-empty string")
    return value


def f_enum(data, key, allowed, required=True, default=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise _bad(key, "is required")
        return default
    if not isinstance(value, str) or value not in allowed:
        raise _bad(key, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def _to_decimal(key, value):
    if isinstance(value, bool):
        raise _bad(key, "must be a number")
    if isinstance(value, (int, float)):
        try:
            dec = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise _bad(key, "must be a number")
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise _bad(key, "must be a number")
        try:
            dec = Decimal(text)
        except InvalidOperation:
            raise _bad(key, "must be a number")
    else:
        raise _bad(key, "must be a number")
    if not dec.is_finite():
        raise _bad(key, "must be a finite number")
    return dec


def f_num(data, key, required=True, default=None, gt=None, ge=None, lt=None, le=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise _bad(key, "is required")
        return default
    dec = _to_decimal(key, value)
    if gt is not None and not dec > D(str(gt)):
        raise _bad(key, "must be greater than %s" % gt)
    if ge is not None and not dec >= D(str(ge)):
        raise _bad(key, "must be at least %s" % ge)
    if lt is not None and not dec < D(str(lt)):
        raise _bad(key, "must be less than %s" % lt)
    if le is not None and not dec <= D(str(le)):
        raise _bad(key, "must be at most %s" % le)
    return dec


def f_int(data, key, required=True, default=None, gt=None, ge=None, lt=None, le=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise _bad(key, "is required")
        return default
    dec = _to_decimal(key, value)
    if dec != dec.to_integral_value():
        raise _bad(key, "must be an integer")
    number = int(dec)
    if gt is not None and not number > gt:
        raise _bad(key, "must be greater than %s" % gt)
    if ge is not None and not number >= ge:
        raise _bad(key, "must be at least %s" % ge)
    if lt is not None and not number < lt:
        raise _bad(key, "must be less than %s" % lt)
    if le is not None and not number <= le:
        raise _bad(key, "must be at most %s" % le)
    return number


def f_dt(data, key, required=True, default=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise _bad(key, "is required")
        return default
    try:
        return parse_dt(value)
    except (ValueError, TypeError):
        raise _bad(key, "must be an ISO 8601 UTC instant")


def f_id_list(data, key):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        raise _bad(key, "is required")
    if not isinstance(value, list) or not value:
        raise _bad(key, "must be a non-empty array")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _bad(key, "must contain identifiers")
        if item not in out:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# pagination -- PRD 2.3
# ---------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def paginate(rows, data):
    limit = f_int(
        data,
        "limit",
        required=False,
        default=PAGINATION_DEFAULT_LIMIT,
        ge=PAGINATION_MIN_LIMIT,
        le=PAGINATION_MAX_LIMIT,
    )
    offset = f_int(
        data, "offset", required=False, default=PAGINATION_DEFAULT_OFFSET, ge=0
    )
    total = len(rows)
    return Page(rows[offset : offset + limit], limit, offset, total)


def filter_eq(rows, data, key, field=None):
    value = data.get(key)
    if value is None:
        return rows
    field = field or key
    return [r for r in rows if r.get(field) == value]
