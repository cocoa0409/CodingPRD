"""Shared lookups, validation primitives, inventory roll-up, pagination, and
serialization that the route handlers build on."""
from flask import request

import errors
from db import db, touch, now_iso
from errors import err

# ---------------------------------------------------------------------------
# Existence lookups (priority 3: ERR_NOT_FOUND, validated left-to-right)
# ---------------------------------------------------------------------------

_COLLECTIONS = {
    "boutique": "boutiques",
    "customer": "customers",
    "style": "styles",
    "sku_variant": "sku_variants",
    "fitting_room": "fitting_rooms",
    "fitting_room_hold": "fitting_room_holds",
    "stylist": "stylists",
    "styling_appointment": "styling_appointments",
    "markdown_schedule": "markdown_schedules",
    "sales_order": "sales_orders",
    "order_line": "order_lines",
    "return_request": "return_requests",
    "special_order": "special_orders",
    "lookbook": "lookbooks",
}


def get_or_404(kind, rid):
    coll = getattr(db, _COLLECTIONS[kind])
    rec = coll.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, f"{kind} not found")
    return rec


# ---------------------------------------------------------------------------
# Request-body field validation (priority 5: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {n}")


def require_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def require_int(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def require_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = body[name]
    if v not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


def validate_minute(value, name):
    """Minute-of-day: >= 0 and < 1440 for start; end handled separately."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


def validate_interval(start_minute, end_minute):
    """PRD §3.3/§3.4: start in [0,1440), end in (start,1440]."""
    if not (0 <= start_minute < 1440):
        raise err(errors.ERR_INVALID_REQUEST, "start_minute must be >= 0 and < 1440")
    if not (start_minute < end_minute <= 1440):
        raise err(errors.ERR_INVALID_REQUEST, "end_minute must be > start_minute and <= 1440")


# ---------------------------------------------------------------------------
# Inventory conservation & roll-up (PRD §2.5)
# ---------------------------------------------------------------------------

def recompute_variant(variant):
    """available = on_hand - reserved (never negative); then bubble up style."""
    avail = variant["on_hand"] - variant["reserved"]
    variant["available"] = avail if avail > 0 else 0
    touch(variant)
    bubble_style_total(variant["style_id"])


def bubble_style_total(style_id):
    """Refresh the style's derived `total_available` roll-up (PRD §2.5).

    `total_available` is a derived field ("a derived roll-up that never drifts
    from its variants"), so recomputing it refreshes `updated_at` but must NOT
    increment the style's `version`. The style's `version` is the OCC anchor for
    markdown creation (PRD §2.7/§3.5: only the markdown create — and the markdown
    activate/end price writes — mutate the style itself and bump its version).
    Bumping `version` on every inventory move would falsely invalidate a client's
    last-observed style version between reading it and creating a markdown.
    """
    style = db.styles.get(style_id)
    if style is None:
        return
    total = 0
    for v in db.sku_variants.values():
        if v["style_id"] == style_id:
            total += v["available"]
    style["total_available"] = total
    style["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_VALIDATION_LIMIT, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_VALIDATION_LIMIT, "limit must be in [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_VALIDATION_LIMIT, "offset must be >= 0")
        if offset < 0:
            raise err(errors.ERR_VALIDATION_LIMIT, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable via _seq), then window."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# ---------------------------------------------------------------------------
# Serialization — strip private fields like _seq before returning
# ---------------------------------------------------------------------------

def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_list(records):
    return [serialize(r) for r in records]
