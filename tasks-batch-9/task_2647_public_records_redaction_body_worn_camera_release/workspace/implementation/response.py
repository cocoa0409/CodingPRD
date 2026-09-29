"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string

from db import store

ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def api_request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": store.now_str(),
    }


class ListResult(object):
    """A page of rows plus the pagination counters that describe it."""

    def __init__(self, rows, limit, offset, total_count):
        self.rows = rows
        self.limit = limit
        self.offset = offset
        self.total_count = total_count

    @property
    def has_more(self):
        return (self.offset + len(self.rows)) < self.total_count


def paginate(rows, limit, offset):
    total = len(rows)
    return ListResult(rows[offset:offset + limit], limit, offset, total)


def object_response(data):
    return {"meta": _meta(), "response_type": "object", "data": data or {}}


def list_response(result):
    meta = _meta()
    meta["limit"] = result.limit
    meta["offset"] = result.offset
    meta["total_count"] = result.total_count
    meta["has_more"] = result.has_more
    return {"meta": meta, "response_type": "array", "data": result.rows}


def error_response(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
