"""Response envelope helpers (PRD 2.2 / SCAFFOLD response_envelope)."""
import random
import string

from flask import g, jsonify

import config
from clock import clock
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array_response(items, total_count, limit, offset, status=200):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows):
    """Apply the limit/offset window declared in PRD 2.3."""
    from flask import request

    limit = config.PAGE_LIMIT_DEFAULT
    offset = config.PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < config.PAGE_LIMIT_MIN or limit > config.PAGE_LIMIT_MAX:
            fail(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d."
                % (config.PAGE_LIMIT_MIN, config.PAGE_LIMIT_MAX),
            )
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    total = len(rows)
    return rows[offset : offset + limit], total, limit, offset


def listing(rows, serializer):
    window, total, limit, offset = paginate(rows)
    return array_response([serializer(r) for r in window], total, limit, offset)


def touch(entity, force=True):
    """Refresh updated_at and increment version, at most once per request.

    PRD 2.5: recomputing a derived field counts as a mutation. Entities created
    inside the current request are exempt (they are born at version 1).
    """
    if entity is None:
        return
    created = getattr(g, "created_ids", None)
    if created is not None and entity["id"] in created:
        return
    touched = getattr(g, "touched_ids", None)
    if touched is not None:
        if entity["id"] in touched:
            return
        touched.add(entity["id"])
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = clock.iso()


def mark_created(entity):
    created = getattr(g, "created_ids", None)
    if created is not None:
        created.add(entity["id"])
    return entity
