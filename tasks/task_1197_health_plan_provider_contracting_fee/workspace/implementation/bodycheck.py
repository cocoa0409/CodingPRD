"""Request-body conformance validation (validation tier 1, ERR_INVALID_REQUEST).

Checks required fields, types, enum membership, conditionally required
fields, and rejects undeclared fields — all before any auth/existence/state
evaluation, per the PRD section 2.10 ordering.
"""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bad(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def parse_date(value, field="date"):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise _bad(f"Field {field} must be an ISO 8601 date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _bad(f"Field {field} is not a valid calendar date.")


def parse_datetime_value(value, field="to_iso8601"):
    if not isinstance(value, str):
        raise _bad(f"Field {field} must be an ISO 8601 datetime string.")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise _bad(f"Field {field} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Spec:
    def __init__(self, kind, values=None):
        self.kind = kind
        self.values = values


STR = Spec("str")
INT = Spec("int")
BOOL = Spec("bool")
DATE = Spec("date")
DATETIME = Spec("datetime")


def ENUM(*values):
    return Spec("enum", set(values))


def _check_type(name, value, spec):
    kind = spec.kind
    if kind == "str":
        if not isinstance(value, str):
            raise _bad(f"Field {name} must be a string.")
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _bad(f"Field {name} must be an integer.")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise _bad(f"Field {name} must be a boolean.")
    elif kind == "date":
        parse_date(value, name)
    elif kind == "datetime":
        parse_datetime_value(value, name)
    elif kind == "enum":
        if not isinstance(value, str) or value not in spec.values:
            raise _bad(f"Field {name} must be one of {sorted(spec.values)}.")


def get_body():
    body = request.get_json(silent=True, force=True)
    if body is None:
        raw = request.get_data()
        if raw and raw.strip():
            raise _bad("Request body is not valid JSON.")
        body = {}
    if not isinstance(body, dict):
        raise _bad("Request body must be a JSON object.")
    return body


def validate_body(schema):
    """schema: {field: (Spec, required: bool)}. Returns a cleaned dict where
    absent optional fields map to None. Undeclared fields are rejected."""
    body = get_body()
    for key in body:
        if key not in schema:
            raise _bad(f"Undeclared field in request body: {key}.")
    out = {}
    for name, (spec, required) in schema.items():
        if name in body and body[name] is not None:
            _check_type(name, body[name], spec)
            out[name] = body[name]
        elif required:
            raise _bad(f"Missing required field: {name}.")
        else:
            out[name] = None
    return out


def require_present(data, name):
    """Conditionally-required field gate (still tier 1 conformance)."""
    if data.get(name) is None:
        raise _bad(f"Missing required field: {name}.")
    return data[name]


def forbid_present(data, name):
    if data.get(name) is not None:
        raise _bad(f"Field {name} must not be supplied for this resource shape.")
