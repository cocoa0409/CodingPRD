"""Shared helpers: response envelope, timestamps, rounding, pagination, validation."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import clock
import store
from errors import raise_err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# timestamps — ISO 8601 UTC with three fractional digits (PRD 2.2 / 2.5)
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(clock.now())


def parse_dt(s):
    """Parse an ISO-8601 datetime (a bare date is midnight UTC). Aware UTC or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    try:
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# rounding — round-half-up (PRD 2.6); never bare floats for reported values
# ---------------------------------------------------------------------------
def _quantize(x, places):
    d = Decimal(repr(float(x)))
    return float(d.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def round2(x):
    return _quantize(x, "0.01")


def round4(x):
    return _quantize(x, "0.0001")


# ---------------------------------------------------------------------------
# response envelope (PRD 2.2)
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
# pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(records, serializer):
    """Pre-filtered records; sorted by created_at ascending; paginated."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# request body / field validation (ERR_INVALID_REQUEST, 400)
# ---------------------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or not v:
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a non-empty string" % key)
    return v


def opt_str(body, key):
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "%s must be a string" % key)
    return v


def req_num(body, key):
    v = body.get(key)
    if not _is_num(v):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a number" % key)
    return float(v)


def opt_num(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not _is_num(v):
        raise_err(ERR_INVALID_REQUEST, "%s must be a number" % key)
    return float(v)


def req_int(body, key):
    v = body.get(key)
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be an integer" % key)
    return v


def opt_int(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    return v


def opt_bool(body, key, default=False):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "%s must be a boolean" % key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def req_dt(body, key):
    dt = parse_dt(body.get(key))
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be an ISO 8601 datetime" % key)
    return dt


def opt_dt(body, key):
    if key not in body or body.get(key) is None:
        return None
    dt = parse_dt(body.get(key))
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 datetime" % key)
    return dt


def req_str_list(body, key):
    v = body.get(key)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a list of strings" % key)
    return list(v)


# ---------------------------------------------------------------------------
# entity plumbing
# ---------------------------------------------------------------------------
def new_record():
    """Full common-fields set (PRD 2.5): id, created_at, updated_at, version."""
    ts = clock.now()
    return {
        "id": store.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def new_journal_record():
    """Reduced set for append-only journals: id and created_at only."""
    return {"id": store.new_id(), "created_at": clock.now(), "_seq": store.next_seq()}


def touch(rec):
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


def serialize(rec, fields):
    out = {}
    for f in fields:
        v = rec.get(f)
        if isinstance(v, datetime):
            out[f] = fmt_ts(v)
        else:
            out[f] = v
    return out
