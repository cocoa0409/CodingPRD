"""Request body / query validation helpers.

Stage 6 of the validation pipeline (shape): required fields present, types
match, enum members valid, integer ranges honored -> ERR_VALIDATION (400).
"""
from flask import request

from errors import raise_err, ERR_VALIDATION
from util import parse_dt


def body_json():
    """Parse the request JSON body. Empty body -> {}. Non-object JSON -> 400."""
    raw = request.get_json(force=True, silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    return raw


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or isinstance(v, bool):
        raise_err(ERR_VALIDATION, "field '%s' is required and must be a string" % field)
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, "field '%s' must be a string" % field)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not _is_int(v):
        raise_err(ERR_VALIDATION, "field '%s' is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_VALIDATION, "field '%s' must be >= %d" % (field, minimum))
    return v


def opt_int(data, field, default=None, minimum=None, nullable=False):
    if field not in data:
        return default
    v = data[field]
    if v is None:
        if nullable:
            return None
        raise_err(ERR_VALIDATION, "field '%s' must be an integer" % field)
    if not _is_int(v):
        raise_err(ERR_VALIDATION, "field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_VALIDATION, "field '%s' must be >= %d" % (field, minimum))
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, "field '%s' is required and must be a boolean" % field)
    return v


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, "field '%s' must be a boolean" % field)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_VALIDATION,
                  "field '%s' must be one of {%s}" % (field, ", ".join(sorted(allowed))))
    return v


def req_dt(data, field):
    if field not in data or data[field] is None:
        raise_err(ERR_VALIDATION, "field '%s' is required" % field)
    return parse_dt(data[field], field)


def opt_dt(data, field):
    if field not in data or data[field] is None:
        return None
    return parse_dt(data[field], field)


def req_list(data, field):
    v = data.get(field)
    if not isinstance(v, list):
        raise_err(ERR_VALIDATION, "field '%s' is required and must be an array" % field)
    return v


def valid_shots(data, field="shots"):
    """shots: list of {colorant_code: string, ounces_128ths: integer}."""
    v = req_list(data, field)
    out = []
    for i, shot in enumerate(v):
        if not isinstance(shot, dict):
            raise_err(ERR_VALIDATION, "field '%s[%d]' must be an object" % (field, i))
        code = shot.get("colorant_code")
        ounces = shot.get("ounces_128ths")
        if not isinstance(code, str):
            raise_err(ERR_VALIDATION, "field '%s[%d].colorant_code' must be a string" % (field, i))
        if not _is_int(ounces):
            raise_err(ERR_VALIDATION,
                      "field '%s[%d].ounces_128ths' must be an integer" % (field, i))
        out.append({"colorant_code": code, "ounces_128ths": ounces})
    return out


def pagination_params():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw, 10)
        except (ValueError, TypeError):
            raise_err(ERR_VALIDATION, "query parameter 'limit' must be an integer")
        if str(limit_raw).strip() != str(limit):
            raise_err(ERR_VALIDATION, "query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "query parameter 'limit' must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw, 10)
        except (ValueError, TypeError):
            raise_err(ERR_VALIDATION, "query parameter 'offset' must be an integer")
        if str(offset_raw).strip() != str(offset):
            raise_err(ERR_VALIDATION, "query parameter 'offset' must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "query parameter 'offset' must be >= 0")
    return limit, offset


def query_enum_filter(name, allowed):
    """Validate an enum-typed query filter value if present; returns value or None."""
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        raise_err(ERR_VALIDATION,
                  "query parameter '%s' must be one of {%s}" % (name, ", ".join(sorted(allowed))))
    return v
