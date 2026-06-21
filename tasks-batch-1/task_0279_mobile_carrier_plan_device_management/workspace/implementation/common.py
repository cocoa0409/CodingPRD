"""Shared helpers: common-field stamping, datetime parsing, rounding, body parsing."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import db
from errors import err, ERR_VALIDATION


def clock_iso():
    """ISO 8601 UTC (three fractional digits) of the server's logical clock.

    Entity timestamps (created_at/updated_at/activated_at, charge created_at)
    reflect the logical clock (PRD §3.11) so that proration day-counts measured
    against the cycle window stay consistent when an operator drives the clock.
    """
    dt = db.now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Common system-managed fields (PRD §2.5).
# ---------------------------------------------------------------------------
def stamp_create(record, common=True):
    """Set id/created_at, plus updated_at/version when the entity carries them.

    Charge and UsageRecord are append-only ledger events: id + created_at only
    (PRD §2.5), so they pass common=False.
    """
    record["id"] = db.new_id()
    ts = clock_iso()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if common:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """A mutation: refresh updated_at and bump version (PRD §2.5)."""
    record["updated_at"] = clock_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Strip internal-only fields (those prefixed with _) for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Datetime parsing — all instants are ISO 8601 UTC.
# ---------------------------------------------------------------------------
def parse_dt(value, field):
    if not isinstance(value, str):
        err(ERR_VALIDATION, f"{field} must be an ISO 8601 string")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        err(ERR_VALIDATION, f"{field} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_utc_days(start, end):
    """Whole number of UTC days between two instants (proration denominator)."""
    delta = end - start
    return int(delta.total_seconds() // 86400)


def is_whole_days(start, end):
    delta = end - start
    return delta.total_seconds() % 86400 == 0


# ---------------------------------------------------------------------------
# Rounding (PRD §2.6).
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator=1):
    """Round numerator/denominator to nearest whole cent, half rounds up."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def ceil_div(numerator, denominator):
    """Ceiling of numerator/denominator to whole cents (EIP installment)."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_CEILING
    )
    return int(q)


# ---------------------------------------------------------------------------
# Body field extraction with type checks (ERR_VALIDATION, PRD §2.4).
# ---------------------------------------------------------------------------
def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        err(ERR_VALIDATION, "request body must be a JSON object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        err(ERR_VALIDATION, f"missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str):
        err(ERR_VALIDATION, f"{field} must be a string")
    return v


def require_int(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        err(ERR_VALIDATION, f"{field} must be an integer")
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        err(ERR_VALIDATION, f"{field} must be one of {sorted(allowed)}")
    return v


def opt_int(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err(ERR_VALIDATION, f"{field} must be an integer")
    return v
