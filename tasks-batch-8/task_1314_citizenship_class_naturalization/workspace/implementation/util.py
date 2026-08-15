"""Response envelope, request body validation, pagination helpers."""
import secrets
from flask import request, jsonify

from db import fmt_dt, now_dt
from errors import err_invalid_request


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_dt(now_dt()),
    }


def success_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------- Request body parsing / field validation ----------------

def json_body():
    """Parse request JSON. Empty body yields {}; malformed yields 400."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def _present(body, field):
    return field in body and body[field] is not None


def v_str(body, field, required=True):
    if field not in body:
        if required:
            raise err_invalid_request("Missing required field: %s" % field)
        return None
    val = body[field]
    if val is None:
        if required:
            raise err_invalid_request("Field %s must not be null" % field)
        return None
    if not isinstance(val, str):
        raise err_invalid_request("Field %s must be a string" % field)
    return val


def v_int(body, field, required=True, minv=None, maxv=None):
    if field not in body:
        if required:
            raise err_invalid_request("Missing required field: %s" % field)
        return None
    val = body[field]
    if val is None:
        if required:
            raise err_invalid_request("Field %s must not be null" % field)
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_invalid_request("Field %s must be an integer" % field)
    if minv is not None and val < minv:
        raise err_invalid_request("Field %s is below its minimum" % field)
    if maxv is not None and val > maxv:
        raise err_invalid_request("Field %s exceeds its maximum" % field)
    return val


def v_bool(body, field, required=True):
    if field not in body:
        if required:
            raise err_invalid_request("Missing required field: %s" % field)
        return None
    val = body[field]
    if val is None:
        if required:
            raise err_invalid_request("Field %s must not be null" % field)
        return None
    if not isinstance(val, bool):
        raise err_invalid_request("Field %s must be a boolean" % field)
    return val


def v_enum(body, field, members, required=True):
    val = v_str(body, field, required=required)
    if val is None:
        return None
    if val not in members:
        raise err_invalid_request("Field %s has an invalid value" % field)
    return val


def v_datetime(body, field, required=True):
    """Returns (raw_string, parsed_utc_datetime) or (None, None)."""
    from db import parse_dt
    raw = v_str(body, field, required=required)
    if raw is None:
        return None, None
    try:
        dt = parse_dt(raw)
    except (ValueError, TypeError):
        raise err_invalid_request("Field %s must be an ISO-8601 timestamp" % field)
    return raw, dt


def v_date(body, field, required=True):
    import datetime as _dt
    raw = v_str(body, field, required=required)
    if raw is None:
        return None
    try:
        _dt.date.fromisoformat(raw)
    except (ValueError, TypeError):
        raise err_invalid_request("Field %s must be an ISO date" % field)
    return raw


# ---------------- Pagination ----------------

def pagination_params():
    limit_raw = request.args.get("limit", None)
    offset_raw = request.args.get("offset", None)
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err_invalid_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise err_invalid_request("limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err_invalid_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise err_invalid_request("offset out of range")
    return limit, offset


def sort_records(recs):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(recs, key=lambda r: (r.created_at, r._seq))


def paginate(recs, serializer):
    limit, offset = pagination_params()
    ordered = sort_records(list(recs))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)
