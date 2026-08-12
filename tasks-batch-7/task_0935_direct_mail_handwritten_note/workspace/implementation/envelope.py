"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""
from flask import jsonify

import store
from errors import ApiError

_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _request_id():
    n = store.db.next_request_id()
    out = []
    for _ in range(20):
        out.append(_ALNUM[n % len(_ALNUM)])
        n //= len(_ALNUM)
    return "req_" + "".join(reversed(out))


def _meta():
    return {
        "api_request_id": _request_id(),
        # The logical clock is the only clock this service reads.
        "api_request_timestamp": store.render_instant(store.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paginate(rows, args):
    """Apply the PRD 2.3 limit/offset contract.

    limit and offset are not members of rung 8's closed numeric list, so an
    out-of-range or non-integer value is reported as ERR_VALIDATION at rung 6
    (PRD 2.6: "every other malformed value is reported ... as ERR_VALIDATION").
    """
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be at least 0.")
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total


def sort_rows(rows):
    """PRD 2.3: collections are always sorted by created_at ascending.

    Ids are minted monotonically, so the id tie-break preserves creation order
    when several rows share the logical clock's coarse instant.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))
