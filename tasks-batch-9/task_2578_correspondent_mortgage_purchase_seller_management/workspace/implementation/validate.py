"""Request schema validation (PRD 2.5 group 4) and pagination (PRD 2.3)."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_date, parse_instant

MISSING = object()


def bad(message="The request body is invalid."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body; a malformed or absent body behaves as empty."""
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("The request body must be a JSON object.")
    return data


def _present(payload, key):
    return key in payload and payload[key] is not None


def opt_present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, min_len=None, max_len=None, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % key)
    return value


def req_int(payload, key, minimum=None, maximum=None, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below the accepted minimum." % key)
    if maximum is not None and value > maximum:
        bad("Field '%s' is above the accepted maximum." % key)
    return value


def req_num(payload, key, minimum=None, maximum=None, required=True, default=None):
    """A `_pct` style numeric field. Returned as Decimal for exact arithmetic."""
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' is below the accepted minimum." % key)
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' is above the accepted maximum." % key)
    return dec


def req_bool(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def req_enum(payload, key, members, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def req_date(payload, key, required=True, default=None):
    """Returns (raw_string, date) or (default, None)."""
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default, None
    value = payload[key]
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % key)
    return value, parsed


def req_instant(payload, key, required=True):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    parsed = parse_instant(payload[key])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def req_enum_array(payload, key, members, required=True, default=None):
    if not _present(payload, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, list) or not value:
        bad("Field '%s' must be a non-empty array." % key)
    for item in value:
        if not isinstance(item, str) or item not in members:
            bad("Field '%s' contains an undeclared member." % key)
    if len(set(value)) != len(value):
        bad("Field '%s' contains duplicates." % key)
    return list(value)


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
