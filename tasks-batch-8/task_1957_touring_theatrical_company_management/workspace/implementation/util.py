"""Request-shape validators, date/datetime parsing, money rounding, pagination.

All money is integer cents; every rounding is ROUND_HALF_UP (PRD §2.5).
"""

import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from flask import request

from errors import err, ERR_INVALID_REQUEST


# --- Money / rounding ---------------------------------------------------------
def rhu(value):
    """Round-half-up a Decimal-compatible value to whole cents -> int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Exact Decimal from a JSON number (str() avoids float artifacts)."""
    return Decimal(str(value))


# --- Body access ---------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def reject_unknown(body, allowed):
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise err(ERR_INVALID_REQUEST, 400,
                  "Unknown field(s): %s" % ", ".join(sorted(extra)))


def require_present(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
    return body[name]


# --- Scalar validators ----------------------------------------------------------
def as_int(v, name, minv=None, maxv=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, 400, "Field %s must be an integer" % name)
    if minv is not None and v < minv:
        raise err(ERR_INVALID_REQUEST, 400, "Field %s must be >= %s" % (name, minv))
    if maxv is not None and v > maxv:
        raise err(ERR_INVALID_REQUEST, 400, "Field %s must be <= %s" % (name, maxv))
    return v


def as_number(v, name, minv=None, maxv=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, 400, "Field %s must be a number" % name)
    if minv is not None and v < minv:
        raise err(ERR_INVALID_REQUEST, 400, "Field %s must be >= %s" % (name, minv))
    if maxv is not None and v > maxv:
        raise err(ERR_INVALID_REQUEST, 400, "Field %s must be <= %s" % (name, maxv))
    return v


def as_str(v, name):
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, 400, "Field %s must be a string" % name)
    return v


def as_enum(v, name, values):
    if not isinstance(v, str) or v not in values:
        raise err(ERR_INVALID_REQUEST, 400,
                  "Field %s must be one of: %s" % (name, ", ".join(values)))
    return v


# --- Dates / times ---------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURTAIN_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse_iso_date(v, name):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise err(ERR_INVALID_REQUEST, 400,
                  "Field %s must be an ISO date (YYYY-MM-DD)" % name)
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, "Field %s is not a valid date" % name)


def parse_iso_datetime(v, name):
    if not isinstance(v, str) or "T" not in v:
        raise err(ERR_INVALID_REQUEST, 400,
                  "Field %s must be an ISO datetime" % name)
    try:
        s = v.replace("Z", "+00:00") if v.endswith("Z") else v
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, "Field %s is not a valid datetime" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_curtain(v, name):
    if not isinstance(v, str) or not _CURTAIN_RE.match(v):
        raise err(ERR_INVALID_REQUEST, 400,
                  "Field %s must be a curtain time (HH:MM, 24h)" % name)
    hh, mm = v.split(":")
    return int(hh) * 60 + int(mm)


def date_to_dt(d):
    """Midnight UTC for an ISO date (cancellation 'days_out' math)."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# --- Pagination (PRD §2.3) --------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records, serializer):
    """records: full filtered list of dicts (insertion-ordered = created_at ASC)."""
    limit, offset = pagination_params()
    total = len(records)
    window = records[offset:offset + limit]
    return [serializer(r) for r in window], total, limit, offset
