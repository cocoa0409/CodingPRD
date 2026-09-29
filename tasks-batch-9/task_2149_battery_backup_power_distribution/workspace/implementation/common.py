"""Foundation: errors, envelope, auth, in-memory store, logical clock, validation."""
import random
import re
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from flask import request

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "SalesRep",
    "WarehouseOperator",
    "HazmatCertifier",
    "ComplianceOfficer",
    "Customer",
)
ALL_ROLES = list(ROLES)

# ---------------------------------------------------------------------------
# Error catalogue
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ACCOUNT_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_BATTERY_MODEL_NOT_FOUND": 404,
    "ERR_WAREHOUSE_NOT_FOUND": 404,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_INVENTORY_LOT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_CORE_RETURN_NOT_FOUND": 404,
    "ERR_WARRANTY_CLAIM_NOT_FOUND": 404,
    "ERR_SERVICE_CONTRACT_NOT_FOUND": 404,
    "ERR_STORM_EVENT_NOT_FOUND": 404,
    "ERR_DISPOSAL_MANIFEST_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ORDER_HAS_NO_LINES": 422,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_REFRESH_CYCLES_EXHAUSTED": 409,
    "ERR_WAREHOUSE_NOT_HAZMAT_ENDORSED": 422,
    "ERR_CARRIER_HAZMAT_REFUSED": 422,
    "ERR_AIR_MODE_PROHIBITED": 422,
    "ERR_LITHIUM_WH_LIMIT_EXCEEDED": 422,
    "ERR_MODEL_DISCONTINUED": 422,
    "ERR_ACCOUNT_MISMATCH": 422,
    "ERR_STORM_REGION_MISMATCH": 422,
    "ERR_ORDER_NOT_DELIVERED": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_STORM_PRIORITY_TOO_LOW": 403,
    "ERR_STORM_POOL_EXHAUSTED": 422,
    "ERR_CORE_RETURN_WINDOW_CLOSED": 422,
    "ERR_REFRESH_COOLDOWN_ACTIVE": 409,
    "ERR_CARRIER_WINDOW_CONFLICT": 409,
    "ERR_DISPATCH_WINDOW_NOT_OPEN": 409,
    "ERR_LOT_SHELF_EXPIRED": 422,
    "ERR_LOT_REFRESH_REQUIRED": 422,
    "ERR_INSUFFICIENT_SELLABLE_STOCK": 422,
    "ERR_CORE_COUNT_EXCEEDS_PROMISE": 422,
    "ERR_LOT_RESERVED": 409,
    "ERR_DOCK_CAPACITY_EXCEEDED": 422,
    "ERR_MANIFEST_EMPTY": 422,
    "ERR_MANIFEST_LEAD_LIMIT_EXCEEDED": 422,
    "ERR_NO_ELIGIBLE_BATTERY_MODEL": 422,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_DUPLICATE_SERIAL_NUMBER": 409,
    "ERR_SHIPMENT_ALREADY_OPEN": 409,
    "ERR_CARRIER_PREVIOUSLY_REJECTED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()
        self.status = status if status is not None else ERROR_STATUS.get(error_id, 400)


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole number of cents (int)."""
    return int(rhu(value, 0))


def num(value, places):
    """Round half up to `places` decimals, returned as a float."""
    return float(rhu(value, places))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_ts(dt):
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO-8601 instant. Raises ValueError on failure."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value.strip()):
        raise ValueError("not a date")
    return date.fromisoformat(value.strip())


def days_between(d1, d2):
    return (d2 - d1).days


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.accounts = {}
        self.battery_models = {}
        self.warehouses = {}
        self.carriers = {}
        self.inventory_lots = {}
        self.orders = {}
        self.order_lines = {}
        self.shipments = {}
        self.core_returns = {}
        self.warranty_claims = {}
        self.service_contracts = {}
        self.storm_events = {}
        self.disposal_manifests = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def now_dt():
    return DB.clock


def now_ts():
    return fmt_ts(DB.clock)


def now_date():
    return DB.clock.date()


def new_row(fields):
    ts = now_ts()
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = DB.next_seq()
    return row


def touch(row):
    row["updated_at"] = now_ts()
    row["version"] = int(row["version"]) + 1
    return row


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(row, extra=None):
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_ts(),
    }


def ok(data, status=200):
    return {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}, status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, 200


def err_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Authentication / authorisation (ladder rungs 1-3)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header missing or empty")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header missing or empty")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unrecognised role")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role %s is not authorised for this endpoint" % role)
    return user_id, role


def scope(role, user_id, account_id):
    """Ladder rung 7: Customer callers may only touch their own account."""
    if role == "Customer" and account_id != user_id:
        raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION", "customer may only act on its own account")


# ---------------------------------------------------------------------------
# Body parsing / validation (ladder rung 5)
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True, force=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "field '%s' %s" % (name, why))


def _present(body, name):
    return name in body and body[name] is not None


def _fetch(body, name, required, default):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    return body[name]


def f_str(body, name, required=True, default=None, nonempty=True, pattern=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if nonempty and value.strip() == "":
        _bad(name, "must not be empty")
    if pattern and not re.match(pattern, value):
        _bad(name, "does not match the required format")
    return value


def f_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % maximum)
    return value


def f_num(body, name, required=True, default=None, minimum=None, maximum=None,
          exclusive_min=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    value = float(value)
    if exclusive_min is not None and not value > exclusive_min:
        _bad(name, "must be > %s" % exclusive_min)
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % maximum)
    return value


def f_bool(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def f_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def f_enum_list(body, name, allowed, required=True, default=None, nonempty=True):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    if nonempty and len(value) == 0:
        _bad(name, "must not be empty")
    for element in value:
        if not isinstance(element, str) or element not in allowed:
            _bad(name, "contains an undeclared member")
    return value


def f_date(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 calendar date")
    try:
        parse_date(value)
    except Exception:
        _bad(name, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return value


def f_datetime(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 UTC instant")
    try:
        parse_dt(value)
    except Exception:
        _bad(name, "must be an ISO 8601 UTC instant")
    return value


STATE_CODE_RE = r"^[A-Z]{2}$"


# ---------------------------------------------------------------------------
# Pagination and filtering
# ---------------------------------------------------------------------------
_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset.strip()):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def page(rows, serializer):
    limit, offset = pagination()
    rows = sort_rows(rows)
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], total, limit, offset)


def qp(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


# ---------------------------------------------------------------------------
# Path / body foreign key resolution (ladder rungs 4 and 6)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "accounts": "ERR_ACCOUNT_NOT_FOUND",
    "battery_models": "ERR_BATTERY_MODEL_NOT_FOUND",
    "warehouses": "ERR_WAREHOUSE_NOT_FOUND",
    "carriers": "ERR_CARRIER_NOT_FOUND",
    "inventory_lots": "ERR_INVENTORY_LOT_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "order_lines": "ERR_ORDER_LINE_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "core_returns": "ERR_CORE_RETURN_NOT_FOUND",
    "warranty_claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
    "service_contracts": "ERR_SERVICE_CONTRACT_NOT_FOUND",
    "storm_events": "ERR_STORM_EVENT_NOT_FOUND",
    "disposal_manifests": "ERR_DISPOSAL_MANIFEST_NOT_FOUND",
}


def must(collection, row_id):
    table = getattr(DB, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection], "%s not found" % collection[:-1].replace("_", " "))
    return row
