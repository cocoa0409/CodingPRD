"""Request-shape validation (PRD 2.9 ladder step 3) and pagination (step 4)."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

MISSING = object()

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def body():
    """Parse the JSON body; an unparseable body is an invalid request."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def parse_instant(raw, field):
    """Parse an ISO 8601 UTC instant; anything else is an invalid request."""
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 string." % field)
    match = _ISO_RE.match(raw.strip())
    if not match:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 UTC instant." % field)
    year, month, day, hour, minute, second, frac, offset = match.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        moment = datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 UTC instant." % field)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        shift = int(digits[:2]) * 60 + int(digits[2:4])
        moment = moment - sign * _minutes(shift)
    return moment


def _minutes(count):
    from datetime import timedelta

    return timedelta(minutes=count)


def _present(payload, field, required):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return False
    return True


def get_str(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if required and not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return value


def get_enum(payload, field, allowed, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (field, ", ".join(allowed)),
        )
    return value


def get_bool(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def get_int(payload, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, maximum))
    return value


def get_decimal(
    payload,
    field,
    required=True,
    default=None,
    minimum=None,
    maximum=None,
    exclusive_min=None,
    places=None,
):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    if minimum is not None and number < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    if exclusive_min is not None and number <= Decimal(str(exclusive_min)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (field, exclusive_min))
    if maximum is not None and number > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, maximum))
    if places is not None:
        number = number.quantize(Decimal(1).scaleb(-places))
    return number


def get_instant(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    return parse_instant(payload[field], field)


def pagination():
    """PRD 2.3 — limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _positive_int(raw_limit)
        if limit is None or limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
    if raw_offset is not None:
        offset = _positive_int(raw_offset)
        if offset is None or offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
    return limit, offset


def _positive_int(raw):
    text = raw.strip()
    if not text:
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    return None
