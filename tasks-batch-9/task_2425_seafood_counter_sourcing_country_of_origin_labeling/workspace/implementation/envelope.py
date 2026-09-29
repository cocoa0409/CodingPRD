"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify

from common import iso
from errors import ApiError, fail
from store import db

ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def build_meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(db.clock),
    }
    if pagination:
        meta.update(pagination)
    return meta


class Result(object):
    def __init__(self, kind, render, status=200, pagination=None):
        self.kind = kind
        self.render = render
        self.status = status
        self.pagination = pagination


def obj_result(serializer, entity, status=200):
    return Result("object", lambda: serializer(entity), status)


def empty_result(status=200):
    return Result("object", lambda: {}, status)


def list_result(serializer, items, limit, offset, total):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }
    return Result("array", lambda: [serializer(e) for e in items], 200, pagination)


def render_result(result):
    body = {
        "meta": build_meta(result.pagination),
        "response_type": result.kind,
        "data": result.render(),
    }
    return jsonify(body), result.status


def render_error(error):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status


# --------------------------------------------------------------------------
# pagination helpers
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def read_pagination(args):
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate(serializer, items, args):
    limit, offset = read_pagination(args)
    total = len(items)
    page = items[offset: offset + limit]
    return list_result(serializer, page, limit, offset, total)
