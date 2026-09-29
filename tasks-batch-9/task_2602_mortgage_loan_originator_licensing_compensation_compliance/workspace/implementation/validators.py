"""Declarative request-body reader. Every failure here is priority 7,
ERR_INVALID_REQUEST (400)."""
import re

from flask import request

from errors import ApiError, bad_request
from util import parse_iso

STATE_RE = re.compile(r"^[A-Z]{2}$")
NMLS_RE = re.compile(r"^[0-9]{6,8}$")


def raw_body(required=True):
    """Parse the JSON body. Non-object bodies are rejected as invalid."""
    data = request.get_data(cache=True)
    if not data:
        if required:
            raise bad_request("A JSON object request body is required.")
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if parsed is None:
        if required:
            raise bad_request("A JSON object request body is required.")
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object.")
    return parsed


def optional_body():
    """For endpoints whose entire input list is optional."""
    try:
        return raw_body(required=False)
    except ApiError:
        raise


class Body(object):
    def __init__(self, raw):
        self.raw = raw if isinstance(raw, dict) else {}

    def _present(self, name):
        return name in self.raw and self.raw[name] is not None

    def string(self, name, required=True, default=None, min_len=None,
               max_len=None, pattern=None):
        if not self._present(name):
            if required:
                raise bad_request("Field '%s' is required." % name)
            return default
        value = self.raw[name]
        if not isinstance(value, str):
            raise bad_request("Field '%s' must be a string." % name)
        if min_len is not None and len(value) < min_len:
            raise bad_request("Field '%s' is shorter than %d characters." % (name, min_len))
        if max_len is not None and len(value) > max_len:
            raise bad_request("Field '%s' is longer than %d characters." % (name, max_len))
        if pattern is not None and not pattern.match(value):
            raise bad_request("Field '%s' is malformed." % name)
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        if not self._present(name):
            if required:
                raise bad_request("Field '%s' is required." % name)
            return default
        value = self.raw[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad_request("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            raise bad_request("Field '%s' is below the permitted minimum." % name)
        if maximum is not None and value > maximum:
            raise bad_request("Field '%s' is above the permitted maximum." % name)
        return value

    def boolean(self, name, required=True, default=None):
        if not self._present(name):
            if required:
                raise bad_request("Field '%s' is required." % name)
            return default
        value = self.raw[name]
        if not isinstance(value, bool):
            raise bad_request("Field '%s' must be a boolean." % name)
        return value

    def enum(self, name, values, required=True, default=None):
        value = self.string(name, required=required, default=None)
        if value is None:
            return default
        if value not in values:
            raise bad_request("Field '%s' must be one of %s." % (name, ", ".join(values)))
        return value

    def datetime(self, name, required=True, default=None):
        if not self._present(name):
            if required:
                raise bad_request("Field '%s' is required." % name)
            return default
        value = self.raw[name]
        if not isinstance(value, str):
            raise bad_request("Field '%s' must be an ISO 8601 string." % name)
        parsed = parse_iso(value)
        if parsed is None:
            raise bad_request("Field '%s' is not a valid ISO 8601 instant." % name)
        return parsed

    def str_array(self, name, required=True, default=None, min_items=None,
                  max_items=None, pattern=None, item_min_len=None,
                  item_max_len=None):
        if not self._present(name):
            if required:
                raise bad_request("Field '%s' is required." % name)
            return list(default) if default is not None else default
        value = self.raw[name]
        if not isinstance(value, list):
            raise bad_request("Field '%s' must be an array." % name)
        if min_items is not None and len(value) < min_items:
            raise bad_request("Field '%s' needs at least %d entries." % (name, min_items))
        if max_items is not None and len(value) > max_items:
            raise bad_request("Field '%s' allows at most %d entries." % (name, max_items))
        for item in value:
            if not isinstance(item, str):
                raise bad_request("Field '%s' must contain only strings." % name)
            if pattern is not None and not pattern.match(item):
                raise bad_request("Field '%s' contains a malformed entry." % name)
            if item_min_len is not None and len(item) < item_min_len:
                raise bad_request("Field '%s' contains a too-short entry." % name)
            if item_max_len is not None and len(item) > item_max_len:
                raise bad_request("Field '%s' contains a too-long entry." % name)
        return list(value)


def body_fk(raw, name):
    """Return the raw foreign key string if usable for the priority-6 lookup."""
    if not isinstance(raw, dict):
        return None
    value = raw.get(name)
    if isinstance(value, str):
        return value
    return None


def query_enum(name, values, default):
    value = request.args.get(name)
    if value is None:
        return default
    if value not in values:
        raise bad_request("Query parameter '%s' is invalid." % name)
    return value


def query_int(name, default=None):
    value = request.args.get(name)
    if value is None:
        return default
    value = value.strip()
    if not re.match(r"^[+-]?[0-9]+$", value):
        raise bad_request("Query parameter '%s' must be an integer." % name)
    return int(value)


def query_iso(name, default=None):
    value = request.args.get(name)
    if value is None:
        return default
    parsed = parse_iso(value)
    if parsed is None:
        raise bad_request("Query parameter '%s' is not a valid ISO 8601 instant." % name)
    return parsed
