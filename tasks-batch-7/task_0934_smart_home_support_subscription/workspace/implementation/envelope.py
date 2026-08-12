"""The response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""

import os
import random
import string

from flask import jsonify

from errors import ApiError
from timeutil import render_instant
from store import clock

_ALNUM = string.ascii_uppercase + string.digits

# PRD 2.3 pagination defaults.
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    # The api_request_timestamp is a server-generated instant and therefore
    # goes through the ONE renderer (G2).
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Pagination parameters (rung 20: a limit below 1 or above 100, or an offset
# below 0, is ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
def _as_int(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    neg = text.startswith("-")
    digits = text[1:] if neg else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    return -int(digits) if neg else int(digits)


def read_pagination(args):
    limit = _as_int(args.get("limit"))
    offset = _as_int(args.get("offset"))
    if limit is None:
        limit = LIMIT_DEFAULT
    elif limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None:
        offset = OFFSET_DEFAULT
    elif offset < OFFSET_MIN:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
