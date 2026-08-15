"""Distribution lines: add, remove, return, reverse lookups (PRD 3.3)."""
from flask import Blueprint, request

import db
import services as svc
from db import stamp_new, store, touch
from errors import ApiError, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from routes.visits import get_visit_or_404
from util import get_body, opt_enum_filter, page_params, paginate

bp = Blueprint("lines", __name__)

LINE_STATUSES = {"ACTIVE", "DISTRIBUTED", "RELEASED", "RETURNED"}


def get_line_or_404(line_id):
    ln = store.lines.get(line_id)
    if ln is None:
        raise not_found("Distribution line not found")
    return ln


@bp.post("/closet/visits/<vid>/lines")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def add_line(vid):
    visit = get_visit_or_404(vid)
    data = get_body()
    item_id = data.get("item_id")
    if item_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: item_id")
    if not isinstance(item_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "item_id must be a string")
    item = store.items.get(item_id)
    if item is None:
        raise not_found("Item not found")

    # Availability: visit CHECKED_IN and item STOCKED (PRD 3.3 — both surface
    # as ERR_ITEM_NOT_AVAILABLE).
    if visit["status"] != "CHECKED_IN":
        raise ApiError(
            "ERR_ITEM_NOT_AVAILABLE", 409, "Visit is not CHECKED_IN"
        )
    if item["status"] != "STOCKED":
        raise ApiError(
            "ERR_ITEM_NOT_AVAILABLE", 409, "Item is not currently STOCKED"
        )

    drive = None
    is_drive_line = False
    if item["drive_id"] is not None:
        drive = store.drives.get(item["drive_id"])
        if drive is not None:
            svc.refresh_drive(drive)
            is_drive_line = drive["status"] == "ACTIVE"

    active = [
        ln for ln in store.lines.values()
        if ln["visit_id"] == vid and ln["status"] == "ACTIVE"
    ]

    # Limit order (PRD 3.3): per-visit allowance, category cap, rolling cap,
    # drive-active requirement.
    if is_drive_line:
        pool_count = sum(
            1 for ln in active if ln["is_drive_line"] and ln["drive_id"] == drive["id"]
        )
        if pool_count + 1 > drive["bonus_items_per_client"]:
            raise ApiError(
                "ERR_ITEM_LIMIT_EXCEEDED", 409,
                "Drive bonus pool exhausted for this visit",
            )
    else:
        general_count = sum(1 for ln in active if not ln["is_drive_line"])
        if general_count + 1 > visit["general_allowance"]:
            raise ApiError(
                "ERR_ITEM_LIMIT_EXCEEDED", 409,
                "Per-visit general allowance exhausted",
            )
        cap = svc.CATEGORY_CAPS.get(item["category"])
        if cap is not None:
            cat_count = sum(
                1 for ln in active
                if not ln["is_drive_line"]
                and ln["category_snapshot"] == item["category"]
            )
            if cat_count + 1 > cap:
                raise ApiError(
                    "ERR_CATEGORY_LIMIT_EXCEEDED", 409,
                    f"Category cap exceeded for {item['category']}",
                )
    _, items_30d = svc.visit_window_stats(visit["client_id"])
    if items_30d + len(active) + 1 > svc.MAX_ITEMS_PER_30D:
        raise ApiError(
            "ERR_ROLLING_ITEM_CAP_EXCEEDED", 409,
            "Rolling 30-day item cap would be exceeded",
        )
    if item["drive_id"] is not None and not is_drive_line:
        raise ApiError(
            "ERR_DRIVE_NOT_ACTIVE", 409,
            "The item's drive is not ACTIVE",
        )

    item["status"] = "RESERVED"
    item["reserved_visit_id"] = vid
    touch(item)
    line = stamp_new({
        "visit_id": vid,
        "item_id": item["id"],
        "category_snapshot": item["category"],
        "is_drive_line": is_drive_line,
        "drive_id": drive["id"] if is_drive_line else None,
        "status": "ACTIVE",
    })
    store.lines[line["id"]] = line
    return ok(svc.serialize_line(line), 201)


@bp.get("/closet/distribution-lines/<lid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_line(lid):
    return ok(svc.serialize_line(get_line_or_404(lid)))


@bp.get("/closet/distribution-lines")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_lines():
    status = opt_enum_filter("status", LINE_STATUSES)
    visit_id = request.args.get("visit_id")
    item_id = request.args.get("item_id")
    drive_id = request.args.get("drive_id")
    limit, offset = page_params()
    rows = list(store.lines.values())
    if visit_id is not None:
        rows = [l for l in rows if l["visit_id"] == visit_id]
    if item_id is not None:
        rows = [l for l in rows if l["item_id"] == item_id]
    if drive_id is not None:
        rows = [l for l in rows if l["drive_id"] == drive_id]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_line(l) for l in page], total, limit, offset)


@bp.delete("/closet/distribution-lines/<lid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def delete_line(lid):
    ln = get_line_or_404(lid)
    visit = store.visits.get(ln["visit_id"])
    if ln["status"] != "ACTIVE" or visit is None or visit["status"] != "CHECKED_IN":
        raise invalid_state("Only an ACTIVE line on a CHECKED_IN visit can be removed")
    ln["status"] = "RELEASED"
    touch(ln)
    item = store.items[ln["item_id"]]
    if item["status"] == "RESERVED":
        item["status"] = "STOCKED"
        item["reserved_visit_id"] = None
        touch(item)
    return ok(svc.serialize_line(ln))


@bp.post("/closet/distribution-lines/<lid>/return")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def return_line(lid):
    ln = get_line_or_404(lid)
    if ln["status"] != "DISTRIBUTED":
        raise invalid_state("Only a DISTRIBUTED line can be returned")
    ln["status"] = "RETURNED"
    touch(ln)
    item = store.items[ln["item_id"]]
    zone = store.zones.get(item["distributed_from_zone_id"])
    item["status"] = "STOCKED"
    item["storage_zone_id"] = item["distributed_from_zone_id"]
    item["stocked_at"] = db.now()
    touch(item)
    if zone is not None:
        # Returns deliberately bypass the capacity check (PRD 3.3).
        zone["current_stock"] += 1
        touch(zone)
    return ok(svc.serialize_line(ln))
