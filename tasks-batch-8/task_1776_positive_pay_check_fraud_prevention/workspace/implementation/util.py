"""Shared helpers: envelope, timestamps, pagination, field validation."""
import random
import string
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import clock
import store
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, raise_err

UTC = timezone.utc


# ---------------------------------------------------------------------------
# timestamps
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_value(v):
    if isinstance(v, datetime):
        return fmt_ts(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def now_iso():
    return fmt_ts(clock.now())


def parse_iso_datetime(s):
    """Parse an ISO-8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith(("Z", "z")):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def parse_iso_date(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def valid_year_month(s):
    if not isinstance(s, str):
        return False
    parts = s.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        return False
    if not (parts[0].isdigit() and parts[1].isdigit()):
        return False
    return 1 <= int(parts[1]) <= 12


def period_of(dt):
    return "%04d-%02d" % (dt.year, dt.month)


# ---------------------------------------------------------------------------
# rounding (round-half-up, integer results — PRD §2.6)
# ---------------------------------------------------------------------------
def round_half_up_int(numer, denom):
    """round_half_up(numer / denom) as an integer (exact rational math)."""
    d = Decimal(numer) / Decimal(denom)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# response envelope (PRD §2.2)
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
# pagination (PRD §2.3): limit/offset, defaults 10/0, clamp 1..100 / >=0
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(records, serializer):
    """Records are pre-filtered; sorts by created_at ascending (insertion
    order tie-break) and applies limit/offset pagination."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# request body / field validation (PRD §2.10 priority 4)
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


def req_str(body, key, non_empty=True):
    v = body.get(key)
    if not isinstance(v, str) or (non_empty and v == ""):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a string" % key)
    return v


def opt_str(body, key):
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "%s must be a string" % key)
    return v


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


def opt_nullable_int(body, key):
    """Distinguishes 'absent' from explicit null. Returns (present, value)."""
    if key not in body:
        return False, None
    v = body.get(key)
    if v is None:
        return True, None
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    return True, v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def opt_enum(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def req_positive_int(body, key):
    v = req_int(body, key)
    if v <= 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be a positive integer" % key)
    return v


def req_datetime(body, key):
    v = body.get(key)
    dt = parse_iso_datetime(v)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 datetime" % key)
    return dt


def opt_datetime(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_datetime(body, key)


def req_date(body, key):
    v = body.get(key)
    d = parse_iso_date(v)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO date (YYYY-MM-DD)" % key)
    return d


def opt_nullable_date(body, key):
    """Returns (present, value); explicit null is allowed."""
    if key not in body:
        return False, None
    v = body.get(key)
    if v is None:
        return True, None
    d = parse_iso_date(v)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO date (YYYY-MM-DD)" % key)
    return True, d


# ---------------------------------------------------------------------------
# entity plumbing
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
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (label, rid))
    return rec


def serialize(rec, fields):
    out = {}
    for f in fields:
        out[f] = fmt_value(rec.get(f))
    return out
