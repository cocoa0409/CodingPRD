"""Shared helpers: envelopes, timestamps, decimals, validation, records."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import clock
import store
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, raise_err


# ---------------------------------------------------------------------------
# timestamps — ISO 8601 UTC with three fractional digits (PRD 2.4)
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_value(v):
    if isinstance(v, datetime):
        return fmt_ts(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


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
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# decimal helpers (PRD 2.8: 4dp round-half-up for scores; integer cents)
# ---------------------------------------------------------------------------
def dec(v):
    if isinstance(v, Decimal):
        return v
    if isinstance(v, int):
        return Decimal(v)
    return Decimal(repr(float(v)))


def round4(x):
    return dec(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


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
    """records pre-filtered; sorted by created_at ascending (PRD 2.3)."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# request body / field validation (pipeline priority 3)
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


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a non-empty string" % key)
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


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def opt_enum(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_enum(body, key, allowed)


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


# ---------------------------------------------------------------------------
# entity plumbing (PRD 2.4)
# ---------------------------------------------------------------------------
def new_record():
    """Full-tracking resource: id, created_at, updated_at, version."""
    ts = clock.now()
    return {
        "id": store.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def new_child_record():
    """Evidence record (EntryMaterial/ConflictDeclaration/Score/AuditLog):
    only id + created_at; updated_at and version are absent (PRD 2.4)."""
    ts = clock.now()
    return {
        "id": store.new_id(),
        "created_at": ts,
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


def ref_or_404(table, rid, label):
    """Body-referenced FK (pipeline priority 5): ERR_REFERENCE_NOT_FOUND."""
    from errors import ERR_REFERENCE_NOT_FOUND
    rec = table.get(rid)
    if rec is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "%s not found: %s" % (label, rid))
    return rec


def serialize(rec, fields):
    out = {}
    for f in fields:
        out[f] = fmt_value(rec.get(f))
    return out
