"""Request-body schema validation (rejection precedence 3) and pagination
parameter validation (rejection precedence 4), PRD 2.9.
"""

from flask import request

from core import dec, parse_date, parse_iso8601
from errors import ApiError


def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


class Field(object):
    """One declared input field of an endpoint's schema."""

    def __init__(self, name, kind, required=True, members=None, minimum=None,
                 maximum=None, exclusive_minimum=None, min_length=None,
                 max_length=None, item_fields=None, non_empty_array=False,
                 default=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.members = members
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_minimum = exclusive_minimum
        self.min_length = min_length
        self.max_length = max_length
        self.item_fields = item_fields
        self.non_empty_array = non_empty_array
        self.default = default

    def coerce(self, value):
        name = self.name
        kind = self.kind

        if kind == "string":
            if not isinstance(value, str):
                _fail("`%s` must be a string." % name)
            if self.min_length is not None and len(value) < self.min_length:
                _fail("`%s` must be at least %d characters." % (name, self.min_length))
            if self.max_length is not None and len(value) > self.max_length:
                _fail("`%s` must be at most %d characters." % (name, self.max_length))
            return value

        if kind == "enum":
            if not isinstance(value, str) or value not in self.members:
                _fail("`%s` must be one of %s." % (name, ", ".join(self.members)))
            return value

        if kind == "boolean":
            if not isinstance(value, bool):
                _fail("`%s` must be a boolean." % name)
            return value

        if kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                _fail("`%s` must be an integer." % name)
            if self.minimum is not None and value < self.minimum:
                _fail("`%s` must be >= %s." % (name, self.minimum))
            if self.maximum is not None and value > self.maximum:
                _fail("`%s` must be <= %s." % (name, self.maximum))
            return value

        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _fail("`%s` must be a number." % name)
            number = dec(value)
            if self.exclusive_minimum is not None and number <= dec(self.exclusive_minimum):
                _fail("`%s` must be greater than %s." % (name, self.exclusive_minimum))
            if self.minimum is not None and number < dec(self.minimum):
                _fail("`%s` must be >= %s." % (name, self.minimum))
            if self.maximum is not None and number > dec(self.maximum):
                _fail("`%s` must be <= %s." % (name, self.maximum))
            return number

        if kind == "datetime":
            parsed = parse_iso8601(value)
            if parsed is None:
                _fail("`%s` must be a valid ISO 8601 UTC instant." % name)
            return parsed

        if kind == "date":
            parsed = parse_date(value)
            if parsed is None:
                _fail("`%s` must be a calendar date in YYYY-MM-DD form." % name)
            return value

        if kind == "enum_array":
            if not isinstance(value, list):
                _fail("`%s` must be an array." % name)
            if self.non_empty_array and len(value) == 0:
                _fail("`%s` must not be empty." % name)
            for element in value:
                if not isinstance(element, str) or element not in self.members:
                    _fail("every element of `%s` must be one of %s."
                          % (name, ", ".join(self.members)))
            return list(value)

        if kind == "object_array":
            if not isinstance(value, list):
                _fail("`%s` must be an array." % name)
            if self.non_empty_array and len(value) == 0:
                _fail("`%s` must not be empty." % name)
            out = []
            for element in value:
                if not isinstance(element, dict):
                    _fail("every element of `%s` must be an object." % name)
                out.append(validate_object(element, self.item_fields, name))
            return out

        _fail("unsupported field kind for `%s`." % name)


def validate_object(raw, fields, container=None):
    allowed = set(f.name for f in fields)
    for key in raw.keys():
        if key not in allowed:
            _fail("unknown field `%s`%s." % (key, " in " + container if container else ""))
    out = {}
    for field in fields:
        if field.name not in raw or raw[field.name] is None:
            if field.required:
                _fail("`%s` is required." % field.name)
            out[field.name] = field.default
            continue
        out[field.name] = field.coerce(raw[field.name])
    return out


def validate_body(fields):
    """Validate the JSON body against the endpoint's declared input schema."""
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        _fail("request body must be a JSON object.")
    return validate_object(raw, fields)


def require_window(payload, start_key, end_key):
    """Every window's end must be strictly after its start (PRD 2.9 rule 3)."""
    start = payload.get(start_key)
    end = payload.get(end_key)
    if start is not None and end is not None and not end > start:
        _fail("`%s` must be strictly later than `%s`." % (end_key, start_key))


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
def _parse_int_param(raw):
    text = raw.strip()
    if text == "":
        return None
    negative = text.startswith("-")
    body = text[1:] if (negative or text.startswith("+")) else text
    if not body.isdigit():
        return None
    value = int(body)
    return -value if negative else value


def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        parsed = _parse_int_param(raw_limit)
        if parsed is None or parsed < 1 or parsed > 100:
            raise ApiError("ERR_PAGINATION_INVALID",
                           "`limit` must be an integer within 1 and 100 inclusive.")
        limit = parsed
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        parsed = _parse_int_param(raw_offset)
        if parsed is None or parsed < 0:
            raise ApiError("ERR_PAGINATION_INVALID",
                           "`offset` must be an integer greater than or equal to 0.")
        offset = parsed
    return limit, offset


def apply_page(rows, limit, offset):
    return rows[offset:offset + limit]
