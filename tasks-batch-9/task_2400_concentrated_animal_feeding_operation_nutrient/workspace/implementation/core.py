"""Core plumbing for the CAFO Nutrient Management API.

Holds the in-memory store (which always starts EMPTY), the server-held logical
clock, decimal/date helpers, the response envelope and the error type.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext

getcontext().prec = 40

UTC = timezone.utc

# --------------------------------------------------------------------------
# decimal helpers
# --------------------------------------------------------------------------


def D(v):
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        return Decimal(int(v))
    return Decimal(str(v))


def q(v, n=2):
    """round_half_up to n decimal places"""
    return D(v).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)


def q2(v):
    return q(v, 2)


def q4(v):
    return q(v, 4)


def ifloor(v):
    return int(D(v).to_integral_value(rounding=ROUND_FLOOR))


def iceil(v):
    d = D(v)
    f = ifloor(d)
    return f if D(f) == d else f + 1


def floor_to_100(v):
    return ifloor(D(v) / 100) * 100


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------


def parse_dt(s):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """Domain instants: no fractional part when it is zero."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_stamp(dt):
    """Audit stamps: always three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29
        return dt.replace(year=dt.year + years, day=28)


def add_days(dt, days):
    return dt + timedelta(days=days)


def year_of(dt):
    return dt.astimezone(UTC).year


def month_of(dt):
    return dt.astimezone(UTC).month


# --------------------------------------------------------------------------
# store  (ALWAYS starts empty -- no seeding whatsoever)
# --------------------------------------------------------------------------

TABLES = (
    "operations",
    "haulers",
    "permits",
    "plans",
    "fields",
    "soil_tests",
    "budgets",
    "storages",
    "storage_inspections",
    "events",
    "transfers",
    "incidents",
    "inspections",
    "reports",
)

DB = {t: {} for t in TABLES}

STATE = {
    "clock": datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC),
    "seq": 0,
}

NOT_FOUND_CODE = {
    "operations": "ERR_OPERATION_NOT_FOUND",
    "haulers": "ERR_HAULER_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "fields": "ERR_FIELD_NOT_FOUND",
    "soil_tests": "ERR_SOIL_TEST_NOT_FOUND",
    "budgets": "ERR_BUDGET_NOT_FOUND",
    "storages": "ERR_STORAGE_NOT_FOUND",
    "storage_inspections": "ERR_STORAGE_INSPECTION_NOT_FOUND",
    "events": "ERR_EVENT_NOT_FOUND",
    "transfers": "ERR_TRANSFER_NOT_FOUND",
    "incidents": "ERR_INCIDENT_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
}

IMMUTABLE_TABLES = ("soil_tests", "storage_inspections")


def now():
    return STATE["clock"]


def set_clock(dt):
    STATE["clock"] = dt.astimezone(UTC)


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def new_row(table, fields):
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = fmt_stamp(now())
    if table not in IMMUTABLE_TABLES:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    DB[table][row["id"]] = row
    return row


def touch(table, row):
    """Explicit mutation of a row: refresh updated_at and bump version."""
    if table in IMMUTABLE_TABLES:
        return row
    row["updated_at"] = fmt_stamp(now())
    row["version"] = int(row.get("version", 1)) + 1
    return row


def rows(table):
    """All rows of a table in creation order."""
    return sorted(DB[table].values(), key=lambda r: r["_seq"])


def get(table, rid):
    if not isinstance(rid, str):
        return None
    return DB[table].get(rid)


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_OPERATION_NOT_FOUND": 404,
    "ERR_HAULER_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_FIELD_NOT_FOUND": 404,
    "ERR_SOIL_TEST_NOT_FOUND": 404,
    "ERR_BUDGET_NOT_FOUND": 404,
    "ERR_STORAGE_NOT_FOUND": 404,
    "ERR_STORAGE_INSPECTION_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_OPERATION_VERSION": 412,
    "ERR_PERMIT_STATE_INVALID": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_STORAGE_STATE_INVALID": 409,
    "ERR_EVENT_ALREADY_TERMINAL": 409,
    "ERR_TRANSFER_STATE_INVALID": 409,
    "ERR_INCIDENT_STATE_INVALID": 409,
    "ERR_INSPECTION_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    "ERR_PERMIT_COVERAGE_REQUIRED": 409,
    "ERR_PERMIT_COVERAGE_EXPIRED": 409,
    "ERR_PLAN_NOT_APPROVED": 409,
    "ERR_BUDGET_NOT_ACTIVE": 409,
    "ERR_OPERATION_SUSPENDED": 409,
    "ERR_OPERATION_RESTRICTED": 409,
    "ERR_FROZEN_GROUND_APPLICATION": 422,
    "ERR_SATURATED_SOIL_APPLICATION": 422,
    "ERR_WINTER_WINDOW_APPLICATION": 422,
    "ERR_PRECIPITATION_RISK": 422,
    "ERR_SETBACK_VIOLATION": 422,
    "ERR_FUTURE_DATED_RECORD": 422,
    "ERR_PERMIT_COVERAGE_OVERLAP": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 422,
    "ERR_REAPPLICATION_INTERVAL_CONFLICT": 409,
    "ERR_HAULER_LICENSE_LAPSED": 422,
    "ERR_APPLICATION_METHOD_NOT_IN_PLAN": 422,
    "ERR_NO_VALID_SOIL_TEST": 422,
    "ERR_RECIPIENT_DOCUMENTATION_MISSING": 422,
    "ERR_REPORT_PERIOD_DUPLICATE": 409,
    "ERR_NOV_NOT_WARRANTED": 422,
    "ERR_INSUFFICIENT_STORAGE_DAYS": 422,
    "ERR_NO_FIELD_BUDGETS": 422,
    "ERR_ZERO_ALLOWABLE_RATE": 422,
    "ERR_VARIANCE_EXPLANATION_REQUIRED": 422,
    "ERR_ACRES_EXCEED_NET_APPLICABLE": 422,
    "ERR_RATE_EXCEEDS_LIMIT": 422,
    "ERR_FIELD_ALLOWANCE_EXCEEDED": 422,
    "ERR_INSUFFICIENT_STORAGE_VOLUME": 422,
    "ERR_STORAGE_OPERATING_CAPACITY_EXCEEDED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognised X-User-ID / X-User-Role headers.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_OWNERSHIP_VIOLATION": "The acting identity does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The actor closing an inspection must differ from the inspector of record.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, "Request rejected: %s." % error_id
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# envelope
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
        + ("%03d" % (datetime.now(UTC).microsecond // 1000))
        + "Z",
    }


def jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, list):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    return v


def serialize(row):
    return {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}


def ok_object(data, code=200):
    return {"meta": meta(), "response_type": "object", "data": jsonable(data)}, code


def ok_list(items, limit, offset, total):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return {"meta": m, "response_type": "array", "data": [jsonable(i) for i in items]}, 200


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
