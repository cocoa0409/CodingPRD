"""Body-field declarations and the well-formedness checks used by ladder rung 6.

ENUM ERROR ROUTING (single, explicit rule, applied to every enum-valued body
field without exception):

  The 38-code catalogue in PRD section 5 contains **no** dedicated enum error.
  PRD section 5's ``ERR_VALIDATION`` trigger list names "unknown enum member"
  outright, and ladder rung 6 (PRD section 2.6) covers "every enum, integer,
  boolean, date and datetime field is well formed and inside its declared
  range".  Therefore EVERY enum-membership failure — whether the field is
  spelled out in the PRD narrative or merely implied by an entity constraint —
  is reported as ``ERR_VALIDATION`` with HTTP 400 at rung 6.  No enum field is
  routed anywhere else.
"""

import clock
from errors import ApiError


class Field(object):
    def __init__(
        self,
        name,
        kind,
        required=False,
        values=None,
        minimum=None,
        maximum=None,
        min_len=None,
        max_len=None,
        nullable=False,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.values = values
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.nullable = nullable


def _fail(name):
    raise ApiError("ERR_VALIDATION", "Field '%s' is missing or malformed." % name)


def check_body(body, schema):
    """Validate a request body against a list of Field declarations.

    Returns nothing; raises ERR_VALIDATION on the first offending field, in the
    declaration order of the schema.
    """
    if not isinstance(body, dict):
        body = {}
    for field in schema:
        present = field.name in body and body[field.name] is not None
        if not present:
            if field.required:
                _fail(field.name)
            continue
        value = body[field.name]
        _check_value(field, value)


def _check_value(field, value):
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            _fail(field.name)
        if field.min_len is not None and len(value) < field.min_len:
            _fail(field.name)
        if field.max_len is not None and len(value) > field.max_len:
            _fail(field.name)
    elif kind == "enum":
        if not isinstance(value, str) or value not in field.values:
            _fail(field.name)
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(field.name)
        if field.minimum is not None and value < field.minimum:
            _fail(field.name)
        if field.maximum is not None and value > field.maximum:
            _fail(field.name)
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(field.name)
        if field.minimum is not None and value < field.minimum:
            _fail(field.name)
        if field.maximum is not None and value > field.maximum:
            _fail(field.name)
    elif kind == "boolean":
        if not isinstance(value, bool):
            _fail(field.name)
    elif kind == "date":
        if clock.parse_date(value) is None:
            _fail(field.name)
    elif kind == "datetime":
        if clock.parse_datetime(value) is None:
            _fail(field.name)
    else:  # pragma: no cover - defensive
        _fail(field.name)


def opt(body, name, default=None):
    """Read an optional body value, treating explicit null as absent."""
    if not isinstance(body, dict):
        return default
    value = body.get(name)
    if value is None:
        return default
    return value


def parse_pagination(args):
    """PRD 2.3 / ladder rung 7."""
    limit = _int_param(args, "limit", 10)
    offset = _int_param(args, "offset", 0)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be an integer between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be an integer of at least 0.")
    return limit, offset


def _int_param(args, name, default):
    if name not in args:
        return default
    raw = args.get(name)
    if raw is None or raw == "":
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    text = raw.strip()
    if text.startswith("+") or text.startswith("-"):
        digits = text[1:]
    else:
        digits = text
    if not digits.isdigit():
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    return int(text)
