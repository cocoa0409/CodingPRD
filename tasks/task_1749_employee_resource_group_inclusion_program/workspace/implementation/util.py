"""Datetime handling, response envelope, numeric helpers."""
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Datetimes: ISO 8601 UTC with exactly three fractional digits on the wire.
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2).
# ---------------------------------------------------------------------------
def new_request_id():
    return "req_" + secrets.token_hex(10)


def meta_block():
    # Logical clock is the only clock the service exposes.
    from db import clock_now
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(clock_now()),
    }


def ok_object(data, code=200):
    return {"meta": meta_block(), "response_type": "object", "data": data}, code


def ok_list(items, limit, offset, total_count):
    meta = meta_block()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, 200


def err_body(error_id, message):
    return {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Decimal helpers: round-half-up at 2 decimal places / whole cents.
# ---------------------------------------------------------------------------
CENT = Decimal("1")
TWO_DP = Decimal("0.01")


def rhu2(value):
    """round_half_up to 2 decimal places -> float for JSON."""
    return float(Decimal(value).quantize(TWO_DP, rounding=ROUND_HALF_UP))


def rhu_cents(value):
    """round_half_up to whole cents -> int."""
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))
