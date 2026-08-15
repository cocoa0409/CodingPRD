"""Shared helpers: response envelope, timestamps, pagination, validation."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

import clock
import store
from errors import raise_err


# ---------------------------------------------------------------------------
# timestamps (PRD 2.4: ISO 8601 UTC, three fractional digits)
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_value(v):
    if isinstance(v, datetime):
        return fmt_ts(v)
    return v


def now_iso():
    return fmt_ts(clock.now())


def parse_iso_datetime(s):
    """Parse an ISO-8601 datetime (or bare YYYY-MM-DD date); aware datetime or None."""
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith("Z") or txt.endswith("z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# response envelope (SCAFFOLD 1.0 / PRD 2.2)
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def success_object(data, status=200):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(records, serializer):
    """Records pre-filtered; sorted by created_at ascending (insertion order as
    final tie-break) and paginated per PRD 2.3."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# request body / field validation (validation priority 3 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", "%s is required and must be a string" % key)
    return v


def opt_str(body, key, default=None):
    v = body.get(key)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", "%s must be a string" % key)
    return v


def req_int(body, key):
    v = body.get(key)
    if not _is_int(v):
        raise_err("ERR_INVALID_REQUEST", "%s is required and must be an integer" % key)
    return v


def opt_int(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not _is_int(v):
        raise_err("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise_err("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def req_datetime(body, key):
    v = body.get(key)
    dt = parse_iso_datetime(v)
    if dt is None:
        raise_err("ERR_INVALID_REQUEST", "%s is required and must be an ISO 8601 datetime" % key)
    return dt


def opt_datetime(body, key):
    if key not in body or body.get(key) is None:
        return None
    dt = parse_iso_datetime(body.get(key))
    if dt is None:
        raise_err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime" % key)
    return dt


def check_int_range(value, minimum, maximum, key):
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise_err("ERR_INVALID_REQUEST", "%s must be >= %d" % (key, minimum))
        raise_err("ERR_INVALID_REQUEST", "%s must be between %d and %d" % (key, minimum, maximum))
    return value


# ---------------------------------------------------------------------------
# entity plumbing (PRD 2.4 common fields; version increments per mutation)
# ---------------------------------------------------------------------------
def new_record():
    ts = clock.now()
    return {
        "id": store.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def bump(rec):
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


def get_or_404(table, rid, label):
    rec = table.get(rid)
    if rec is None:
        raise_err("ERR_NOT_FOUND", "%s not found: %s" % (label, rid))
    return rec


def serialize(rec, fields):
    return {f: fmt_value(rec.get(f)) for f in fields}
