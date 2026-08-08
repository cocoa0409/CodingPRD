"""The response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""

import random
import string

import clock

ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.audit_stamp(),
    }


def success(data, response_type="object", pagination=None):
    meta = base_meta()
    if pagination is not None:
        meta.update(pagination)
    return {"meta": meta, "response_type": response_type, "data": data}


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


class ObjResult(object):
    def __init__(self, row, serializer, status=200):
        self.row = row
        self.serializer = serializer
        self.status = status


class ListResult(object):
    def __init__(self, rows, serializer, limit, offset):
        self.rows = rows
        self.serializer = serializer
        self.limit = limit
        self.offset = offset
        self.status = 200


class RawResult(object):
    def __init__(self, data, status=200):
        self.data = data
        self.status = status


def render_result(result):
    if isinstance(result, ObjResult):
        return success(result.serializer(result.row), "object"), result.status
    if isinstance(result, ListResult):
        total = len(result.rows)
        window = result.rows[result.offset:result.offset + result.limit]
        pagination = {
            "limit": result.limit,
            "offset": result.offset,
            "total_count": total,
            "has_more": (result.offset + len(window)) < total,
        }
        data = [result.serializer(row) for row in window]
        return success(data, "array", pagination), result.status
    if isinstance(result, RawResult):
        return success(result.data, "object"), result.status
    return success(result, "object"), 200
