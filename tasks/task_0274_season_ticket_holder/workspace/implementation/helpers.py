"""Shared helpers: body parsing, pagination, validation primitives, serializers."""
from flask import request

import db
from errors import err


# ---------------------------------------------------------------------------
# Body / query parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON body as a dict (empty dict when no body)."""
    if not request.data:
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


def parse_pagination():
    """Parse limit/offset query params. Returns (limit, offset).

    limit defaults to 10, min 1, max 100. offset defaults to 0, min 0.
    Out-of-range or non-integer values -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(rows):
    """Sort by created_at asc, then id for stability, and apply limit/offset.

    Returns (page_items, limit, offset, total_count).
    """
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Field validation
# ---------------------------------------------------------------------------
def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a non-empty string" % field)
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be <= %s" % (field, maximum))
    return val


def optional_int(body, field, default=0, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be <= %s" % (field, maximum))
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return val


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % field)
    return val


def require_str_field(body, field):
    """A required string field that is a datetime (we keep it as a string)."""
    return require_str(body, field)


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_or_404(collection, rid):
    """Path-referenced resource existence -> ERR_NOT_FOUND."""
    row = collection.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return row


def get_fk_or_404(collection, rid):
    """Body FK existence -> ERR_REFERENCED_RESOURCE_NOT_FOUND."""
    row = collection.get(rid)
    if row is None:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "Referenced resource not found")
    return row


# ---------------------------------------------------------------------------
# Serializers — public views of each entity
# ---------------------------------------------------------------------------
def _base(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def section_view(row):
    total = sum(1 for s in db.seats.values() if s["section_id"] == row["id"])
    available = sum(
        1
        for s in db.seats.values()
        if s["section_id"] == row["id"] and s["status"] == "AVAILABLE"
    )
    v = _base(row)
    v.update(
        {
            "name": row["name"],
            "tier": row["tier"],
            "base_price_cents": row["base_price_cents"],
            "total_seats": total,
            "available_seats": available,
        }
    )
    return v


def seat_view(row):
    v = _base(row)
    v.update(
        {
            "section_id": row["section_id"],
            "row_label": row["row_label"],
            "seat_number": row["seat_number"],
            "season_start_date": row["season_start_date"],
            "season_end_date": row["season_end_date"],
            "status": row["status"],
        }
    )
    return v


def account_view(row):
    v = _base(row)
    v.update(
        {
            "full_name": row["full_name"],
            "email": row["email"],
            "consecutive_seasons": row["consecutive_seasons"],
            "priority_points": row["priority_points"],
            "loyalty_tier": loyalty_tier(row["priority_points"]),
            "status": row["status"],
        }
    )
    return v


def season_plan_view(row):
    v = _base(row)
    v.update(
        {
            "name": row["name"],
            "plan_type": row["plan_type"],
            "game_count": row["game_count"],
            "price_multiplier_bps": row["price_multiplier_bps"],
            "includes_playoffs": row["includes_playoffs"],
        }
    )
    return v


def subscription_view(row):
    seat_count = sum(
        1
        for sa in db.seat_assignments.values()
        if sa["subscription_id"] == row["id"] and sa["status"] == "ASSIGNED"
    )
    v = _base(row)
    v.update(
        {
            "account_id": row["account_id"],
            "season_plan_id": row["season_plan_id"],
            "status": row["status"],
            "locked_price_cents": row["locked_price_cents"],
            "seat_count": seat_count,
            "renewal_cycle": row["renewal_cycle"],
        }
    )
    return v


def seat_assignment_view(row):
    v = _base(row)
    v.update(
        {
            "subscription_id": row["subscription_id"],
            "seat_id": row["seat_id"],
            "assigned_price_cents": row["assigned_price_cents"],
            "status": row["status"],
        }
    )
    return v


def payment_plan_view(row):
    v = _base(row)
    v.update(
        {
            "subscription_id": row["subscription_id"],
            "total_cents": row["total_cents"],
            "installment_count": row["installment_count"],
            "amount_paid_cents": row["amount_paid_cents"],
            "status": row["status"],
        }
    )
    # Expose refund settlement when present (recorded at cancellation).
    if "refund_cents" in row:
        v["refund_cents"] = row["refund_cents"]
    return v


def installment_view(row):
    v = _base(row)
    v.update(
        {
            "payment_plan_id": row["payment_plan_id"],
            "sequence": row["sequence"],
            "amount_cents": row["amount_cents"],
            "status": row["status"],
        }
    )
    return v


def ticket_transfer_view(row):
    v = _base(row)
    v.update(
        {
            "seat_assignment_id": row["seat_assignment_id"],
            "transfer_type": row["transfer_type"],
            "recipient_account_id": row["recipient_account_id"],
            "listing_price_cents": row["listing_price_cents"],
            "payout_cents": row["payout_cents"],
            "status": row["status"],
        }
    )
    return v


def parking_zone_view(row):
    active = sum(
        1
        for p in db.parking_addons.values()
        if p["parking_zone_id"] == row["id"] and p["status"] == "ACTIVE"
    )
    v = _base(row)
    v.update(
        {
            "name": row["name"],
            "capacity": row["capacity"],
            "price_cents": row["price_cents"],
            "active_pass_count": active,
        }
    )
    return v


def parking_addon_view(row):
    v = _base(row)
    v.update(
        {
            "subscription_id": row["subscription_id"],
            "parking_zone_id": row["parking_zone_id"],
            "price_cents": row["price_cents"],
            "status": row["status"],
        }
    )
    return v


# ---------------------------------------------------------------------------
# Loyalty tier
# ---------------------------------------------------------------------------
def loyalty_tier(points):
    if points < 500:
        return "BRONZE"
    if points < 1000:
        return "SILVER"
    return "GOLD"
