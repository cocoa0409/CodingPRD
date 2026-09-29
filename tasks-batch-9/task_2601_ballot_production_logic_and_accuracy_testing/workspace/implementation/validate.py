"""Payload and query-string schema validation.

Unknown extra fields are not schema violations -- they are ignored, and the
response echoes only declared fields.
"""

from flask import request

import envelope
import util
from errors import fail


def body():
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


def _present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key):
    if not _present(payload, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    return value


def opt_str(payload, key, default=None):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %d." % (key, maximum))
    return value


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if not _present(payload, key):
        return default
    return req_int(payload, key, minimum, maximum)


def req_bool(payload, key):
    if not _present(payload, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def opt_bool(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_bool(payload, key)


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not _present(payload, key):
        return default
    return req_enum(payload, key, allowed)


def req_ts(payload, key):
    raw = req_str(payload, key)
    parsed = util.parse_ts(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a parseable ISO 8601 UTC instant." % key)
    return parsed


def opt_ts(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_ts(payload, key)


def req_str_set(payload, key, allowed=None, must_contain=()):
    """Non-empty array of strings, de-duplicated, compared as a set."""
    if not _present(payload, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, list) or not value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array of strings." % key)
    out = []
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain only strings." % key)
        if allowed is not None and item not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains unknown value '%s'." % (key, item))
        if item not in out:
            out.append(item)
    for needed in must_contain:
        if needed not in out:
            fail("ERR_INVALID_REQUEST", "Field '%s' must include '%s'." % (key, needed))
    return out


def req_marks(payload, key, min_mark_count=1):
    """Array of {contest_id, candidate_id, mark_count} objects."""
    if not _present(payload, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    out = []
    for entry in value:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each '%s' entry must be an object." % key)
        contest_id = req_str(entry, "contest_id")
        candidate_id = req_str(entry, "candidate_id")
        mark_count = req_int(entry, "mark_count", minimum=min_mark_count)
        out.append({
            "contest_id": contest_id,
            "candidate_id": candidate_id,
            "mark_count": mark_count,
        })
    return out


def pagination():
    limit = envelope.PAGE_LIMIT_DEFAULT
    offset = envelope.PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < envelope.PAGE_LIMIT_MIN or limit > envelope.PAGE_LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between %d and %d."
                 % (envelope.PAGE_LIMIT_MIN, envelope.PAGE_LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be zero or greater.")
    return limit, offset


def query_enum(name, allowed, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    return raw


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
