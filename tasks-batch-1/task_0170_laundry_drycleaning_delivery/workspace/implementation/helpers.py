"""Shared helpers: auth, request parsing, pagination, datetime, calculations."""

import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import constants as C
from errors import err


# --------------------------------------------------------------------------
# Auth (PRD §2.1, validations priority 1 & 2)
# --------------------------------------------------------------------------
def require_auth(allowed_roles):
    """Validate the user-context headers and role permission.

    Returns (user_id, role). Raises ApiError on failure.
    Priority 1: headers present & well-formed -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    Priority 2: role permitted -> ERR_INSUFFICIENT_PERMISSIONS
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if not role or role not in C.ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if role not in allowed_roles:
        raise err("ERR_INSUFFICIENT_PERMISSIONS")
    return user_id, role


# --------------------------------------------------------------------------
# Request body
# --------------------------------------------------------------------------
def get_body():
    if request.data is None or request.data == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# --------------------------------------------------------------------------
# Field validation (priority 4: ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
def req_str(body, field, allow_empty=False):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % field)
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    if not allow_empty and v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must not be empty" % field)
    return v


def req_enum(body, field, choices):
    v = req_str(body, field)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, choices))
    return v


def req_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (field, maximum))
    return v


def opt_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_number(body, field, minimum=None, maximum=None):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (field, maximum))
    return v


def req_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % field)
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def parse_dt(body, field):
    """Required ISO 8601 datetime field. Returns aware datetime."""
    v = req_str(body, field)
    dt = _parse_iso(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field %s must be ISO 8601" % field)
    return dt


def _parse_iso(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = C.PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < C.PAGINATION_MIN_LIMIT or limit > C.PAGINATION_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST", "limit out of range")
    if offset_raw is None:
        offset = C.PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records):
    """records: list of stored dicts. Returns (page_views, limit, offset, total)."""
    limit, offset = pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# --------------------------------------------------------------------------
# Rounding (PRD §2.5)
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to whole integer cents, round-half-up (away from
    zero on .5)."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# System-field stamping (PRD §2.4, §2.8)
# --------------------------------------------------------------------------
def stamp_new(record):
    ts = db.iso_now()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on any mutation (PRD §2.8)."""
    record["updated_at"] = db.iso_now()
    record["version"] = record["version"] + 1


# --------------------------------------------------------------------------
# Garment line pricing (PRD §3.3) — variant-driven.
# --------------------------------------------------------------------------
def garment_line_price(garment, order, plan_or_none, weight_grams, piece_count):
    """Compute one garment's line price in whole cents.

    plan_or_none: the active SubscriptionPlan record, or None if no active sub.
    weight_grams / piece_count: declared (estimate) or actual (final) values.
    """
    service_type = garment["service_type"]
    has_active_sub = plan_or_none is not None

    if service_type == "WASH_FOLD":
        kg = Decimal(weight_grams) / Decimal(1000)
        tier1 = Decimal(str(C.WF_TIER1_KG))
        if kg <= tier1:
            base = kg * Decimal(C.WF_RATE1_CENTS_PER_KG)
        else:
            base = (tier1 * Decimal(C.WF_RATE1_CENTS_PER_KG)) + \
                   ((kg - tier1) * Decimal(C.WF_RATE2_CENTS_PER_KG))
    elif service_type == "DRY_CLEAN":
        base = Decimal(piece_count) * Decimal(C.DRYCLEAN_RATE_CENTS_PER_PIECE)
    else:  # ALTERATION
        base = Decimal(piece_count) * Decimal(garment["alteration_fee_cents"])

    # Subscriber discount: only DRY_CLEAN and ALTERATION, never WASH_FOLD.
    if service_type in ("DRY_CLEAN", "ALTERATION") and has_active_sub:
        disc = Decimal(str(plan_or_none["dryclean_discount_pct"]))
        base = base * (Decimal(1) - disc)

    # Rush surcharge: applies to every line unless plan rush_waived.
    plan_rush_waived = bool(plan_or_none["rush_waived"]) if has_active_sub else False
    if order["rush"] and not plan_rush_waived:
        base = base * Decimal(C.RUSH_MULTIPLIER)

    return round_half_up(base)


def active_plan_for_order(order):
    """Return the plan record if the order has an active subscription, else None.
    (PRD §3.3: subscriber benefits apply only for an active subscription.)"""
    sub_id = order.get("subscription_id")
    if not sub_id:
        return None
    sub = db.subscriptions.get(sub_id)
    if sub is None or sub["status"] != "ACTIVE":
        return None
    plan = db.plans.get(sub["plan_id"])
    return plan
