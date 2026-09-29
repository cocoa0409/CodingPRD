"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

from db import iso, wall_now, public, sort_key
from errors import bad_request

ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(wall_now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(raw, name):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise bad_request("%s must be an integer" % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise bad_request("%s must be an integer" % name)
    return -int(digits) if negative else int(digits)


def pagination(args):
    limit = _int_param(args.get("limit"), "limit")
    offset = _int_param(args.get("offset"), "offset")
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise bad_request("limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < PAGE_OFFSET_MIN:
        raise bad_request("offset must be greater than or equal to %d" % PAGE_OFFSET_MIN)
    return limit, offset


def paged(rows, limit, offset, serializer=public):
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
