"""Request-body parsing, structural validation, and pagination (PRD §2.3, §2.10).

Structural problems (missing field, wrong type, invalid enum, non-positive
amount, end-before-start) are tier-8 ERR_INVALID_REQUEST (400). They are
*recorded* while higher tiers (existence/OCC/state/safety/temporal) run, and
raised by ``raise_if_errors()`` once those tiers pass.
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def parse_body():
    """Lenient JSON body parse. Returns (dict, error_message_or_None).
    JSON numbers keep full decimal precision via parse_float=Decimal."""
    raw = request.get_data(as_text=True)
    if raw is None or not raw.strip():
        return {}, None
    try:
        data = json.loads(raw, parse_float=Decimal)
    except Exception:
        return {}, "Request body is not valid JSON"
    if not isinstance(data, dict):
        return {}, "Request body must be a JSON object"
    return data, None


def parse_datetime(value):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Struct:
    def __init__(self, data, parse_error=None):
        self.data = data
        self.errors = []
        if parse_error:
            self.errors.append(parse_error)

    def _miss(self, f):
        self.errors.append("Missing required field: %s" % f)
        return None

    def _bad(self, f, why):
        self.errors.append("Field %s %s" % (f, why))
        return None

    def get_str(self, f, required=True):
        v = self.data.get(f)
        if v is None:
            return self._miss(f) if required else None
        if not isinstance(v, str):
            return self._bad(f, "must be a string")
        return v

    def get_int(self, f, required=True, min=None, default=None):
        v = self.data.get(f)
        if v is None:
            if required:
                self._miss(f)
            return default
        if type(v) is not int:
            return self._bad(f, "must be an integer")
        if min is not None and v < min:
            return self._bad(f, "must be at least %d" % min)
        return v

    def get_num(self, f, required=True, positive=False):
        """JSON number -> Decimal. `positive` enforces > 0."""
        v = self.data.get(f)
        if v is None:
            return self._miss(f) if required else None
        if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
            return self._bad(f, "must be a number")
        d = Decimal(v) if type(v) is int else v
        if positive and d <= 0:
            return self._bad(f, "must be greater than zero")
        return d

    def get_enum(self, f, values, required=True):
        v = self.data.get(f)
        if v is None:
            return self._miss(f) if required else None
        if not isinstance(v, str) or v not in values:
            return self._bad(f, "must be one of %s" % "|".join(values))
        return v

    def get_bool(self, f, required=False, default=None):
        v = self.data.get(f)
        if v is None:
            if required:
                self._miss(f)
            return default
        if type(v) is not bool:
            return self._bad(f, "must be a boolean")
        return v

    def get_date(self, f, required=True):
        v = self.data.get(f)
        if v is None:
            return self._miss(f) if required else None
        if not isinstance(v, str):
            return self._bad(f, "must be an ISO date string")
        try:
            return date.fromisoformat(v.strip())
        except ValueError:
            return self._bad(f, "must be a valid ISO date (YYYY-MM-DD)")

    def get_datetime(self, f, required=True):
        v = self.data.get(f)
        if v is None:
            return self._miss(f) if required else None
        if not isinstance(v, str):
            return self._bad(f, "must be an ISO datetime string")
        try:
            return parse_datetime(v)
        except ValueError:
            return self._bad(f, "must be a valid ISO 8601 datetime")

    def raise_if_errors(self):
        if self.errors:
            raise ApiError(400, ERR_INVALID_REQUEST, self.errors[0])


def pagination():
    """PRD §2.3: limit defaults to 10, range 1..100; offset defaults to 0."""
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
