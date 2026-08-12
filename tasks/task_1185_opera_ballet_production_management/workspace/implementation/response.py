"""Response envelope helpers (PRD section 2.2 — fixed structure)."""

import secrets
import string

from flask import jsonify

from util import now_iso


def _req_id():
    return "req_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def _meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(page_items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(page_items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": page_items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), http_status
