"""UcutTag and CullRecord endpoints (PRD 3.7, 3.2)."""
from flask import Blueprint, request

from authz import require_role
from db import store
from errors import (block_not_harvestable, block_not_ucut, bucket_empty,
                    cull_exceeds_standing, invalid_state, not_found,
                    posture_forbids)
from helpers import (body, get_or_404, new_record, paginate, req_enum,
                     req_field, req_int, req_str, touch)
from respond import success
from serialize import cull_out, tag_out
from services import (CULL_REASONS, check_lot_depleted, lot_of_bucket,
                      season_of_block, tag_expiry_instant)

bp = Blueprint("tags", __name__)


# ---------------------------------------------------------------------------
# Choose-and-cut tags
# ---------------------------------------------------------------------------

@bp.post("/api/ucut-tags")
def create_tag():
    require_role("FarmManager")
    data = body()
    # Existence of body FK references, left to right (priority 4).
    block_id = req_field(data, "block_id")
    if isinstance(block_id, str):
        get_or_404(store.blocks, block_id, "block_id does not exist")
    bucket_id = req_field(data, "bucket_id")
    if isinstance(bucket_id, str):
        get_or_404(store.stand_buckets, bucket_id, "bucket_id does not exist")
    # Well-formedness (priority 5).
    block_id = req_str(data, "block_id")
    bucket_id = req_str(data, "bucket_id")
    customer_name = req_str(data, "customer_name")
    price_cents = req_int(data, "price_cents", minimum=0)
    block = store.blocks[block_id]
    bucket = store.stand_buckets[bucket_id]
    # The bucket must belong to a lot of the named block.
    if lot_of_bucket(bucket)["block_id"] != block_id:
        raise not_found("The bucket does not belong to the named block")
    # Posture (priority 7): every tag operation requires HARVEST.
    if season_of_block(block)["posture"] != "HARVEST":
        raise posture_forbids("Choose-and-cut tags require HARVEST posture")
    # Referential (priority 11): the block must be HARVESTABLE.
    if block["rotation_state"] != "HARVESTABLE":
        raise block_not_harvestable("The block is not HARVESTABLE")
    # Referential (priority 13): the block must be u-cut designated.
    if not block["ucut_designated"]:
        raise block_not_ucut("The block is not designated for choose-and-cut")
    # Constraint (priority 23): the bucket must have at least one standing tree.
    if bucket["standing_count"] < 1:
        raise bucket_empty("The bucket has no standing trees")
    # The tree is claimed the moment the tag is sold.
    bucket["standing_count"] -= 1
    bucket["tagged_active_count"] += 1
    touch(bucket)
    rec = new_record({
        "block_id": block_id,
        "bucket_id": bucket_id,
        "customer_name": customer_name,
        "price_cents": price_cents,
        "expires_at": tag_expiry_instant(store.clock),
        "status": "ACTIVE",
    })
    store.tags[rec["id"]] = rec
    return success(tag_out(rec), status=201)


@bp.get("/api/ucut-tags/<tid>")
def get_tag(tid):
    require_role("Owner", "FarmManager")
    return success(tag_out(get_or_404(store.tags, tid)))


@bp.get("/api/ucut-tags")
def list_tags():
    require_role("Owner", "FarmManager")
    items = sorted(store.tags.values(), key=lambda t: t["_seq"])
    block_id = request.args.get("block_id")
    bucket_id = request.args.get("bucket_id")
    status = request.args.get("status")
    if block_id is not None:
        items = [t for t in items if t["block_id"] == block_id]
    if bucket_id is not None:
        items = [t for t in items if t["bucket_id"] == bucket_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items)
    return success([tag_out(t) for t in page], response_type="array",
                   pagination=meta)


def _tag_harvest_gate(tag):
    if tag["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE tag can transition")
    block = store.blocks[tag["block_id"]]
    if season_of_block(block)["posture"] != "HARVEST":
        raise posture_forbids("Tag operations require HARVEST posture")


@bp.post("/api/ucut-tags/<tid>/redeem")
def redeem_tag(tid):
    require_role("FarmManager")
    tag = get_or_404(store.tags, tid)
    _tag_harvest_gate(tag)
    bucket = store.stand_buckets[tag["bucket_id"]]
    bucket["tagged_active_count"] -= 1
    bucket["ucut_sold_cumulative"] += 1
    touch(bucket)
    tag["status"] = "REDEEMED"
    touch(tag)
    check_lot_depleted(lot_of_bucket(bucket))
    return success(tag_out(tag))


@bp.post("/api/ucut-tags/<tid>/release")
def release_tag(tid):
    require_role("FarmManager")
    tag = get_or_404(store.tags, tid)
    _tag_harvest_gate(tag)
    bucket = store.stand_buckets[tag["bucket_id"]]
    bucket["tagged_active_count"] -= 1
    bucket["standing_count"] += 1
    touch(bucket)
    tag["status"] = "RELEASED"
    touch(tag)
    return success(tag_out(tag))


# ---------------------------------------------------------------------------
# Cull records
# ---------------------------------------------------------------------------

@bp.post("/api/cull-records")
def create_cull():
    require_role("FarmManager")
    data = body()
    bucket_id = req_field(data, "bucket_id")
    if isinstance(bucket_id, str):
        get_or_404(store.stand_buckets, bucket_id, "bucket_id does not exist")
    bucket_id = req_str(data, "bucket_id")
    count = req_int(data, "count", minimum=1)
    reason = req_enum(data, "reason", CULL_REASONS)
    bucket = store.stand_buckets[bucket_id]
    # Posture (priority 7): cull recording is permitted in any non-CLOSED posture.
    block = store.blocks[lot_of_bucket(bucket)["block_id"]]
    if season_of_block(block)["posture"] == "CLOSED":
        raise posture_forbids("The season is CLOSED")
    # Constraint (priority 22): count <= bucket available_count.
    if count > bucket["standing_count"] - bucket["reserved_count"]:
        raise cull_exceeds_standing("count exceeds the bucket's available_count")
    bucket["standing_count"] -= count
    bucket["culled_cumulative"] += count
    touch(bucket)
    rec = new_record({
        "bucket_id": bucket_id,
        "count": count,
        "reason": reason,
    })
    store.culls[rec["id"]] = rec
    check_lot_depleted(lot_of_bucket(bucket))
    return success(cull_out(rec), status=201)


@bp.get("/api/cull-records/<cid>")
def get_cull(cid):
    require_role("Owner", "FarmManager")
    return success(cull_out(get_or_404(store.culls, cid)))


@bp.get("/api/cull-records")
def list_culls():
    require_role("Owner", "FarmManager")
    items = sorted(store.culls.values(), key=lambda c: c["_seq"])
    bucket_id = request.args.get("bucket_id")
    if bucket_id is not None:
        items = [c for c in items if c["bucket_id"] == bucket_id]
    page, meta = paginate(items)
    return success([cull_out(c) for c in page], response_type="array",
                   pagination=meta)
