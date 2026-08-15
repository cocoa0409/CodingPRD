"""Item stocking, quarantine, and release (PRD 3.6), reads and filters."""
from flask import Blueprint, request

import db
import services as svc
from db import store, touch
from errors import ApiError, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from util import get_body, opt_enum_filter, page_params, paginate

bp = Blueprint("items", __name__)

ITEM_STATUSES = {
    "PENDING_STOCK", "STOCKED", "RESERVED", "DISTRIBUTED",
    "OFF_SEASON", "QUARANTINED", "REJECTED", "RECYCLED",
}


def get_item_or_404(item_id):
    i = store.items.get(item_id)
    if i is None:
        raise not_found("Item not found")
    return i


def get_zone_or_404(zone_id):
    z = store.zones.get(zone_id)
    if z is None:
        raise not_found("Storage zone not found")
    return z


@bp.get("/closet/items/<iid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_item(iid):
    return ok(svc.serialize_item(get_item_or_404(iid)))


@bp.get("/closet/items")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_items():
    status = opt_enum_filter("status", ITEM_STATUSES)
    season = opt_enum_filter("season", svc.SEASONS)
    category = opt_enum_filter("category", svc.CATEGORIES)
    batch_id = request.args.get("donation_batch_id")
    zone_id = request.args.get("storage_zone_id")
    drive_id = request.args.get("drive_id")
    recycling_id = request.args.get("recycling_batch_id")
    limit, offset = page_params()
    rows = list(store.items.values())
    if batch_id is not None:
        rows = [i for i in rows if i["donation_batch_id"] == batch_id]
    if zone_id is not None:
        rows = [i for i in rows if i["storage_zone_id"] == zone_id]
    if drive_id is not None:
        rows = [i for i in rows if i["drive_id"] == drive_id]
    if recycling_id is not None:
        rows = [i for i in rows if i["recycling_batch_id"] == recycling_id]
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    if season is not None:
        rows = [i for i in rows if i["season"] == season]
    if category is not None:
        rows = [i for i in rows if i["category"] == category]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_item(i) for i in page], total, limit, offset)


@bp.post("/closet/items/<iid>/stock")
@require_roles("VolunteerLead", "Volunteer")
def stock_item(iid):
    item = get_item_or_404(iid)
    data = get_body()
    zone_id = data.get("storage_zone_id")
    if zone_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: storage_zone_id"
        )
    if not isinstance(zone_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "storage_zone_id must be a string")
    zone = get_zone_or_404(zone_id)

    # Check order (PRD 3.6): state, zone fullness, season, drive status.
    if item["status"] != "PENDING_STOCK":
        raise invalid_state("Only a PENDING_STOCK item can be stocked")
    if zone["current_stock"] >= zone["capacity_items"]:
        raise ApiError("ERR_ZONE_FULL", 409, "Zone is at capacity")
    if not svc.season_compatible(item["season"], zone["season_policy"]):
        raise ApiError(
            "ERR_SEASON_INCOMPATIBLE", 409,
            "Item season is incompatible with the zone's season policy",
        )
    if item["drive_id"] is not None:
        drive = store.drives.get(item["drive_id"])
        if drive is not None:
            svc.refresh_drive(drive)
        if drive is None or drive["status"] not in ("UPCOMING", "ACTIVE"):
            raise ApiError(
                "ERR_DRIVE_NOT_ACTIVE", 409,
                "Drive-pool items may only be stocked while the drive is "
                "UPCOMING or ACTIVE",
            )
    item["status"] = "STOCKED"
    item["storage_zone_id"] = zone["id"]
    item["stocked_at"] = db.now()
    touch(item)
    zone["current_stock"] += 1
    touch(zone)
    return ok(svc.serialize_item(item))


@bp.post("/closet/items/<iid>/quarantine")
@require_roles("ProgramAdmin", "VolunteerLead")
def quarantine_item(iid):
    item = get_item_or_404(iid)
    if item["status"] != "STOCKED":
        raise invalid_state("Only a STOCKED item can be quarantined")
    item["status"] = "QUARANTINED"
    touch(item)
    zone = store.zones.get(item["storage_zone_id"])
    if zone is not None:
        zone["current_stock"] -= 1
        touch(zone)
    return ok(svc.serialize_item(item))


@bp.post("/closet/items/<iid>/release-quarantine")
@require_roles("ProgramAdmin", "VolunteerLead")
def release_quarantine(iid):
    item = get_item_or_404(iid)
    data = get_body()
    outcome = data.get("outcome")
    if outcome is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: outcome")
    if outcome not in ("RESTOCK", "REJECT"):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "outcome must be RESTOCK or REJECT"
        )
    if item["status"] != "QUARANTINED":
        raise invalid_state("Only a QUARANTINED item can be released")
    if outcome == "RESTOCK":
        # Back into the same zone, deliberately bypassing the capacity check.
        item["status"] = "STOCKED"
        item["stocked_at"] = db.now()
        touch(item)
        zone = store.zones.get(item["storage_zone_id"])
        if zone is not None:
            zone["current_stock"] += 1
            touch(zone)
    else:
        item["status"] = "REJECTED"
        item["storage_zone_id"] = None
        touch(item)
    return ok(svc.serialize_item(item))
