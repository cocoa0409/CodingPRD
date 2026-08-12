"""Record factory + payload field validators (ERR_INVALID_REQUEST on shape)."""

from decimal import Decimal, InvalidOperation

import db
from errors import invalid_request, not_found
from util import new_id, now_iso, next_seq, to_d


def new_record(slim=False):
    r = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}
    if not slim:
        r["updated_at"] = r["created_at"]
        r["version"] = 1
    return r


def touch(rec):
    """Refresh updated_at (version bumps only where the spec states them)."""
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()


def req_field(data, name):
    if name not in data or data[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return data[name]


def as_str(value, name):
    if not isinstance(value, str) or not value:
        raise invalid_request("Field %s must be a non-empty string" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field %s must be an integer" % name)
    return value


def as_decimal(value, name):
    try:
        return to_d(value)
    except (ValueError, InvalidOperation):
        raise invalid_request("Field %s must be a number" % name)


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise invalid_request("Field %s must be one of %s" % (name, "|".join(allowed)))
    return value


def opt_str(data, name, default=None):
    v = data.get(name, default)
    if v is not None and not isinstance(v, str):
        raise invalid_request("Field %s must be a string" % name)
    return v


def opt_int(data, name, default=None):
    v = data.get(name, default)
    if v is not None:
        v = as_int(v, name)
    return v


def opt_bool(data, name, default=False):
    v = data.get(name, default)
    return as_bool(v, name)


def opt_enum(data, name, allowed, default):
    v = data.get(name, default)
    return as_enum(v, name, allowed)


def occ_early(data, term):
    """OCC pre-check (runs right after existence): a present, well-typed
    expected_term_version that mismatches the term's version -> 412.
    Missing/ill-typed values defer to shape validation (400) later."""
    from errors import ApiError, ERR_STALE_TERM_VERSION
    v = data.get("expected_term_version")
    if isinstance(v, int) and not isinstance(v, bool):
        if v != term["version"]:
            raise ApiError(ERR_STALE_TERM_VERSION, 412,
                           "expected_term_version does not match the term's "
                           "current version")


def occ_required(data):
    """Shape-stage check: expected_term_version is non-optional."""
    if "expected_term_version" not in data or data["expected_term_version"] is None:
        raise invalid_request("Missing required field: expected_term_version")
    as_int(data["expected_term_version"], "expected_term_version")


def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise not_found()
    return rec


def fk_or_404(table, value, name):
    """Body-referenced FK existence (only when a value was supplied)."""
    if value is None:
        return None
    rec = table.get(value)
    if rec is None:
        raise not_found("Referenced %s does not exist" % name)
    return rec
