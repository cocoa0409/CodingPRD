"""Block endpoints: create, read, list, advance-rotation (PRD 3.1)."""
from flask import Blueprint, request

from authz import require_role
from db import store
from errors import invalid_state, malformed
from helpers import (body, get_or_404, has_field, new_record, paginate,
                     req_field, req_num, req_str, touch)
from respond import success
from serialize import block_out

bp = Blueprint("blocks", __name__)


@bp.post("/api/blocks")
def create_block():
    require_role("FarmManager")
    data = body()
    # Existence of body FK references, left to right (priority 4).
    season_id = req_field(data, "season_id")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season_id does not exist")
    # Well-formedness (priority 5).
    season_id = req_str(data, "season_id")
    block_code = req_str(data, "block_code")
    acreage = req_num(data, "acreage")
    ucut_designated = data.get("ucut_designated", False)
    if not isinstance(ucut_designated, bool):
        raise malformed("Field ucut_designated must be a boolean")
    if any(b["season_id"] == season_id and b["block_code"] == block_code
           for b in store.blocks.values()):
        raise malformed("block_code must be unique within the season")
    rec = new_record({
        "season_id": season_id,
        "block_code": block_code,
        "acreage": acreage,
        "ucut_designated": ucut_designated,
        "rotation_state": "RESTING",
    })
    store.blocks[rec["id"]] = rec
    return success(block_out(rec), status=201)


@bp.get("/api/blocks/<bid>")
def get_block(bid):
    require_role("Owner", "FarmManager")
    return success(block_out(get_or_404(store.blocks, bid)))


@bp.get("/api/blocks")
def list_blocks():
    require_role("Owner", "FarmManager")
    items = sorted(store.blocks.values(), key=lambda b: b["_seq"])
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [b for b in items if b["season_id"] == season_id]
    page, meta = paginate(items)
    return success([block_out(b) for b in page], response_type="array",
                   pagination=meta)


@bp.post("/api/blocks/<bid>/advance-rotation")
def advance_rotation(bid):
    require_role("FarmManager")
    block = get_or_404(store.blocks, bid)
    state = block["rotation_state"]

    if state == "RESTING":
        # RESTING -> PLANTED is system-driven only (crop-lot create or
        # replant execute); the explicit advance cannot leave RESTING.
        raise invalid_state("A RESTING block is planted via crop-lot or replant")

    if state in ("PLANTED", "GROWING"):
        # Requires a lot in ACTIVE on this block.
        if not any(lot["block_id"] == bid and lot["status"] == "ACTIVE"
                   for lot in store.crop_lots.values()):
            raise invalid_state("The block has no ACTIVE crop lot")
        block["rotation_state"] = "GROWING" if state == "PLANTED" else "HARVESTABLE"

    elif state == "HARVESTABLE":
        lot_ids = {lot["id"] for lot in store.crop_lots.values()
                   if lot["block_id"] == bid}
        bucket_ids = {b["id"] for b in store.stand_buckets.values()
                      if b["crop_lot_id"] in lot_ids}
        if any(a["bucket_id"] in bucket_ids and a["status"] in ("RESERVED", "CUT")
               for a in store.allocations.values()):
            raise invalid_state("Allocations remain RESERVED or CUT on this block")
        if any(t["block_id"] == bid and t["status"] == "ACTIVE"
               for t in store.tags.values()):
            raise invalid_state("Choose-and-cut tags remain ACTIVE on this block")
        block["rotation_state"] = "HARVESTED"

    elif state == "HARVESTED":
        lots = [lot for lot in store.crop_lots.values() if lot["block_id"] == bid]
        if not lots or any(lot["status"] != "DEPLETED" for lot in lots):
            raise invalid_state("Every crop lot of the block must be DEPLETED")
        block["rotation_state"] = "RESTING"

    else:
        raise invalid_state("Unknown rotation state")

    touch(block)
    return success(block_out(block))
