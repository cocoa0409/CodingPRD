"""Pellet lot endpoints — pelletizing and cold-storage inventory (PRD §3.4)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_FARM_MANAGER
from response import success_object, success_list, parse_pagination
from util import get_body, check_unknown_fields, req_str, req_str_list
from errors import ApiError, ERR_LOT_NOT_DRIED, ERR_MIXED_VARIETY, ERR_MIXED_CROP_YEAR
from services.core import (
    base_record, touch, public, get_pellet_lot,
    compute_pellet_qty, recompute_pellet_blend, filtered_sorted,
    VARIETIES, INVENTORY_STATUSES, AGE_CLASSES,
)

bp = Blueprint("pellet_lots", __name__)


@bp.route("/api/pellet-lots", methods=["POST"])
def create_pellet_lot():
    require_roles([ROLE_FARM_MANAGER])
    body = get_body()
    check_unknown_fields(body, {"source_lot_ids", "storage_room"})
    source_lot_ids = req_str_list(body, "source_lot_ids", min_items=1)
    storage_room = req_str(body, "storage_room")

    source_lots = []
    for sid in source_lot_ids:
        lot = store.harvest_lots.get(sid)
        if lot is None:
            from errors import not_found
            raise not_found("HarvestLot not found")
        source_lots.append(lot)

    # priority 11: every source lot must be DRIED
    for lot in source_lots:
        if lot["status"] != "DRIED":
            raise ApiError(ERR_LOT_NOT_DRIED, 422,
                           "A source harvest lot is not DRIED")
    # priority 12: one variety, one crop year across the blend
    if len({lot["variety"] for lot in source_lots}) != 1:
        raise ApiError(ERR_MIXED_VARIETY, 422, "Source lots do not all share one variety")
    if len({lot["crop_year"] for lot in source_lots}) != 1:
        raise ApiError(ERR_MIXED_CROP_YEAR, 422, "Source lots do not all share one crop_year")

    qty_lbs = compute_pellet_qty(source_lots)

    rec = base_record()
    rec.update({
        "source_lot_ids": list(source_lot_ids),
        "variety": source_lots[0]["variety"],
        "crop_year": source_lots[0]["crop_year"],
        "qty_lbs": qty_lbs,
        "blended_alpha_pct": None,  # filled below from current alpha data
        "storage_room": storage_room,
        "entered_storage_at": store.now(),
        "inventory_status": "AVAILABLE",
        "age_class": "CURRENT",
    })
    rec["blended_alpha_pct"] = recompute_pellet_blend(rec)
    store.pellet_lots[rec["id"]] = rec

    # every source lot moves DRIED -> CONSUMED
    for lot in source_lots:
        lot["status"] = "CONSUMED"
        touch(lot)

    return success_object(public(rec), status=201)


@bp.route("/api/pellet-lots/<lot_id>", methods=["GET"])
def get_pellet_lot_endpoint(lot_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_pellet_lot(lot_id)))


@bp.route("/api/pellet-lots", methods=["GET"])
def list_pellet_lots():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.pellet_lots.values()), request.args, {
        "variety": ("enum", "variety", VARIETIES),
        "inventory_status": ("enum", "inventory_status", INVENTORY_STATUSES),
        "age_class": ("enum", "age_class", AGE_CLASSES),
        "source_lot_ids": ("member", "source_lot_ids"),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)
