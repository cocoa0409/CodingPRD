"""Rank 8 request-shape validation helpers (ERR_INVALID_REQUEST)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from errors import ApiError

TWO_LETTER = re.compile(r"^[A-Z]{2}$")
UPPER_SNAKE = re.compile(r"^[A-Z0-9]+(_[A-Z0-9]+)*$")


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def present(body, name):
    return name in body and body[name] is not None


def require_present(body, name):
    if not present(body, name):
        raise bad("'%s' is required." % name)
    return body[name]


def req_str(body, name, min_len=1, max_len=None):
    value = require_present(body, name)
    return check_str(value, name, min_len, max_len)


def check_str(value, name, min_len=1, max_len=None):
    if not isinstance(value, str):
        raise bad("'%s' must be a string." % name)
    if min_len is not None and len(value.strip()) < min_len:
        raise bad("'%s' must be at least %d non-blank characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("'%s' may be at most %d characters." % (name, max_len))
    return value


def opt_str(body, name, min_len=1, max_len=None, default=None):
    if not present(body, name):
        return default
    return check_str(body[name], name, min_len, max_len)


def req_int(body, name, minimum=None, maximum=None):
    value = require_present(body, name)
    return check_int(value, name, minimum, maximum)


def check_int(value, name, minimum=None, maximum=None):
    if not is_int(value):
        raise bad("'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("'%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("'%s' may be at most %d." % (name, maximum))
    return value


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not present(body, name):
        return default
    return check_int(body[name], name, minimum, maximum)


def req_bool(body, name):
    value = require_present(body, name)
    return check_bool(value, name)


def check_bool(value, name):
    if not isinstance(value, bool):
        raise bad("'%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    return check_bool(body[name], name)


def req_enum(body, name, allowed):
    value = require_present(body, name)
    return check_enum(value, name, allowed)


def check_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise bad("'%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return check_enum(body[name], name, allowed)


def req_fraction(body, name, minimum, maximum, max_decimals=4):
    value = require_present(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("'%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise bad("'%s' must be a number." % name)
    if dec < 0:
        raise bad("'%s' may not be negative." % name)
    if dec < Decimal(str(minimum)) or dec > Decimal(str(maximum)):
        raise bad("'%s' must lie between %s and %s inclusive." % (name, minimum, maximum))
    exponent = dec.normalize().as_tuple().exponent
    if exponent < -max_decimals:
        raise bad("'%s' carries at most %d decimals." % (name, max_decimals))
    return value


def _check_array(value, name, allow_empty):
    if not isinstance(value, list):
        raise bad("'%s' must be an array." % name)
    if not allow_empty and len(value) == 0:
        raise bad("'%s' may not be empty." % name)
    return value


def req_code_array(body, name, allow_empty=True, must_include=None):
    value = _check_array(require_present(body, name), name, allow_empty)
    for item in value:
        if not isinstance(item, str) or not TWO_LETTER.match(item):
            raise bad("'%s' entries must be two-letter uppercase codes." % name)
    if len(set(value)) != len(value):
        raise bad("'%s' entries must be distinct." % name)
    if must_include is not None and must_include not in value:
        raise bad("'%s' must include '%s'." % (name, must_include))
    return value


def req_tag_array(body, name, allow_empty=True):
    value = _check_array(require_present(body, name), name, allow_empty)
    for item in value:
        if not isinstance(item, str) or not UPPER_SNAKE.match(item):
            raise bad("'%s' entries must be upper-snake-case tags." % name)
    if len(set(value)) != len(value):
        raise bad("'%s' entries must be distinct." % name)
    return value


def req_enum_array(body, name, allowed, allow_empty=True):
    value = _check_array(require_present(body, name), name, allow_empty)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad("'%s' entries must be drawn from %s." % (name, ", ".join(sorted(allowed))))
    if len(set(value)) != len(value):
        raise bad("'%s' entries must be distinct." % name)
    return value


def req_text_array(body, name, min_len=1, max_len=200, allow_empty=True):
    value = _check_array(require_present(body, name), name, allow_empty)
    for item in value:
        if not isinstance(item, str):
            raise bad("'%s' entries must be strings." % name)
        if len(item) < min_len or len(item) > max_len:
            raise bad("'%s' entries must be %d to %d characters." % (name, min_len, max_len))
    if len(set(value)) != len(value):
        raise bad("'%s' entries must be distinct." % name)
    return value


def req_id(body, name):
    """Foreign keys are validated for shape at rank 8; existence is rank 5."""
    value = require_present(body, name)
    if not isinstance(value, str) or value.strip() == "":
        raise bad("'%s' must be a non-blank string identifier." % name)
    return value


def parse_instant(value, name):
    """Parse an ISO 8601 instant to whole-second UTC resolution (PRD 2.9)."""
    if not isinstance(value, str) or value.strip() == "":
        raise bad("'%s' must be an ISO 8601 timestamp string." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad("'%s' must be an ISO 8601 timestamp string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def req_instant(body, name):
    raw = require_present(body, name)
    return parse_instant(raw, name), raw


def opt_instant(body, name):
    if not present(body, name):
        return None, None
    return req_instant(body, name)
