"""Shared helpers: datetime handling, decimal rounding, body validation,
pagination, serialization, auth context."""
import json
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import (
    ApiError,
    err_unauthenticated,
    err_forbidden_role,
    err_invalid_request,
    err_not_found,
)

ROLES = {
    "Donor",
    "IntakeStaff",
    "HazmatTechnician",
    "CrewCoordinator",
    "CrewLead",
    "StoreManager",
    "Cashier",
    "Contractor",
    "WarehouseAdmin",
}

# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------


def parse_dt(value, field="timestamp"):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err_invalid_request("%s must be an ISO 8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request("%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def period_of(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------


def D(x):
    """Exact Decimal from an int/float/str JSON number."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_cents(x):
    """Round half-up to integer cents, returning a Python int."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec1(x):
    """Round half-up to one decimal place (weights), returning a float."""
    return float(D(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body parsing & shape validation
# ---------------------------------------------------------------------------


def get_body():
    """Return the request JSON body as a dict; {} when absent."""
    data = request.get_json(silent=True)
    if data is None and request.data:
        try:
            data = json.loads(request.data)
        except (ValueError, TypeError):
            data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) or isinstance(
        v, Decimal
    )


def req_str(data, field):
    v = data.get(field)
    if v is None:
        raise err_invalid_request("Missing required field: %s" % field)
    if not isinstance(v, str):
        raise err_invalid_request("%s must be a string" % field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err_invalid_request("%s must be a string" % field)
    return v


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise err_invalid_request("%s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request("%s must be one of %s" % (field, sorted(allowed)))
    return v


def req_bool(data, field):
    v = data.get(field)
    if v is None:
        raise err_invalid_request("Missing required field: %s" % field)
    if not isinstance(v, bool):
        raise err_invalid_request("%s must be a boolean" % field)
    return v


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err_invalid_request("%s must be a boolean" % field)
    return v


def req_int(data, field, min_value=None):
    v = data.get(field)
    if v is None:
        raise err_invalid_request("Missing required field: %s" % field)
    if not _is_int(v):
        raise err_invalid_request("%s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise err_invalid_request("%s must be >= %s" % (field, min_value))
    return v


def opt_int(data, field, default=None, min_value=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_int(v):
        raise err_invalid_request("%s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise err_invalid_request("%s must be >= %s" % (field, min_value))
    return v


def req_num(data, field, gt=None, ge=None):
    v = data.get(field)
    if v is None:
        raise err_invalid_request("Missing required field: %s" % field)
    if not _is_num(v):
        raise err_invalid_request("%s must be a number" % field)
    if gt is not None and not D(v) > D(gt):
        raise err_invalid_request("%s must be > %s" % (field, gt))
    if ge is not None and not D(v) >= D(ge):
        raise err_invalid_request("%s must be >= %s" % (field, ge))
    return v


def opt_num(data, field, default=None, gt=None, ge=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_num(v):
        raise err_invalid_request("%s must be a number" % field)
    if gt is not None and not D(v) > D(gt):
        raise err_invalid_request("%s must be > %s" % (field, gt))
    if ge is not None and not D(v) >= D(ge):
        raise err_invalid_request("%s must be >= %s" % (field, ge))
    return v


def req_dt(data, field):
    return parse_dt(req_str(data, field), field)


def opt_dt(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    return parse_dt(v, field)


def opt_fk(data, field):
    """Optional FK string; explicit null and absent both yield None."""
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid_request("%s must be a string" % field)
    return v


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return Ctx(uid, role)


def require_role(ctx, roles):
    if ctx.role not in roles:
        raise err_forbidden_role()


# ---------------------------------------------------------------------------
# Store lookup
# ---------------------------------------------------------------------------


def lookup(store, resource, entity_id):
    entity = store.get(entity_id)
    if entity is None:
        raise err_not_found(resource)
    return entity


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(records):
    """records: full filtered list. Returns (page, meta_fields)."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise err_invalid_request("offset must be >= 0")
    total = len(records)
    page = records[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def parse_bool_param(name):
    v = request.args.get(name)
    if v is None:
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    raise err_invalid_request("%s must be true or false" % name)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def new_request_id():
    return "req_" + secrets.token_hex(10)
