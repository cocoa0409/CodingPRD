"""Request-body shape checking, pagination and path/FK resolution."""

from flask import request

import store
from errors import fail

MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(name, why="is invalid"):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def req_str(data, name, min_len=1, max_len=None):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(name, "is required")
    if not isinstance(v, str):
        _bad(name, "must be a string")
    if len(v) < min_len:
        _bad(name, "is too short")
    if max_len is not None and len(v) > max_len:
        _bad(name, "is too long")
    return v


def opt_str(data, name, default=None):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def req_enum(data, name, allowed):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(name, "is required")
    if not isinstance(v, str) or v not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return v


def opt_enum(data, name, allowed, default=None):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return v


def req_int(data, name, lo=None, hi=None):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(name, "is required")
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "must be an integer")
    if lo is not None and v < lo:
        _bad(name, "is below the allowed minimum")
    if hi is not None and v > hi:
        _bad(name, "is above the allowed maximum")
    return v


def req_number(data, name, lo=None, hi=None):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(name, "is required")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "must be a number")
    if lo is not None and v < lo:
        _bad(name, "is below the allowed minimum")
    if hi is not None and v > hi:
        _bad(name, "is above the allowed maximum")
    return v


def req_dt(data, name):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(name, "is required")
    dt = store.parse_dt(v)
    if dt is None:
        _bad(name, "must be a valid ISO 8601 UTC instant")
    return dt


def opt_dt(data, name):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        return None
    dt = store.parse_dt(v)
    if dt is None:
        _bad(name, "must be a valid ISO 8601 UTC instant")
    return dt


def req_id(data, name):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(name, "is required")
    if not isinstance(v, str) or v.strip() == "":
        _bad(name, "must be a non-empty string identifier")
    return v


def opt_id(data, name):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        return None
    if not isinstance(v, str) or v.strip() == "":
        _bad(name, "must be a non-empty string identifier")
    return v


def req_id_list(data, name):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        _bad(name, "is required")
    if not isinstance(v, list):
        _bad(name, "must be an array")
    for entry in v:
        if not isinstance(entry, str) or entry.strip() == "":
            _bad(name, "must contain only non-empty string identifiers")
    return list(v)


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must not be negative")
    return limit, offset


def query_enum(name, allowed):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return v


def query_str(name):
    v = request.args.get(name)
    if v is None:
        return None
    return v


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

_TABLE_ERROR = {
    "board_members": "ERR_BOARD_MEMBER_NOT_FOUND",
    "committees": "ERR_COMMITTEE_NOT_FOUND",
    "assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "disclosures": "ERR_DISCLOSURE_NOT_FOUND",
    "policies": "ERR_POLICY_NOT_FOUND",
    "policy_versions": "ERR_POLICY_VERSION_NOT_FOUND",
    "mandates": "ERR_MANDATE_NOT_FOUND",
    "meetings": "ERR_MEETING_NOT_FOUND",
    "agenda_items": "ERR_AGENDA_ITEM_NOT_FOUND",
    "public_comments": "ERR_AGENDA_ITEM_NOT_FOUND",
    "waivers": "ERR_WAIVER_NOT_FOUND",
    "evaluations": "ERR_EVALUATION_NOT_FOUND",
    "ratings": "ERR_EVALUATION_NOT_FOUND",
    "publications": "ERR_PUBLICATION_NOT_FOUND",
}


def find(table, rec_id):
    rec = store.db[table].get(rec_id)
    if rec is None:
        fail(_TABLE_ERROR[table], "Resource %s was not found." % rec_id)
    return rec


def maybe(table, rec_id):
    return store.db[table].get(rec_id)
