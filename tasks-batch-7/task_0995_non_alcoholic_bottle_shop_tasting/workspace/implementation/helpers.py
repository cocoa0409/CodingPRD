"""Shared helpers: body parsing, field validation, pagination, public shaping."""
import re
from datetime import datetime, date

from flask import request

from errors import invalid_request, not_found

# Fields the server manages; client input may never set or override them.
RESERVED_INPUT_FIELDS = {
    "id", "created_at", "updated_at", "version", "_seq",
}


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("JSON body must be an object")
    return data


def _missing(data, field):
    return field not in data or data[field] is None


def req_str(data, field, min_len=None, max_len=None, pattern=None):
    if _missing(data, field) or not isinstance(data[field], str):
        raise invalid_request("Field '%s' is required and must be a string" % field)
    v = data[field]
    if min_len is not None and len(v) < min_len:
        raise invalid_request("Field '%s' is too short" % field)
    if max_len is not None and len(v) > max_len:
        raise invalid_request("Field '%s' is too long" % field)
    if pattern is not None and not re.fullmatch(pattern, v):
        raise invalid_request("Field '%s' has invalid format" % field)
    return v


def opt_str(data, field, default=None):
    if field not in data:
        return default
    if data[field] is not None and not isinstance(data[field], str):
        raise invalid_request("Field '%s' must be a string" % field)
    return data[field]


def req_bool(data, field):
    if _missing(data, field) or not isinstance(data[field], bool):
        raise invalid_request("Field '%s' is required and must be a boolean" % field)
    return data[field]


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], bool):
        raise invalid_request("Field '%s' must be a boolean" % field)
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, field, min_v=None, max_v=None):
    if _missing(data, field) or not _is_int(data[field]):
        raise invalid_request("Field '%s' is required and must be an integer" % field)
    v = data[field]
    if min_v is not None and v < min_v:
        raise invalid_request("Field '%s' is below minimum" % field)
    if max_v is not None and v > max_v:
        raise invalid_request("Field '%s' exceeds maximum" % field)
    return v


def opt_int(data, field, default=None, min_v=None, max_v=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, min_v=min_v, max_v=max_v)


def req_enum(data, field, values):
    v = req_str(data, field)
    if v not in values:
        raise invalid_request("Field '%s' must be one of %s" % (field, sorted(values)))
    return v


def req_date(data, field):
    v = req_str(data, field)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise invalid_request("Field '%s' must be an ISO date (YYYY-MM-DD)" % field)
    return v


def opt_date(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_date(data, field)


def parse_dt(v):
    """Parse an ISO-8601 datetime (accepts trailing Z or offset)."""
    if not isinstance(v, str):
        raise invalid_request("Expected ISO-8601 datetime string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        raise invalid_request("Invalid ISO-8601 datetime: %r" % v)


def req_dt(data, field):
    if _missing(data, field):
        raise invalid_request("Field '%s' is required" % field)
    return parse_dt(data[field]), data[field]


def req_list(data, field):
    if _missing(data, field) or not isinstance(data[field], list):
        raise invalid_request("Field '%s' is required and must be an array" % field)
    return data[field]


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("Query param 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("Query param 'limit' out of range (1..100)")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("Query param 'offset' must be an integer")
        if offset < 0:
            raise invalid_request("Query param 'offset' must be >= 0")
    return limit, offset


def parse_bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise invalid_request("Query param '%s' must be a boolean" % name)


def paginate(items, limit, offset):
    items = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def public(ent):
    if ent is None:
        return None
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def get_or_404(store, ent_id, msg="Referenced entity does not exist"):
    ent = store.get(ent_id)
    if ent is None:
        raise not_found(msg)
    return ent


def age_on(dob_str, ref):
    """Age in whole years at reference date (date or datetime)."""
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0
    if isinstance(ref, datetime):
        ref = ref.date()
    years = ref.year - dob.year
    if (ref.month, ref.day) < (dob.month, dob.day):
        years -= 1
    return years
