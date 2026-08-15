"""Response envelope, request parsing/validation, auth, pagination."""
import random
import string
from datetime import datetime, date, timezone

from flask import request, jsonify

from errors import err
from store import now_iso

ROLES = {
    "FleetManager",
    "MaintenanceSupervisor",
    "Mechanic",
    "Operator",
    "PartsClerk",
    "WarrantyClerk",
}


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def success(data, response_type="object", code=200, pagination=None):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def caller():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "Missing or unrecognized X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(*roles):
    uid, role = caller()
    if role not in roles:
        raise err("ERR_FORBIDDEN",
                  f"Role {role} is not permitted to perform this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing & field validation
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def req_field(data, name):
    val = data.get(name)
    if val is None:
        raise err("ERR_VALIDATION", f"Missing required field: {name}")
    return val


def req_str(data, name):
    val = req_field(data, name)
    if not isinstance(val, str) or val == "":
        raise err("ERR_VALIDATION", f"Field {name} must be a non-empty string")
    return val


def opt_str(data, name):
    val = data.get(name)
    if val is not None and not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {name} must be a string")
    return val


def req_int(data, name):
    val = req_field(data, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field {name} must be an integer")
    return val


def opt_int(data, name):
    val = data.get(name)
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field {name} must be an integer")
    return val


def req_bool(data, name):
    val = req_field(data, name)
    if not isinstance(val, bool):
        raise err("ERR_VALIDATION", f"Field {name} must be a boolean")
    return val


def req_number(data, name):
    val = req_field(data, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_VALIDATION", f"Field {name} must be a number")
    return val


def req_enum(data, name, allowed):
    val = req_field(data, name)
    if val not in allowed:
        raise err("ERR_VALIDATION",
                  f"Field {name} must be one of {sorted(allowed)}")
    return val


def parse_date_str(val, name):
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {name} must be an ISO date string")
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        raise err("ERR_VALIDATION", f"Field {name} must be an ISO date (YYYY-MM-DD)")


def req_date(data, name):
    return parse_date_str(req_field(data, name), name)


def opt_date(data, name):
    val = data.get(name)
    if val is None:
        return None
    return parse_date_str(val, name)


def parse_iso_datetime(val, name="to_iso8601"):
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {name} must be an ISO 8601 datetime string")
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_VALIDATION", f"Field {name} must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items: full sorted list. Returns (page_items, pagination_meta)."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
    limit = max(1, min(100, limit))
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


def sort_default(items):
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
