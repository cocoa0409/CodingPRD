"""Response envelope helpers (PRD Section 2.2) and pagination (Section 2.3)."""
import json
import re
from decimal import Decimal

from flask import Response, request

import config
import store

_NUL = "\x00"
_RAW_RE = re.compile(r'"\\u0000D([^"\\]*)\\u0000"')


def _prep(value):
    """Replace Decimals with a sentinel string so they can be re-emitted with
    their exact declared scale as JSON numbers (never strings)."""
    if isinstance(value, Decimal):
        return _NUL + "D" + str(value) + _NUL
    if isinstance(value, dict):
        return {k: _prep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_prep(v) for v in value]
    return value


def dump(payload):
    text = json.dumps(_prep(payload))
    return _RAW_RE.sub(lambda m: m.group(1), text)


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def _respond(payload, status):
    return Response(dump(payload), status=status, mimetype="application/json")


def object_response(data, status=200):
    return _respond({"meta": _meta(), "response_type": "object", "data": data or {}}, status)


def list_response(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return _respond({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, status)


def _as_int(raw, fallback):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback


def pagination():
    limit = _as_int(request.args.get("limit"), config.PAGE_LIMIT_DEFAULT)
    offset = _as_int(request.args.get("offset"), config.PAGE_OFFSET_DEFAULT)
    if limit < config.PAGE_LIMIT_MIN:
        limit = config.PAGE_LIMIT_MIN
    if limit > config.PAGE_LIMIT_MAX:
        limit = config.PAGE_LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    ordered = store.sorted_rows(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)
