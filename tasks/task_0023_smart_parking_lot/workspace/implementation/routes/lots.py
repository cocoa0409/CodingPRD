"""Lot, Zone, Space, and revenue/settlement endpoints (lot-rooted)."""
from flask import Blueprint, request, g

import db
from clock import iso, now, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.validation import (
    get_body, require_str, require_int, require_enum, optional_int,
    require_field, require_reason,
)
from services.projection import (
    lot_view, zone_view, space_view, revenue_entry_view, invoice_view,
)
from services.zones import recompute_zone_counts
from services.billing import settlement_day_key


bp = Blueprint("lots", __name__)


READ_ROLES = {"Operator", "Driver", "EnforcementOfficer", "ParkingPartner", "Auditor"}
ZONE_TYPES = {"STANDARD", "VIP", "DISABLED", "EMERGENCY"}


# ============================================================================
# Lots
# ============================================================================

@bp.route("/lots", methods=["POST"])
@require_auth(roles={"Operator"})
def create_lot():
    body = get_body()
    name = require_str(body, "name", min_len=1, max_len=200)
    timezone = require_str(body, "timezone", min_len=1, max_len=64)
    hourly_rate = require_int(body, "hourly_rate_cents", ge=0)
    daily_cap = require_int(body, "daily_cap_cents", ge=0)
    free_minutes = optional_int(body, "free_minutes", default=15, ge=0)
    tow_grace_minutes = optional_int(body, "tow_grace_minutes", default=5, ge=0)
    reservation_hold_minutes = optional_int(body, "reservation_hold_minutes", default=15, ge=0)
    no_show_penalty = optional_int(body, "no_show_penalty_cents", default=500, ge=0)
    partner_share_bps = optional_int(body, "partner_share_bps", default=0, ge=0, le=10000)

    lot = {
        "name": name,
        "timezone": timezone,
        "hourly_rate_cents": hourly_rate,
        "daily_cap_cents": daily_cap,
        "free_minutes": free_minutes,
        "tow_grace_minutes": tow_grace_minutes,
        "reservation_hold_minutes": reservation_hold_minutes,
        "no_show_penalty_cents": no_show_penalty,
        "partner_share_bps": partner_share_bps,
    }
    db.stamp_create(lot)
    db.parking_lots[lot["id"]] = lot
    return success(lot_view(lot), status=201)


