"""Request-shape validation (PRD 2.11 rung 6 -> ERR_INVALID_REQUEST)."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_UNSET = object()


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def raw_body():
    """Parse the JSON body loosely so body FKs (rung 5) can be resolved before
    the full shape pass (rung 6)."""
    data = request.get_data(cache=True)
    if data is None or not data.strip():
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"))
    except Exception:
        invalid("request body must be valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        invalid("request body must be a JSON object")
    return parsed


def parse_instant(value):
    """ISO 8601 UTC instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_decimal(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, Decimal):
        return value
    return None


class Payload(object):
    """Validates a request body against a declared field set."""

    def __init__(self, body, known):
        if not isinstance(body, dict):
            invalid("request body must be a JSON object")
        self.body = body
        self.known = set(known or ())
        for key in body:
            if key not in self.known:
                invalid("unknown field: %s" % key)

    def present(self, name):
        return name in self.body and self.body[name] is not None

    def _pick(self, name, required, default):
        if name not in self.body or self.body[name] is None:
            if required:
                invalid("missing required field: %s" % name)
            return default, False
        return self.body[name], True

    # -- scalars ---------------------------------------------------------
    def string(
        self,
        name,
        required=True,
        default=None,
        min_len=1,
        max_len=None,
        pattern=None,
    ):
        value, got = self._pick(name, required, default)
        if not got:
            return value
        if not isinstance(value, str):
            invalid("%s must be a string" % name)
        if min_len is not None and len(value) < min_len:
            invalid("%s must be at least %d characters" % (name, min_len))
        if max_len is not None and len(value) > max_len:
            invalid("%s must be at most %d characters" % (name, max_len))
        if pattern is not None and not re.fullmatch(pattern, value):
            invalid("%s has an invalid format" % name)
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        value, got = self._pick(name, required, default)
        if not got:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            invalid("%s must be an integer" % name)
        if minimum is not None and value < minimum:
            invalid("%s must be >= %s" % (name, minimum))
        if maximum is not None and value > maximum:
            invalid("%s must be <= %s" % (name, maximum))
        return value

    def decimal(
        self,
        name,
        required=True,
        default=None,
        minimum=None,
        maximum=None,
        exclusive_min=None,
        exclusive_max=None,
        max_decimals=None,
    ):
        value, got = self._pick(name, required, default)
        if not got:
            return value
        number = _to_decimal(value)
        if number is None:
            invalid("%s must be a number" % name)
        if minimum is not None and number < Decimal(str(minimum)):
            invalid("%s must be >= %s" % (name, minimum))
        if maximum is not None and number > Decimal(str(maximum)):
            invalid("%s must be <= %s" % (name, maximum))
        if exclusive_min is not None and number <= Decimal(str(exclusive_min)):
            invalid("%s must be > %s" % (name, exclusive_min))
        if exclusive_max is not None and number >= Decimal(str(exclusive_max)):
            invalid("%s must be < %s" % (name, exclusive_max))
        if max_decimals is not None:
            exponent = number.as_tuple().exponent
            if isinstance(exponent, int) and -exponent > max_decimals:
                invalid("%s may carry at most %d decimals" % (name, max_decimals))
        return number

    def boolean(self, name, required=True, default=None):
        value, got = self._pick(name, required, default)
        if not got:
            return value
        if not isinstance(value, bool):
            invalid("%s must be a boolean" % name)
        return value

    def enum(self, name, values, required=True, default=None):
        value, got = self._pick(name, required, default)
        if not got:
            return value
        if not isinstance(value, str) or value not in values:
            invalid("%s must be one of %s" % (name, ", ".join(sorted(values))))
        return value

    def instant(self, name, required=True, default=None):
        value, got = self._pick(name, required, default)
        if not got:
            return value
        if not isinstance(value, str):
            invalid("%s must be an ISO 8601 UTC instant" % name)
        parsed = parse_instant(value)
        if parsed is None:
            invalid("%s must be an ISO 8601 UTC instant" % name)
        return parsed

    def enum_array(self, name, values, required=True, default=None, min_items=1):
        value, got = self._pick(name, required, default)
        if not got:
            return value
        if not isinstance(value, list):
            invalid("%s must be an array" % name)
        if min_items is not None and len(value) < min_items:
            invalid("%s must contain at least %d entries" % (name, min_items))
        seen = set()
        for item in value:
            if not isinstance(item, str) or item not in values:
                invalid("%s entries must be one of %s" % (name, ", ".join(sorted(values))))
            if item in seen:
                invalid("%s entries must be distinct" % name)
            seen.add(item)
        return list(value)

    def id_ref(self, name, required=True):
        """Reads a foreign-key string without applying rung-6 semantics."""
        if name not in self.body or self.body[name] is None:
            return None
        value = self.body[name]
        if not isinstance(value, str):
            return None
        return value


def body_fk(body, name):
    """Rung 5 helper: returns the raw FK string when it looks like an id."""
    if not isinstance(body, dict):
        return None
    value = body.get(name)
    if isinstance(value, str) and value.strip():
        return value
    return None
