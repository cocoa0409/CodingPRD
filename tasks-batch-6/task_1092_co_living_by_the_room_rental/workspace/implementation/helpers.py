"""Shared helpers: errors, response envelope, parsing, rounding, validation, auth."""
import random
import re
import string
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, g, request

import state

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalogue
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_HOST_NOT_FOUND": 404,
    "ERR_HOUSE_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_ENTITY_MISMATCH": 409,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_DUPLICATE_ROOM_NUMBER": 409,
    "ERR_MEMBER_ALREADY_HOUSED": 409,
    "ERR_APPLICATION_NOT_PENDING": 409,
    "ERR_ROOM_NOT_AVAILABLE": 409,
    "ERR_INVALID_MEMBERSHIP_STATE": 409,
    "ERR_INVALID_INCIDENT_STATE": 409,
    "ERR_INVALID_TICKET_STATE": 409,
    "ERR_INVALID_PAYOUT_STATE": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_STALE_ROOM_VERSION": 412,
    "ERR_STALE_HOUSE_VERSION": 412,
    "ERR_BACKGROUND_FAILED": 409,
    "ERR_HOUSE_POSTURE_BLOCKED": 409,
    "ERR_HOUSE_FROZEN": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_MOVE_IN_DATE_IN_PAST": 409,
    "ERR_NOTICE_TOO_SHORT": 409,
    "ERR_NOT_PAST_DUE": 409,
    "ERR_INVALID_PERIOD_LENGTH": 422,
    "ERR_INVOICE_PERIOD_OVERLAP": 409,
    "ERR_PAYOUT_CYCLE_OVERLAP": 409,
    "ERR_LATE_FEE_NOT_DUE": 409,
    "ERR_LATE_FEE_ALREADY_ASSESSED": 409,
    "ERR_NO_LATE_FEE_TO_WAIVE": 409,
    "ERR_ROOM_TURNOVER_CONFLICT": 409,
    "ERR_VISIT_CAPACITY_CONFLICT": 409,
    "ERR_DISPUTE_LIMIT_REACHED": 409,
    "ERR_APPLICATION_ROUND_LIMIT": 409,
    "ERR_INCOME_INSUFFICIENT": 422,
    "ERR_OVERPAYMENT": 422,
}

ROLES = {"PlatformAdmin", "Host", "Member", "CommunityManager",
         "ComplianceOfficer", "FinanceAdmin"}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_instant(state.clock_dt()),
    }


def ok(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def err_body(error_id, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })


# ---------------------------------------------------------------------------
# Timestamp / date formatting & parsing
# ---------------------------------------------------------------------------
def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def parse_date(s):
    if not isinstance(s, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        raise ApiError("ERR_INVALID_REQUEST", "malformed date; expected YYYY-MM-DD")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "malformed date; expected YYYY-MM-DD")


def parse_instant(s):
    if not isinstance(s, str) or "T" not in s:
        raise ApiError("ERR_INVALID_REQUEST", "malformed datetime; expected ISO 8601 UTC")
    t = s.strip()
    tt = t[:-1] + "+00:00" if t.endswith("Z") else t
    try:
        dt = datetime.fromisoformat(tt)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "malformed datetime; expected ISO 8601 UTC")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric/Decimal value to the nearest integer, halves away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(num, den):
    """Integer ceiling division for non-negative integers."""
    if den <= 0:
        den = 1
    return -(-num // den)


# ---------------------------------------------------------------------------
# Body / query parsing & validation (raise ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def _invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def req_field(b, name):
    if name not in b or b[name] is None:
        _invalid("missing required field: %s" % name)
    return b[name]


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str) or v == "":
        _invalid("field %s must be a non-empty string" % name)
    return v


def opt_str(b, name):
    if name not in b or b[name] is None:
        return None
    v = b[name]
    if not isinstance(v, str):
        _invalid("field %s must be a string" % name)
    return v


def req_int_nonneg(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("field %s must be an integer" % name)
    if v < 0:
        _invalid("field %s must be >= 0" % name)
    return v


def req_int_pos(b, name):
    v = req_int_nonneg(b, name)
    if v <= 0:
        _invalid("field %s must be > 0" % name)
    return v


def opt_int_nonneg(b, name):
    if name not in b or b[name] is None:
        return None
    return req_int_nonneg(b, name)


def req_enum(b, name, allowed):
    v = req_field(b, name)
    if v not in allowed:
        _invalid("field %s must be one of %s" % (name, sorted(allowed)))
    return v


def req_bool_opt(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, bool):
        _invalid("field %s must be a boolean" % name)
    return v


def req_date(b, name):
    return parse_date(req_field(b, name))


def opt_date(b, name):
    if name not in b or b[name] is None:
        return None
    return parse_date(b[name])


def req_instant(b, name):
    return parse_instant(req_field(b, name))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            _invalid("limit must be within 1..100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _invalid("offset must be an integer")
        if offset < 0:
            _invalid("offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Auth / ownership
# ---------------------------------------------------------------------------
def authorize(*allowed):
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role %s not permitted" % g.role)


def new_common():
    now = fmt_instant(state.clock_dt())
    return {
        "id": state.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": state.S.next_seq(),
    }


def new_ledger():
    now = fmt_instant(state.clock_dt())
    return {
        "id": state.new_id(),
        "created_at": now,
        "_seq": state.S.next_seq(),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = fmt_instant(state.clock_dt())


def find_or_404(collection, id_, error_id):
    entity = collection.get(id_)
    if entity is None:
        raise ApiError(error_id)
    return entity


def query_val(name):
    return request.args.get(name)
