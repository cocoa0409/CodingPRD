"""Request parsing, shape validation (rung 3), pagination (rung 4) and
existence resolution (rungs 5-6)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import db

# --------------------------------------------------------------------------
# body / query parsing
# --------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", message="The request body must be a JSON object.")
    return data


def _invalid(msg):
    return ApiError("ERR_INVALID_REQUEST", message=msg)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or not v.strip():
        raise _invalid("'%s' is required and must be a non-empty string." % name)
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str):
        raise _invalid("'%s' must be a string." % name)
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise _invalid("'%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return v


def opt_enum(b, name, allowed, default=None):
    if name not in b or b[name] is None:
        return default
    return req_enum(b, name, allowed)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, minimum=None, maximum=None):
    v = b.get(name)
    if not _is_int(v):
        raise _invalid("'%s' is required and must be an integer." % name)
    if minimum is not None and v < minimum:
        raise _invalid("'%s' must be at least %s." % (name, minimum))
    if maximum is not None and v > maximum:
        raise _invalid("'%s' must be at most %s." % (name, maximum))
    return v


def opt_int(b, name, default=None, minimum=None, maximum=None):
    if name not in b or b[name] is None:
        return default
    return req_int(b, name, minimum, maximum)


def _to_decimal(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float, str, Decimal)):
        raise _invalid("'%s' must be a number." % name)
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise _invalid("'%s' must be a number." % name)


def req_number(b, name, gt=None, ge=None, le=None):
    if name not in b or b[name] is None:
        raise _invalid("'%s' is required." % name)
    d = _to_decimal(b[name], name)
    _check_number_range(d, name, gt, ge, le)
    return d


def opt_number(b, name, default=None, gt=None, ge=None, le=None):
    if name not in b or b[name] is None:
        return default
    d = _to_decimal(b[name], name)
    _check_number_range(d, name, gt, ge, le)
    return d


def _check_number_range(d, name, gt, ge, le):
    if gt is not None and not d > gt:
        raise _invalid("'%s' must be greater than %s." % (name, gt))
    if ge is not None and not d >= ge:
        raise _invalid("'%s' must be at least %s." % (name, ge))
    if le is not None and not d <= le:
        raise _invalid("'%s' must be at most %s." % (name, le))


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        raise _invalid("'%s' is required and must be a boolean." % name)
    return v


def opt_bool(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, bool):
        raise _invalid("'%s' must be a boolean." % name)
    return v


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, name):
    dt = parse_dt(b.get(name))
    if dt is None:
        raise _invalid("'%s' is required and must be an ISO 8601 instant." % name)
    return dt


def opt_dt(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    dt = parse_dt(b.get(name))
    if dt is None:
        raise _invalid("'%s' must be an ISO 8601 instant." % name)
    return dt


# --------------------------------------------------------------------------
# pagination (rung 4)
# --------------------------------------------------------------------------


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def page(rows_list, limit, offset):
    total = len(rows_list)
    return rows_list[offset:offset + limit], total


# --------------------------------------------------------------------------
# existence resolution
# --------------------------------------------------------------------------


def _lookup(collection, ident, error_id):
    if not isinstance(ident, str):
        raise ApiError(error_id)
    row = collection.get(ident)
    if row is None:
        raise ApiError(error_id)
    return row


def get_chapter(ident):
    return _lookup(db.chapters, ident, "ERR_CHAPTER_NOT_FOUND")


def get_standard(ident):
    return _lookup(db.standards, ident, "ERR_STANDARD_NOT_FOUND")


def get_owner_assignment(ident):
    return _lookup(db.owner_assignments, ident, "ERR_OWNER_ASSIGNMENT_NOT_FOUND")


def get_evidence(ident):
    return _lookup(db.evidence_items, ident, "ERR_EVIDENCE_NOT_FOUND")


def get_unit(ident):
    return _lookup(db.units, ident, "ERR_UNIT_NOT_FOUND")


def get_tracer(ident):
    return _lookup(db.tracers, ident, "ERR_TRACER_NOT_FOUND")


def get_session(ident):
    return _lookup(db.rounding_sessions, ident, "ERR_ROUNDING_SESSION_NOT_FOUND")


def get_ticket(ident):
    return _lookup(db.tickets, ident, "ERR_TICKET_NOT_FOUND")


def get_window(ident):
    return _lookup(db.windows, ident, "ERR_SURVEY_WINDOW_NOT_FOUND")


def get_finding(ident):
    return _lookup(db.findings, ident, "ERR_FINDING_NOT_FOUND")


def get_ppr(ident):
    return _lookup(db.pprs, ident, "ERR_PPR_NOT_FOUND")
