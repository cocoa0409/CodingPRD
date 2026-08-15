"""Response envelope helpers — exact structure from SCAFFOLD response_envelope / PRD §2.2."""
import secrets

from flask import jsonify

import db
from util import fmt_dt


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_dt(db.now()),
    }
    if pagination:
        m.update(pagination)
    return m


def ok_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def err(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status
