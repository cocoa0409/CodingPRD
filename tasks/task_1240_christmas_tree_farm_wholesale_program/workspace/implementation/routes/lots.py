"""CropLot, StandBucket, and InventorySurvey endpoints (PRD 3.1, 3.2)."""
from flask import Blueprint, request

from authz import require_role
from db import now, store
from errors import (block_occupied, invalid_state, malformed, posture_forbids,
                    stale_version)
from helpers import (body, get_or_404, is_int, new_record, paginate,
                     req_enum, req_field, req_int, req_str, touch)
from respond import success
from serialize import bucket_out, crop_lot_out, survey_out
from services import (HEIGHT_CLASSES, SPECIES, buckets_of_lot,
                      check_lot_depleted, over_reservation_sweep,
                      season_of_lot)

bp = Blueprint("lots", __name__)


def _req_counts(data, name):
    """Validate a six-key height-class count object (ints >= 0)."""
    raw = req_field(data, name)
    if not isinstance(raw, dict):
        raise malformed("Field %s must be an object over height classes" % name)
    out = {}
    for hc in HEIGHT_CLASSES:
        v = raw.get(hc)
        if not is_int(v) or v < 0:
            raise malformed("Field %s.%s must be an integer >= 0" % (name, hc))
        out[hc] = v
    return out


def _make_buckets(lot_id, counts):
    """Create the lot's six stand buckets (baseline = standing = counts)."""
    for hc in HEIGHT_CLASSES:
        b = new_record({
            "crop_lot_id": lot_id,
            "height_class": hc,
            "baseline_count": counts[hc],
            "standing_count": counts[hc],
            "reserved_count": 0,
            "tagged_active_count": 0,
            "cut_cumulative": 0,
            "culled_cumulative": 0,
            "ucut_sold_cumulative": 0,
            "consigned_cumulative": 0,
            "last_shrink_delta": None,
        })
        store.stand_buckets[b["id"]] = b


def create_lot_on_block(block, species, planted_year, counts):
    """Shared by direct planting and replant execution: lot + six buckets,
    block -> PLANTED."""
    lot = new_record({
        "block_id": block["id"],
        "species": species,
        "planted_year": planted_year,
        "status": "ACTIVE",
    })
    store.crop_lots[lot["id"]] = lot
    _make_buckets(lot["id"], counts)
    block["rotation_state"] = "PLANTED"
    touch(block)
    return lot


@bp.post("/api/crop-lots")
def create_crop_lot():
    require_role("FarmManager")
    data = body()
    # Existence of body FK references (priority 4).
    block_id = req_field(data, "block_id")
    if isinstance(block_id, str):
        get_or_404(store.blocks, block_id, "block_id does not exist")
    # Well-formedness (priority 5).
    block_id = req_str(data, "block_id")
    species = req_enum(data, "species", SPECIES)
    planted_year = req_int(data, "planted_year")
    counts = _req_counts(data, "initial_counts")
    # Referential (priority 12): block must be RESTING with no ACTIVE lot.
    block = store.blocks[block_id]
    if block["rotation_state"] != "RESTING":
        raise block_occupied("The block is not RESTING")
    if any(lot["block_id"] == block_id and lot["status"] == "ACTIVE"
           for lot in store.crop_lots.values()):
        raise block_occupied("The block already hosts an ACTIVE crop lot")
    lot = create_lot_on_block(block, species, planted_year, counts)
    return success(crop_lot_out(lot), status=201)


@bp.get("/api/crop-lots/<lid>")
def get_crop_lot(lid):
    require_role("Owner", "FarmManager")
    return success(crop_lot_out(get_or_404(store.crop_lots, lid)))


@bp.get("/api/crop-lots")
def list_crop_lots():
    require_role("Owner", "FarmManager")
    items = sorted(store.crop_lots.values(), key=lambda lot: lot["_seq"])
    block_id = request.args.get("block_id")
    if block_id is not None:
        items = [lot for lot in items if lot["block_id"] == block_id]
    page, meta = paginate(items)
    return success([crop_lot_out(lot) for lot in page], response_type="array",
                   pagination=meta)


