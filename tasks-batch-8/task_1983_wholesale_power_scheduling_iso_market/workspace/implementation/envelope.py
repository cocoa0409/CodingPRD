"""Response envelope helpers matching the scaffold's response_envelope spec."""
from flask import jsonify, request

from errors import ApiError, invalid_request
from util import request_id, now_ts


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": now_ts()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    return ok(
        items,
        status=200,
        response_type="array",
        pagination={"limit": limit, "offset": offset,
                    "total_count": total_count, "has_more": has_more},
    )


def error_response(err: ApiError):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def pagination_params():
    """Parse limit/offset query params with defaults 10/0, range 1..100 / >=0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(records):
    """records: full sorted+filtered list of serialized dicts."""
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list(page, total, limit, offset)
