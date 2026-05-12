"""Common helpers: pagination, OCC, body parsing."""

from flask import request

import clock
import errors


PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def parse_pagination():
    args = request.args
    limit = args.get("limit", PAGINATION_DEFAULTS["limit"])
    offset = args.get("offset", PAGINATION_DEFAULTS["offset"])

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "limit must be an integer.")
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "offset must be an integer.")

    if limit < PAGINATION_DEFAULTS["min"] or limit > PAGINATION_DEFAULTS["max"]:
        errors.raise_error(
            errors.ERR_QUANTITY_OUT_OF_RANGE,
            f"limit must be between {PAGINATION_DEFAULTS['min']} and {PAGINATION_DEFAULTS['max']}.",
        )
    if offset < 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset : offset + limit], total


def get_json_body():
    """Return request JSON body as dict, or empty dict if missing."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Request body must be a JSON object.")
    return body


def check_occ(entity, supplied_version):
    """Raise ERR_STALE_VERSION if supplied_version is provided and mismatches."""
    if supplied_version is None:
        return
    try:
        v = int(supplied_version)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_STALE_VERSION, "version must be an integer.")
    if v != entity.get("version"):
        errors.raise_error(errors.ERR_STALE_VERSION, "version does not match server-side value.")


def bump(entity):
    """Refresh updated_at and bump version. Returns entity for chaining."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 0) + 1
    return entity


def common_create():
    """Return a dict with common create fields (created_at, updated_at, version=1)."""
    now = clock.now()
    return {"created_at": now, "updated_at": now, "version": 1}
