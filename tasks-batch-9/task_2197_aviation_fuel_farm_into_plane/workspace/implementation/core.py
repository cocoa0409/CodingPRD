"""Core infrastructure: response envelope, errors, in-memory store, logical clock."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------- error catalog
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ACCOUNT_OWNERSHIP_REQUIRED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_CROSS_FARM_REFERENCE": 422,
    "ERR_INVALID_PAYLOAD": 400,
    "ERR_FIELD_OUT_OF_RANGE": 422,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_INVALID_RECEIPT_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_TANK_STATE": 409,
    "ERR_INVALID_ASSET_STATE": 409,
    "ERR_INVALID_SPILL_STATE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_FARM_FROZEN": 409,
    "ERR_PERMIT_NOT_ACTIVE": 409,
    "ERR_TANK_QUARANTINED": 409,
    "ERR_SAMPLE_VERDICT_FAIL": 409,
    "ERR_WATER_BOTTOM_EXCEEDED": 409,
    "ERR_RETEST_LIMIT_REACHED": 409,
    "ERR_ASSET_NOT_SERVICEABLE": 409,
    "ERR_SPILL_NOT_REPORTABLE": 422,
    "ERR_EMPTY_TEST_RESULT_SET": 422,
    "ERR_AUTH_CODE_MISMATCH": 422,
    "ERR_AUTHORIZATION_NOT_REDEEMABLE": 409,
    "ERR_DELIVERY_MODE_MISMATCH": 422,
    "ERR_PIT_WINDOW_CONFLICT": 409,
    "ERR_ASSET_WINDOW_CONFLICT": 409,
    "ERR_TANK_ISOLATION_CONFLICT": 409,
    "ERR_OUTSIDE_FUELING_WINDOW": 409,
    "ERR_PERIOD_NOT_ELAPSED": 409,
    "ERR_MEASUREMENT_SET_INCOMPLETE": 422,
    "ERR_VARIANCE_OVERRIDE_REQUIRED": 409,
    "ERR_NO_UPLIFT_RECORDED": 409,
    "ERR_NOTHING_TO_SWEEP": 422,
    "ERR_DISPUTE_LIMIT_REACHED": 409,
    "ERR_SAFE_FILL_EXCEEDED": 409,
    "ERR_PERMIT_THROUGHPUT_EXCEEDED": 409,
    "ERR_INSUFFICIENT_TANK_VOLUME": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_UPLIFT_EXCEEDS_AUTHORIZATION": 409,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


# ---------------------------------------------------------------- envelope
def _req_id():
    alnum = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def _meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": _now_iso()}


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(rows) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def err_response(error_id, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), ERROR_STATUS.get(error_id, 400)


# ---------------------------------------------------------------- numeric helpers
def D(v):
    if isinstance(v, Decimal):
        return v
    if v is None:
        return Decimal(0)
    return Decimal(str(v))


def q2(v):
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(v):
    return D(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q5(v):
    return D(v).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def cents(v):
    return int(D(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def f2(v):
    return float(q2(v))


def f4(v):
    return float(q4(v))


# ---------------------------------------------------------------- time helpers
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


def parse_dt(s):
    """Parse an ISO-8601 instant into a tz-aware UTC datetime; None on failure."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def fmt_dt(d):
    if d is None:
        return None
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


# ---------------------------------------------------------------- store
class Store:
    COLLECTIONS = [
        "farms", "permits", "tanks", "receipts", "samples", "assets",
        "filter_changes", "pits", "accounts", "flights", "authorizations",
        "orders", "uplifts", "spills", "runs", "invoices", "payments",
        "gauges", "tank_status_changes", "pit_occupancies",
    ]

    def __init__(self):
        self.reset()

    def reset(self):
        for c in self.COLLECTIONS:
            setattr(self, c, {})
        self.clock = parse_dt(CLOCK_DEFAULT)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def now():
    return db.clock


def now_iso():
    return fmt_dt(db.clock)


def touch(row):
    """Bump version + updated_at on a mutated row (skips immutable rows)."""
    if row is None:
        return
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now_iso()


def base_row(with_mutable=True):
    r = {"id": db.new_id(), "created_at": now_iso(), "_seq": db.next_seq()}
    if with_mutable:
        r["updated_at"] = r["created_at"]
        r["version"] = 1
    return r


def public(row, hidden=("_seq",)):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows):
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "offset must be >= 0")
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total


def listing(rows, mapper=public):
    rows = sort_rows(rows)
    page, limit, offset, total = paginate(rows)
    return ok_list([mapper(r) for r in page], limit, offset, total)
