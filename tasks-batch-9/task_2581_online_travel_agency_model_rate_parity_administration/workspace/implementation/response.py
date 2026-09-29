"""Response envelope helpers (PRD §2.2 / SCAFFOLD §1.0)."""
import datetime as _dt
import random
import string

from flask import jsonify

import store

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_now_iso():
    now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _wall_now_iso()}
    if extra:
        meta.update(extra)
    return meta


def obj(row, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": store.public(row) if row else {}}
    return jsonify(body), status


def empty(status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": {}}), status


def collection(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [store.public(r) for r in window],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
