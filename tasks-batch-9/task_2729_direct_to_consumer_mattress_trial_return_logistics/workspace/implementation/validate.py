"""Request body / query-string shape validation (precedence step 3)."""
from flask import request

from errors import invalid
from util import parse_date, parse_datetime

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0

_MISSING = object()


def _json_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    body = request.get_json(force=True, silent=True)
    if body is None:
        raise invalid("request body is not valid JSON")
    if not isinstance(body, dict):
        raise invalid("request body must be a JSON object")
    return body


class Fields(object):
    """Reads a request body against a closed set of declared input fields."""

    def __init__(self, *allowed):
        self.body = _json_body()
        for key in self.body:
            if key not in allowed:
                raise invalid("unknown field %s" % key)

    def present(self, name):
        return name in self.body and self.body[name] is not None

    def _absent(self, name, required, default):
        if required:
            raise invalid("missing required field %s" % name)
        return default

    def string(self, name, required=True, default=None, non_empty=True):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        if not isinstance(value, str):
            raise invalid("%s must be a string" % name)
        if non_empty and value.strip() == "":
            raise invalid("%s must be a non-empty string" % name)
        return value

    def integer(self, name, required=True, default=None, minimum=None,
                maximum=None):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("%s must be an integer" % name)
        if minimum is not None and value < minimum:
            raise invalid("%s must be at least %d" % (name, minimum))
        if maximum is not None and value > maximum:
            raise invalid("%s must be at most %d" % (name, maximum))
        return value

    def number(self, name, required=True, default=None, minimum=None,
               exclusive_minimum=None):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid("%s must be a number" % name)
        if isinstance(value, float) and value != value:
            raise invalid("%s must be a number" % name)
        if minimum is not None and value < minimum:
            raise invalid("%s must be at least %s" % (name, minimum))
        if exclusive_minimum is not None and value <= exclusive_minimum:
            raise invalid("%s must be greater than %s" % (name,
                                                          exclusive_minimum))
        return value

    def boolean(self, name, required=True, default=None):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        if not isinstance(value, bool):
            raise invalid("%s must be a boolean" % name)
        return value

    def enum(self, name, choices, required=True, default=None):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        if not isinstance(value, str) or value not in choices:
            raise invalid("%s must be one of %s" % (name, ", ".join(choices)))
        return value

    def enum_list(self, name, choices, required=True, default=None):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        if not isinstance(value, list) or not value:
            raise invalid("%s must be a non-empty array" % name)
        out = []
        for item in value:
            if not isinstance(item, str) or item not in choices:
                raise invalid("%s entries must be among %s"
                              % (name, ", ".join(choices)))
            if item not in out:
                out.append(item)
        return out

    def timestamp(self, name, required=True, default=None):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        parsed = parse_datetime(value)
        if parsed is None:
            raise invalid("%s must be an ISO 8601 UTC datetime" % name)
        return parsed

    def date(self, name, required=True, default=None):
        if not self.present(name):
            return self._absent(name, required, default)
        value = self.body[name]
        parsed = parse_date(value)
        if parsed is None:
            raise invalid("%s must be a YYYY-MM-DD date" % name)
        return parsed

    def reference(self, name, required=True, default=None):
        return self.string(name, required=required, default=default,
                           non_empty=True)


class Query(object):
    """Reads query-string filters against a closed set of declared filters."""

    def __init__(self, *allowed):
        self.allowed = set(allowed) | {"limit", "offset"}
        for key in request.args.keys():
            if key not in self.allowed:
                raise invalid("unknown query parameter %s" % key)

    def _raw(self, name):
        values = request.args.getlist(name)
        if not values:
            return None
        return values[-1]

    def string(self, name):
        value = self._raw(name)
        if value is None or value == "":
            return None
        return value

    def enum(self, name, choices):
        value = self._raw(name)
        if value is None or value == "":
            return None
        if value not in choices:
            raise invalid("%s must be one of %s" % (name, ", ".join(choices)))
        return value

    def date(self, name):
        value = self._raw(name)
        if value is None or value == "":
            return None
        parsed = parse_date(value)
        if parsed is None:
            raise invalid("%s must be a YYYY-MM-DD date" % name)
        return parsed

    def _bounded_int(self, name, default, minimum, maximum):
        raw = self._raw(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw.strip())
        except (TypeError, ValueError):
            raise invalid("%s must be an integer" % name)
        if value < minimum:
            raise invalid("%s must be at least %d" % (name, minimum))
        if maximum is not None and value > maximum:
            raise invalid("%s must be at most %d" % (name, maximum))
        return value

    def limit(self):
        return self._bounded_int("limit", PAGINATION_DEFAULT_LIMIT,
                                 PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)

    def offset(self):
        return self._bounded_int("offset", PAGINATION_DEFAULT_OFFSET,
                                 PAGINATION_MIN_OFFSET, None)

    def page(self):
        """limit is validated before offset so a bad limit wins."""
        return self.limit(), self.offset()
