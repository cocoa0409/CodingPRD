"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

from errors import err
from store import real_now_iso

ALPHANUM = string.ascii_uppercase + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choice(ALPHANUM) for _ in range(20)),
        "api_request_timestamp": real_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, page_meta, status=200):
    body = {"meta": _meta(page_meta), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


def _int_arg(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise err("ERR_INVALID_REQUEST")
    try:
        return int(text)
    except ValueError:
        raise err("ERR_INVALID_REQUEST")


def read_pagination():
    limit = _int_arg(request.args.get("limit"))
    offset = _int_arg(request.args.get("offset"))
    if limit is None:
        limit = DEFAULT_LIMIT
    if offset is None:
        offset = DEFAULT_OFFSET
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(records, serializer):
    """Window a list of already-sorted records and build the page meta."""
    limit, offset = read_pagination()
    total = len(records)
    window = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return ok_list([serializer(r) for r in window], meta)
