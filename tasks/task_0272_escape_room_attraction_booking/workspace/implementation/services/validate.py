"""Shared validation helpers: typed body-field extraction, pagination, OCC."""
from flask import request

import errors
from errors import err


def _bad(msg):
    raise err(errors.ERR_INVALID_REQUEST, msg)


def req_str(body, name):
    if name not in body or body[name] is None:
        _bad("Missing required field: " + name)
    v = body[name]
    if not isinstance(v, str) or v == "":
        _bad("Field must be a non-empty string: " + name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        _bad("Field must be a string: " + name)
    return v


def req_int(body, name, min_v=None, max_v=None):
    if name not in body or body[name] is None:
        _bad("Missing required field: " + name)
    v = body[name]
    # bool is a subclass of int — reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field must be an integer: " + name)
    if min_v is not None and v < min_v:
        _bad("Field below minimum (%s): %s" % (min_v, name))
    if max_v is not None and v > max_v:
        _bad("Field above maximum (%s): %s" % (max_v, name))
    return v


def opt_int(body, name, default=None, min_v=None, max_v=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field must be an integer: " + name)
    if min_v is not None and v < min_v:
        _bad("Field below minimum (%s): %s" % (min_v, name))
    if max_v is not None and v > max_v:
        _bad("Field above maximum (%s): %s" % (max_v, name))
    return v


def req_number(body, name, min_v=None, max_v=None):
    if name not in body or body[name] is None:
        _bad("Missing required field: " + name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field must be a number: " + name)
    if min_v is not None and v < min_v:
        _bad("Field below minimum (%s): %s" % (min_v, name))
    if max_v is not None and v > max_v:
        _bad("Field above maximum (%s): %s" % (max_v, name))
    return v


def opt_number(body, name, default=None, min_v=None, max_v=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field must be a number: " + name)
    if min_v is not None and v < min_v:
        _bad("Field below minimum (%s): %s" % (min_v, name))
    if max_v is not None and v > max_v:
        _bad("Field above maximum (%s): %s" % (max_v, name))
    return v


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        _bad("Field must be a boolean: " + name)
    return v


def req_enum(body, name, choices):
    v = req_str(body, name)
    if v not in choices:
        _bad("Invalid enum value for %s: %s" % (name, v))
    return v


def parse_pagination():
    """Read limit/offset query params (PRD §2.3). Out-of-range ->
    ERR_VALIDATION_PAGINATION (422)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION_PAGINATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_VALIDATION_PAGINATION, "limit out of range 1..100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION_PAGINATION, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_VALIDATION_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at asc (PRD §2.3), then slice."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def check_occ(body, field, current_version, stale_spec):
    """Validate an OCC version field. The field is required (PRD lists it as
    a required input on these endpoints). Mismatch -> stale_spec error."""
    expected = req_int(body, field)
    if expected != current_version:
        raise err(stale_spec, "Stale version on %s" % field)
    return expected
