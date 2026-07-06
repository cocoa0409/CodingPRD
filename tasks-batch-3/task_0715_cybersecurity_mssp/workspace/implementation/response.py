"""Response envelope helpers and money/number precision."""
from decimal import Decimal, ROUND_HALF_UP
from flask import jsonify

from store import new_request_id, fmt_iso, now_clock


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_iso(now_clock()),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


def round2(value):
    """Round to 2 decimals HALF_UP; return a float carrying 2-decimal precision."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)
