"""Schema validation (validation band 3 -> ERR_INVALID_REQUEST)."""

from datetime import date, datetime, timezone

from errors import invalid_request
from arith import dec, is_number, places_of

_MISSING = object()


class Body(object):
    """Thin validating reader over a JSON request body."""

    def __init__(self, raw):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise invalid_request("Request body must be a JSON object.")
        self.raw = raw

    # ---------------------------------------------------------------- access
    def present(self, name):
        return name in self.raw and self.raw[name] is not None

    def _get(self, name, required, default):
        if name not in self.raw or self.raw[name] is None:
            if required:
                raise invalid_request("Field '%s' is required." % name)
            return _MISSING if default is _MISSING else default
        return self.raw[name]

    # ---------------------------------------------------------------- types
    def string(self, name, required=True, default=_MISSING, min_len=1, max_len=None,
               length=None, digits=False):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, str):
            raise invalid_request("Field '%s' must be a string." % name)
        if length is not None and len(value) != length:
            raise invalid_request("Field '%s' must be exactly %d characters." % (name, length))
        if min_len is not None and len(value) < min_len:
            raise invalid_request("Field '%s' is too short." % name)
        if max_len is not None and len(value) > max_len:
            raise invalid_request("Field '%s' is too long." % name)
        if digits and not value.isdigit():
            raise invalid_request("Field '%s' must contain digits only." % name)
        return value

    def integer(self, name, required=True, default=_MISSING, minimum=None, maximum=None,
                nonzero=False):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, int) or isinstance(value, bool):
            raise invalid_request("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            raise invalid_request("Field '%s' must be >= %s." % (name, minimum))
        if maximum is not None and value > maximum:
            raise invalid_request("Field '%s' must be <= %s." % (name, maximum))
        if nonzero and value == 0:
            raise invalid_request("Field '%s' may not be zero." % name)
        return value

    def number(self, name, required=True, default=_MISSING, places=None, minimum=None,
               maximum=None, exclusive_minimum=None):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not is_number(value):
            raise invalid_request("Field '%s' must be a number." % name)
        if places is not None and places_of(value) > places:
            raise invalid_request(
                "Field '%s' may carry at most %d decimal places." % (name, places))
        if minimum is not None and value < minimum:
            raise invalid_request("Field '%s' must be >= %s." % (name, minimum))
        if exclusive_minimum is not None and value <= exclusive_minimum:
            raise invalid_request("Field '%s' must be > %s." % (name, exclusive_minimum))
        if maximum is not None and value > maximum:
            raise invalid_request("Field '%s' must be <= %s." % (name, maximum))
        if places is not None:
            return dec(value, places)
        return value

    def boolean(self, name, required=False, default=_MISSING):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, bool):
            raise invalid_request("Field '%s' must be a boolean." % name)
        return value

    def enum(self, name, allowed, required=True, default=_MISSING):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, str) or value not in allowed:
            raise invalid_request(
                "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
        return value

    def date(self, name, required=True, default=_MISSING):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, str):
            raise invalid_request("Field '%s' must be a YYYY-MM-DD date string." % name)
        return parse_date(value, name)

    def datetime(self, name, required=True, default=_MISSING):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, str):
            raise invalid_request("Field '%s' must be an ISO 8601 timestamp." % name)
        return parse_datetime(value, name)

    def mapping(self, name, required=False, default=_MISSING):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, dict):
            raise invalid_request("Field '%s' must be an object." % name)
        return value

    def array(self, name, required=True, default=_MISSING, min_items=None):
        value = self._get(name, required, default)
        if value is _MISSING or (not required and name not in self.raw):
            return value
        if value is None:
            return value
        if not isinstance(value, list):
            raise invalid_request("Field '%s' must be an array." % name)
        if min_items is not None and len(value) < min_items:
            raise invalid_request("Field '%s' must carry at least %d items." % (name, min_items))
        return value


def parse_date(value, name="date"):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise invalid_request("Field '%s' must be a valid YYYY-MM-DD date." % name)
    return date(parsed.year, parsed.month, parsed.day)


def parse_datetime(value, name="timestamp"):
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise invalid_request("Field '%s' must be a valid ISO 8601 timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def query_int(args, name, default, minimum=None, maximum=None):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise invalid_request("Query parameter '%s' must be an integer." % name)
    if str(value) != raw.strip():
        raise invalid_request("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid_request("Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def query_enum(args, name, allowed):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise invalid_request("Query parameter '%s' has an unrecognized value." % name)
    return raw


def query_string(args, name):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    return raw
