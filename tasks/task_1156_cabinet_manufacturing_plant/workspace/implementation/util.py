"""Response envelope, timestamps, pagination, and deferred field validation.

Envelope shape is fixed by SCAFFOLD §1.0 / PRD §2.2:
  success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
  error:   {"meta": {...}, "response_type": "error",
            "data": {"error_id": ..., "message": ...}}
List responses add limit/offset/total_count/has_more to meta (PRD §2.3).
"""
import random
import re
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from errors import api_error
from store import db

CENT = Decimal("1")
TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# Decimal helpers — money is integer cents, round-half-up everywhere (§2.5).
# ---------------------------------------------------------------------------

def D(x) -> Decimal:
    return Decimal(str(x))


def rhu_int(x) -> int:
    """Round half up to whole cents."""
    return int(Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP))


def rhu_2dp(x) -> Decimal:
    """Round half up to two decimal places (cube / utilization)."""
    return Decimal(x).quantize(TWO_DP, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Timestamps (ISO 8601 UTC; three fractional digits when sub-second, PRD §2.4)
# ---------------------------------------------------------------------------

def fmt_ts(dt) -> str:
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return f"{base}.{dt.microsecond // 1000:03d}Z"
    return base + "Z"


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.clock),
    }


def respond_object(data, code: int = 200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def respond_list(items, total_count: int, limit: int, offset: int):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def paginate(records):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise api_error("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_error("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise api_error("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise api_error("ERR_VALIDATION", "offset must be >= 0")
    total = len(records)
    page = records[offset:offset + limit]
    return page, total, limit, offset


def sort_records(records):
    """Every list is sorted by created_at ascending (PRD §2.3); the monotonic
    creation sequence breaks ties within one logical-clock instant."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def bool_filter(raw):
    """Parse a boolean query filter; None means 'not provided'."""
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    return "__no_match__"


# ---------------------------------------------------------------------------
# Deferred field-level validation (PRD §2.7 priority 14 — evaluated LAST).
# Readers record errors instead of raising so that higher-priority rules
# (auth, existence, state, business) can fire first; raise_field_errors() is
# called only after all earlier rule classes pass.
# ---------------------------------------------------------------------------

MISSING = object()

# Pinned order inside priority 14: required/malformed (ERR_VALIDATION), then
# enum, then quantity, then time window, then duplicate code.
_RANK = {
    "ERR_VALIDATION": 0,
    "ERR_INVALID_ENUM": 1,
    "ERR_INVALID_QUANTITY": 2,
    "ERR_INVALID_TIME_WINDOW": 3,
    "ERR_DUPLICATE_CODE": 4,
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Body:
    def __init__(self, raw):
        self.d = raw if isinstance(raw, dict) else {}
        self.errors = []  # list of (rank, error_id, message)

    def add_error(self, error_id: str, message: str):
        self.errors.append((_RANK[error_id], error_id, message))

    def raise_field_errors(self):
        if self.errors:
            self.errors.sort(key=lambda e: e[0])
            _, error_id, message = self.errors[0]
            raise api_error(error_id, message)

    # -- readers ------------------------------------------------------------

    def req_str(self, key):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None or not isinstance(v, str):
            self.add_error("ERR_VALIDATION", f"{key} is required and must be a string")
            return None
        return v

    def opt_str(self, key):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            return None
        if not isinstance(v, str):
            self.add_error("ERR_VALIDATION", f"{key} must be a string")
            return None
        return v

    def opt_bool(self, key, default=None):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            return default
        if not isinstance(v, bool):
            self.add_error("ERR_VALIDATION", f"{key} must be a boolean")
            return default
        return v

    def req_int(self, key, min_value=None, range_error="ERR_INVALID_QUANTITY"):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            self.add_error("ERR_VALIDATION", f"{key} is required")
            return None
        if isinstance(v, bool) or not isinstance(v, int):
            self.add_error("ERR_VALIDATION", f"{key} must be an integer")
            return None
        if min_value is not None and v < min_value:
            self.add_error(range_error, f"{key} must be >= {min_value}")
            return None
        return v

    def opt_int(self, key, min_value=None, default=None):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, int):
            self.add_error("ERR_VALIDATION", f"{key} must be an integer")
            return default
        if min_value is not None and v < min_value:
            self.add_error("ERR_INVALID_QUANTITY", f"{key} must be >= {min_value}")
            return default
        return v

    def req_num(self, key, min_value=None, exclusive_min=False):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            self.add_error("ERR_VALIDATION", f"{key} is required")
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.add_error("ERR_VALIDATION", f"{key} must be a number")
            return None
        if min_value is not None:
            bad = v <= min_value if exclusive_min else v < min_value
            if bad:
                op = ">" if exclusive_min else ">="
                self.add_error("ERR_INVALID_QUANTITY", f"{key} must be {op} {min_value}")
                return None
        return v

    def opt_num(self, key, default=None, min_value=None, exclusive_min=False):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.add_error("ERR_VALIDATION", f"{key} must be a number")
            return default
        if min_value is not None:
            bad = v <= min_value if exclusive_min else v < min_value
            if bad:
                op = ">" if exclusive_min else ">="
                self.add_error("ERR_INVALID_QUANTITY", f"{key} must be {op} {min_value}")
                return default
        return v

    def req_enum(self, key, values):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            self.add_error("ERR_VALIDATION", f"{key} is required")
            return None
        if not isinstance(v, str):
            self.add_error("ERR_VALIDATION", f"{key} must be a string")
            return None
        if v not in values:
            self.add_error("ERR_INVALID_ENUM", f"{key} must be one of {sorted(values)}")
            return None
        return v

    def opt_enum(self, key, values, default=None):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None:
            return default
        if not isinstance(v, str):
            self.add_error("ERR_VALIDATION", f"{key} must be a string")
            return default
        if v not in values:
            self.add_error("ERR_INVALID_ENUM", f"{key} must be one of {sorted(values)}")
            return default
        return v

    def req_str_list(self, key):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None or not isinstance(v, list):
            self.add_error("ERR_VALIDATION", f"{key} is required and must be an array")
            return None
        if not v:
            self.add_error("ERR_VALIDATION", f"{key} must not be empty")
            return None
        if any(not isinstance(x, str) for x in v):
            self.add_error("ERR_VALIDATION", f"{key} entries must be strings")
            return None
        # order-independent set of ids: dedupe preserving first occurrence
        return list(dict.fromkeys(v))

    def req_date(self, key):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None or not isinstance(v, str):
            self.add_error("ERR_VALIDATION", f"{key} is required (YYYY-MM-DD)")
            return None
        if not _DATE_RE.match(v):
            self.add_error("ERR_VALIDATION", f"{key} must be an ISO date (YYYY-MM-DD)")
            return None
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            self.add_error("ERR_VALIDATION", f"{key} is not a valid calendar date")
            return None

    def req_datetime_utc(self, key):
        v = self.d.get(key, MISSING)
        if v is MISSING or v is None or not isinstance(v, str):
            self.add_error("ERR_VALIDATION", f"{key} is required (ISO 8601 UTC)")
            return None
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            self.add_error("ERR_VALIDATION", f"{key} must be an ISO 8601 timestamp")
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
