"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from store import db, fmt_dt

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(db.clock),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, page_meta):
    return jsonify({"meta": _meta(page_meta), "response_type": "array", "data": rows}), 200


def error_response(error_id, message, http_status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        http_status,
    )


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def pagination_params():
    limit = _int_arg("limit", PAGE_LIMIT_DEFAULT)
    offset = _int_arg("offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN:
        limit = PAGE_LIMIT_MIN
    if limit > PAGE_LIMIT_MAX:
        limit = PAGE_LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset: offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def listing(rows, serializer):
    page, page_meta = paginate(rows)
    return ok_list([serializer(r) for r in page], page_meta)
