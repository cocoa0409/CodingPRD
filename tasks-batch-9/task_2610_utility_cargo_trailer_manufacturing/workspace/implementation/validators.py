"""Schema conformance — PRD 2.7 step 6 (scaffold validations priority 40).

Everything in here raises ERR_INVALID_REQUEST (HTTP 400).
"""
import re
from datetime import datetime, timezone

from flask import request

import errors

CODE_RE = re.compile(r"^[A-Z0-9-]+$")
FRAME_RE = re.compile(r"^[A-Z]{2}$")


def body():
    """The parsed JSON body; a missing or non-object body reads as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid("body must be a JSON object")
    return data


def present(data, field):
    return field in data and data[field] is not None


def req_present(data, field):
    if not present(data, field):
        raise errors.invalid("%s is required" % field)
    return data[field]


def req_str(data, field, min_len=None, max_len=None, pattern=None):
    val = req_present(data, field)
    if not isinstance(val, str):
        raise errors.invalid("%s must be a string" % field)
    if min_len is not None and len(val) < min_len:
        raise errors.invalid("%s must be at least %d characters" % (field, min_len))
    if max_len is not None and len(val) > max_len:
        raise errors.invalid("%s must be at most %d characters" % (field, max_len))
    if pattern is not None and not pattern.match(val):
        raise errors.invalid("%s has an invalid format" % field)
    return val


def req_code(data, field, min_len=4, max_len=16):
    return req_str(data, field, min_len, max_len, CODE_RE)


def req_int(data, field, minimum=None, maximum=None):
    val = req_present(data, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid("%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise errors.invalid("%s must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise errors.invalid("%s must be <= %s" % (field, maximum))
    return val


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    return req_int(data, field, minimum, maximum)


def req_version(data, field):
    """Optimistic-concurrency fields are mandatory integers (PRD 2.8)."""
    val = req_present(data, field)
    if isinstance(val, bool):
        raise errors.invalid("%s must be an integer" % field)
    if isinstance(val, int):
        return val
    if isinstance(val, str) and re.match(r"^-?\d+$", val.strip()):
        return int(val.strip())
    raise errors.invalid("%s must be an integer" % field)


def req_num(data, field, minimum=None, maximum=None):
    val = req_present(data, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid("%s must be a number" % field)
    if minimum is not None and val < minimum:
        raise errors.invalid("%s must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise errors.invalid("%s must be <= %s" % (field, maximum))
    return val


def req_bool(data, field):
    val = req_present(data, field)
    if not isinstance(val, bool):
        raise errors.invalid("%s must be a boolean" % field)
    return val


def req_enum(data, field, allowed):
    val = req_present(data, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid("%s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return val


def req_id(data, field):
    val = req_present(data, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid("%s must be a string identifier" % field)
    return val


def opt_id(data, field):
    if not present(data, field):
        return None
    return req_id(data, field)


def parse_dt(raw, field):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime."""
    if not isinstance(raw, str):
        raise errors.invalid("%s must be an ISO 8601 UTC timestamp" % field)
    text = raw.strip()
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise errors.invalid("%s must be an ISO 8601 UTC timestamp" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(data, field):
    """Returns (raw string as supplied, parsed datetime)."""
    raw = req_present(data, field)
    return raw, parse_dt(raw, field)


def opt_dt(data, field):
    if not present(data, field):
        return None, None
    return req_dt(data, field)


def pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        if not re.match(r"^-?\d+$", raw.strip()):
            raise errors.invalid("limit must be an integer")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            raise errors.invalid("limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        if not re.match(r"^-?\d+$", raw.strip()):
            raise errors.invalid("offset must be an integer")
        offset = int(raw.strip())
        if offset < 0:
            raise errors.invalid("offset must be >= 0")
    return limit, offset


def query_flag(name, default=False):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise errors.invalid("%s must be a boolean" % name)


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise errors.invalid("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return raw


def request_arg(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def opt_str(data, field, min_len=None, max_len=None, pattern=None):
    if not present(data, field):
        return None
    return req_str(data, field, min_len=min_len, max_len=max_len, pattern=pattern)
