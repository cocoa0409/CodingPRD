"""Shared utilities: envelope, timestamps, logical clock, decimal arithmetic,
request parsing/validation helpers, and the system clock sweep."""
import calendar
import random
import re
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import db
from errors import ApiError, err_invalid_request

# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# ---------------------------------------------------------------------------


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _request_timestamp():
    """Wall-clock timestamp for the meta envelope (three fractional digits)."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _public(rec):
    """Strip internal bookkeeping fields (e.g. _seq) from a stored record."""
    if isinstance(rec, dict):
        return {k: v for k, v in rec.items() if not k.startswith("_")}
    return rec


def success(data, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    if isinstance(data, list):
        payload = [_public(r) for r in data]
    else:
        payload = _public(data)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": payload,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)


def parse_ts(value):
    """Parse an ISO 8601 datetime string to an aware datetime; None if invalid."""
    if not isinstance(value, str) or not _ISO_RE.match(value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with 'Z' (millisecond precision
    used only when the value carries sub-second data; logical clock values are
    whole-second)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso():
    """Current logical clock reading (ISO string)."""
    return db.clock_now


def now_dt():
    return parse_ts(db.clock_now)


def set_clock(to_iso):
    db.clock_now = fmt_ts(parse_ts(to_iso))
    return db.clock_now


# ---------------------------------------------------------------------------
# Money / decimal arithmetic
# ---------------------------------------------------------------------------


def rhu(value):
    """Round half up to whole cents (accepts Decimal, float, int)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_ratio(numerator, denominator):
    """round_half_up(numerator / denominator) for non-negative ints."""
    return int(
        (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def days_later(base_dt, days):
    return base_dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Request body helpers (request-shape validation: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def req_present(data, field):
    if field not in data or data[field] is None:
        raise err_invalid_request("Missing required field: %s" % field)
    return data[field]


def opt_present(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return data[field]


def req_string(data, field):
    v = req_present(data, field)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request("Field %s must be a non-empty string" % field)
    return v


def req_enum(data, field, allowed):
    v = req_present(data, field)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request(
            "Field %s must be one of %s" % (field, ", ".join(allowed))
        )
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, field, min_v=None, max_v=None):
    v = req_present(data, field)
    if not _is_int(v):
        raise err_invalid_request("Field %s must be an integer" % field)
    if min_v is not None and v < min_v:
        raise err_invalid_request("Field %s below minimum" % field)
    if max_v is not None and v > max_v:
        raise err_invalid_request("Field %s above maximum" % field)
    return v


def opt_int(data, field, default=None, min_v=None, max_v=None):
    v = opt_present(data, field, default)
    if v is None:
        return None
    if not _is_int(v):
        raise err_invalid_request("Field %s must be an integer" % field)
    if min_v is not None and v < min_v:
        raise err_invalid_request("Field %s below minimum" % field)
    if max_v is not None and v > max_v:
        raise err_invalid_request("Field %s above maximum" % field)
    return v


def req_bool(data, field, default=None):
    if field not in data or data[field] is None:
        if default is not None:
            return default
        raise err_invalid_request("Missing required field: %s" % field)
    v = data[field]
    if not isinstance(v, bool):
        raise err_invalid_request("Field %s must be a boolean" % field)
    return v


def req_ts(data, field):
    v = req_present(data, field)
    dt = parse_ts(v)
    if dt is None:
        raise err_invalid_request("Field %s must be an ISO 8601 datetime" % field)
    return v


def opt_ts(data, field):
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if parse_ts(v) is None:
        raise err_invalid_request("Field %s must be an ISO 8601 datetime" % field)
    return v


# ---------------------------------------------------------------------------
# Common fields / mutation audit (PRD section 2.6)
# ---------------------------------------------------------------------------


def touch(rec):
    """Refresh updated_at and bump version on any mutation (incl. cascades)."""
    rec["updated_at"] = now_iso()
    rec["version"] = int(rec.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# System clock sweep (PRD section 2.4)
# ---------------------------------------------------------------------------


def system_sweep():
    """Apply every clock-driven auto-transition whose condition the current
    clock position satisfies. Idempotent."""
    clock = now_dt()

    # ACTIVE engagements past window_end -> EXPIRED
    for eng in list(db.engagements.values()):
        if eng["status"] == "ACTIVE" and parse_ts(eng["window_end"]) < clock:
            eng["status"] = "EXPIRED"
            touch(eng)

    # DUE deposits past due_date -> DELINQUENT
    for dep in list(db.deposits.values()):
        if dep["status"] == "DUE" and parse_ts(dep["due_date"]) < clock:
            dep["status"] = "DELINQUENT"
            touch(dep)

    # QUOTED payoffs past quote_expires_at -> STALE
    for po in list(db.payoffs.values()):
        if po["status"] == "QUOTED" and parse_ts(po["quote_expires_at"]) < clock:
            po["status"] = "STALE"
            touch(po)

    # Bidder access windows whose end has been reached or passed -> EXPIRED
    for bidder in list(db.bidders.values()):
        changed = False
        for win in bidder["access_windows"]:
            if win["window_status"] == "ACTIVE" and clock >= parse_ts(
                win["window_end"]
            ):
                win["window_status"] = "EXPIRED"
                changed = True
        if changed:
            touch(bidder)

    # Escrow auto-release at/after release_date with no FILED claims
    for esc in list(db.escrows.values()):
        if esc["status"] in ("HELD", "PARTIALLY_RELEASED") and clock >= parse_ts(
            esc["release_date"]
        ):
            if not any(c["claim_status"] == "FILED" for c in esc["claims"]):
                if esc["available_cents"] > 0:
                    esc["released_to_seller_cents"] += esc["available_cents"]
                    esc["available_cents"] = 0
                esc["status"] = "RELEASED"
                touch(esc)


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------


def paginate(items):
    limit_raw = request.args.get("limit", None)
    offset_raw = request.args.get("offset", None)
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
