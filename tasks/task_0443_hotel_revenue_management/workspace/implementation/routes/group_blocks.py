"""GroupBlock endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import (
    err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_INVALID_STATE,
    ERR_NOT_EVALUATED, ERR_LOS_VIOLATION, ERR_MISSING_INVENTORY_DAY,
    ERR_STALE_VERSION, ERR_OVERSELL_LIMIT_EXCEEDED,
)
from services.common import (
    get_body, require_str, require_number, require_int, require_datetime,
    opt_number, opt_int, stay_date_midnight, iso_out, stamp_new, bump,
    parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_group_block
from services.calc import (
    compute_displacement, master_bar_plan, recompute_availability,
    recompute_property_kpi,
)

bp = Blueprint("group_blocks", __name__)

READ_ROLES = {"GroupSalesManager", "RevenueManager", "Analyst"}
EVAL_METHODS = {"LRV", "FORECAST_REV"}


@bp.route("/group-blocks", methods=["POST"])
def create_group_block():
    _, role = authenticate()
    require_role(role, {"GroupSalesManager"})
    body = get_body()
    room_type_id = require_str(body, "room_type_id")
    group_name = require_str(body, "group_name")
    arrival_dt = require_datetime(body, "arrival_date")
    nights = require_int(body, "nights")
    if nights < 1:
        raise err(ERR_INVALID_REQUEST, "nights must be >= 1")
    rooms_per_night = require_int(body, "rooms_per_night")
    if rooms_per_night < 1:
        raise err(ERR_INVALID_REQUEST, "rooms_per_night must be >= 1")
    offered_rate = require_number(body, "offered_rate")
    if offered_rate < 0:
        raise err(ERR_INVALID_REQUEST, "offered_rate must be >= 0")

    if room_type_id not in db.room_types:
        raise err(ERR_FK_NOT_FOUND, "room_type_id does not reference an existing room type")

    arrival_mid = stay_date_midnight(arrival_dt)
    rec = {
        "id": new_id(),
        "room_type_id": room_type_id,
        "group_name": group_name,
        "arrival_date": arrival_mid.strftime("%Y-%m-%d"),
        "arrival_date_iso": iso_out(arrival_mid),
        "nights": nights,
        "rooms_per_night": rooms_per_night,
        "offered_rate": offered_rate,
        "status": "NEGOTIATING",
        "displacement_cost": None,
        "recommendation": None,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.group_blocks[rec["id"]] = rec
    return success(ser_group_block(rec), status=201)


@bp.route("/group-blocks/<gid>", methods=["GET"])
def get_group_block(gid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.group_blocks, gid)
    return success(ser_group_block(rec), status=200)


@bp.route("/group-blocks", methods=["GET"])
def list_group_blocks():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    room_type_id = request.args.get("room_type_id")
    status = request.args.get("status")
    items = []
    for g in db.group_blocks.values():
        if room_type_id is not None and g["room_type_id"] != room_type_id:
            continue
        if status is not None and g["status"] != status:
            continue
        items.append(g)
    items = sort_by_created(items)
    total = len(items)
    page = [ser_group_block(g) for g in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)


@bp.route("/group-blocks/<gid>", methods=["PATCH"])
def revise_group_block(gid):
    _, role = authenticate()
    require_role(role, {"GroupSalesManager"})
    rec = get_or_404(db.group_blocks, gid)
    body = get_body()
    # Revision moves REVISION_REQUESTED -> NEGOTIATING.
    if rec["status"] != "REVISION_REQUESTED":
        raise err(ERR_INVALID_STATE, "Block is not in REVISION_REQUESTED state")

    if "offered_rate" in body and body["offered_rate"] is not None:
        rate = opt_number(body, "offered_rate", rec["offered_rate"])
        if rate < 0:
            raise err(ERR_INVALID_REQUEST, "offered_rate must be >= 0")
        rec["offered_rate"] = rate
    if "rooms_per_night" in body and body["rooms_per_night"] is not None:
        rpn = opt_int(body, "rooms_per_night", rec["rooms_per_night"])
        if rpn < 1:
            raise err(ERR_INVALID_REQUEST, "rooms_per_night must be >= 1")
        rec["rooms_per_night"] = rpn

    rec["status"] = "NEGOTIATING"
    rec["displacement_cost"] = None
    rec["recommendation"] = None
    bump(rec)
    return success(ser_group_block(rec), status=200)


@bp.route("/group-blocks/<gid>/evaluate", methods=["POST"])
def evaluate_group_block(gid):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    rec = get_or_404(db.group_blocks, gid)
    method = request.args.get("method", "LRV")
    if method not in EVAL_METHODS:
        raise err(ERR_INVALID_REQUEST, "method must be LRV or FORECAST_REV")

    # Evaluation requires an inventory day for every night in the window.
    _require_inventory_days(rec)

    cost, recommendation = compute_displacement(rec, method)
    rec["displacement_cost"] = cost
    rec["recommendation"] = recommendation
    bump(rec)
    return success(ser_group_block(rec), status=200)


@bp.route("/group-blocks/<gid>/request-revision", methods=["POST"])
def request_revision(gid):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    rec = get_or_404(db.group_blocks, gid)
    # Must be NEGOTIATING and have been evaluated to REJECT.
    if rec["status"] != "NEGOTIATING":
        raise err(ERR_INVALID_STATE, "Block is not in NEGOTIATING state")
    if rec["displacement_cost"] is None:
        raise err(ERR_NOT_EVALUATED, "Block has not been evaluated")
    if rec["recommendation"] != "REJECT":
        # Only a REJECT recommendation permits requesting a revision.
        raise err(ERR_INVALID_STATE, "Block did not evaluate to REJECT")
    rec["status"] = "REVISION_REQUESTED"
    bump(rec)
    return success(ser_group_block(rec), status=200)


@bp.route("/group-blocks/<gid>/commit", methods=["POST"])
def commit_group_block(gid):
    _, role = authenticate()
    require_role(role, {"GroupSalesManager"})
    rec = get_or_404(db.group_blocks, gid)
    body = get_body()
    expected_version = require_int(body, "expected_room_type_version")

    rt = db.room_types.get(rec["room_type_id"])

    # Gating order (PRD §3.7): state -> evaluated/ACCEPT -> LOS -> inventory day
    # exists -> OCC -> per-night availability.
    if rec["status"] != "NEGOTIATING":
        raise err(ERR_INVALID_STATE, "Block is not in NEGOTIATING state")
    if rec["displacement_cost"] is None:
        raise err(ERR_NOT_EVALUATED, "Block has not been evaluated")
    if rec["recommendation"] != "ACCEPT":
        raise err(ERR_NOT_EVALUATED, "Block did not evaluate to ACCEPT")

    # LOS check against the room type's master BAR plan (if any).
    mb = master_bar_plan(rec["room_type_id"])
    if mb is not None:
        nights = rec["nights"]
        if nights < mb["min_los"] or (mb["max_los"] > 0 and nights > mb["max_los"]):
            raise err(ERR_LOS_VIOLATION, "Block nights violate the master BAR LOS band")

    # Inventory day must exist for every night.
    invs = _require_inventory_days(rec)

    # OCC on room type.
    if expected_version != rt["version"]:
        raise err(ERR_STALE_VERSION, "expected_room_type_version does not match room type version")

    # Per-night availability after oversell ceiling >= rooms_per_night.
    rpn = rec["rooms_per_night"]
    for inv in invs:
        recompute_availability(inv)
        if inv["rooms_available"] < rpn:
            raise err(ERR_OVERSELL_LIMIT_EXCEEDED, "A night cannot accommodate the group's rooms")

    # Commit: status -> COMMITTED.
    rec["status"] = "COMMITTED"
    bump(rec)

    # Cascade hop 1: each overlapping InventoryDay group_held_rooms += rpn;
    # recompute availability and bump.
    for inv in invs:
        # group_held_rooms is derived from committed blocks; recompute_availability
        # already counts this block (now COMMITTED). Bump version + timestamp.
        recompute_availability(inv)
        bump(inv)

    # RoomType.version += 1.
    bump(rt)

    # Hop 2: property KPI recompute.
    prop = db.properties.get(rt["property_id"])
    if prop is not None:
        recompute_property_kpi(prop)
        bump(prop)

    return success(ser_group_block(rec), status=200)


@bp.route("/group-blocks/<gid>/cancel", methods=["POST"])
def cancel_group_block(gid):
    _, role = authenticate()
    require_role(role, {"GroupSalesManager"})
    rec = get_or_404(db.group_blocks, gid)
    status = rec["status"]
    if status == "COMMITTED":
        rec["status"] = "CANCELLED"
        bump(rec)
        # Each overlapping InventoryDay group_held_rooms -= rpn (now block no
        # longer COMMITTED, so recompute restores exactly), recompute + bump.
        invs = _inventory_days_for(rec)
        for inv in invs:
            recompute_availability(inv)
            bump(inv)
        rt = db.room_types.get(rec["room_type_id"])
        prop = db.properties.get(rt["property_id"]) if rt else None
        if prop is not None:
            recompute_property_kpi(prop)
            bump(prop)
        return success(ser_group_block(rec), status=200)
    elif status in ("NEGOTIATING", "REVISION_REQUESTED"):
        # No inventory held -> LOST, no inventory change.
        rec["status"] = "LOST"
        bump(rec)
        return success(ser_group_block(rec), status=200)
    else:
        raise err(ERR_INVALID_STATE, "Block cannot be cancelled from its current state")


# ----------------------------------------------------------------------------
def _block_night_keys(rec):
    from datetime import datetime, timezone
    start = datetime.strptime(rec["arrival_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(rec["nights"])]


def _inventory_days_for(rec):
    """Return the InventoryDay records overlapping the block window (those that
    exist)."""
    keys = set(_block_night_keys(rec))
    return [inv for inv in db.inventory_days.values()
            if inv["room_type_id"] == rec["room_type_id"] and inv["stay_date_key"] in keys]


def _require_inventory_days(rec):
    """Ensure every night has an InventoryDay; return the list of them."""
    keys = _block_night_keys(rec)
    found = {}
    for inv in db.inventory_days.values():
        if inv["room_type_id"] == rec["room_type_id"] and inv["stay_date_key"] in keys:
            found[inv["stay_date_key"]] = inv
    for k in keys:
        if k not in found:
            raise err(ERR_MISSING_INVENTORY_DAY, f"No InventoryDay exists for night {k}")
    return [found[k] for k in keys]
