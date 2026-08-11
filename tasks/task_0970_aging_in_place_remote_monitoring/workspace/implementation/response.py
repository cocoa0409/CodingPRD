"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import secrets
import string

from flask import jsonify, request

import db
import errors
from util import iso


def _rid():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(16))


def _meta(pagination=None):
    m = {
        "api_request_id": _rid(),
        "api_request_timestamp": iso(db.clock),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, rtype="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": rtype, "data": data}
    return jsonify(body), status


def error_resp(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_ok(records, serializer):
    """Sort by created_at ascending and apply limit/offset pagination."""
    limit, offset = parse_pagination()
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serializer(r) for r in page], 200, "array", pag)
