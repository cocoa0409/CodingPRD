"""Body payload validation (PRD 2.9 priority 4 -> ERR_INVALID_REQUEST)."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def parse_date(value):
    """Strict YYYY-MM-DD -> datetime.date, or None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def minutes_of(hhmm):
    return int(hhmm[0:2]) * 60 + int(hhmm[3:5])


def parse_iso_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class Payload(object):
    """Thin typed accessor over a JSON object body.

    An explicitly supplied ``null`` is treated as "absent" for optional fields
    and as a violation for required ones.
    """

    def __init__(self, body):
        if body is None:
            body = {}
        if not isinstance(body, dict):
            bad("request body must be a JSON object")
        self.body = body

    def has(self, name):
        return name in self.body and self.body[name] is not None

    def present(self, name):
        return name in self.body

    def raw(self, name):
        return self.body.get(name)

    def _missing(self, name, required, default):
        if required:
            bad("%s is required" % name)
        return default

    def string(self, name, required=False, default=None, min_len=1, max_len=None):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if min_len is not None and len(value) < min_len:
            bad("%s must be at least %d characters" % (name, min_len))
        if max_len is not None and len(value) > max_len:
            bad("%s must be at most %d characters" % (name, max_len))
        return value

    def integer(self, name, required=False, default=None, minimum=None, maximum=None,
                multiple_of=None):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if isinstance(value, bool) or not isinstance(value, int):
            bad("%s must be an integer" % name)
        if minimum is not None and value < minimum:
            bad("%s must be >= %s" % (name, minimum))
        if maximum is not None and value > maximum:
            bad("%s must be <= %s" % (name, maximum))
        if multiple_of is not None and value % multiple_of != 0:
            bad("%s must be a multiple of %s" % (name, multiple_of))
        return value

    def number(self, name, required=False, default=None, minimum=None, maximum=None,
               decimals=None, step=None):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad("%s must be a number" % name)
        dec = _decimal(value)
        if dec is None:
            bad("%s must be a number" % name)
        if minimum is not None and dec < _decimal(minimum):
            bad("%s must be >= %s" % (name, minimum))
        if maximum is not None and dec > _decimal(maximum):
            bad("%s must be <= %s" % (name, maximum))
        if decimals is not None and -dec.as_tuple().exponent > decimals:
            bad("%s allows at most %d decimal places" % (name, decimals))
        if step is not None:
            scaled = dec / _decimal(step)
            if scaled != scaled.to_integral_value():
                bad("%s must be in steps of %s" % (name, step))
        return value

    def boolean(self, name, required=False, default=None):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if not isinstance(value, bool):
            bad("%s must be a boolean" % name)
        return value

    def enum(self, name, allowed, required=False, default=None):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if not isinstance(value, str) or value not in allowed:
            bad("%s must be one of %s" % (name, ", ".join(allowed)))
        return value

    def array(self, name, required=False, default=None, allowed=None, non_empty=True,
              unique=True, item="string"):
        if not self.has(name):
            if required:
                bad("%s is required" % name)
            return list(default) if default is not None else default
        value = self.body[name]
        if not isinstance(value, list):
            bad("%s must be an array" % name)
        if non_empty and len(value) == 0:
            bad("%s must not be empty" % name)
        for element in value:
            if item == "string":
                if not isinstance(element, str) or element == "":
                    bad("%s elements must be non-empty strings" % name)
            if allowed is not None and element not in allowed:
                bad("%s elements must be one of %s" % (name, ", ".join(allowed)))
        if unique and len(set(value)) != len(value):
            bad("%s must not contain duplicates" % name)
        return value

    def date(self, name, required=False, default=None):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if parse_date(value) is None:
            bad("%s must be an ISO 8601 date (YYYY-MM-DD)" % name)
        return value

    def time(self, name, required=False, default=None, multiple_of_5=False):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if not isinstance(value, str) or not _TIME_RE.match(value):
            bad("%s must be a 24-hour HH:MM time" % name)
        if multiple_of_5 and minutes_of(value) % 5 != 0:
            bad("%s must fall on a 5-minute boundary" % name)
        return value

    def language(self, name, required=False, default=None):
        if not self.has(name):
            return self._missing(name, required, default)
        value = self.body[name]
        if not isinstance(value, str) or not re.match(r"^[a-z]{2}$", value):
            bad("%s must be a lowercase two-letter ISO 639-1 code" % name)
        return value

    def language_array(self, name, required=False, default=None):
        values = self.array(name, required=required, default=default)
        if values is None:
            return None
        for element in values:
            if not re.match(r"^[a-z]{2}$", element):
                bad("%s elements must be lowercase two-letter ISO 639-1 codes" % name)
        return values
