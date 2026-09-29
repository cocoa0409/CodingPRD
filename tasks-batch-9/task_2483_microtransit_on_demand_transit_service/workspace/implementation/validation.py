"""Request-shape validation (PRD Section 2.9 step 7 -> ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError

MISSING = object()


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """Parse the JSON body; an absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        invalid("Request body must be a JSON object.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


# --------------------------------------------------------------------------
# scalar helpers
# --------------------------------------------------------------------------

def _present(body, field):
    value = body.get(field, MISSING)
    if value is MISSING:
        invalid("Field '%s' is required." % field)
    return value


def req_str(body, field, min_len=1, max_len=None):
    value = _present(body, field)
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % field)
    if len(value) < min_len:
        invalid("Field '%s' must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' must be at most %d characters." % (field, max_len))
    return value


def opt_str(body, field, default=None, min_len=1, max_len=None):
    value = body.get(field, MISSING)
    if value is MISSING or value is None:
        return default
    return req_str(body, field, min_len=min_len, max_len=max_len)


def _check_int(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be <= %s." % (field, maximum))
    return value


def req_int(body, field, minimum=None, maximum=None):
    return _check_int(field, _present(body, field), minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    value = body.get(field, MISSING)
    if value is MISSING or value is None:
        return default
    return _check_int(field, value, minimum, maximum)


def req_number(body, field, minimum=None, maximum=None, max_dp=None):
    value = _present(body, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        invalid("Field '%s' must be a number." % field)
    if minimum is not None and dec < Decimal(str(minimum)):
        invalid("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        invalid("Field '%s' must be <= %s." % (field, maximum))
    if max_dp is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_dp:
            invalid("Field '%s' accepts at most %d decimal places." % (field, max_dp))
    return value


def req_bool(body, field):
    value = _present(body, field)
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % field)
    return value


def opt_bool(body, field, default=False):
    value = body.get(field, MISSING)
    if value is MISSING or value is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, members):
    value = _present(body, field)
    if not isinstance(value, str) or value not in members:
        invalid("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def opt_enum(body, field, members, default=None):
    value = body.get(field, MISSING)
    if value is MISSING or value is None:
        return default
    return req_enum(body, field, members)


def req_datetime(body, field):
    """Return (raw_string, aware_datetime); the raw string is echoed back."""
    value = _present(body, field)
    if not isinstance(value, str):
        invalid("Field '%s' must be an ISO 8601 datetime string." % field)
    parsed = clock.parse_dt(value)
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 datetime string." % field)
    return value, parsed


def req_date(body, field):
    value = _present(body, field)
    if not isinstance(value, str) or not clock.is_date_string(value):
        invalid("Field '%s' must be a YYYY-MM-DD date string." % field)
    return value


def req_id(body, field):
    """A foreign key that must be a non-empty string once shape is checked."""
    return req_str(body, field, min_len=1)


def raw_fk(body, field):
    """The raw value of a foreign key, for the priority-5 existence pass.

    Missing / non-string values are deferred to the shape pass so that
    ERR_INVALID_REQUEST -- not a not-found code -- is reported for them.
    """
    value = body.get(field, MISSING)
    if value is MISSING or value is None or not isinstance(value, str) or value == "":
        return None
    return value


# --------------------------------------------------------------------------
# query-string helpers
# --------------------------------------------------------------------------

def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = 10
    else:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer.")
        if str(limit_value) != limit.strip():
            invalid("Query parameter 'limit' must be an integer.")
        if limit_value < 1 or limit_value > 100:
            invalid("Query parameter 'limit' must be between 1 and 100.")
    if offset is None or offset == "":
        offset_value = 0
    else:
        try:
            offset_value = int(offset)
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer.")
        if str(offset_value) != offset.strip():
            invalid("Query parameter 'offset' must be an integer.")
        if offset_value < 0:
            invalid("Query parameter 'offset' must be >= 0.")
    return limit_value, offset_value


_TRUE = {"true", "True", "TRUE", "1"}
_FALSE = {"false", "False", "FALSE", "0"}


def filters(rows, spec):
    """Apply optional equality filters.

    ``spec`` maps a query-parameter name to either the record field name
    (string equality) or a ``(field, "bool")`` pair.
    """
    out = rows
    for param, target in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if isinstance(target, tuple):
            field, kind = target
        else:
            field, kind = target, "str"
        if kind == "bool":
            if raw in _TRUE:
                wanted = True
            elif raw in _FALSE:
                wanted = False
            else:
                return []
            out = [r for r in out if r.get(field) is wanted]
        else:
            out = [r for r in out if r.get(field) == raw]
    return out


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
