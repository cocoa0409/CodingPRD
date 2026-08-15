import uuid
from datetime import datetime, timezone

from flask import jsonify


def _meta():
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
    return {"api_request_id": "req_" + uuid.uuid4().hex, "api_request_timestamp": stamp}


def ok(data, rtype="object", status=200, page=None):
    meta = _meta()
    if page is not None:
        meta.update(page)
    body = {"meta": meta, "response_type": rtype, "data": data}
    return jsonify(body), status


def ok_list(items, page):
    return ok(items, rtype="array", status=200, page=page)


def err(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.status
