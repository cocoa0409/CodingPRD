"""Request-schema validation (PRD 2.11 step 5) and pagination (PRD 2.3)."""

from flask import request

import clockutil
from errors import ApiError

BAD = "ERR_INVALID_REQUEST"


def invalid(detail):
    return ApiError(BAD, detail)


def body():
    """Parse the JSON body. A body that does not parse, or is not an object, is a schema failure."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise invalid("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


class Schema(object):
    """Reads and validates one request body. Every failure is ERR_INVALID_REQUEST."""

    def __init__(self, data):
        self.data = data if isinstance(data, dict) else {}

    def present(self, name):
        return name in self.data

    def _required(self, name):
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        return self.data[name]

    def string(self, name, required=True, default=None, allow_empty=False):
        if name not in self.data or self.data[name] is None:
            if required:
                raise invalid("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, str):
            raise invalid("Field '%s' must be a string." % name)
        if not allow_empty and value.strip() == "":
            raise invalid("Field '%s' may not be empty." % name)
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        if name not in self.data or self.data[name] is None:
            if required:
                raise invalid("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            raise invalid("Field '%s' may not be lower than %d." % (name, minimum))
        if maximum is not None and value > maximum:
            raise invalid("Field '%s' may not exceed %d." % (name, maximum))
        return value

    def boolean(self, name, required=True, default=None):
        if name not in self.data or self.data[name] is None:
            if required:
                raise invalid("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, bool):
            raise invalid("Field '%s' must be a boolean." % name)
        return value

    def enum(self, name, allowed, required=True, default=None):
        value = self.string(name, required=required, default=default)
        if value is None:
            return None
        if value not in allowed:
            raise invalid("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
        return value

    def datetime(self, name, required=True, default=None):
        value = self.string(name, required=required, default=default)
        if value is None:
            return None
        if clockutil.parse_dt(value) is None:
            raise invalid("Field '%s' must be an ISO 8601 instant with a Z offset." % name)
        return value

    def date(self, name, required=True, default=None):
        value = self.string(name, required=required, default=default)
        if value is None:
            return None
        if clockutil.parse_date(value) is None:
            raise invalid("Field '%s' must be a YYYY-MM-DD calendar date." % name)
        return value

    def string_list(self, name, required=True, default=None, allowed=None):
        if name not in self.data or self.data[name] is None:
            if required:
                raise invalid("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, list):
            raise invalid("Field '%s' must be an array." % name)
        for item in value:
            if not isinstance(item, str):
                raise invalid("Field '%s' must be an array of strings." % name)
            if allowed is not None and item not in allowed:
                raise invalid("Field '%s' carries an unrecognized code." % name)
        return list(value)

    def reference(self, name, required=True):
        """A foreign-key identifier: schema-checked as a non-empty string here, resolved later."""
        return self.string(name, required=required, default=None)


def time_window(open_value, close_value):
    """The later instant must be strictly after the earlier one (PRD 2.11 closing note)."""
    opened = clockutil.parse_dt(open_value)
    closed = clockutil.parse_dt(close_value)
    if opened is None or closed is None:
        return
    if not closed > opened:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "The closing instant must be strictly after the opening instant.")


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 and may not be negative."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' may not be negative.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("Query parameter '%s' carries an unrecognized value." % name)
    return value


def query_string(name):
    return request.args.get(name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
