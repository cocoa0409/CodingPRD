"""In-memory store, logical clock, timestamps, response envelope, pagination.

Storage is process-local Python dicts keyed by id.  Nothing is ever seeded:
every row in every collection is created by an API caller.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from flask import g

from errors import ApiError

# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------
DB = {
    "accounts": {},
    "merchant_categories": {},
    "rotations": {},
    "transactions": {},
    "ledger": {},
    "agencies": {},
    "offers": {},
    "orders": {},
    "agreements": {},
    "bonus_events": {},
    "transfer_requests": {},
    "fraud_cases": {},
    "entitlements": {},
    "notices": {},
    "snapshots": {},
}

RESOURCE_NAMES = {
    "accounts": "Account",
    "merchant_categories": "MerchantCategory",
    "rotations": "EarningCategoryRotation",
    "transactions": "Transaction",
    "ledger": "PointsLedgerEntry",
    "agencies": "TravelAgencyPartner",
    "offers": "PortalInventoryOffer",
    "orders": "RedemptionOrder",
    "agreements": "PartnerAgreement",
    "bonus_events": "TransferBonusEvent",
    "transfer_requests": "TransferRequest",
    "fraud_cases": "FraudCase",
    "entitlements": "BenefitEntitlement",
    "notices": "ProgramChangeNotice",
    "snapshots": "LiabilitySnapshot",
}

_SEQ = {"n": 0}

# The logical clock.  Before any client sets it the clock reads this instant.
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"
_CLOCK = {"current_utc": CLOCK_DEFAULT}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None on failure."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    offset = timedelta(0)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt - offset


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000
    )


def canonical_dt(value):
    return fmt_dt(parse_dt(value))


def wall_now_iso():
    return fmt_dt(datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def clock_iso():
    return _CLOCK["current_utc"]


def clock_dt():
    return parse_dt(_CLOCK["current_utc"])


def set_clock(dt):
    _CLOCK["current_utc"] = fmt_dt(dt)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def new_row(kind, data, audit=True):
    row = {"id": new_id()}
    row.update(data)
    stamp = clock_iso()
    row["created_at"] = stamp
    if audit:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_kind"] = kind
    row["_seq"] = next_seq()
    return row


def store(kind, row):
    DB[kind][row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1 (once per request per row)."""
    if "version" not in row:
        return row
    key = (row["_kind"], row["id"])
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    if key in touched:
        return row
    touched.add(key)
    row["updated_at"] = clock_iso()
    row["version"] = row["version"] + 1
    return row


def ordered(kind, rows=None):
    """created_at ASC, insertion order as the deterministic tie-break."""
    source = DB[kind].values() if rows is None else rows
    return sorted(source, key=lambda r: (r["created_at"], r["_seq"]))


def find(kind, ident):
    if not isinstance(ident, str):
        return None
    return DB[kind].get(ident)


def must_find(kind, ident):
    row = find(kind, ident)
    if row is None:
        raise ApiError(
            "ERR_RESOURCE_NOT_FOUND",
            "%s '%s' not found." % (RESOURCE_NAMES[kind], ident),
        )
    return row


# --------------------------------------------------------------------------
# arithmetic helpers
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_CEILING))


# --------------------------------------------------------------------------
# response envelope
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": wall_now_iso()}


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": meta_base(),
        "response_type": "object",
        "data": {} if data is None else data,
    }
    return body, status


def ok_list(rows, limit, offset, total):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    return {"meta": meta, "response_type": "array", "data": rows}, 200


def error_body(error_id, message):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------
def pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "Invalid pagination: limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "Invalid pagination: limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "Invalid pagination: offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "Invalid pagination: offset may not be negative.")
    return limit, offset


def window(rows, limit, offset):
    return rows[offset:offset + limit]
