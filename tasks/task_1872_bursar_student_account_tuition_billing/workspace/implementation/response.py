"""Response envelope helpers per PRD section 2.2 / 2.3."""
import uuid
from flask import jsonify, request

from db import now_iso
from errors import ApiError, err, ERR_INVALID_REQUEST


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_envelope(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def pagination_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(items, serializer, status=200):
    """items must already be sorted by creation (created_at ASC)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return success([serializer(x) for x in page], response_type="array",
                   status=status, pagination=pagination)


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


# ---- typed field extraction (schema failures -> ERR_INVALID_REQUEST 400) ----

def req_field(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, f"Field must be a non-empty string: {name}")
    return v


def req_int(body, name):
    v = req_field(body, name)
    if isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field must be an integer: {name}")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field must be an integer: {name}")
    return v


def opt_int(body, name):
    if name not in body or body[name] is None:
        return None
    return req_int(body, name)


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field must be a boolean: {name}")
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_number(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field must be a number: {name}")
    return v
