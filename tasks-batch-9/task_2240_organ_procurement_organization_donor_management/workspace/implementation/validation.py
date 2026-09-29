"""Body-shape / pagination validation (PRD 2.3, 2.5, precedence steps 6-7)."""

import re
from datetime import datetime, timezone

from flask import request

from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import ApiError

_INT_RE = re.compile(r"^[+-]?\d+$")


def parse_instant(raw):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None on failure."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def json_body():
    if not request.data:
        return {}
    raw = request.get_json(silent=True)
    if raw is None:
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be valid JSON.")
    return raw


class Body:
    """Thin typed accessor. Every failure is ERR_INVALID_REQUEST (400)."""

    def __init__(self, raw=None):
        raw = json_body() if raw is None else raw
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
        self.raw = raw

    # ---------------------------------------------------------------- helpers
    def _fail(self, field, detail):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))

    def present(self, field):
        return field in self.raw and self.raw[field] is not None

    def _fetch(self, field, required, default):
        if not self.present(field):
            if required:
                self._fail(field, "is required")
            return False, default
        return True, self.raw[field]

    # ----------------------------------------------------------------- types
    def string(self, field, required=False, default=None, min_len=None, max_len=None):
        found, value = self._fetch(field, required, default)
        if not found:
            return value
        if not isinstance(value, str):
            self._fail(field, "must be a string")
        if min_len is not None and len(value) < min_len:
            self._fail(field, "must be at least %d characters" % min_len)
        if max_len is not None and len(value) > max_len:
            self._fail(field, "must be at most %d characters" % max_len)
        return value

    def integer(self, field, required=False, default=None, minimum=None, maximum=None):
        found, value = self._fetch(field, required, default)
        if not found:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail(field, "must be an integer")
        if minimum is not None and value < minimum:
            self._fail(field, "must be >= %s" % minimum)
        if maximum is not None and value > maximum:
            self._fail(field, "must be <= %s" % maximum)
        return value

    def number(self, field, required=False, default=None, minimum=None, maximum=None):
        found, value = self._fetch(field, required, default)
        if not found:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._fail(field, "must be a number")
        if minimum is not None and value < minimum:
            self._fail(field, "must be >= %s" % minimum)
        if maximum is not None and value > maximum:
            self._fail(field, "must be <= %s" % maximum)
        return value

    def boolean(self, field, required=False, default=None):
        found, value = self._fetch(field, required, default)
        if not found:
            return value
        if not isinstance(value, bool):
            self._fail(field, "must be a boolean")
        return value

    def enum(self, field, allowed, required=False, default=None):
        found, value = self._fetch(field, required, default)
        if not found:
            return value
        if not isinstance(value, str) or value not in allowed:
            self._fail(field, "must be one of %s" % ", ".join(allowed))
        return value

    def instant(self, field, required=False, default=None):
        found, value = self._fetch(field, required, default)
        if not found:
            return value
        parsed = parse_instant(value)
        if parsed is None:
            self._fail(field, "must be an ISO 8601 instant")
        return parsed

    def array(self, field, required=False, default=None):
        found, value = self._fetch(field, required, default)
        if not found:
            return [] if default is None and not required else value
        if not isinstance(value, list):
            self._fail(field, "must be an array")
        return value

    def enum_array(self, field, allowed, required=False):
        value = self.array(field, required=required, default=[])
        if value is None:
            return []
        for member in value:
            if not isinstance(member, str) or member not in allowed:
                self._fail(field, "must contain only members of %s" % ", ".join(allowed))
        return value

    def raw_value(self, field):
        return self.raw.get(field)


def pagination():
    """Precedence 7 (ERR_INVALID_PAGINATION)."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        text = raw_limit.strip()
        if not _INT_RE.match(text):
            raise ApiError("ERR_INVALID_PAGINATION")
        limit = int(text)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        text = raw_offset.strip()
        if not _INT_RE.match(text):
            raise ApiError("ERR_INVALID_PAGINATION")
        offset = int(text)
        if offset < PAGINATION_DEFAULT_OFFSET:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset : offset + limit]


def query_int(field, default, minimum=None, maximum=None):
    raw = request.args.get(field)
    if raw is None:
        return default
    text = raw.strip()
    if not _INT_RE.match(text):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % field)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %s." % (field, maximum))
    return value


def query_enum(field, allowed, default):
    raw = request.args.get(field)
    if raw is None:
        return default
    if raw not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (field, ", ".join(allowed)),
        )
    return raw
