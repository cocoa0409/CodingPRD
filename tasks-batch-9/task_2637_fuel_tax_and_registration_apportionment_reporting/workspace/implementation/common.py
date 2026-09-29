"""Foundation layer: logical clock, in-memory store, response envelope,
errors, authentication/authorisation and request-shape validation helpers.

Every structural name in this module is taken verbatim from PRD.md §2 and
SCAFFOLD.yaml (response_envelope / validations / errors).
"""

import re
import random
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import g, request

API_PREFIX = "/apportionment"

ROLES = ("CarrierAdmin", "MileageAnalyst", "TaxPreparer", "ComplianceOfficer")

# --------------------------------------------------------------------------
# Decimal helpers — PRD §2.7: all rounding is round half up, away from zero.
# --------------------------------------------------------------------------

MILE_SCALE = 1
GALLON_SCALE = 3
MONEY_SCALE = 2
RATE_SCALE = 4
RATIO_SCALE = 4
PERCENT_SCALE = 6

ZERO = Decimal("0")


def D(value):
    """Coerce to Decimal without binary-float contamination."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rnd(value, places):
    """round half up to `places` decimals."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def miles(value):
    return rnd(value, MILE_SCALE)


def gallons(value):
    return rnd(value, GALLON_SCALE)


def money(value):
    return rnd(value, MONEY_SCALE)


def ratio(value):
    return rnd(value, RATIO_SCALE)


def percent(value):
    return rnd(value, PERCENT_SCALE)


def whole(value):
    """round half up to an integer."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fnum(value, places):
    """Serialise a Decimal quantity at its pinned scale."""
    if value is None:
        return None
    return float(rnd(value, places))


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

TS_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
JCODE_RE = re.compile(r"^[A-Z]{2}$")


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_instant(text):
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(text):
    if not isinstance(text, str) or not DATE_RE.match(text.strip()):
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None


class LogicalClock(object):
    """PRD §2.5 — reads 2026-08-01T00:00:00Z until moved; never falls back to
    wall-clock time."""

    def __init__(self):
        self._now = TS_DEFAULT

    def now(self):
        return self._now

    def today(self):
        return self._now.astimezone(timezone.utc).date()

    def set(self, instant):
        self._now = instant


class WallClock(object):
    """Strictly increasing real-time source used only for created_at /
    updated_at / api_request_timestamp."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last = None

    def now(self):
        with self._lock:
            current = datetime.now(timezone.utc)
            if self._last is not None and current <= self._last:
                current = self._last + timedelta(milliseconds=1)
            self._last = current
            return current


WALL = WallClock()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def bad_request(message="The request payload is not valid."):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


# --------------------------------------------------------------------------
# In-memory store — starts empty on every boot. Nothing is ever seeded.
# --------------------------------------------------------------------------


class Store(object):
    def __init__(self):
        self.clock = LogicalClock()
        self.jurisdictions = {}
        self.weight_group_fees = {}
        self.carriers = {}
        self.drivers = {}
        self.vehicles = {}
        self.trip_records = {}
        self.mileage_legs = {}
        self.fuel_purchases = {}
        self.fuel_tax_returns = {}
        self.return_lines = {}
        self.registration_applications = {}
        self.schedule_lines = {}
        self.fleet_change_requests = {}
        self.credentials = {}
        self.audit_selections = {}
        self._seq = 0
        self._lock = threading.Lock()

    def next_seq(self):
        with self._lock:
            self._seq += 1
            return self._seq


DB = Store()

VERSIONED = True
LIGHT = False


def new_id():
    return str(uuid.uuid4())


def new_row(versioned):
    """Common property set (PRD §2.4). Light entities carry only id and
    created_at; no updated_at and no version field is ever serialised."""
    created = fmt_instant(WALL.now())
    row = {
        "id": new_id(),
        "created_at": created,
        "_seq": DB.next_seq(),
    }
    if versioned:
        row["updated_at"] = created
        row["version"] = 1
    return row


def touch(row):
    """One mutation of a versioned row: version += 1 and updated_at refreshed
    (PRD §2.4 / §2.10 — cascade mutations count exactly like direct writes)."""
    row["updated_at"] = fmt_instant(WALL.now())
    row["version"] = row.get("version", 1) + 1
    return row


# --------------------------------------------------------------------------
# Response envelope — PRD §2.2
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_meta():
    rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
    return {
        "api_request_id": rid,
        "api_request_timestamp": fmt_instant(WALL.now()),
    }


