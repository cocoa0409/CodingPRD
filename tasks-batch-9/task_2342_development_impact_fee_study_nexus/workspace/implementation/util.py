"""Rounding discipline, timestamp handling and request-shape validation helpers."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from errors import raise_error

UTC = timezone.utc

# --------------------------------------------------------------------------- #
# Rounding (PRD 2.5: round half up, whole cents / 4 decimal places)
# --------------------------------------------------------------------------- #


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to whole cents, returned as an int."""
    return int(round_half_up(value, 0))


def d4(value):
    """Round half up to 4 decimal places, returned as a Decimal."""
    return round_half_up(value, 4)


def bp(value):
    """Basis points as a multiplier."""
    return dec(value) / Decimal(10000)


# --------------------------------------------------------------------------- #
# Timestamps
# --------------------------------------------------------------------------- #

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_timestamp(raw):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    match = _TS_RE.match(raw.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, frac, offset = match.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        moment = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        moment = moment - sign * delta
    return moment


def iso_ms(moment):
    """ISO 8601 UTC with exactly three fractional digits."""
    if moment is None:
        return None
    moment = moment.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day, moment.hour,
        moment.minute, moment.second, moment.microsecond // 1000,
    )


def add_days(moment, days):
    return moment + timedelta(days=int(days))


def add_years(moment, years):
    years = int(years)
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:  # 29 February on a non-leap target year
        return moment.replace(year=moment.year + years, month=2, day=28)


# --------------------------------------------------------------------------- #
# Numeric serialisation
# --------------------------------------------------------------------------- #


def num(value):
    """Serialise a 4-decimal quantity as a JSON number."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------- #
# Request shape validation (all failures are ERR_INVALID_REQUEST / 422)
# --------------------------------------------------------------------------- #

_MISSING = object()

VERSION_FIELDS = (
    "expected_fee_program_version",
    "expected_development_application_version",
    "expected_facility_category_version",
)


class Body(object):
    """Validating accessor over a JSON request body."""

    def __init__(self, data):
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise_error("ERR_INVALID_REQUEST")
        self.data = data

    def present(self, name):
        return name in self.data and self.data.get(name) is not None

    def any_present(self, names):
        return any(self.present(name) for name in names)

    def _get(self, name, required, default):
        """Returns (found, value). An explicit null counts as absent."""
        if name not in self.data or self.data.get(name) is None:
            if required:
                raise_error("ERR_INVALID_REQUEST")
            return False, default
        return True, self.data[name]

    def string(self, name, required=False, default=None,
               min_len=None, max_len=None, pattern=None):
        found, value = self._get(name, required, default)
        if not found:
            return default
        if not isinstance(value, str):
            raise_error("ERR_INVALID_REQUEST")
        stripped = value.strip()
        if min_len is not None and (len(stripped) < min_len or not stripped):
            raise_error("ERR_INVALID_REQUEST")
        if max_len is not None and len(value) > max_len:
            raise_error("ERR_INVALID_REQUEST")
        if pattern is not None and not re.fullmatch(pattern, value):
            raise_error("ERR_INVALID_REQUEST")
        return value

    def integer(self, name, required=False, default=None,
                minimum=None, maximum=None):
        found, value = self._get(name, required, default)
        if not found:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise_error("ERR_INVALID_REQUEST")
        if minimum is not None and value < minimum:
            raise_error("ERR_INVALID_REQUEST")
        if maximum is not None and value > maximum:
            raise_error("ERR_INVALID_REQUEST")
        return value

    def number(self, name, required=False, default=None, scale=4,
               gt=None, ge=None):
        found, value = self._get(name, required, default)
        if not found:
            return None if default is None else dec(default)
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise_error("ERR_INVALID_REQUEST")
        try:
            parsed = dec(value)
        except (InvalidOperation, ValueError):
            raise_error("ERR_INVALID_REQUEST")
            return None
        if not parsed.is_finite():
            raise_error("ERR_INVALID_REQUEST")
        exponent = parsed.normalize().as_tuple().exponent
        if scale is not None and isinstance(exponent, int) and exponent < -scale:
            raise_error("ERR_INVALID_REQUEST")
        if gt is not None and not parsed > dec(gt):
            raise_error("ERR_INVALID_REQUEST")
        if ge is not None and not parsed >= dec(ge):
            raise_error("ERR_INVALID_REQUEST")
        return parsed

    def enum(self, name, choices, required=False, default=None):
        found, value = self._get(name, required, default)
        if not found:
            return default
        if not isinstance(value, str) or value not in choices:
            raise_error("ERR_INVALID_REQUEST")
        return value

    def timestamp(self, name, required=False, default=None):
        found, value = self._get(name, required, default)
        if not found:
            return default
        parsed = parse_timestamp(value)
        if parsed is None:
            raise_error("ERR_INVALID_REQUEST")
        return parsed

    def forbid_versions(self, *allowed):
        for field in VERSION_FIELDS:
            if field in allowed:
                continue
            if field in self.data:
                raise_error("ERR_INVALID_REQUEST")
