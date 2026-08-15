"""Envelope, errors, logical-clock time helpers, validation helpers."""
import re
import secrets
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

from store import CLOCK, next_seq

ROLES = {
    "BankOperationsAdmin", "TreasuryImplementer", "TreasuryActivator",
    "LockboxOperator", "CustomerOperator", "BillingSpecialist",
    "BillingApprover", "Auditor",
}


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def invalid(msg="malformed request body"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def now():
    return CLOCK["now"]


def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        invalid("expected ISO8601 datetime string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s2)
    except Exception:
        invalid("bad datetime: %r" % s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s.strip()):
        invalid("expected YYYY-MM-DD date")
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        invalid("bad date: %r" % s)


def add_business_days(d, n):
    step = 1 if n >= 0 else -1
    for _ in range(abs(n)):
        d = d + timedelta(days=step)
        while d.weekday() >= 5:
            d = d + timedelta(days=step)
    return d


def rhu(x):
    """Round half-up to whole integer (cents / bp)."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": fmt(now()),
    }


def ok(data, rtype="object", status=200, pag=None):
    m = meta()
    if pag:
        m.update(pag)
    return jsonify({"meta": m, "response_type": rtype, "data": data}), status


def err_body(e):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


# ---------------------------------------------------------------------------
# Request body field validation
# ---------------------------------------------------------------------------

def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        invalid("request body must be a JSON object")
    return b


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or not v.strip():
        invalid("missing or invalid field: %s" % k)
    return v


def opt_str(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, str):
        invalid("bad field: %s" % k)
    return v


def req_int(b, k, minv=None):
    v = b.get(k)
    if type(v) is not int:
        invalid("missing or invalid integer field: %s" % k)
    if minv is not None and v < minv:
        invalid("out-of-range numeric field: %s" % k)
    return v


def opt_int(b, k, minv=None):
    v = b.get(k)
    if v is None:
        return None
    if type(v) is not int:
        invalid("bad integer field: %s" % k)
    if minv is not None and v < minv:
        invalid("out-of-range numeric field: %s" % k)
    return v


def opt_bool(b, k, default=False):
    v = b.get(k)
    if v is None:
        return default
    if type(v) is not bool:
        invalid("bad boolean field: %s" % k)
    return v


def req_enum(b, k, allowed):
    v = b.get(k)
    if v not in allowed:
        invalid("bad enum field: %s" % k)
    return v


def req_date_field(b, k):
    return parse_date(b.get(k)).isoformat()


def opt_date_field(b, k):
    v = b.get(k)
    if v is None:
        return None
    return parse_date(v).isoformat()


def req_dt_field(b, k):
    return parse_dt(b.get(k))


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity(fields):
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    ts = fmt(now())
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def touch(e):
    e["version"] += 1
    e["updated_at"] = fmt(now())


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except Exception:
            invalid("bad limit")
        if limit < 1 or limit > 100:
            invalid("limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except Exception:
            invalid("bad offset")
        if offset < 0:
            invalid("offset out of range")
    total = len(rows)
    page = rows[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pag


def filter_rows(rows, allowed):
    for f in allowed:
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r.get(f) is not None and str(r.get(f)) == v]
    return rows


def list_response(rows, allowed_filters, serialize=None):
    rows = filter_rows(rows, allowed_filters)
    rows = sort_rows(rows)
    page, pag = paginate(rows)
    ser = serialize or pub
    return ok([ser(r) for r in page], rtype="array", pag=pag)