def ok(data, status=200):
    body = {
        "meta": _request_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return body, status


def ok_list(items, page):
    meta = _request_meta()
    meta["limit"] = page["limit"]
    meta["offset"] = page["offset"]
    meta["total_count"] = page["total_count"]
    meta["has_more"] = page["has_more"]
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return body, 200


def err_body(error_id, message):
    return {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Auth — PRD §2.1
# --------------------------------------------------------------------------


def authenticate(allowed_roles):
    """Validation priority 1 then 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-ID header is missing or empty.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role header is missing or empty.")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role is not a recognised role.")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403, "Role %s may not call this endpoint." % role
        )
    g.user_id = str(user_id).strip()
    g.user_role = role
    return g.user_id, g.user_role


ALL_ROLES = list(ROLES)


def carrier_scope_guard(carrier_id):
    """Validation priority 15/PRD step 7 — a CarrierAdmin is confined to the
    carrier whose id equals X-User-ID."""
    if g.get("user_role") != "CarrierAdmin":
        return
    if carrier_id is None or str(carrier_id) != g.get("user_id"):
        raise ApiError(
            "ERR_CARRIER_SCOPE_VIOLATION",
            403,
            "A CarrierAdmin may only act on its own carrier's resources.",
        )


# --------------------------------------------------------------------------
# Request body access & shape validation (validation priority 13 / PRD step 5)
# --------------------------------------------------------------------------

MISSING = object()


def raw_body():
    """The parsed JSON body, or {} when no body was supplied.  A body that is
    present but not a JSON object is a request-shape error, reported at the
    shape step rather than here so higher-priority checks still win."""
    if not request.data:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        return {"__malformed__": True}
    if not isinstance(parsed, dict):
        return {"__malformed__": True}
    return parsed


def reject_unknown(body, allowed):
    if body.get("__malformed__"):
        raise bad_request("The request body must be a JSON object.")
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise bad_request("Unknown field(s): %s." % ", ".join(sorted(extra)))


def field(body, key):
    return body.get(key, MISSING)


def need_str(body, key, required=True, default=None, allow_empty=False):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return default
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise bad_request("Field '%s' may not be empty." % key)
    return value


def need_int(body, key, required=True, default=None, minimum=None, maximum=None,
             choices=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (key, maximum))
    if choices is not None and value not in choices:
        raise bad_request("Field '%s' must be one of %s." % (key, list(choices)))
    return value


def need_num(body, key, required=True, default=None, minimum=None,
             minimum_exclusive=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise bad_request("Field '%s' must be a number." % key)
    try:
        dec = D(value)
    except (InvalidOperation, ValueError):
        raise bad_request("Field '%s' must be a number." % key)
    if minimum is not None and dec < D(minimum):
        raise bad_request("Field '%s' must be >= %s." % (key, minimum))
    if minimum_exclusive is not None and dec <= D(minimum_exclusive):
        raise bad_request("Field '%s' must be > %s." % (key, minimum_exclusive))
    return dec


def need_bool(body, key, required=True, default=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return default
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return value


def need_enum(body, key, choices, required=True, default=None):
    value = need_str(body, key, required=required, default=None)
    if value is None:
        return default
    if value not in choices:
        raise bad_request("Field '%s' must be one of %s." % (key, list(choices)))
    return value


def need_date(body, key, required=True, default=None):
    value = need_str(body, key, required=required, default=None)
    if value is None:
        return default
    parsed = parse_date(value)
    if parsed is None:
        raise bad_request("Field '%s' must be a YYYY-MM-DD date." % key)
    return value


def need_instant(body, key, required=True, default=None):
    value = need_str(body, key, required=required, default=None)
    if value is None:
        return default
    parsed = parse_instant(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 UTC instant." % key)
    return value


def need_legs(body, key, required=True):
    """A legs / reconstructed_legs array. Shape only — jurisdiction declaration
    is a later, separate step."""
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % key)
    out = []
    for element in value:
        if not isinstance(element, dict):
            raise bad_request("Each element of '%s' must be an object." % key)
        extra = [k for k in element.keys() if k not in ("jurisdiction_code", "leg_miles")]
        if extra:
            raise bad_request("Unknown leg field(s): %s." % ", ".join(sorted(extra)))
        code = need_str(element, "jurisdiction_code")
        leg_miles = need_num(element, "leg_miles", minimum_exclusive=0)
        out.append({"jurisdiction_code": code, "leg_miles": miles(leg_miles)})
    return out


# --------------------------------------------------------------------------
# Collection reads — PRD §2.3
# --------------------------------------------------------------------------

_UNMATCHABLE = object()


def page_params():
    """limit defaults to 10 (1..100), offset defaults to 0 (>= 0). Anything
    outside those bounds is ERR_INVALID_REQUEST."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer of at least 0.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return _UNMATCHABLE


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return _UNMATCHABLE


def apply_filters(rows, filters):
    """filters maps a row key to a wanted value; None means 'not supplied'."""
    out = list(rows)
    for key, wanted in filters.items():
        if wanted is None:
            continue
        if wanted is _UNMATCHABLE:
            return []
        out = [row for row in out if row.get(key) == wanted]
    return out


def sort_rows(rows, keys):
    """Sort by the given row keys, then created_at ASC, then insertion order."""
    def sort_key(row):
        parts = []
        for key in keys:
            value = row.get(key)
            parts.append("" if value is None else value)
        parts.append(row.get("created_at") or "")
        parts.append(row.get("_seq") or 0)
        return tuple(parts)

    return sorted(rows, key=sort_key)


def window(rows, limit, offset):
    total = len(rows)
    slice_ = rows[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(slice_) < total,
    }
    return slice_, page


def collection(rows, filters, sort_keys, serializer):
    limit, offset = page_params()
    filtered = apply_filters(rows, filters)
    ordered = sort_rows(filtered, sort_keys)
    slice_, page = window(ordered, limit, offset)
    return ok_list([serializer(row) for row in slice_], page)


def find_or_404(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id, 404, "No such resource: %s." % row_id)
    return row


# --------------------------------------------------------------------------
# Error catalogue — SCAFFOLD.yaml errors
# --------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CARRIER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_DRIVER_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_TRIP_RECORD_NOT_FOUND": 404,
    "ERR_FUEL_PURCHASE_NOT_FOUND": 404,
    "ERR_FUEL_TAX_RETURN_NOT_FOUND": 404,
    "ERR_REGISTRATION_APPLICATION_NOT_FOUND": 404,
    "ERR_FLEET_CHANGE_REQUEST_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_AUDIT_SELECTION_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_CARRIER_VERSION": 412,
    "ERR_INVALID_TRIP_STATE": 409,
    "ERR_INVALID_PURCHASE_STATE": 409,
    "ERR_INVALID_RETURN_STATE": 409,
    "ERR_INVALID_APPLICATION_STATE": 409,
    "ERR_CHANGE_REQUEST_NOT_PENDING": 409,
    "ERR_CREDENTIAL_NOT_ISSUED": 409,
    "ERR_AUDIT_SELECTION_NOT_SELECTED": 409,
    "ERR_CARRIER_LICENSE_INACTIVE": 409,
    "ERR_CARRIER_IRP_INACTIVE": 409,
    "ERR_VEHICLE_STATE_INCOMPATIBLE": 409,
    "ERR_TRANSFER_NOT_REVERSIBLE": 409,
    "ERR_TRIP_GAP_UNRESOLVED": 409,
    "ERR_TRIP_INTERVAL_OVERLAP": 409,
    "ERR_DRIVER_CREDENTIAL_WINDOW_CONFLICT": 409,
    "ERR_PURCHASE_LOCKED_BY_FILED_RETURN": 409,
    "ERR_DUPLICATE_JURISDICTION": 409,
    "ERR_DUPLICATE_WEIGHT_GROUP_FEE": 409,
    "ERR_DUPLICATE_USDOT_NUMBER": 409,
    "ERR_DUPLICATE_UNIT_NUMBER": 409,
    "ERR_DUPLICATE_RETURN_PERIOD": 409,
    "ERR_DUPLICATE_APPLICATION_YEAR": 409,
    "ERR_DUPLICATE_AUDIT_PERIOD": 409,
    "ERR_DUPLICATE_JURISDICTION_LINE": 409,
    "ERR_NO_FILED_RETURN_FOR_PERIOD": 409,
    "ERR_JURISDICTION_NOT_DECLARED": 422,
    "ERR_RECONSTRUCTION_SUPPORT_MISSING": 422,
    "ERR_RETENTION_PERIOD_EXPIRED": 422,
    "ERR_RECONSTRUCTION_WINDOW_CLOSED": 422,
    "ERR_LEG_MILEAGE_MISMATCH": 422,
    "ERR_DRIVER_CARRIER_MISMATCH": 422,
    "ERR_EFFECTIVE_DATE_OUT_OF_YEAR": 422,
    "ERR_WEIGHT_GROUP_FEE_MISSING": 422,
    "ERR_NO_TAX_PAID_GALLONS": 422,
    "ERR_NO_ACCEPTED_MILEAGE": 422,
    "ERR_BOND_CEILING_EXCEEDED": 402,
}


def fail(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP.get(error_id, 400), message)
