"""Timestamp / date / numeric helpers and request-body validation primitives.

PRD §2.4  — ISO 8601 UTC with three fractional digits.
PRD §2.6  — minutes are floored integers, percentages 2dp round-half-up,
            money is integer cents rounded half up at each named step.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------- timestamps ---
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 UTC timestamp.  Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or "T" not in value:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC timestamp" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC timestamp" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a calendar date written YYYY-MM-DD" % field)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a calendar date written YYYY-MM-DD" % field)


def dt_of(stored):
    """Re-hydrate a stored ISO timestamp string."""
    if stored is None:
        return None
    return parse_dt(stored)


def date_of(stored):
    if stored is None:
        return None
    return parse_dt(stored).date()


def day_str(d):
    return d.isoformat()


def add_days(d, n):
    return d + timedelta(days=n)


def midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ------------------------------------------------------------------ numbers ---
def round_half_up(value, places=2):
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole number of cents (integer)."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct2(numerator, denominator):
    """round_half_up(numerator * 100 / denominator, 2) as a float; empty -> 0.00."""
    if denominator == 0:
        return 0.0
    value = (Decimal(numerator) * Decimal(100)) / Decimal(denominator)
    return float(round_half_up(value, 2))


def num2(value):
    return float(round_half_up(value, 2))


# --------------------------------------------------------- body / query args ---
class Body:
    """Ordered request-shape validation (PRD §2.5 rank 5)."""

    def __init__(self, raw):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
        self.raw = raw

    def present(self, key):
        return key in self.raw and self.raw[key] is not None

    def _require(self, key):
        if not self.present(key):
            raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
        return self.raw[key]

    # -- strings
    def str_field(self, key, required=True, min_len=1, max_len=None, pattern=None, default=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return default
        value = self.raw[key]
        if not isinstance(value, str):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be a string" % key)
        if min_len is not None and len(value) < min_len:
            raise ApiError("ERR_INVALID_REQUEST", "%s is too short" % key)
        if max_len is not None and len(value) > max_len:
            raise ApiError("ERR_INVALID_REQUEST", "%s is too long" % key)
        if pattern is not None and not re.match(pattern, value):
            raise ApiError("ERR_INVALID_REQUEST", "%s is malformed" % key)
        return value

    # -- booleans
    def bool_field(self, key, required=True, default=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return default
        value = self.raw[key]
        if not isinstance(value, bool):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % key)
        return value

    # -- integers
    def int_field(self, key, required=True, minimum=None, maximum=None, default=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return default
        value = self.raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % key)
        if isinstance(value, float):
            if not value.is_integer():
                raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % key)
            value = int(value)
        if minimum is not None and value < minimum:
            raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % key)
        if maximum is not None and value > maximum:
            raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % key)
        return int(value)

    # -- numbers (2 decimals)
    def num_field(self, key, required=True, minimum=None, maximum=None, default=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return default
        value = self.raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be a number" % key)
        rounded = round_half_up(Decimal(str(value)), 2)
        if minimum is not None and rounded < Decimal(str(minimum)):
            raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % key)
        if maximum is not None and rounded > Decimal(str(maximum)):
            raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % key)
        return float(rounded)

    # -- enums
    def enum_field(self, key, allowed, required=True, default=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return default
        value = self.raw[key]
        if not isinstance(value, str) or value not in allowed:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, ", ".join(sorted(allowed))))
        return value

    # -- timestamps / dates
    def dt_field(self, key, required=True, default=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return default
        return parse_dt(self.raw[key], key)

    def date_field(self, key, required=True, default=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return default
        return parse_date(self.raw[key], key)

    # -- id references
    def id_field(self, key, required=True, default=None):
        return self.str_field(key, required=required, min_len=1, default=default)

    # -- enum lists
    def enum_list_field(self, key, allowed, required=True, min_len=1, max_len=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return None
        value = self.raw[key]
        if not isinstance(value, list):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an array" % key)
        if min_len is not None and len(value) < min_len:
            raise ApiError("ERR_INVALID_REQUEST", "%s must not be empty" % key)
        if max_len is not None and len(value) > max_len:
            raise ApiError("ERR_INVALID_REQUEST", "%s has too many entries" % key)
        for item in value:
            if not isinstance(item, str) or item not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "%s entries must be one of %s" % (key, ", ".join(sorted(allowed))))
        if len(set(value)) != len(value):
            raise ApiError("ERR_INVALID_REQUEST", "%s must not contain duplicates" % key)
        return list(value)

    def id_list_field(self, key, required=True, min_len=1, max_len=None):
        if not self.present(key):
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "%s is required" % key)
            return None
        value = self.raw[key]
        if not isinstance(value, list):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an array" % key)
        if min_len is not None and len(value) < min_len:
            raise ApiError("ERR_INVALID_REQUEST", "%s must not be empty" % key)
        if max_len is not None and len(value) > max_len:
            raise ApiError("ERR_INVALID_REQUEST", "%s has too many entries" % key)
        for item in value:
            if not isinstance(item, str) or not item:
                raise ApiError("ERR_INVALID_REQUEST", "%s entries must be identifiers" % key)
        if len(set(value)) != len(value):
            raise ApiError("ERR_INVALID_REQUEST", "%s must not contain duplicates" % key)
        return list(value)


def serialize(entity):
    """Public representation: every stored key that is not internal."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
