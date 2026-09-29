"""Request-body reading and validation.

PRD 2.9 rule 15 (required field present, declared type, numeric bounds ->
ERR_VALIDATION) is evaluated before rule 16 (enum membership ->
ERR_INVALID_ENUM_VALUE), so enum membership checks are deferred until
``finish()`` while presence/type checks fire immediately.
"""

from flask import request

from errors import ApiError
from store import parse_iso

_MISSING = object()


def raw_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return data


class Body(object):
    def __init__(self, data=None):
        self.data = raw_body() if data is None else data
        self._deferred = []

    # ---------------------------------------------------------------- utils
    def has(self, name):
        return name in self.data and self.data.get(name) is not None

    def present(self, name):
        return name in self.data

    def get(self, name, default=None):
        value = self.data.get(name, _MISSING)
        if value is _MISSING:
            return default
        return value

    def _fetch(self, name, required, default):
        value = self.data.get(name, _MISSING)
        if value is _MISSING or value is None:
            if required:
                raise ApiError("ERR_VALIDATION", "Field '%s' is required" % name)
            return default, False
        return value, True

    # ---------------------------------------------------------------- types
    def string(self, name, required=True, default=None, min_len=None, max_len=None,
               allow_blank=False):
        value, found = self._fetch(name, required, default)
        if not found:
            return value
        if not isinstance(value, str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string" % name)
        if not allow_blank and value.strip() == "" and (min_len or 0) > 0:
            raise ApiError("ERR_VALIDATION", "Field '%s' must not be blank" % name)
        if min_len is not None and len(value) < min_len:
            raise ApiError("ERR_VALIDATION", "Field '%s' is too short" % name)
        if max_len is not None and len(value) > max_len:
            raise ApiError("ERR_VALIDATION", "Field '%s' is too long" % name)
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        value, found = self._fetch(name, required, default)
        if not found:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be an integer" % name)
        if minimum is not None and value < minimum:
            raise ApiError("ERR_VALIDATION", "Field '%s' is below its minimum" % name)
        if maximum is not None and value > maximum:
            raise ApiError("ERR_VALIDATION", "Field '%s' is above its maximum" % name)
        return value

    def number(self, name, required=True, default=None, minimum=None, maximum=None):
        value, found = self._fetch(name, required, default)
        if not found:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a number" % name)
        if minimum is not None and value < minimum:
            raise ApiError("ERR_VALIDATION", "Field '%s' is below its minimum" % name)
        if maximum is not None and value > maximum:
            raise ApiError("ERR_VALIDATION", "Field '%s' is above its maximum" % name)
        return value

    def boolean(self, name, required=True, default=None):
        value, found = self._fetch(name, required, default)
        if not found:
            return value
        if not isinstance(value, bool):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a boolean" % name)
        return value

    def array(self, name, required=True, default=None, item_type=None):
        value, found = self._fetch(name, required, default)
        if not found:
            return value
        if not isinstance(value, list):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be an array" % name)
        if item_type is not None:
            for item in value:
                if not isinstance(item, item_type) or isinstance(item, bool):
                    raise ApiError("ERR_VALIDATION",
                                   "Field '%s' has an item of the wrong type" % name)
        return value

    def datetime(self, name, required=True, default=None):
        value, found = self._fetch(name, required, default)
        if not found:
            return value
        if not isinstance(value, str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be an ISO-8601 string" % name)
        parsed = parse_iso(value)
        if parsed is None:
            raise ApiError("ERR_VALIDATION", "Field '%s' is not a valid instant" % name)
        return parsed

    def enum(self, name, allowed, required=True, default=None):
        value, found = self._fetch(name, required, default)
        if not found:
            return value
        if not isinstance(value, str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string" % name)
        self._deferred.append((name, value, tuple(allowed)))
        return value

    def enum_array(self, name, allowed, required=True, default=None):
        value = self.array(name, required=required, default=default, item_type=str)
        if isinstance(value, list) and allowed is not None:
            for item in value:
                self._deferred.append((name, item, tuple(allowed)))
        return value

    def finish(self):
        for name, value, allowed in self._deferred:
            if value not in allowed:
                raise ApiError("ERR_INVALID_ENUM_VALUE",
                               "Field '%s' has value '%s' outside its declared set"
                               % (name, value))
        self._deferred = []
        return self
