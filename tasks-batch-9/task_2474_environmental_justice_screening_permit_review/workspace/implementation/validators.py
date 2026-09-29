"""Request well-formedness checks (rejection ladder step 4 -> ERR_INVALID_REQUEST)."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from constants import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import bad_request

_SENTINEL = object()
_LANG_RE = re.compile(r"^[a-z]{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body_json():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise bad_request("Request body must be a JSON object.")
    return payload


def _present(body, name):
    return name in body and body[name] is not None


def _missing(body, name, required, default):
    if required:
        raise bad_request("Field '%s' is required." % name)
    return default


# ------------------------------------------------------------------ scalars
def f_str(body, name, required=True, default=None, min_len=None, max_len=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def f_lang(body, name, required=True, default=None):
    value = f_str(body, name, required=required, default=default)
    if value is default and not _present(body, name):
        return default
    if not _LANG_RE.match(value):
        raise bad_request("Field '%s' must be a 2-character lower-case ISO 639-1 code." % name)
    return value


def f_bool(body, name, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % name)
    return value


def f_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and float(value).is_integer():
        result = int(value)
    else:
        raise bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and result < minimum:
        raise bad_request("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and result > maximum:
        raise bad_request("Field '%s' must be at most %s." % (name, maximum))
    return result


def f_num(body, name, required=True, default=None, minimum=None, maximum=None,
          exclusive_min=None):
    """Decimal-valued numeric field."""
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise bad_request("Field '%s' must be a number." % name)
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise bad_request("Field '%s' must be a number." % name)
    if not result.is_finite():
        raise bad_request("Field '%s' must be a finite number." % name)
    if exclusive_min is not None and result <= exclusive_min:
        raise bad_request("Field '%s' must be greater than %s." % (name, exclusive_min))
    if minimum is not None and result < minimum:
        raise bad_request("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and result > maximum:
        raise bad_request("Field '%s' must be at most %s." % (name, maximum))
    return result


def f_num_unchecked(body, name, required=True, default=None):
    """Numeric field whose range is policed by a dedicated business error."""
    return f_num(body, name, required=required, default=default)


def f_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "Field '%s' must be one of: %s." % (name, ", ".join(allowed))
        )
    return value


def f_lang_array(body, name, required=False, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default if default is not None else [])
    value = body[name]
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or not _LANG_RE.match(item):
            raise bad_request(
                "Field '%s' must contain 2-character lower-case ISO 639-1 codes." % name
            )
    return list(value)


def f_date(body, name, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise bad_request("Field '%s' must be an ISO 8601 UTC date (YYYY-MM-DD)." % name)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise bad_request("Field '%s' must be a valid ISO 8601 date." % name)


def parse_instant(value, name):
    if not isinstance(value, str) or len(value.strip()) == 0:
        raise bad_request("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    text = value.strip()
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise bad_request("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def f_instant(body, name, required=True, default=None):
    """Returns (raw_string, datetime) so the stored payload echoes the client format."""
    if not _present(body, name):
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default, None
    raw = body[name]
    return raw, parse_instant(raw, name)


# ------------------------------------------------------------------ query string
def q_pagination():
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise bad_request("Query parameter '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_date(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if not _DATE_RE.match(value):
        raise bad_request("Query parameter '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise bad_request("Query parameter '%s' must be a valid ISO 8601 date." % name)
