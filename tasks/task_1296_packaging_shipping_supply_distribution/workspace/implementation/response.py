"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""
import uuid
from datetime import datetime, timezone

from flask import jsonify

from errors import err_invalid_request


def _meta(pagination=None):
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": ts,
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit/offset per scaffold defaults: limit 10 (min 1, max 100), offset 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("Query parameter 'limit' must be an integer.")
        if str(raw_limit).strip() != str(limit) or isinstance(raw_limit, bool):
            # reject things like '1.5'
            try:
                if float(raw_limit) != limit:
                    raise err_invalid_request("Query parameter 'limit' must be an integer.")
            except ValueError:
                raise err_invalid_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise err_invalid_request("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("Query parameter 'offset' must be an integer.")
        try:
            if float(raw_offset) != offset:
                raise err_invalid_request("Query parameter 'offset' must be an integer.")
        except ValueError:
            raise err_invalid_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise err_invalid_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
