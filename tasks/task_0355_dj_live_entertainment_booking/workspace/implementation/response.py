"""Standard response envelope helpers.

Envelope shape (PRD §2.2 / scaffold response_envelope):

  success:
    { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
                [pagination fields for lists] },
      "response_type": "object" | "array",
      "data": {} | [] }

  error:
    { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
      "response_type": "error",
      "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

from clock import now
from timeutil import iso_now

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(now()),
    }
    if extra:
        m.update(extra)
    return m


# Fields that are internal bookkeeping and must never leak into responses.
_HIDDEN = {"_seq"}


def _clean(record):
    if isinstance(record, dict):
        return {k: v for k, v in record.items() if k not in _HIDDEN}
    return record


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data) if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": [_clean(i) for i in items],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
