"""Standard response envelope (PRD §2.2) and resource serialization.

Success: { "meta": { api_request_id, api_request_timestamp, [pagination] },
           "response_type": "object"|"array", "data": {} }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id, message } }
"""
import random
import string

from flask import jsonify

from clock import clock

# Fields that are internal bookkeeping and must never be serialized out.
_PRIVATE = {"_seq", "_applied_amounts", "_suspend_intervals", "_confirm_invoice_id",
            "_delinquent_invoice_id"}


def _request_id():
    alnum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock_now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def clock_now_iso():
    # api_request_timestamp is server-generated ISO8601 UTC w/ 3 fractional digits.
    return clock.iso()


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if k not in _PRIVATE}


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def object_response(rec, status=200):
    return success(public(rec), status=status, response_type="object")


def list_response(records, limit, offset, total_count):
    has_more = (offset + len(records)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(
        [public(r) for r in records],
        status=200,
        response_type="array",
        pagination=pagination,
    )


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
