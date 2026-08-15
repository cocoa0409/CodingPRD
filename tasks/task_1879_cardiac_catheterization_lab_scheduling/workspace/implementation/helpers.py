"""Parsing, validation, datetime, and pagination helpers."""
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

EQUIPMENT_CODES = {
    "BIPLANE_ANGIOGRAPHY", "IVUS", "OCT", "FFR",
    "ROTATIONAL_ATHERECTOMY", "IABP", "MECHANICAL_SUPPORT",
}

STAFF_ROLES = {"INTERVENTIONAL_CARDIOLOGIST", "SCRUB_TECHNOLOGIST", "CIRCULATING_NURSE"}
PROCEDURE_TYPES = {"DIAGNOSTIC_CATHETERIZATION", "PCI", "STEMI_PCI", "DEVICE_IMPLANT", "EP_STUDY"}
PRIORITIES = {"ELECTIVE", "URGENT", "STEMI"}
ROLES_IN_CASE = {"PRIMARY_OPERATOR", "SCRUB", "CIRCULATOR"}
DEVICE_TYPES = {"STENT_DES", "STENT_BMS", "PACEMAKER_LEAD", "ICD_LEAD", "CLOSURE_DEVICE"}
OWNERSHIPS = {"OWNED", "CONSIGNMENT"}
RECORD_TYPES = {"CONTRAST", "RADIATION"}
AUC_SCORES = {"APPROPRIATE", "MAY_BE_APPROPRIATE", "RARELY_APPROPRIATE"}
DECISION_OUTCOMES = {"ACCEPTED", "REJECTED"}

# role_in_case -> required staff_role
ROLE_IN_CASE_TO_STAFF_ROLE = {
    "PRIMARY_OPERATOR": "INTERVENTIONAL_CARDIOLOGIST",
    "SCRUB": "SCRUB_TECHNOLOGIST",
    "CIRCULATOR": "CIRCULATING_NURSE",
}


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------

def fmt_s(dt):
    """Second-resolution ISO 8601 UTC with Z suffix (business datetimes)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ms(dt):
    """Millisecond-resolution ISO 8601 UTC with Z suffix (system timestamps)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string; normalize to UTC, second resolution."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# JSON body parsing (floats as Decimal for exact round-half-up semantics)
# ---------------------------------------------------------------------------

def get_payload():
    raw = request.get_data(as_text=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw, parse_float=Decimal, parse_int=int)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a valid JSON object", 400)
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def is_number(x):
    return isinstance(x, (int, Decimal)) and not isinstance(x, bool)


def is_int_valued(x):
    return is_number(x) and int(x) == x


def _bad(field, msg):
    raise ApiError(ERR_INVALID_REQUEST, "%s %s" % (field, msg), 400)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        _bad(field, "is required and must be a string")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "is required and must be one of %s" % sorted(allowed))
    return v


def req_num(data, field, gt=None, ge=None):
    v = data.get(field)
    if not is_number(v):
        _bad(field, "is required and must be a number")
    if gt is not None and not (v > gt):
        _bad(field, "must be greater than %s" % gt)
    if ge is not None and v < ge:
        _bad(field, "must be at least %s" % ge)
    return v


def opt_num(data, field, ge=None):
    """Optional numeric field: absent/None -> None, else validated number."""
    v = data.get(field)
    if v is None:
        return None
    if not is_number(v):
        _bad(field, "must be a number")
    if ge is not None and not (v >= ge):
        _bad(field, "must be at least %s" % ge)
    return v


def req_int(data, field, ge=None):
    v = data.get(field)
    if not is_int_valued(v):
        _bad(field, "is required and must be a whole number")
    v = int(v)
    if ge is not None and v < ge:
        _bad(field, "must be at least %d" % ge)
    return v


def req_dt(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        _bad(field, "is required and must be an ISO 8601 datetime string")
    try:
        return parse_dt(v)
    except Exception:
        _bad(field, "must be a valid ISO 8601 datetime")


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def opt_code_list(data, field):
    v = data.get(field)
    if v is None:
        return []
    if not isinstance(v, list):
        _bad(field, "must be an array")
    for el in v:
        if not isinstance(el, str) or el not in EQUIPMENT_CODES:
            _bad(field, "contains an unknown equipment code: %r" % (el,))
    return list(v)


def opt_str_list(data, field):
    v = data.get(field)
    if v is None:
        return []
    if not isinstance(v, list):
        _bad(field, "must be an array")
    for el in v:
        if not isinstance(el, str):
            _bad(field, "must contain only strings")
    return list(v)


# ---------------------------------------------------------------------------
# Pagination (limit / offset; defaults 10 / 0; limit in [1, 100])
# ---------------------------------------------------------------------------

def pagination_params():
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be at least 0")
    return limit, offset


def paginate(items):
    """Slice a created_at-ascending list; returns (page, pagination meta)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
