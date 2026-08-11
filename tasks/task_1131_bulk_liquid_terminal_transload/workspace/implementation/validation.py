"""Request-body schema/field validation helpers (priority 4, ERR_VALIDATION)
plus list-pagination parsing per PRD 2.3."""
import re
from datetime import date

from flask import request

from clock import _parse_iso
from errors import err

PRODUCT_GRADES = ("GASOLINE", "DIESEL", "JET", "ETHANOL", "CRUDE")
RESOURCE_TYPES = ("DOCK", "RAIL_RACK", "TRUCK_BAY")
PERMIT_TYPES = ("VAPOR_CONTROL", "HOT_WORK")
DIRECTIONS = ("RECEIPT", "DISCHARGE")
MODES = ("VESSEL", "RAIL", "TRUCK")
TICKET_TYPES = ("OPENING", "CLOSING")
SAMPLE_TYPES = ("FIRST_FOOT", "INLINE", "ALL_LEVELS")
LAB_RESULTS = ("PASSED", "FAILED")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def get_body():
    """Return the JSON request body as a dict, or raise ERR_VALIDATION.

    A missing body is treated as an empty object so that required-field
    checks produce ERR_VALIDATION rather than a framework 400/500.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a string" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_VALIDATION",
                  "Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_number(body, field, gt=None, ge=None):
    v = body.get(field)
    if not _is_number(v):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a number" % field)
    if gt is not None and not v > gt:
        raise err("ERR_VALIDATION", "Field '%s' must be > %s" % (field, gt))
    if ge is not None and not v >= ge:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, ge))
    return v


def opt_number(body, field, default, gt=None, ge=None, le=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_number(v):
        raise err("ERR_VALIDATION", "Field '%s' must be a number" % field)
    if gt is not None and not v > gt:
        raise err("ERR_VALIDATION", "Field '%s' must be > %s" % (field, gt))
    if ge is not None and not v >= ge:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, ge))
    if le is not None and not v <= le:
        raise err("ERR_VALIDATION", "Field '%s' must be <= %s" % (field, le))
    return v


def req_int(body, field, ge=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be an integer" % field)
    if ge is not None and not v >= ge:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, ge))
    return v


def opt_int(body, field, default, ge=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field '%s' must be an integer" % field)
    if ge is not None and not v >= ge:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, ge))
    return v


def parse_date(value):
    """Parse a YYYY-MM-DD string; None when invalid."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def req_date(body, field):
    raw = body.get(field)
    d = parse_date(raw)
    if d is None:
        raise err("ERR_VALIDATION",
                  "Field '%s' must be a valid YYYY-MM-DD date" % field)
    return raw, d


def req_datetime(body, field):
    raw = body.get(field)
    dt = _parse_iso(raw)
    if dt is None:
        raise err("ERR_VALIDATION",
                  "Field '%s' must be a valid ISO 8601 datetime" % field)
    return dt


def opt_string(body, field):
    if field not in body:
        return None
    v = body.get(field)
    if v is not None and not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field '%s' must be a string" % field)
    return v


def req_period(body, field):
    raw = body.get(field)
    if not isinstance(raw, str) or not _PERIOD_RE.match(raw):
        raise err("ERR_VALIDATION",
                  "Field '%s' must be a calendar month in YYYY-MM form" % field)
    month = int(raw[5:7])
    if month < 1 or month > 12:
        raise err("ERR_VALIDATION",
                  "Field '%s' must be a calendar month in YYYY-MM form" % field)
    return raw


def pagination_params():
    """PRD 2.3: limit default 10, allowed range [1, 100]; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION",
                      "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "Query parameter 'offset' must be >= 0")
    return limit, offset


def sort_and_page(rows, key=None):
    """All list endpoints sort by created_at ascending, then paginate."""
    limit, offset = pagination_params()
    ordered = sorted(rows, key=key or (lambda r: (r["created_at"], r["id"])))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total, limit, offset
