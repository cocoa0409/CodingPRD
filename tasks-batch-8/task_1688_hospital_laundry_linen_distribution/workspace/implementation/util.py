"""Shared helpers: envelopes, timestamps, rounding, validation, pagination."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import jsonify, request

import clock
import store
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, raise_err


# ---------------------------------------------------------------------------
# timestamps
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(clock.now())


def parse_iso_datetime(s):
    """Parse an ISO-8601 datetime; returns aware datetime or None."""
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# rounding / money (integer cents; round-half-up per PRD 2.6)
# ---------------------------------------------------------------------------
def dec(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(1 if x else 0)
    if isinstance(x, int):
        return Decimal(x)
    return Decimal(repr(float(x)))


def rhu0(x):
    """Round half up to a whole integer."""
    return int(dec(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(x):
    """Round half up to two decimal places; returned as float."""
    return float(dec(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rhu2_dec(x):
    """Round half up to two decimal places; returned as Decimal."""
    return dec(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_int(x):
    """Ceiling to the next whole piece."""
    return int(dec(x).to_integral_value(rounding=ROUND_CEILING))


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
    """Sort by created_at ascending (insertion-order tie-break) and paginate."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


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
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a non-empty string" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
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


def req_number(body, key):
    v = body.get(key)
    if not _is_number(v):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a number" % key)
    return v


def req_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a boolean" % key)
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


def opt_enum(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def req_dt(body, key):
    v = body.get(key)
    dt = parse_iso_datetime(v)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 datetime" % key)
    return dt


def req_list(body, key):
    v = body.get(key)
    if not isinstance(v, list):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a list" % key)
    return v


def occ_field(body, key):
    """OCC version fields are non-optional (PRD 2.8). Accept int or numeric str."""
    if key not in body or body.get(key) is None:
        raise_err(ERR_INVALID_REQUEST, "%s is required" % key)
    v = body.get(key)
    if isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v.strip())
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % key)


def fk_ref(body, key, table, label):
    """Resolve a body foreign-key reference (priority 4, ERR_NOT_FOUND).

    A missing key is a shape error (400); a present-but-unresolvable reference
    is a 404.
    """
    if key not in body or body.get(key) is None:
        raise_err(ERR_INVALID_REQUEST, "%s is required" % key)
    v = body.get(key)
    if not isinstance(v, str):
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (label, v))
    rec = table.get(v)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (label, v))
    return rec


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
