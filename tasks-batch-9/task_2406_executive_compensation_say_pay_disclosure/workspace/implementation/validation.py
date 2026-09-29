"""Request well-formedness helpers — ladder step 6 (ERR_INVALID_REQUEST)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from calc import dec, round_half_up
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def parse_instant(raw, field):
    if not isinstance(raw, str):
        bad("%s must be an ISO 8601 string" % field)
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("%s is not a parseable ISO 8601 instant" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Body:
    """Typed accessor over the JSON request body."""

    def __init__(self):
        raw = request.get_json(silent=True)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            bad("request body must be a JSON object")
        self.raw = raw

    def has(self, key):
        return key in self.raw and self.raw[key] is not None

    def present(self, key):
        return key in self.raw

    # ---------------------------------------------------------------- scalars
    def _fetch(self, key, required):
        if key not in self.raw or self.raw[key] is None:
            if required:
                bad("%s is required" % key)
            return _MISSING
        return self.raw[key]

    def string(self, key, required=False, default=None, min_len=None, max_len=None):
        value = self._fetch(key, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str):
            bad("%s must be a string" % key)
        if not value.strip():
            bad("%s may not be blank" % key)
        if min_len is not None and len(value) < min_len:
            bad("%s is too short" % key)
        if max_len is not None and len(value) > max_len:
            bad("%s is too long" % key)
        return value

    def enum(self, key, allowed, required=False, default=None):
        value = self._fetch(key, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str) or value not in allowed:
            bad("%s must be one of %s" % (key, ", ".join(sorted(allowed))))
        return value

    def boolean(self, key, required=False, default=None):
        value = self._fetch(key, required)
        if value is _MISSING:
            return default
        if not isinstance(value, bool):
            bad("%s must be a boolean" % key)
        return value

    def integer(self, key, required=False, default=None, minimum=None, maximum=None):
        value = self._fetch(key, required)
        if value is _MISSING:
            return default
        if isinstance(value, bool):
            bad("%s must be an integer" % key)
        if isinstance(value, float):
            if not value.is_integer():
                bad("%s must be an integer" % key)
            value = int(value)
        if not isinstance(value, int):
            bad("%s must be an integer" % key)
        if minimum is not None and value < minimum:
            bad("%s is below its permitted minimum" % key)
        if maximum is not None and value > maximum:
            bad("%s is above its permitted maximum" % key)
        return value

    def number(
        self,
        key,
        required=False,
        default=None,
        minimum=None,
        maximum=None,
        gt=None,
        places=None,
    ):
        value = self._fetch(key, required)
        if value is _MISSING:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            bad("%s must be a number" % key)
        try:
            number = dec(value)
        except (InvalidOperation, ValueError):
            bad("%s must be a number" % key)
        if not number.is_finite():
            bad("%s must be a finite number" % key)
        if gt is not None and number <= dec(gt):
            bad("%s must be strictly greater than %s" % (key, gt))
        if minimum is not None and number < dec(minimum):
            bad("%s is below its permitted minimum" % key)
        if maximum is not None and number > dec(maximum):
            bad("%s is above its permitted maximum" % key)
        if places is not None:
            number = round_half_up(number, places)
        return number

    def instant(self, key, required=False, default=None):
        value = self._fetch(key, required)
        if value is _MISSING:
            return default
        return parse_instant(value, key)

    def array(self, key, required=False, default=None):
        value = self._fetch(key, required)
        if value is _MISSING:
            return default
        if not isinstance(value, list):
            bad("%s must be an array" % key)
        return value
