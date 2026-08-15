"""Shared helpers: ids, timestamps, dates, decimals, validation primitives."""
import re
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from db import store, now_iso
from errors import ApiError


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Refresh updated_at and bump version (PRD §2.4: every mutation)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity):
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field):
    """Strict YYYY-MM-DD parsing; bad format -> ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a YYYY-MM-DD date string", 400)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is not a valid calendar date", 400)


def last_day_of_month(year, month):
    return monthrange(year, month)[1]


def round_half_up_cents(value):
    """value is a Decimal or Fraction-like; returns int cents, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(value.numerator) / Decimal(value.denominator) if hasattr(value, "numerator") else Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to exactly two decimals, half-up. Returns a float with 2dp representation."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def get_body():
    from flask import request
    if not request.is_json:
        # Allow empty body for action endpoints
        if request.data:
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be JSON", 400)
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body", 400)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return body


def reject_unknown_fields(body, allowed_fields):
    for key in body:
        if key not in allowed_fields:
            raise ApiError("ERR_INVALID_REQUEST", f"Unknown or computed field supplied: {key}", 400)


def require_fields(body, required):
    for f in required:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}", 400)


def req_string(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)
        return None
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a non-empty string", 400)
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a string", 400)
    return v


def req_int(body, field, min_value=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an integer", 400)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be >= {min_value}", 400)
    return v


def opt_int(body, field, min_value=None):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an integer", 400)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be >= {min_value}", 400)
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if v not in values:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(values)}", 400)
    return v


def find_or_404(collection, entity_id, label="resource"):
    entity = collection.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} not found: {entity_id}", 404)
    return entity


def get_plan(plan_id):
    return find_or_404(store.plan_years, plan_id, "plan year")


def get_territory(tid):
    return find_or_404(store.territories, tid, "territory")


def get_account(aid):
    return find_or_404(store.accounts, aid, "account")


def active_children(territory_id):
    kids = [t for t in store.territories.values()
            if t.get("parent_territory_id") == territory_id and t["status"] == "ACTIVE"]
    kids.sort(key=lambda t: (t["created_at"], t["id"]))
    return kids


def active_assignments(territory_id):
    out = [a for a in store.rep_assignments.values()
           if a["territory_id"] == territory_id and a["status"] == "ACTIVE"]
    out.sort(key=lambda a: (a["created_at"], a["id"]))
    return out


def paginate(items, args):
    """limit/offset per response_envelope pagination_defaults."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0", 400)
    total = len(items)
    return items[offset:offset + limit], limit, offset, total
