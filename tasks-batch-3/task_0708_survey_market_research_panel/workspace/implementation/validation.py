"""Body / query validation helpers (PRD §2.5: ERR_VALIDATION 400 on a missing
required field, wrong type, or enum value outside the allowed set; §2.3 pagination).
"""
from flask import request

import errors


def get_json_body():
    """Parse the JSON body; a non-object / unparseable body is ERR_VALIDATION."""
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            # Allow empty body for transition endpoints that take no input.
            if not (request.data or b"").strip():
                return {}
            errors.fail(errors.ERR_VALIDATION, "Request body must be valid JSON")
        if not isinstance(data, dict):
            errors.fail(errors.ERR_VALIDATION, "Request body must be a JSON object")
        return data
    return {}


def require_str(body, field):
    if field not in body:
        errors.fail(errors.ERR_VALIDATION, "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, str) or val == "":
        errors.fail(errors.ERR_VALIDATION, "Field %s must be a non-empty string" % field)
    return val


def require_present_str(body, field):
    """Field must be present and a string, but MAY be the empty string.

    Used where emptiness is allowed at write time and enforced by a later
    business precondition (e.g. irb_protocol_number, non-empty only at launch).
    """
    if field not in body:
        errors.fail(errors.ERR_VALIDATION, "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, str):
        errors.fail(errors.ERR_VALIDATION, "Field %s must be a string" % field)
    return val


def require_present_str(body, field):
    """Require the field be present and a string, but allow an empty value.

    Used for fields the PRD requires the caller to supply but whose non-empty
    constraint is enforced later (e.g. irb_protocol_number is supplied at study
    creation per §3.1 but is only required non-empty at launch).
    """
    if field not in body:
        errors.fail(errors.ERR_VALIDATION, "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, str):
        errors.fail(errors.ERR_VALIDATION, "Field %s must be a string" % field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        errors.fail(errors.ERR_VALIDATION, "Field %s must be a string" % field)
    return val


def require_int(body, field, minimum=None):
    if field not in body:
        errors.fail(errors.ERR_VALIDATION, "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_VALIDATION, "Field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        errors.fail(errors.ERR_VALIDATION,
                    "Field %s must be >= %s" % (field, minimum))
    return val


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_VALIDATION, "Field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        errors.fail(errors.ERR_VALIDATION,
                    "Field %s must be >= %s" % (field, minimum))
    return val


def require_bool(body, field):
    if field not in body:
        errors.fail(errors.ERR_VALIDATION, "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, bool):
        errors.fail(errors.ERR_VALIDATION, "Field %s must be a boolean" % field)
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        errors.fail(errors.ERR_VALIDATION,
                    "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def pagination_params():
    """limit defaults to 10 [1..100]; offset defaults to 0 [>=0] (PRD §2.3).

    An out-of-range or non-integer value is rejected with ERR_VALIDATION (400).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.fail(errors.ERR_VALIDATION, "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            errors.fail(errors.ERR_VALIDATION, "offset must be >= 0")

    return limit, offset


def paginate(records):
    """Sort by created_at ascending (stable on insertion seq), then window."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total_count = len(ordered)
    window = ordered[offset:offset + limit]
    return window, limit, offset, total_count
