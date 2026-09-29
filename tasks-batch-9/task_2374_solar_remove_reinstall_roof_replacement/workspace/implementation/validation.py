"""Request-body / query-string schema validation (validation precedence step 5).

Every failure here raises ERR_INVALID_REQUEST with HTTP 422.
"""

from datetime import datetime, timezone

from flask import request

from errors import invalid_request

MISSING = object()


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise invalid_request("request body must be a JSON object")
    return body


def _raw(body, name, required):
    if name not in body or body[name] is None:
        if required:
            raise invalid_request("field '%s' is required" % name)
        return MISSING
    return body[name]


def str_field(body, name, required=True, default=None, non_empty=True, max_len=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str):
        raise invalid_request("field '%s' must be a string" % name)
    if non_empty and value.strip() == "":
        raise invalid_request("field '%s' must be non-empty" % name)
    if max_len is not None and len(value) > max_len:
        raise invalid_request("field '%s' must be at most %d characters" % (name, max_len))
    return value


def enum_field(body, name, allowed, required=True, default=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise invalid_request(
            "field '%s' must be one of %s" % (name, ", ".join(sorted(allowed)))
        )
    return value


def int_field(body, name, required=True, default=None, minimum=None, maximum=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        raise invalid_request("field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("field '%s' must be <= %s" % (name, maximum))
    return value


def num_field(body, name, required=True, default=None, minimum=None, maximum=None,
              exclusive_min=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("field '%s' must be a number" % name)
    if exclusive_min is not None and not value > exclusive_min:
        raise invalid_request("field '%s' must be greater than %s" % (name, exclusive_min))
    if minimum is not None and value < minimum:
        raise invalid_request("field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("field '%s' must be <= %s" % (name, maximum))
    return value


def bool_field(body, name, required=True, default=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        raise invalid_request("field '%s' must be a boolean" % name)
    return value


def parse_iso8601(text):
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def datetime_field(body, name, required=True, default=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    parsed = parse_iso8601(value)
    if parsed is None:
        raise invalid_request("field '%s' must be an ISO 8601 timestamp" % name)
    return parsed


def date_field(body, name, required=True, default=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str):
        raise invalid_request("field '%s' must be a YYYY-MM-DD date" % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise invalid_request("field '%s' must be a YYYY-MM-DD date" % name)
    return value


def str_list_field(body, name, allowed, required=True, default=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, list) or len(value) == 0:
        raise invalid_request("field '%s' must be a non-empty array" % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid_request(
                "field '%s' must be a non-empty subset of %s"
                % (name, ", ".join(sorted(allowed)))
            )
    return value


def pagination():
    """Read and validate the limit/offset query parameters (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("'limit' must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            raise invalid_request("'limit' must be between 1 and 100 inclusive")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("'offset' must be a non-negative integer")
        if offset < 0:
            raise invalid_request("'offset' must be a non-negative integer")
    return limit, offset


def enum_query(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise invalid_request(
            "query parameter '%s' must be one of %s" % (name, ", ".join(sorted(allowed)))
        )
    return value


def str_query(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
