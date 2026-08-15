"""Response envelope, auth, pagination, datetime and body-validation helpers."""

import random
import string
from datetime import datetime, timezone, date

from flask import request, jsonify

from errors import ApiError, raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, \
    ERR_VALIDATION, ERR_NOT_FOUND
from store import fmt_ts, clock_now

ROLES = {
    "RegistryAdmin", "GeneratorOperator", "MeterAttester", "BrokerTrader",
    "ProgramManager", "ComplianceOfficer", "Auditor",
}

TECHNOLOGIES = {"SOLAR", "WIND", "HYDRO", "BIOMASS", "GEOTHERMAL"}


# ---------------------------------------------------------------- envelope

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(clock_now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# -------------------------------------------------------------------- auth

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this endpoint" % role)


def forbidden(msg="Ownership or scope mismatch"):
    raise_err(ERR_FORBIDDEN_ROLE, msg)


# -------------------------------------------------------------- pagination

def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, filters=None):
    """records: list of stored dicts. filters: dict of query-param -> value
    already applied by caller. Sorts by (created_at, seq) ascending."""
    items = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            items = [r for r in items if str(r.get(key)) == val]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --------------------------------------------------------------- datetimes

def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, "%s must be an ISO 8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_VALIDATION, "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_month(value, field="period_month"):
    """Parse a YYYY-MM month string into (year, month)."""
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, "%s must be a YYYY-MM string" % field)
    parts = value.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise_err(ERR_VALIDATION, "%s must be in YYYY-MM form" % field)
    try:
        y = int(parts[0])
        m = int(parts[1])
    except ValueError:
        raise_err(ERR_VALIDATION, "%s must be in YYYY-MM form" % field)
    if m < 1 or m > 12:
        raise_err(ERR_VALIDATION, "%s must be in YYYY-MM form" % field)
    return y, m


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, "%s must be a YYYY-MM-DD string" % field)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise_err(ERR_VALIDATION, "%s must be a valid YYYY-MM-DD date" % field)
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise_err(ERR_VALIDATION, "%s must be in YYYY-MM-DD form" % field)
    return value


# ------------------------------------------------------------------- body

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_field(body, field):
    if field not in body or body[field] is None:
        raise_err(ERR_VALIDATION, "Missing required field: %s" % field)
    return body[field]


def req_str(body, field):
    v = req_field(body, field)
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, "%s must be a string" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, "%s must be a string" % field)
    return v


def req_int(body, field):
    v = req_field(body, field)
    if not _is_int(v):
        raise_err(ERR_VALIDATION, "%s must be an integer" % field)
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        raise_err(ERR_VALIDATION, "%s must be an integer" % field)
    return v


def req_enum(body, field, allowed):
    v = req_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_VALIDATION, "%s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_list(body, field):
    v = req_field(body, field)
    if not isinstance(v, list):
        raise_err(ERR_VALIDATION, "%s must be an array" % field)
    return v


def opt_list(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_list(body, field)


def get_or_404(collection, rid, what="Resource"):
    rec = collection.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (what, rid))
    return rec
