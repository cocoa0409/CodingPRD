"""Response envelope helpers (PRD Section 2.2, 2.3)."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from timeutil import fmt_iso

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_iso(datetime.now(timezone.utc)),
    }


def to_json_value(value):
    if isinstance(value, datetime):
        return fmt_iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: to_json_value(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [to_json_value(v) for v in value]
    return value


def public(entity):
    """Serialise an entity: drop private keys, format datetimes."""
    if entity is None:
        return None
    return {k: to_json_value(v) for k, v in entity.items() if not k.startswith("_")}


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {} if data is None else public(data) if isinstance(data, dict) else data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(item) for item in page],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
