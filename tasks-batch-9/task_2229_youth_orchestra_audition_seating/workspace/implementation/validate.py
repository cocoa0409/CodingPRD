"""Request body schema validation and pagination parsing (PRD 2.3, 2.10)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_MISSING = object()

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The parsed JSON object of the request, or {} when no body was sent."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        bad("Request body must be valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def parse_datetime(value, field):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC datetime string." % field)
    m = _ISO_RE.match(value.strip())
    if not m:
        bad("Field '%s' must be an ISO 8601 UTC datetime string." % field)
    year, month, day, hour, minute, second, frac, offset = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        naive = datetime(int(year), int(month), int(day), int(hour), int(minute),
                         int(second or 0), micro)
    except ValueError:
        bad("Field '%s' is not a valid calendar instant." % field)
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    digits = offset[1:].replace(":", "")
    delta_minutes = sign * (int(digits[:2]) * 60 + int(digits[2:]))
    from datetime import timedelta
    return (naive - timedelta(minutes=delta_minutes)).replace(tzinfo=timezone.utc)


class Body(object):
    """Small typed accessor over a request body, raising ERR_INVALID_REQUEST."""

    def __init__(self, data=None):
        self.data = body() if data is None else data

    # ------------------------------------------------------------------ raw
    def raw(self, name):
        return self.data.get(name, None)

    def present(self, name):
        return name in self.data and self.data.get(name) is not None

    def _fetch(self, name, required):
        """Returns _MISSING when the field is absent or explicitly null."""
        if name not in self.data or self.data.get(name) is None:
            if required:
                bad("Field '%s' is required." % name)
            return _MISSING
        return self.data[name]

    # --------------------------------------------------------------- string
    def string(self, name, required=True, default=None, min_len=1, max_len=None):
        value = self._fetch(name, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str):
            bad("Field '%s' must be a string." % name)
        if min_len is not None and len(value) < min_len:
            bad("Field '%s' must be at least %d characters." % (name, min_len))
        if max_len is not None and len(value) > max_len:
            bad("Field '%s' must be at most %d characters." % (name, max_len))
        return value

    # -------------------------------------------------------------- integer
    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        value = self._fetch(name, required)
        if value is _MISSING:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            bad("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            bad("Field '%s' must be >= %d." % (name, minimum))
        if maximum is not None and value > maximum:
            bad("Field '%s' must be <= %d." % (name, maximum))
        return value

    # -------------------------------------------------------------- boolean
    def boolean(self, name, required=False, default=False):
        value = self._fetch(name, required)
        if value is _MISSING:
            return default
        if not isinstance(value, bool):
            bad("Field '%s' must be a boolean." % name)
        return value

    # ----------------------------------------------------------------- enum
    def enum(self, name, values, required=True, default=None):
        value = self._fetch(name, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str) or value not in values:
            bad("Field '%s' must be one of %s." % (name, ", ".join(values)))
        return value

    # ------------------------------------------------------------- datetime
    def datetime(self, name, required=True, default=None):
        value = self._fetch(name, required)
        if value is _MISSING:
            return default
        return parse_datetime(value, name)

    # ---------------------------------------------------------- string array
    def str_array(self, name, required=True, default=None, min_items=None,
                  max_items=None, distinct=False, item_min_len=1):
        value = self._fetch(name, required)
        if value is _MISSING:
            return default
        if not isinstance(value, list):
            bad("Field '%s' must be an array." % name)
        for item in value:
            if not isinstance(item, str) or len(item) < item_min_len:
                bad("Every entry of '%s' must be a non-empty string." % name)
        if min_items is not None and len(value) < min_items:
            bad("Field '%s' must hold at least %d entries." % (name, min_items))
        if max_items is not None and len(value) > max_items:
            bad("Field '%s' must hold at most %d entries." % (name, max_items))
        if distinct and len(set(value)) != len(value):
            bad("Field '%s' entries must be distinct." % name)
        return value


# ------------------------------------------------------------------ paging
_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    """Returns (limit, offset); ERR_INVALID_PAGINATION on any violation."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = (args.get("limit") or "").strip()
        if not _INT_RE.match(raw):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer 1..100.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer 1..100.")
    if "offset" in args:
        raw = (args.get("offset") or "").strip()
        if not _INT_RE.match(raw):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
        offset = int(raw)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
    return limit, offset
