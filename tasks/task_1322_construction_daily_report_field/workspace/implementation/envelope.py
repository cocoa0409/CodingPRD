import uuid
import json
from flask import jsonify, Response
from clock import clock
from util import fmt_dt


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(clock.now()),
    }


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def success_empty(status=204):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return Response(
        json.dumps(body), status=status, mimetype="application/json"
    )


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status
