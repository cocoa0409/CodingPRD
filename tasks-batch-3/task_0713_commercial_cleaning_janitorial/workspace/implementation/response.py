"""Response envelope helpers (PRD §2.2). Verbatim field names from scaffold §1.0."""
import random
import string

from flask import jsonify

from db import real_utc_now_iso

# Internal bookkeeping keys never serialized to clients.
_HIDDEN = {"_kind", "_seq"}


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphanum) for _ in range(20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": real_utc_now_iso()}
    if extra:
        m.update(extra)
    return m


def public(rec):
    """Strip internal fields from a record before serialization."""
    if isinstance(rec, dict):
        return {k: v for k, v in rec.items() if k not in _HIDDEN}
    return rec


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(data) if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array",
        "data": [public(i) for i in items],
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
