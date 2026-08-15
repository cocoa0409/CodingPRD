"""Body parsing, field validators, datetime/date helpers, pagination."""
import re
from datetime import datetime, timezone, date

from flask import request

from errors import err_invalid, ApiError


# ---------- body ----------

def body():
    """Parse JSON object body; malformed JSON / non-object -> ERR_INVALID_REQUEST.

    Missing body yields {} (endpoints then fail on required-field checks).
    """
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid("Request body must be a JSON object")
    return data


# ---------- scalar validators ----------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_invalid(f"Missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or v == "":
        raise err_invalid(f"Field {name} must be a non-empty string")
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str):
        raise err_invalid(f"Field {name} must be a string")
    return v


def req_int(data, name, minimum=None, maximum=None):
    v = req_field(data, name)
    if not _is_int(v):
        raise err_invalid(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid(f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_invalid(f"Field {name} must be <= {maximum}")
    return v


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not _is_int(v):
        raise err_invalid(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid(f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_invalid(f"Field {name} must be <= {maximum}")
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid(f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid(f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise err_invalid(f"Field {name} must be a boolean")
    return v


def req_number(data, name):
    v = req_field(data, name)
    if not _is_int(v) and not isinstance(v, float):
        raise err_invalid(f"Field {name} must be a number")
    if isinstance(v, float) and (v != v):  # NaN
        raise err_invalid(f"Field {name} must be a number")
    return v


# ---------- datetime / date ----------

def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or not value.strip():
        raise err_invalid(f"Field {field} must be an ISO 8601 datetime string")
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise err_invalid(f"Field {field} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(data, name):
    return parse_dt(req_field(data, name), name)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise err_invalid(f"Field {field} must be a YYYY-MM-DD date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise err_invalid(f"Field {field} must be a YYYY-MM-DD date string")


_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_build_month(value):
    if not isinstance(value, str):
        raise err_invalid("Field build_month must be a YYYY-MM string")
    m = _MONTH_RE.match(value.strip())
    if not m:
        raise err_invalid("Field build_month must be a YYYY-MM string")
    return int(m.group(1)), int(m.group(2))


def month_start(year, month):
    return date(year, month, 1)


def next_month_start(year, month):
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


# ---------- pagination ----------

def _parse_qp_int(raw, default):
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items):
    """limit default 10 clamped to [1,100]; offset default 0 clamped to >= 0."""
    limit = _parse_qp_int(request.args.get("limit"), 10)
    limit = max(1, min(100, limit))
    offset = _parse_qp_int(request.args.get("offset"), 0)
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sort_created(items):
    """Default list sort: created_at ascending (insertion sequence proxy)."""
    return sorted(items, key=lambda e: e["_seq"])


def apply_filters(items, filters):
    """filters: list of (field_name, query_value or None)."""
    out = []
    for e in items:
        ok = True
        for field, want in filters:
            if want is not None and e.get(field) != want:
                ok = False
                break
        if ok:
            out.append(e)
    return out
