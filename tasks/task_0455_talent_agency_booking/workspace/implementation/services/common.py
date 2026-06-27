"""Shared helpers: common-field minting, request-body validation, lookups."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError
from db import db, new_id, now_iso


def mint_common(record):
    """Attach id, created_at, updated_at, version, and an insertion sequence."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Strip internal-only fields from an entity before serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def get_json_body():
    """Parse the JSON request body; return {} when absent/empty."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return body


def require_fields(body, fields):
    """Ensure every named field is present and non-null (ERR_INVALID_REQUEST)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST")


def require_str(body, field):
    require_fields(body, [field])
    value = body[field]
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def require_int(body, field, minimum=None, maximum=None):
    require_fields(body, [field])
    value = body[field]
    # bool is a subclass of int; reject it explicitly
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def require_enum(body, field, allowed):
    value = require_str(body, field)
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def require_array(body, field):
    require_fields(body, [field])
    value = body[field]
    if not isinstance(value, list):
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) -> int, exact decimal arithmetic."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def bps_amount(amount_cents, rate_bps):
    """round_half_up(amount_cents * rate_bps / 10000) in whole cents."""
    return round_half_up_div(Decimal(amount_cents) * Decimal(rate_bps), Decimal(10000))


# --- existence lookups (ERR_NOT_FOUND on miss) ---

_COLLECTIONS = {
    "Agency": "agencies",
    "CastingDirector": "casting_directors",
    "Talent": "talents",
    "CompCard": "comp_cards",
    "CastingCall": "casting_calls",
    "Submission": "submissions",
    "AuditionSlot": "audition_slots",
    "AvailabilityHold": "availability_holds",
    "DealMemo": "deal_memos",
    "Booking": "bookings",
    "CommissionEntry": "commission_entries",
    "Payment": "payments",
    "ResidualSchedule": "residual_schedules",
}


def collection(entity_name):
    return getattr(db, _COLLECTIONS[entity_name])


def lookup(entity_name, entity_id):
    """Return the record or raise ERR_NOT_FOUND."""
    if not isinstance(entity_id, str):
        raise ApiError("ERR_NOT_FOUND")
    record = collection(entity_name).get(entity_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND")
    return record


def paginate(items):
    """Apply limit/offset from query params (PRD §2.3); sort by created_at ASC.

    Returns (page_items, limit, offset, total_count).
    """
    args = request.args
    limit = _parse_pagination_param(args.get("limit"), default=10, minimum=1, maximum=100)
    offset = _parse_pagination_param(args.get("offset"), default=0, minimum=0, maximum=None)
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total


def _parse_pagination_param(raw, default, minimum, maximum):
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value
