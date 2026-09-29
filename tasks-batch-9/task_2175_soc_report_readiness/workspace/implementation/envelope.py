"""Response envelope helpers (PRD 2.2)."""
import random
import string

from flask import jsonify

import store

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
    return {"api_request_id": rid, "api_request_timestamp": store.now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, status=200):
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status


def ok_page(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(items) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
