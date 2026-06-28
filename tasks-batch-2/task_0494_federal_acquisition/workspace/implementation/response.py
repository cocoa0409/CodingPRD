"""Standard response envelope (PRD §2.2)."""
import random
import string

from flask import jsonify

from clock import clock, format_iso8601_ms

# Public (serializable) fields exclude internal bookkeeping keys: any key
# beginning with an underscore (e.g. _seq, _expires_dt) is internal-only.


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso8601_ms(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def public(entity):
    """Strip internal keys for serialization."""
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def object_response(entity, status=200):
    return success(public(entity), status=status, response_type="object")


def list_response(items, limit, offset, total_count):
    data = [public(e) for e in items]
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(data, status=200, response_type="array", pagination=pagination)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
