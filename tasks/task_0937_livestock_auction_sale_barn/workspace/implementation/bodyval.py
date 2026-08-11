"""Ladder rungs 4, 5, 6 and 7 helpers (PRD 2.7, 2.9).

Rung 4 - presence + declared JSON type          -> ERR_INVALID_REQUEST (400)
Rung 5 - closed-set membership, exhaustive list  -> ERR_INVALID_ENUM (400)
Rung 6 - numeric sign / range constraints        -> ERR_INVALID_REQUEST (400)
Rung 7 - body foreign keys resolve               -> ERR_REFERENCE_NOT_FOUND (404)

THE EXHAUSTIVE ENUM LIST (PRD 2.9): exactly and only the fields routed through
``enum_field()`` below answer ERR_INVALID_ENUM. Query-string filters are
deliberately excluded - they never error, an unknown filter value simply
matches nothing - and every other out-of-range value answers ERR_INVALID_REQUEST
(rung 4/6) or ERR_INVALID_STATE (rung 16).
"""
from flask import request

from errors import fail
from money import D
from store import get


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# --------------------------------------------------------------- rung 4 ----
def _is_string(v):
    return isinstance(v, str)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_bool(v):
    return isinstance(v, bool)


_CHECKERS = {
    "string": _is_string,
    "integer": _is_int,
    "number": _is_number,
    "boolean": _is_bool,
}


def require(data, name, kind):
    """Rung 4: required field, declared JSON type."""
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not _CHECKERS[kind](value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a %s." % (name, kind))
    return value


def optional(data, name, kind, default=None):
    """Rung 4 for an optional field: when present it must carry its type."""
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not _CHECKERS[kind](value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a %s." % (name, kind))
    return value


def fields(data, required=(), optional=()):
    """Rung 4 in one sweep: every required field present with its declared
    JSON type, then every supplied optional field with its declared type.
    Running this BEFORE any enum or numeric check is what keeps rung 4 above
    rungs 5 and 6 on the ladder."""
    out = {}
    for name, kind in required:
        out[name] = require(data, name, kind)
    for entry in optional:
        name, kind = entry[0], entry[1]
        default = entry[2] if len(entry) > 2 else None
        out[name] = optional_field(data, name, kind, default)
    return out


def optional_field(data, name, kind, default=None):
    return optional(data, name, kind, default)


# --------------------------------------------------------------- rung 5 ----
def enum_field(data, name, vocabulary, required=True, default=None):
    """Rung 5: a closed-vocabulary field. This is the ONLY door to
    ERR_INVALID_ENUM anywhere in the API."""
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if value not in vocabulary:
        fail("ERR_INVALID_ENUM", "Field '%s' must be one of %s."
             % (name, ", ".join(vocabulary)))
    return value


# --------------------------------------------------------------- rung 6 ----
def check_min(value, minimum, name, inclusive=True):
    if value is None:
        return
    v = D(value)
    if inclusive and v < D(minimum):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, minimum))
    if not inclusive and v <= D(minimum):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (name, minimum))


def check_max(value, maximum, name):
    if value is None:
        return
    if D(value) > D(maximum):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, maximum))


# --------------------------------------------------------------- rung 7 ----
def reference(table, row_id, label=None):
    """Rung 7: a body-supplied foreign key must resolve."""
    row = get(table, row_id)
    if row is None:
        fail("ERR_REFERENCE_NOT_FOUND",
             "%s '%s' does not exist." % (label or table, row_id))
    return row


def path_row(table, row_id, label=None):
    """Rung 3: a path id must resolve, left to right."""
    row = get(table, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND",
             "%s '%s' does not exist." % (label or table, row_id))
    return row
