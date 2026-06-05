"""Shared parsing / validation / datetime / pagination helpers."""

from datetime import datetime, timedelta, timezone

from flask import request

import db
import errors


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON body as a dict. A missing body is treated as {}.
    A malformed body or a non-object body -> ERR_INVALID_REQUEST (400)."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Scalar field validators (all raise ERR_INVALID_REQUEST on type/range issues)
# ---------------------------------------------------------------------------
def req_string(body, field, min_len=1, max_len=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    return _check_string(body[field], field, min_len, max_len)


def opt_string(body, field, default=None, min_len=1, max_len=None):
    if field not in body or body[field] is None:
        return default
    return _check_string(body[field], field, min_len, max_len)


def _check_string(val, field, min_len, max_len):
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be a string.")
    if min_len is not None and len(val) < min_len:
        raise errors.invalid_request(f"Field '{field}' too short.")
    if max_len is not None and len(val) > max_len:
        raise errors.invalid_request(f"Field '{field}' too long.")
    return val


def _is_int(val):
    # bool is a subclass of int; reject it as an integer value.
    return isinstance(val, int) and not isinstance(val, bool)


def req_int(body, field, min_val=None, max_val=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    return _check_int(body[field], field, min_val, max_val)


def opt_int(body, field, default=None, min_val=None, max_val=None):
    if field not in body or body[field] is None:
        return default
    return _check_int(body[field], field, min_val, max_val)


def _check_int(val, field, min_val, max_val):
    if not _is_int(val):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if min_val is not None and val < min_val:
        raise errors.invalid_request(f"Field '{field}' below minimum.")
    if max_val is not None and val > max_val:
        raise errors.invalid_request(f"Field '{field}' above maximum.")
    return val


def req_number(body, field, min_excl=None, max_incl=None, min_incl=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    return _check_number(body[field], field, min_excl, max_incl, min_incl)


def opt_number(body, field, default=None, min_excl=None, max_incl=None, min_incl=None):
    if field not in body or body[field] is None:
        return default
    return _check_number(body[field], field, min_excl, max_incl, min_incl)


def _check_number(val, field, min_excl, max_incl, min_incl):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number.")
    f = float(val)
    if min_excl is not None and not (f > min_excl):
        raise errors.invalid_request(f"Field '{field}' must be > {min_excl}.")
    if min_incl is not None and not (f >= min_incl):
        raise errors.invalid_request(f"Field '{field}' must be >= {min_incl}.")
    if max_incl is not None and not (f <= max_incl):
        raise errors.invalid_request(f"Field '{field}' must be <= {max_incl}.")
    return f


def req_enum(body, field, allowed):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    return _check_enum(body[field], field, allowed)


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return _check_enum(body[field], field, allowed)


def _check_enum(val, field, allowed):
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def opt_enum_array(body, field, allowed, default=None):
    """An array whose elements must each be in `allowed`. Empty list allowed."""
    if field not in body or body[field] is None:
        return list(default) if default is not None else []
    val = body[field]
    if not isinstance(val, list):
        raise errors.invalid_request(f"Field '{field}' must be an array.")
    for el in val:
        if not isinstance(el, str) or el not in allowed:
            raise errors.invalid_request(
                f"Field '{field}' must be a subset of {sorted(allowed)}."
            )
    return val


def opt_id(body, field, default=None):
    """An optional FK string id (or null). Existence is checked separately."""
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or len(val) == 0:
        raise errors.invalid_request(f"Field '{field}' must be a string id.")
    return val


def req_id(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if not isinstance(val, str) or len(val) == 0:
        raise errors.invalid_request(f"Field '{field}' must be a string id.")
    return val


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ---------------------------------------------------------------------------
def parse_iso_datetime(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field '{field}'.")
        return None
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be an ISO 8601 string.")
    dt = parse_iso_string(val)
    if dt is None:
        raise errors.invalid_request(f"Field '{field}' is not a valid ISO 8601 timestamp.")
    return dt


def parse_iso_string(val):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime, or None."""
    if not isinstance(val, str):
        return None
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def timedelta_days(days):
    return timedelta(days=days)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10 [1,100], offset default 0 (>=0)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination()
        if limit < 1 or limit > 100:
            raise errors.invalid_pagination()

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination()
        if offset < 0:
            raise errors.invalid_pagination()

    return limit, offset


def sort_by_created(rows):
    """Sort by created_at ASC, tie-broken by the monotonic creation sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate(rows, limit, offset):
    """rows already sorted; return (page_slice, total_count)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
