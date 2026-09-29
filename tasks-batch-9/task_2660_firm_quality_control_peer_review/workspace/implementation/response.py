"""Response envelope helpers (PRD 2.2 / 2.3, SCAFFOLD response_envelope)."""

import random
import string

from flask import jsonify

import clock
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": clock.now_iso()}


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array_response(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _as_int(raw):
    if isinstance(raw, bool):
        raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")
    try:
        text = str(raw).strip()
        if text != str(int(text)):
            raise ValueError(text)
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")


def pagination(args):
    """limit defaults to 10 with a floor of 1 and a ceiling of 100; offset defaults to 0
    and must not be negative.  Anything out of range is ERR_PAGINATION_OUT_OF_RANGE."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if args.get("limit") is not None and args.get("limit") != "":
        limit = _as_int(args.get("limit"))
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")
    if args.get("offset") is not None and args.get("offset") != "":
        offset = _as_int(args.get("offset"))
        if offset < 0:
            raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
