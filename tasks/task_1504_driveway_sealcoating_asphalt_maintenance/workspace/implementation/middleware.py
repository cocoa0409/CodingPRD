"""Auth middleware and helpers: header extraction, role checking, validation helpers."""

import math
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from clock import now, now_iso_ms, parse_iso, format_iso_ms
from db import DB
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    err,
)

ROLES = {"OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer"}

# Endpoint role map: (method, path-template) -> allowed roles
# Path templates use Flask-style converters; we match on the rule string.
ROLE_TABLE = {}


def require_auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID or X-User-Role header missing or role unrecognized",
        )
    return user_id, role


def require_role(*roles):
    user_id, role = require_auth()
    if role not in roles:
        raise err(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")
    return user_id, role


# ---------- generic request-body validation ----------

def get_json_body():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def check_unknown_fields(body, allowed):
    for k in body.keys():
        if k not in allowed:
            raise err(ERR_INVALID_REQUEST, 400, f"Unknown field: {k}")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_number(body, name, gt=None, ge=None, integer=False):
    v = body.get(name)
    if v is None:
        return None
    if not is_number(v):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a number")
    if integer:
        if isinstance(v, float) and not v.is_integer():
            raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
        v = int(v)
    if gt is not None and not (v > gt):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be >= {ge}")
    return v


def require_enum(body, name, choices):
    v = body.get(name)
    if v is None:
        return None
    if v not in choices:
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be one of {sorted(choices)}")
    return v


def require_bool(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean")
    return v


def require_string(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a string")
    return v


def valid_date_str(s):
    if not isinstance(s, str):
        return False
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) is not None


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------- entity helpers ----------

def new_id():
    return str(uuid.uuid4())


def base_fields():
    ts = now_iso_ms()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    """Bump updated_at and version for a mutation."""
    entity["updated_at"] = now_iso_ms()
    entity["version"] += 1


def paginate(items):
    """Apply limit/offset per PRD §2.3 (defaults 10/0, min 1, max 100)."""
    q = request.args
    limit_raw = q.get("limit")
    offset_raw = q.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def round_half_up_decimal(value):
    """Round a Decimal/numeric to integer cents using ROUND_HALF_UP."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    d = Decimal(str(value))
    return float(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def ceil_div_decimal(numer, denom):
    d = Decimal(str(numer)) / Decimal(str(denom))
    return int(d.to_integral_value(rounding="ROUND_CEILING"))


def ceil_value(v):
    d = Decimal(str(v))
    return int(d.to_integral_value(rounding="ROUND_CEILING"))


def add_months(date_obj, months):
    """Add calendar months to a date, clamping day to end-of-month when needed."""
    y = date_obj.year
    m = date_obj.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    # clamp day
    if m == 12:
        next_month_first = datetime(y + 1, 1, 1).date()
    else:
        next_month_first = datetime(y, m + 1, 1).date()
    last_day = (next_month_first - timedelta(days=1)).day
    d = min(date_obj.day, last_day)
    return datetime(y, m, d).date()
