"""Request-shape validation (PRD s2.7 step 5) and lookup helpers."""
import re
from datetime import date

from flask import request

import store
from constants import (
    PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX, PAGE_LIMIT_MIN,
)
from errors import ApiError
from store import DB

BAD = "ERR_INVALID_REQUEST"

TABLE_FOR = {
    "Building": ("buildings", "ERR_BUILDING_NOT_FOUND"),
    "Floor": ("floors", "ERR_FLOOR_NOT_FOUND"),
    "Room": ("rooms", "ERR_ROOM_NOT_FOUND"),
    "Student": ("students", "ERR_STUDENT_NOT_FOUND"),
    "RAApplication": ("applications", "ERR_APPLICATION_NOT_FOUND"),
    "RA": ("ras", "ERR_RA_NOT_FOUND"),
    "DutyShift": ("shifts", "ERR_SHIFT_NOT_FOUND"),
    "IncidentReport": ("incidents", "ERR_INCIDENT_NOT_FOUND"),
    "ConductCase": ("conduct_cases", "ERR_CONDUCT_CASE_NOT_FOUND"),
    "RoomInspection": ("inspections", "ERR_INSPECTION_NOT_FOUND"),
    "DamageCharge": ("charges", "ERR_CHARGE_NOT_FOUND"),
    "RoomChangeCase": ("rc_cases", "ERR_ROOM_CHANGE_CASE_NOT_FOUND"),
    "ProgramEvent": ("events", "ERR_PROGRAM_EVENT_NOT_FOUND"),
    "BreakHousingRequest": ("breaks", "ERR_BREAK_REQUEST_NOT_FOUND"),
}


def must_get(kind, row_id):
    table, err = TABLE_FOR[kind]
    row = store.get(table, row_id)
    if row is None:
        raise ApiError(err)
    return row


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(BAD)
    return data


def _present(b, key):
    return key in b and b[key] is not None


def s_str(b, key, required=True, default=None, allow_empty=False, pattern=None,
          min_len=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    value = b[key]
    if not isinstance(value, str):
        raise ApiError(BAD, "Field '%s' must be a string." % key)
    if not allow_empty and not value.strip():
        raise ApiError(BAD, "Field '%s' must be non-empty." % key)
    if min_len is not None and len(value) < min_len:
        raise ApiError(BAD, "Field '%s' is too short." % key)
    if pattern is not None and not re.match(pattern, value):
        raise ApiError(BAD, "Field '%s' is malformed." % key)
    return value


def s_enum(b, key, allowed, required=True, default=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    value = b[key]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(BAD, "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def s_int(b, key, lo=None, hi=None, required=True, default=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(BAD, "Field '%s' must be an integer." % key)
    if lo is not None and value < lo:
        raise ApiError(BAD, "Field '%s' is below its minimum." % key)
    if hi is not None and value > hi:
        raise ApiError(BAD, "Field '%s' is above its maximum." % key)
    return value


def s_num(b, key, lo=None, hi=None, required=True, default=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(BAD, "Field '%s' must be a number." % key)
    if lo is not None and value < lo:
        raise ApiError(BAD, "Field '%s' is below its minimum." % key)
    if hi is not None and value > hi:
        raise ApiError(BAD, "Field '%s' is above its maximum." % key)
    return value


def s_bool(b, key, required=False, default=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    value = b[key]
    if not isinstance(value, bool):
        raise ApiError(BAD, "Field '%s' must be a boolean." % key)
    return value


def s_dt(b, key, required=True, default=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    try:
        return store.parse_iso(b[key])
    except Exception:
        raise ApiError(BAD, "Field '%s' must be an ISO 8601 datetime." % key)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def s_date(b, key, required=True, default=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    value = b[key]
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ApiError(BAD, "Field '%s' must be a YYYY-MM-DD date." % key)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise ApiError(BAD, "Field '%s' must be a YYYY-MM-DD date." % key)


def s_list(b, key, required=True, default=None, allow_empty=True):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default if default is not None else []
    value = b[key]
    if not isinstance(value, list):
        raise ApiError(BAD, "Field '%s' must be an array." % key)
    if not allow_empty and not value:
        raise ApiError(BAD, "Field '%s' must not be empty." % key)
    return value


def s_id(b, key, required=True, default=None):
    if not _present(b, key):
        if required:
            raise ApiError(BAD, "Missing required field '%s'." % key)
        return default
    value = b[key]
    if not isinstance(value, str) or not value.strip():
        raise ApiError(BAD, "Field '%s' must be an identifier string." % key)
    return value


# ----------------------------------------------------------------- paging
def pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw_limit = args.get("limit")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(BAD, "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(BAD, "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw_offset = args.get("offset")
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(BAD, "offset must be an integer.")
        if offset < 0:
            raise ApiError(BAD, "offset must not be negative.")
    return limit, offset


def apply_filters(rows, spec):
    """spec: {query_param: entity_field}. Equality filters, conjunctive."""
    import serializers
    args = request.args
    active = {p: f for p, f in spec.items() if p in args and args.get(p) != ""}
    if not active:
        return rows
    out = []
    for row in rows:
        view = serializers.serialize(row)
        keep = True
        for param, field in active.items():
            if str(view.get(field)) != args.get(param):
                keep = False
                break
        if keep:
            out.append(row)
    return out


def listing(table, spec):
    limit, offset = pagination()
    rows = store.all_rows(table)
    rows = apply_filters(rows, spec)
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total, limit, offset
