"""LodgingBlock endpoints: create, get, list, commit, release (waterfall
allocation: per-crew shares rounded first, block total rounded separately,
residual posts as one overhead LODGING entry)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db, parse_iso, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_LODGING_WINDOW_OVERLAP, ERR_LODGING_HAS_ACTIVE_CREWS,
)
from services.core import (
    get_body, req_string, req_int, req_datetime, paginate, new_common, bump,
    get_event, get_block, serialize_block, sort_created_asc,
    post_ledger_entry, check_event_not_closed, block_rooms_allocated,
    LODGING_TAX_PCT,
)

bp = Blueprint("lodging_blocks", __name__)


@bp.route("/om/lodging-blocks", methods=["POST"])
def create_block():
    require_roles(["MutualAidCoordinator"])
    body = get_body()
    event_id = req_string(body, "storm_event_id")
    event = get_event(event_id)
    hotel = req_string(body, "hotel_name")
    county = req_string(body, "county_code")
    rooms = req_int(body, "room_count", minimum=1)
    rate = req_int(body, "nightly_rate_cents", minimum=0)
    ws = req_datetime(body, "window_start")
    we = req_datetime(body, "window_end")
    # Whole number of 24h nights.
    delta = (we - ws).total_seconds()
    if delta <= 0 or delta % 86400 != 0:
        raise_err(ERR_INVALID_REQUEST,
                  "Lodging window must span a whole number of 24h nights")
    check_event_not_closed(event)
    # Half-open overlap scope: (storm_event_id, hotel_name).
    for b in db.lodging_blocks.values():
        if b["storm_event_id"] != event_id or b["hotel_name"] != hotel:
            continue
        bws = parse_iso(b["window_start"])
        bwe = parse_iso(b["window_end"])
        if ws < bwe and bws < we:
            raise_err(ERR_LODGING_WINDOW_OVERLAP,
                      "Window overlaps an existing block for the same event and hotel")

    blk = new_common()
    blk.update({
        "storm_event_id": event_id,
        "hotel_name": hotel,
        "county_code": county,
        "room_count": rooms,
        "nightly_rate_cents": rate,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "block_status": "OPEN",
    })
    db.lodging_blocks[blk["id"]] = blk
    return success_object(serialize_block(blk), status=201)


@bp.route("/om/lodging-blocks/<bid>", methods=["GET"])
def get_one(bid):
    require_roles(ALL_ROLES)
    b = get_block(bid)
    return success_object(serialize_block(b))


@bp.route("/om/lodging-blocks", methods=["GET"])
def list_blocks():
    require_roles(ALL_ROLES)
    items = list(db.lodging_blocks.values())
    event_id = request.args.get("storm_event_id")
    status = request.args.get("block_status")
    if event_id is not None:
        items = [b for b in items if b["storm_event_id"] == event_id]
    if status is not None:
        items = [b for b in items if b["block_status"] == status]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_block(b) for b in page], limit, offset, total)


@bp.route("/om/lodging-blocks/<bid>/commit", methods=["POST"])
def commit(bid):
    require_roles(["MutualAidCoordinator"])
    b = get_block(bid)
    if b["block_status"] != "OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"LodgingBlock in {b['block_status']} cannot be committed")
    event = get_event(b["storm_event_id"])
    check_event_not_closed(event)
    b["block_status"] = "COMMITTED"
    bump(b)
    return success_object(serialize_block(b))


@bp.route("/om/lodging-blocks/<bid>/release", methods=["POST"])
def release(bid):
    require_roles(["MutualAidCoordinator"])
    b = get_block(bid)
    if b["block_status"] != "COMMITTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"LodgingBlock in {b['block_status']} cannot be released")
    event = get_event(b["storm_event_id"])
    check_event_not_closed(event)
    if block_rooms_allocated(b["id"]) != 0:
        raise_err(ERR_LODGING_HAS_ACTIVE_CREWS, "Crews are currently assigned to the block")

    b["block_status"] = "RELEASED"
    bump(b)

    # Waterfall allocation.
    bws = parse_iso(b["window_start"])
    bwe = parse_iso(b["window_end"])
    block_nights = int((bwe - bws).total_seconds() // 86400)
    tax_factor = Decimal(1) + LODGING_TAX_PCT
    block_total = int(
        (Decimal(b["room_count"]) * Decimal(block_nights)
         * Decimal(b["nightly_rate_cents"]) * tax_factor
         ).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    facts = [f for f in db.lodging_assignments if f["block_id"] == bid]
    facts.sort(key=lambda f: (parse_iso(f["created_at"]), f["_mono"]))
    shares_total = 0
    for f in facts:
        cws = parse_iso(f["window_start"])
        cwe = parse_iso(f["window_end"])
        overlap_start = max(cws, bws)
        overlap_end = min(cwe, bwe)
        nights = (overlap_end - overlap_start).total_seconds() / 86400.0
        crew_nights = int(nights) if nights > 0 else 0
        share = int(
            (Decimal(f["roster_size"]) * Decimal(crew_nights)
             * Decimal(b["nightly_rate_cents"]) * tax_factor
             ).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        shares_total += share
        post_ledger_entry(
            storm_event_id=b["storm_event_id"], work_order_id=None,
            entry_type="LODGING", cost_class="O_AND_M",
            county_code=b["county_code"], amount_cents=share,
        )

    residual = block_total - shares_total
    post_ledger_entry(
        storm_event_id=b["storm_event_id"], work_order_id=None,
        entry_type="LODGING", cost_class="O_AND_M",
        county_code=b["county_code"], amount_cents=residual,
    )
    return success_object(serialize_block(b))