@bp.route("/lots/<lot_id>", methods=["GET"])
@require_auth(roles=READ_ROLES)
def get_lot(lot_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    return success(lot_view(lot))


# ============================================================================
# Zones
# ============================================================================

@bp.route("/lots/<lot_id>/zones", methods=["POST"])
@require_auth(roles={"Operator"})
def create_zone(lot_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    body = get_body()
    code = require_str(body, "code", min_len=1, max_len=64)
    zone_type = require_enum(body, "zone_type", ZONE_TYPES)
    # Uniqueness within lot
    for z in db.zones.values():
        if z.get("lot_id") == lot_id and z.get("code") == code:
            raise err("ERR_BAD_REQUEST", "Zone code must be unique within lot")
    zone = {
        "lot_id": lot_id,
        "code": code,
        "zone_type": zone_type,
        "total_spaces": 0,
        "free_spaces": 0,
    }
    db.stamp_create(zone)
    db.zones[zone["id"]] = zone
    return success(zone_view(zone), status=201)


@bp.route("/lots/<lot_id>/availability", methods=["GET"])
@require_auth(roles=READ_ROLES)
def lot_availability(lot_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    zone_type = request.args.get("zone_type")
    if zone_type is not None and zone_type not in ZONE_TYPES:
        raise err("ERR_BAD_REQUEST", f"zone_type must be one of {sorted(ZONE_TYPES)}")
    limit, offset = get_pagination()
    rows = []
    for z in db.zones.values():
        if z.get("lot_id") != lot_id:
            continue
        if zone_type and z.get("zone_type") != zone_type:
            continue
        rows.append(z)
    rows.sort(key=lambda z: z.get("_seq", 0))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([zone_view(z) for z in page], limit, offset, total)


# ============================================================================
# Spaces
# ============================================================================

@bp.route("/lots/<lot_id>/zones/<zone_id>/spaces", methods=["POST"])
@require_auth(roles={"Operator"})
def create_space(lot_id, zone_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    zone = db.zones.get(zone_id)
    if zone is None or zone.get("lot_id") != lot_id:
        raise err("ERR_NOT_FOUND", "Zone not found in lot")
    body = get_body()
    label = require_str(body, "label", min_len=1, max_len=64)
    # Uniqueness within zone
    for s in db.spaces.values():
        if s.get("zone_id") == zone_id and s.get("label") == label:
            raise err("ERR_BAD_REQUEST", "Space label must be unique within zone")
    space = {
        "zone_id": zone_id,
        "lot_id": lot_id,
        "label": label,
        "occupancy_status": "FREE",
        "reservation_lock": "UNRESERVED",
        "current_session_id": None,
        "last_exited_at": None,
    }
    db.stamp_create(space)
    db.spaces[space["id"]] = space
    recompute_zone_counts(zone_id)
    return success(space_view(space), status=201)


@bp.route("/lots/<lot_id>/zones/<zone_id>/spaces/<space_id>", methods=["GET"])
@require_auth(roles=READ_ROLES)
def get_space(lot_id, zone_id, space_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    zone = db.zones.get(zone_id)
    if zone is None or zone.get("lot_id") != lot_id:
        raise err("ERR_NOT_FOUND", "Zone not found in lot")
    space = db.spaces.get(space_id)
    if space is None or space.get("zone_id") != zone_id:
        raise err("ERR_NOT_FOUND", "Space not found in zone")
    return success(space_view(space))


# ============================================================================
# Revenue / Settlement
# ============================================================================

REVENUE_BILLING_TYPES = {
    "HOURLY", "MONTHLY", "RESERVATION", "NO_SHOW_PENALTY",
    "FINE", "REFUND", "ADJUSTMENT",
}

REVENUE_GROUPBYS = {"period", "zone_id", "billing_type"}


@bp.route("/lots/<lot_id>/revenue", methods=["GET"])
@require_auth(roles={"Operator", "ParkingPartner", "Auditor"})
def lot_revenue(lot_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    limit, offset = get_pagination()
    from_q = request.args.get("from")
    to_q = request.args.get("to")
    billing_type_q = request.args.get("billing_type")
    group_by_q = request.args.get("group_by")

    if billing_type_q is not None and billing_type_q not in REVENUE_BILLING_TYPES:
        raise err("ERR_BAD_REQUEST", "billing_type filter is invalid")
    if from_q is not None:
        try:
            parse_iso(from_q)
        except ValueError:
            raise err("ERR_BAD_REQUEST", "from must be ISO 8601")
    if to_q is not None:
        try:
            parse_iso(to_q)
        except ValueError:
            raise err("ERR_BAD_REQUEST", "to must be ISO 8601")

    group_keys = []
    if group_by_q:
        for k in [s.strip() for s in group_by_q.split(",") if s.strip()]:
            if k not in REVENUE_GROUPBYS:
                raise err("ERR_BAD_REQUEST", f"group_by key invalid: {k}")
            group_keys.append(k)

    rows = []
    for r in db.revenue_entries.values():
        if r.get("lot_id") != lot_id:
            continue
        if billing_type_q and r.get("billing_type") != billing_type_q:
            continue
        if from_q and r.get("created_at") and r["created_at"] < from_q:
            continue
        if to_q and r.get("created_at") and r["created_at"] > to_q:
            continue
        rows.append(r)
    rows.sort(key=lambda r: r.get("_seq", 0))

    if not group_keys:
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([revenue_entry_view(r) for r in page], limit, offset, total)

    # Grouped aggregation: sum per-entry-then-aggregate (no re-rounding).
    groups = {}
    for r in rows:
        key = tuple(
            (r.get("settlement_period") if k == "period" else r.get(k))
            for k in group_keys
        )
        bucket = groups.setdefault(key, {
            "gross_amount_cents": 0,
            "partner_share_cents": 0,
            "house_share_cents": 0,
            "count": 0,
        })
        bucket["gross_amount_cents"] += int(r.get("gross_amount_cents") or 0)
        bucket["partner_share_cents"] += int(r.get("partner_share_cents") or 0)
        bucket["house_share_cents"] += int(r.get("house_share_cents") or 0)
        bucket["count"] += 1
        for k, v in zip(group_keys, key):
            bucket[k if k != "period" else "settlement_period"] = v

    flat = sorted(
        groups.values(),
        key=lambda g: tuple(str(g.get(k if k != "period" else "settlement_period") or "") for k in group_keys),
    )
    total = len(flat)
    page = flat[offset:offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/lots/<lot_id>/settlement/run", methods=["POST"])
@require_auth(roles={"Operator"})
def run_settlement(lot_id):
    lot = db.parking_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "Lot not found")
    body = get_body() if request.data else {}
    period = body.get("period") if isinstance(body, dict) else None
    if period is None:
        period = settlement_day_key(lot, now())
    if not isinstance(period, str):
        raise err("ERR_BAD_REQUEST", "period must be a string")

    gross = 0
    partner = 0
    house = 0
    for r in db.revenue_entries.values():
        if r.get("lot_id") != lot_id:
            continue
        if r.get("settlement_period") != period:
            continue
        gross += int(r.get("gross_amount_cents") or 0)
        partner += int(r.get("partner_share_cents") or 0)
        house += int(r.get("house_share_cents") or 0)

    invoice = {
        "invoice_id": db.gen_id(),
        "lot_id": lot_id,
        "period": period,
        "gross_total_cents": gross,
        "partner_total_cents": partner,
        "house_total_cents": house,
    }
    # Use the invoice_id field as the table key too
    invoice["id"] = invoice["invoice_id"]
    db.stamp_create(invoice, common_fields=False)
    db.invoices[invoice["id"]] = invoice
    return success(invoice_view(invoice))


# ============================================================================
# Reservations create (rooted under /lots/{lot_id})  -- delegated to reservations route
# Sessions create (rooted under /lots/{lot_id})       -- delegated to sessions route
# (defined in their own blueprints)
# ============================================================================
