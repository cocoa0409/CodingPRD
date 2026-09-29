"""Request body and pagination validation (PRD 2.3, 2.10 step "only then is the
request body examined")."""

import json
from decimal import Decimal as D
from decimal import InvalidOperation

from flask import request

import errors
from timeutil import Instant, parse_iso, parse_iso_date

_MISSING = object()


def _raw_body():
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        return {}
    try:
        parsed = json.loads(data, parse_float=D)
    except Exception:
        raise errors.invalid_request("Request body must be a JSON object.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return parsed


class Body:
    """A parsed POST body with required/unknown-field discipline already applied."""

    def __init__(self, required=(), optional=()):
        self.data = _raw_body()
        allowed = set(required) | set(optional)
        for key in self.data:
            if key not in allowed:
                raise errors.invalid_request("Unknown field '%s'." % key)
        for key in required:
            if self.data.get(key, None) is None:
                raise errors.invalid_request("Field '%s' is required." % key)

    # ------------------------------------------------------------- primitives
    def present(self, key):
        return self.data.get(key, None) is not None

    def raw(self, key):
        return self.data.get(key, None)

    def string(self, key, min_len=None, max_len=None, default=None):
        value = self.data.get(key, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, str):
            raise errors.invalid_request("Field '%s' must be a string." % key)
        if min_len is not None and len(value) < min_len:
            raise errors.invalid_request(
                "Field '%s' must be at least %d characters." % (key, min_len))
        if max_len is not None and len(value) > max_len:
            raise errors.invalid_request(
                "Field '%s' must be at most %d characters." % (key, max_len))
        return value

    def integer(self, key, minimum=None, maximum=None, default=None):
        value = self.data.get(key, _MISSING)
        if value is _MISSING or value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise errors.invalid_request("Field '%s' must be an integer." % key)
        if minimum is not None and value < minimum:
            raise errors.invalid_request(
                "Field '%s' must be at least %s." % (key, minimum))
        if maximum is not None and value > maximum:
            raise errors.invalid_request(
                "Field '%s' must be at most %s." % (key, maximum))
        return value

    def number(self, key, minimum=None, maximum=None, default=None):
        value = self.data.get(key, _MISSING)
        if value is _MISSING or value is None:
            return default
        value = as_decimal(value, key)
        if minimum is not None and value < minimum:
            raise errors.invalid_request(
                "Field '%s' must be at least %s." % (key, minimum))
        if maximum is not None and value > maximum:
            raise errors.invalid_request(
                "Field '%s' must be at most %s." % (key, maximum))
        return value

    def boolean(self, key, default=None):
        value = self.data.get(key, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, bool):
            raise errors.invalid_request("Field '%s' must be a boolean." % key)
        return value

    def enum(self, key, allowed, default=None):
        value = self.string(key)
        if value is None:
            return default
        if value not in allowed:
            raise errors.invalid_request(
                "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
        return value

    def instant(self, key, default=None):
        value = self.data.get(key, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, str):
            raise errors.invalid_request(
                "Field '%s' must be an ISO 8601 UTC timestamp." % key)
        try:
            parse_iso(value)
        except ValueError:
            raise errors.invalid_request(
                "Field '%s' must be an ISO 8601 UTC timestamp." % key)
        return Instant.from_input(value)

    def date(self, key, default=None):
        """A date-shaped input: a bare ``YYYY-MM-DD`` or a full ISO 8601 instant."""
        value = self.data.get(key, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, str):
            raise errors.invalid_request(
                "Field '%s' must be an ISO 8601 date." % key)
        try:
            dt = parse_iso_date(value)
        except ValueError:
            raise errors.invalid_request(
                "Field '%s' must be an ISO 8601 date." % key)
        return Instant(dt, value.strip())

    def array(self, key, default=None):
        value = self.data.get(key, _MISSING)
        if value is _MISSING or value is None:
            return default
        if not isinstance(value, list):
            raise errors.invalid_request("Field '%s' must be an array." % key)
        return value


def as_decimal(value, key):
    if isinstance(value, bool):
        raise errors.invalid_request("Field '%s' must be a number." % key)
    if isinstance(value, D):
        return value
    if isinstance(value, int):
        return D(value)
    if isinstance(value, float):  # pragma: no cover - parse_float=Decimal
        return D(repr(value))
    raise errors.invalid_request("Field '%s' must be a number." % key)


def decimal_or_none(value, key):
    if value is None:
        return None
    try:
        return as_decimal(value, key)
    except InvalidOperation:  # pragma: no cover
        raise errors.invalid_request("Field '%s' must be a number." % key)


# ------------------------------------------------------------------ pagination
def pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    if raw_limit is not None:
        limit = _positive_int(raw_limit)
        if limit is None or limit < 1 or limit > 100:
            raise _bad_pagination()
    if raw_offset is not None:
        offset = _positive_int(raw_offset)
        if offset is None or offset < 0:
            raise _bad_pagination()
    return limit, offset


def _positive_int(text):
    text = text.strip()
    if text == "":
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def _bad_pagination():
    from errors import ApiError
    return ApiError("ERR_INVALID_PAGINATION", 400,
                    "limit must be an integer in 1..100 and offset an integer >= 0.")


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def query_bool(name):
    """Filter parameters are additive; an unrecognised value simply matches nothing."""
    raw = request.args.get(name, None)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return _NO_MATCH


_NO_MATCH = object()
NO_MATCH = _NO_MATCH
