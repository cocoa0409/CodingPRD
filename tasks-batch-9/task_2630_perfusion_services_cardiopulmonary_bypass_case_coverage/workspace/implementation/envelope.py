"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify

REQUEST_ID_PREFIX = "req_"
REQUEST_ID_ALPHABET = string.ascii_uppercase + string.digits
REQUEST_ID_LENGTH = 20

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    body = "".join(random.choice(REQUEST_ID_ALPHABET) for _ in range(REQUEST_ID_LENGTH))
    return REQUEST_ID_PREFIX + body


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits.

    PRD 2.4 declares this format for `created_at` and `updated_at`, and PRD 2.2
    for `api_request_timestamp`.
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_instant(dt):
    """ISO 8601 UTC preserving the instant exactly as it was expressed.

    Domain instants are either read from the logical clock -- which PRD 2.5
    says "reads exactly `2026-08-01T00:00:00Z`" before it is ever advanced and
    thereafter echoes the `current_utc` the caller set -- or supplied verbatim
    by the caller. PRD 2.4 scopes the three-fractional-digit rule to
    `created_at` and `updated_at`, so these fields are not reformatted.
    """
    if dt is None:
        return None
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta():
    from store import db

    return {"api_request_id": _request_id(), "api_request_timestamp": iso(db.now())}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def fail(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
