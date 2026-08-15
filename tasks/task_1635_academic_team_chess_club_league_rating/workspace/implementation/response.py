"""Response envelope helpers — exact structure from scaffold response_envelope."""
import secrets
import string
from flask import jsonify
from db import now_iso
from errors import ApiError, invalid_request


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_array(items, status=200, paginated=False, limit=None, offset=0, total_count=None):
    meta = _meta()
    if paginated:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


def parse_pagination(args):
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not str(raw_limit).strip().lstrip("+").isdigit():
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit out of range (1..100)")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if str(raw_offset).strip() != str(offset) and not str(raw_offset).strip().lstrip("+").isdigit():
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Sort by (created_at, _seq) ascending and apply limit/offset."""
    limit, offset = parse_pagination(args)
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def num_out(x):
    """Emit integer when the value is whole (half-point arithmetic stays exact)."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x
