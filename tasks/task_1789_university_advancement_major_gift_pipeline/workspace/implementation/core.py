"""Core utilities: logical clock, time math, decimal rounding, response
envelope, auth, request-shape validation, pagination, entity helpers."""

import calendar
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import request

from db import clock
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, ERR_INVALID_REQUEST

ROLES = {
    "GiftOfficer",
    "ProspectResearcher",
    "AdvancementDirector",
    "VPAdvancement",
    "DonorRelationsOfficer",
    "FinanceSteward",
}

# ---------------------------------------------------------------------------
# Logical clock / time helpers
# ---------------------------------------------------------------------------

def now():
    return clock["now"]


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Advance by whole calendar months, clamping the day to month end."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_frequency_step(dt, frequency, steps):
    if frequency == "MONTHLY":
        return add_months(dt, steps)
    if frequency == "QUARTERLY":
        return add_months(dt, 3 * steps)
    # ANNUAL
    return add_months(dt, 12 * steps)


def fy_start(dt):
    """Fiscal year start: July 1 of (year if month >= 7 else year - 1)."""
    year = dt.year if dt.month >= 7 else dt.year - 1
    return datetime(year, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Decimal helpers (money is integer cents; never float)
# ---------------------------------------------------------------------------

def dec_floor_cents(value):
    """Floor a Decimal to a whole cent (integer)."""
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def dec_rhu_int(value):
    """Round a Decimal half-up to a whole integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def meta_base():
    return {"api_request_id": new_request_id(), "api_request_timestamp": iso(now())}


def success_object(data, status=200):
    return {"meta": meta_base(), "response_type": "object", "data": data}, status


def success_list(items, limit, offset, total_count):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, 200


def error_body(error_id, message):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def authenticate():
    """Priority 1: both headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def authorize(role, allowed):
    """Priority 2: acting role must be listed for the endpoint."""
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, f"Role {role} may not invoke this endpoint")


ALL_ROLES = [
    "GiftOfficer", "ProspectResearcher", "AdvancementDirector",
    "VPAdvancement", "DonorRelationsOfficer", "FinanceSteward",
]


# ---------------------------------------------------------------------------
# Request-shape validation (priority 3)
# ---------------------------------------------------------------------------

def body_json():
    """Return the request JSON object; {} when no body is supplied."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def check_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Unknown field: {key}")


def req_str(body, field):
    value = body.get(field)
    if not isinstance(value, str) or isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is required and must be a string")
    return value


def opt_str(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a string")
    return value


def req_int(body, field, minimum=None, maximum=None):
    value = body.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is required and must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be <= {maximum}")
    return value


def opt_int(body, field, minimum=None, maximum=None):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be <= {maximum}")
    return value


def req_money(body, field):
    """Integer money fields must be positive integers."""
    return req_int(body, field, minimum=1)


def req_enum(body, field, allowed):
    value = body.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be one of {sorted(allowed)}")
    return value


def req_bool(body, field, default=False):
    value = body.get(field, default)
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a boolean")
    return value


# ---------------------------------------------------------------------------
# Pagination (limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(str(raw_limit).strip(), 10)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(str(raw_offset).strip(), 10)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(items, sort_key=None):
    """Apply default sort (created_at ASC) and limit/offset pagination."""
    limit, offset = pagination_params()
    if sort_key is None:
        items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    else:
        items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def new_entity():
    """Fresh common fields for a new entity."""
    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """A mutation: version += 1 and updated_at refreshed."""
    entity["version"] += 1
    entity["updated_at"] = now()
