"""Request shape validation (ladder step 7) and pagination (PRD 2.3)."""
import re

from flask import request

import clock
import db
from errors import ApiError

PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


# --- scalars ---------------------------------------------------------------

def req_str(body, name, min_len=1, max_len=None):
    if not present(body, name):
        bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str) or len(value) < min_len:
        bad("Field '%s' must be a string of at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(body, name, default=None, min_len=1, max_len=None):
    if not present(body, name):
        return default
    return req_str(body, name, min_len, max_len)


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not present(body, name):
        bad("Field '%s' is required." % name)
    return _check_int(name, body[name], minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not present(body, name):
        return default
    return _check_int(name, body[name], minimum, maximum)


def _check_number(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def req_number(body, name, minimum=None, maximum=None):
    if not present(body, name):
        bad("Field '%s' is required." % name)
    return _check_number(name, body[name], minimum, maximum)


def opt_number(body, name, default=None, minimum=None, maximum=None):
    if not present(body, name):
        return default
    return _check_number(name, body[name], minimum, maximum)


def req_bool(body, name):
    if not present(body, name):
        bad("Field '%s' is required." % name)
    if not isinstance(body[name], bool):
        bad("Field '%s' must be a boolean." % name)
    return body[name]


def opt_bool(body, name, default=False):
    if not present(body, name):
        return default
    return req_bool(body, name)


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_instant(body, name):
    value = req_str(body, name)
    if clock.parse_instant(value) is None:
        bad("Field '%s' must be an ISO 8601 instant." % name)
    return value


def opt_instant(body, name, default=None):
    if not present(body, name):
        return default
    return req_instant(body, name)


def req_period_month(body, name="period_month"):
    value = req_str(body, name)
    if not PERIOD_MONTH_RE.match(value):
        bad("Field '%s' must match YYYY-MM." % name)
    return value


def req_array(body, name, non_empty=True):
    if not present(body, name):
        bad("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if non_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % name)
    return value


def opt_array(body, name, default=None, non_empty=False):
    if not present(body, name):
        return default
    return req_array(body, name, non_empty)


def req_str_array(body, name, non_empty=True):
    values = req_array(body, name, non_empty)
    for item in values:
        if not isinstance(item, str) or item == "":
            bad("Field '%s' must contain non-empty strings." % name)
    return values


def req_enum_array(body, name, allowed, non_empty=True):
    values = req_str_array(body, name, non_empty)
    for item in values:
        if item not in allowed:
            bad("Field '%s' must be a subset of %s." % (name, ", ".join(sorted(allowed))))
    return values


def obj_field(item, name, label):
    if not isinstance(item, dict) or name not in item or item[name] is None:
        bad("Each entry of '%s' requires '%s'." % (label, name))
    return item[name]


def obj_int(item, name, label, minimum=None, maximum=None):
    value = obj_field(item, name, label)
    return _check_int("%s.%s" % (label, name), value, minimum, maximum)


def obj_str(item, name, label):
    value = obj_field(item, name, label)
    if not isinstance(value, str) or value == "":
        bad("Each entry of '%s' requires a non-empty '%s'." % (label, name))
    return value


def reject_unversioned(body):
    """expected_provider_version / expected_contract_version are accepted nowhere else."""
    for field in ("expected_provider_version", "expected_contract_version"):
        if field in body:
            bad("Field '%s' is not accepted on this endpoint." % field)


# --- pagination ------------------------------------------------------------

def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
        return default
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def filtered(rows, **equals):
    """Apply optional query-string equality filters conjunctively."""
    out = db.by_created_at(rows)
    for field, param in equals.items():
        wanted = request.args.get(param)
        if wanted is None or wanted == "":
            continue
        out = [r for r in out if r.get(field) == wanted]
    return out
