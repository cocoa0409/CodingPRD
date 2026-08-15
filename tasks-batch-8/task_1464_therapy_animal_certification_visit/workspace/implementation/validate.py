"""Request-body schema validation (pipeline category 5).

Required fields present, types match, enums in declared sets, unknown fields
rejected, date/datetime sanity. Raises ERR_INVALID_REQUEST / ERR_INVALID_ENUM_VALUE.
"""
from errors import err_invalid_request, err_invalid_enum
from util import parse_date, parse_datetime


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def validate_body(body, spec, partial=False):
    """Validate `body` against `spec`.

    spec: {field: (kind, required, enum_or_None)}
      kind: 'string', 'integer', 'number', 'date', 'datetime', 'array', 'boolean'
    partial=True (PATCH): required fields may be absent.
    Returns a dict of validated values (only fields present).
    """
    out = {}
    for key in body:
        if key not in spec:
            raise err_invalid_request("Unknown field: %s" % key)
    for field, (kind, required, enum) in spec.items():
        if field not in body or body[field] is None:
            if required and not partial:
                raise err_invalid_request("Missing required field: %s" % field)
            continue
        val = body[field]
        if kind == "string":
            if not isinstance(val, str) or isinstance(val, bool):
                raise err_invalid_request("Field '%s' must be a string" % field)
        elif kind == "integer":
            if not isinstance(val, int) or isinstance(val, bool):
                raise err_invalid_request("Field '%s' must be an integer" % field)
        elif kind == "number":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise err_invalid_request("Field '%s' must be a number" % field)
        elif kind == "boolean":
            if not isinstance(val, bool):
                raise err_invalid_request("Field '%s' must be a boolean" % field)
        elif kind == "array":
            if not isinstance(val, list):
                raise err_invalid_request("Field '%s' must be an array" % field)
        elif kind == "date":
            if not isinstance(val, str):
                raise err_invalid_request("Field '%s' must be an ISO date string" % field)
            try:
                parse_date(val)
            except ValueError:
                raise err_invalid_request("Field '%s' must be an ISO date string" % field)
        elif kind == "datetime":
            if not isinstance(val, str):
                raise err_invalid_request("Field '%s' must be an ISO 8601 datetime string" % field)
            try:
                parse_datetime(val)
            except ValueError:
                raise err_invalid_request("Field '%s' must be an ISO 8601 datetime string" % field)
        if enum is not None and val not in enum:
            raise err_invalid_enum(field, val)
        out[field] = val
    return out
