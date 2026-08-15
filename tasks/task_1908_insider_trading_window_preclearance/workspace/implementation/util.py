"""Datetime, decimal, and request-body helpers."""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ApiError, ERR_INVALID_REQUEST, ERR_INVALID_ENUM

UTC = timezone.utc
TWO_DP = Decimal("0.01")


def parse_dt(value):
    """Parse an ISO-8601 datetime (accepts date-only, 'Z', offsets, fractional
    seconds). Returns an aware UTC datetime. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not value.strip():
        raise err(ERR_INVALID_REQUEST, f"malformed datetime: {value!r}")
    s = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)
        else:
            iso = s
            if iso.endswith(("Z", "z")):
                iso = iso[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
    except (ValueError, OverflowError):
        raise err(ERR_INVALID_REQUEST, f"malformed datetime: {value!r}")
    return dt


def fmt_ts(dt):
    """System timestamp format: ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def dec(value):
    """Decimal view of a JSON number (avoids binary float artifacts)."""
    return Decimal(str(value))


def rhu2(value):
    """Round half up to exactly two decimal places, returned as float."""
    return float(dec(value).quantize(TWO_DP, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body schema collector.
#
# PRD section 2.9 pins body-schema checks (ERR_INVALID_REQUEST /
# ERR_INVALID_ENUM) at the very bottom of the precedence ladder: they are only
# observable as the sole failing check. So field parsing never raises
# immediately; it records a pending schema error, deeper checks that need the
# missing value are skipped, and the pending error is flushed at the end of
# the ladder (Body.flush) once every higher-priority check has passed.
# ---------------------------------------------------------------------------

class Body:
    def __init__(self):
        from flask import request
        raw = request.get_json(silent=True)
        self.raw = raw if isinstance(raw, dict) else {}
        self.pending = None  # ERR_INVALID_REQUEST or ERR_INVALID_ENUM
        self.pending_msg = None

    def _mark(self, error_id, msg):
        # ERR_INVALID_REQUEST (priority 20) outranks ERR_INVALID_ENUM (21)
        if self.pending is None or (self.pending == ERR_INVALID_ENUM and error_id == ERR_INVALID_REQUEST):
            self.pending = error_id
            self.pending_msg = msg

    def has(self, name):
        return name in self.raw and self.raw[name] is not None

    def get_str(self, name, required=True):
        v = self.raw.get(name)
        if v is None:
            if required:
                self._mark(ERR_INVALID_REQUEST, f"required field missing: {name}")
            return None
        if not isinstance(v, str) or not v.strip():
            self._mark(ERR_INVALID_REQUEST, f"field must be a non-empty string: {name}")
            return None
        return v

    def get_num(self, name, required=True, positive=False, max_dp=None):
        v = self.raw.get(name)
        if v is None:
            if required:
                self._mark(ERR_INVALID_REQUEST, f"required field missing: {name}")
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self._mark(ERR_INVALID_REQUEST, f"field must be a number: {name}")
            return None
        d = dec(v)
        if positive and d <= 0:
            self._mark(ERR_INVALID_REQUEST, f"field must be greater than zero: {name}")
            return None
        if max_dp is not None and -d.as_tuple().exponent > max_dp:
            self._mark(ERR_INVALID_REQUEST, f"field accepts at most {max_dp} decimal places: {name}")
            return None
        return v

    def get_int(self, name, required=True):
        v = self.raw.get(name)
        if v is None:
            if required:
                self._mark(ERR_INVALID_REQUEST, f"required field missing: {name}")
            return None
        if isinstance(v, bool) or not isinstance(v, int):
            self._mark(ERR_INVALID_REQUEST, f"field must be an integer: {name}")
            return None
        return v

    def get_dt(self, name, required=True):
        v = self.raw.get(name)
        if v is None:
            if required:
                self._mark(ERR_INVALID_REQUEST, f"required field missing: {name}")
            return None
        try:
            return parse_dt(v)
        except ApiError:
            self._mark(ERR_INVALID_REQUEST, f"malformed datetime: {name}")
            return None

    def get_enum(self, name, allowed, required=True):
        v = self.raw.get(name)
        if v is None:
            if required:
                self._mark(ERR_INVALID_REQUEST, f"required field missing: {name}")
            return None
        if not isinstance(v, str) or v not in allowed:
            self._mark(ERR_INVALID_ENUM, f"field carries an undeclared value: {name}={v!r}")
            return None
        return v

    def flush(self):
        if self.pending is not None:
            raise err(self.pending, self.pending_msg)
