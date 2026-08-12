from flask import jsonify

from util import req_id, wall_iso3


def meta():
    return {
        "api_request_id": req_id(),
        "api_request_timestamp": wall_iso3(),
    }


def success(data, code=200, response_type="object", pagination=None):
    m = meta()
    if pagination:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), code


def ok(data, code=200):
    return success(serialize_out(data), code, "object")


def ok_list(records, limit, offset, total):
    page = [serialize_out(r) for r in records]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success(page, 200, "array", pagination)


def serialize_out(rec):
    from util import serialize
    return serialize(rec)


def error_response(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
