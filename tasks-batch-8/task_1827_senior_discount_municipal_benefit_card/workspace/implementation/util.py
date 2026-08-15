"""Shared helpers: envelopes, timestamps, rounding, validation."""
import math
import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import clock
import store
from errors import ERR_INVALID_REQUEST, raise_err


# ---------------------------------------------------------------------------
# timestamps
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
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
    """Parse an ISO-8601 datetime; returns an aware datetime or None."""
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith(("Z", "z")):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
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


# ---------------------------------------------------------------------------
# rounding / money (integer cents; round-half-up per PRD 2.6)
# ---------------------------------------------------------------------------
def round_half_up_cents(x):
    if isinstance(x, Decimal):
        d = x
    elif isinstance(x, int):
        return x
    else:
        d = Decimal(repr(float(x)))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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
# pagination (PRD 2.3)
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
    """records pre-filtered; sorts by created_at ascending (insertion-order
    tie-break) and applies limit/offset pagination."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


def opt_enum_query(name, allowed):
    v = request.args.get(name)
    if v is not None and v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (name, ", ".join(allowed)))
    return v


# ---------------------------------------------------------------------------
# request body / field validation
# ---------------------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return False
    return True


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str):
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


def req_number(body, key):
    v = body.get(key)
    if not _is_number(v):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a number" % key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def req_date(body, key):
    v = body.get(key)
    d = parse_iso_date(v)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO date (YYYY-MM-DD)" % key)
    return d


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


def get_or_404(table, rid, err_spec, label):
    rec = table.get(rid)
    if rec is None:
        raise_err(err_spec, "%s not found: %s" % (label, rid))
    return rec
