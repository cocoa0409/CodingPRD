"""Shared route helpers: body parsing, pagination, serialization."""
from flask import request

import errors


def query_arg(name):
    """Return a query-string parameter value, or None if absent."""
    return request.args.get(name)


def get_json_body():
    """Return the parsed JSON body as a dict. Treat missing/empty body as {}.

    A body that is present but not a JSON object raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def parse_pagination():
    """Parse limit/offset from query string per PRD §2.3.

    limit: default 10, min 1, max 100.
    offset: default 0, min 0.
    Out-of-bounds or non-integer -> ERR_INVALID_REQUEST (422).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(rows, limit, offset):
    """Sort rows by created_at ascending (stable via insertion seq) and slice."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def require_fields(body, fields):
    """Ensure each named field is present (not missing) in the body.

    Missing required field -> ERR_INVALID_REQUEST (422).
    """
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request("Missing required field: %s" % f)


def as_number(value, field, *, allow_zero=True, positive=False):
    """Validate a numeric (int/float) field. Bool is rejected. Returns the value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request("%s must be a number." % field)
    if positive and not value > 0:
        raise errors.invalid_request("%s must be > 0." % field)
    if not positive and not allow_zero and value <= 0:
        raise errors.invalid_request("%s must be > 0." % field)
    return value


def as_int(value, field, *, minimum=None):
    """Validate an integer field (bool rejected). Returns the value."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise errors.invalid_request("%s must be >= %s." % (field, minimum))
    return value


def as_enum(value, field, choices):
    """Validate an enum membership. Returns the value."""
    if not isinstance(value, str) or value not in choices:
        raise errors.invalid_request("%s must be one of %s." % (field, sorted(choices)))
    return value


def as_string(value, field):
    """Validate a non-empty string field. Returns the value."""
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("%s must be a non-empty string." % field)
    return value