@bp.get("/api/crop-lots/<lid>/stand-buckets")
def list_stand_buckets(lid):
    require_role("Owner", "FarmManager")
    get_or_404(store.crop_lots, lid)
    # Declared exception to created_at ordering: height-class enum order.
    items = buckets_of_lot(lid)
    page, meta = paginate(items)
    return success([bucket_out(b) for b in page], response_type="array",
                   pagination=meta)


@bp.get("/api/crop-lots/<lid>/surveys")
def list_lot_surveys(lid):
    require_role("Owner", "FarmManager")
    get_or_404(store.crop_lots, lid)
    items = [sv for sv in store.surveys.values() if sv["crop_lot_id"] == lid]
    items.sort(key=lambda sv: sv["_seq"])
    page, meta = paginate(items)
    return success([survey_out(sv) for sv in page], response_type="array",
                   pagination=meta)


@bp.post("/api/surveys")
def create_survey():
    require_role("FarmManager")
    data = body()
    # Existence (priority 4) then well-formedness (priority 5).
    lot_id = req_field(data, "crop_lot_id")
    if isinstance(lot_id, str):
        get_or_404(store.crop_lots, lot_id, "crop_lot_id does not exist")
    lot_id = req_str(data, "crop_lot_id")
    counts = _req_counts(data, "surveyed_counts")
    # Posture (priority 7): survey create is permitted in any non-CLOSED posture.
    lot = store.crop_lots[lot_id]
    if season_of_lot(lot)["posture"] == "CLOSED":
        raise posture_forbids("The season is CLOSED")
    rec = new_record({
        "crop_lot_id": lot_id,
        "surveyed_counts": counts,
        "status": "DRAFT",
        "posted_at": None,
    })
    store.surveys[rec["id"]] = rec
    return success(survey_out(rec), status=201)


@bp.post("/api/surveys/<sid>/post")
def post_survey(sid):
    require_role("FarmManager")
    survey = get_or_404(store.surveys, sid)
    data = body()
    # Well-formedness (priority 5): the OCC field is required.
    expected = req_int(data, "expected_crop_lot_version")
    lot = store.crop_lots[survey["crop_lot_id"]]
    # State (priority 6): only a DRAFT survey can be posted.
    if survey["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT survey can be posted")
    # Posture (priority 7): the lot's season must not be CLOSED.
    if season_of_lot(lot)["posture"] == "CLOSED":
        raise posture_forbids("The season is CLOSED")
    # Optimistic concurrency on the crop lot (ERR_STALE_VERSION, 412).
    if expected != lot["version"]:
        raise stale_version("expected_crop_lot_version does not match the lot version")

    # Re-baseline each bucket against the physical count.
    buckets = buckets_of_lot(lot["id"])
    for b in buckets:
        surveyed = survey["surveyed_counts"][b["height_class"]]
        b["last_shrink_delta"] = surveyed - b["standing_count"]
        b["baseline_count"] = surveyed
        b["standing_count"] = surveyed
        b["cut_cumulative"] = 0
        b["culled_cumulative"] = 0
        b["ucut_sold_cumulative"] = 0
        b["consigned_cumulative"] = 0
        # reserved_count and tagged_active_count survive the re-baseline.
        touch(b)
    # Over-reservation sweep per re-baselined bucket.
    for b in buckets:
        over_reservation_sweep(b)
    # The previously POSTED survey of this lot is superseded.
    for other in store.surveys.values():
        if (other["crop_lot_id"] == lot["id"] and other["id"] != survey["id"]
                and other["status"] == "POSTED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    survey["posted_at"] = now()
    survey["status"] = "POSTED"
    touch(survey)
    touch(lot)
    check_lot_depleted(lot)
    return success(survey_out(survey))
