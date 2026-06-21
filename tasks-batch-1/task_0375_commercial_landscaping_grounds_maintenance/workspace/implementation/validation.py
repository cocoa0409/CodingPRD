"""Request-body and pagination validation helpers (PRD 2.3, 2.5, validations p4)."""

from flask import request

import errors


def get_json_body():
    """Parse the JSON body; tolerate empty body (returns {})."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string" % field)
    return val


def require_int(body, field, *, gt=None, ge=None):
    val = body.get(field)
    # bool is a subclass of int; reject it explicitly.
    if not isinstance(val, int) or isinstance(val, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    if gt is not None and not (val > gt):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be > %s" % (field, gt))
    if ge is not None and not (val >= ge):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (field, ge))
    return val


def require_enum(body, field, members):
    val = body.get(field)
    if val not in members:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Field '%s' must be one of %s" % (field, sorted(members)))
    return val


def optional_enum(body, field, members, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if val not in members:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Field '%s' must be one of %s" % (field, sorted(members)))
    return val


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean" % field)
    return val


def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0 (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset
