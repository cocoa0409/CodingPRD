"""Response envelope helpers.

Every response in the platform shares the same JSON shape. These helpers
build success and error envelopes and centralize the api_request_id and
api_request_timestamp generation.
"""

from flask import jsonify

import state


def _meta(pagination=None):
    meta = {
        "api_request_id": state.gen_req_id(),
        "api_request_timestamp": state.fmt_dt(state.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return success(data, status=201)


def list_response(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return success(items, status=200, pagination=pagination)


def error(status, error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# Convenience helpers for the most common errors.
def auth_required(msg="Missing or unrecognized auth headers."):
    return error(401, "ERR_AUTH_REQUIRED", msg)


def forbidden(msg="Caller is not allowed to perform this action."):
    return error(403, "ERR_FORBIDDEN", msg)


def not_found(msg="Resource does not exist."):
    return error(404, "ERR_NOT_FOUND", msg)


def invalid_state(msg="Resource is not in a state that allows this transition."):
    return error(409, "ERR_INVALID_STATE", msg)


def version_conflict(msg="version mismatch."):
    return error(409, "ERR_VERSION_CONFLICT", msg)


def validation(msg="Input failed validation."):
    return error(422, "ERR_VALIDATION", msg)
