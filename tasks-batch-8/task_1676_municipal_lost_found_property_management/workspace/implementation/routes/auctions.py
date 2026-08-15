"""Auction events, lots, lot membership rows, sales, and settlement (PRD 3.8)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_STALE_LOT_VERSION,
    ERR_ITEM_NOT_AUCTION_ELIGIBLE, ERR_LOTS_NOT_FINAL, ERR_LOT_EMPTY,
    ERR_INVALID_TIME_WINDOW, ERR_VENUE_DOUBLE_BOOKED, ERR_EVENT_STILL_OPEN,
    ERR_CROSS_PROGRAM_REFERENCE, ERR_INSURANCE_CAP_EXCEEDED,
    ERR_BELOW_MINIMUM_BID, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authorized, STAFF_ROLES
from response import success_object, success_list
from services import core
from util import CLOCK, parse_dt, fmt_auto
from validate import (
    get_body, req_str, req_int, req_datetime, require_path, require_ref,
    pagination_params, opt_query_enum, opt_query_str, paginate,
)

bp = Blueprint("auctions", __name__)

COORDINATOR = {"AuctionCoordinator"}


# ---------------------------------------------------------------------------
# Auction events
# ---------------------------------------------------------------------------

@bp.post("/auction-events")
def create_event():
    body = get_body()
    venue_id = req_str(body, "venue_id")
    program_id = req_str(body, "program_id")
    name = req_str(body, "name")
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    authorized(COORDINATOR)
    require_ref("programs", program_id, "program_id")
    venue = require_ref("venues", venue_id, "venue_id")
    starts = parse_dt(starts_at)
    ends = parse_dt(ends_at)
    # Checks in order (PRD 3.8): window -> venue calendar -> cross-program.
    if not ends > starts:
        raise_error(ERR_INVALID_TIME_WINDOW, "ends_at must be strictly after starts_at")
    for ev in db["auction_events"].values():
        if ev["venue_id"] != venue_id:
            continue
        if ev["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        ev_s = parse_dt(ev["starts_at"])
        ev_e = parse_dt(ev["ends_at"])
        # Half-open [starts_at, ends_at) overlap; adjacency allowed.
        if starts < ev_e and ev_s < ends:
            raise_error(ERR_VENUE_DOUBLE_BOOKED,
                        "window overlaps another SCHEDULED/COMPLETED event at this venue")
    if program_id != venue["program_id"]:
        raise_error(ERR_CROSS_PROGRAM_REFERENCE,
                    "event program_id must equal the venue's program_id")
    rec = core.new_record("auction_events", {
        "venue_id": venue_id,
        "program_id": program_id,
        "name": name,
        "starts_at": fmt_auto(starts),
        "ends_at": fmt_auto(ends),
        "status": "SCHEDULED",
        "gross_proceeds_cents": None,
        "total_commission_cents": None,
        "net_proceeds_cents": None,
    })
    return success_object(rec, 201)


@bp.get("/auction-events")
def list_events():
    limit, offset = pagination_params()
    venue_id = opt_query_str("venue_id")
    program_id = opt_query_str("program_id")
    status = opt_query_enum("status", core.EVENT_STATUSES)
    authorized(STAFF_ROLES)
    recs = list(db["auction_events"].values())
    if venue_id is not None:
        recs = [r for r in recs if r["venue_id"] == venue_id]
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/auction-events/<event_id>")
def get_event(event_id):
    authorized(STAFF_ROLES)
    rec = require_path("auction_events", event_id)
    return success_object(rec)


def _release_lot_items(lot, bump_unsold):
    """Shared cascade core: transition lotted items, delete membership rows,
    recompute the lot minimum. bump_unsold=True runs the unsold escalation
    (close-unsold); False returns items to AUCTION_ELIGIBLE with no penalty
    (event cancel)."""
    rows = core.lot_items_of(lot["id"])
    for li in rows:
        item = db["items"].get(li["item_id"])
        if item is not None and item["status"] == "LOTTED":
            if bump_unsold:
                item["unsold_count"] += 1
                if item["unsold_count"] >= core.MAX_UNSOLD_CYCLES:
                    item["status"] = "DISPOSAL_PENDING"
                    item["pending_disposal_method"] = "DESTRUCTION"
                else:
                    item["status"] = "AUCTION_ELIGIBLE"
            else:
                item["status"] = "AUCTION_ELIGIBLE"
            core.touch(item)
        del db["lot_items"][li["id"]]
    core.recompute_lot_minimum(lot)


@bp.post("/auction-events/<event_id>/cancel")
def cancel_event(event_id):
    authorized(COORDINATOR)
    event = require_path("auction_events", event_id)
    if event["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "only a SCHEDULED event can be cancelled")
    for lot in db["auction_lots"].values():
        if lot["event_id"] != event["id"] or lot["status"] not in ("DRAFT", "PUBLISHED"):
            continue
        _release_lot_items(lot, bump_unsold=False)
        lot["status"] = "CANCELLED"
        core.touch(lot)
    event["status"] = "CANCELLED"
    core.touch(event)
    return success_object(event)


@bp.post("/auction-events/<event_id>/settle")
def settle_event(event_id):
    authorized(COORDINATOR)
    event = require_path("auction_events", event_id)
    # Preconditions in order (PRD 3.8): SCHEDULED -> all lots final -> clock.
    if event["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "only a SCHEDULED event can be settled")
    lots = [l for l in db["auction_lots"].values() if l["event_id"] == event["id"]]
    if any(l["status"] not in ("SOLD", "CLOSED_UNSOLD", "CANCELLED") for l in lots):
        raise_error(ERR_LOTS_NOT_FINAL,
                    "every lot must be SOLD, CLOSED_UNSOLD, or CANCELLED to settle")
    if CLOCK.now() < parse_dt(event["ends_at"]):
        raise_error(ERR_EVENT_STILL_OPEN, "the event window has not ended")
    gross, commission, net = core.settle_event_figures(event)
    event["gross_proceeds_cents"] = gross
    event["total_commission_cents"] = commission
    event["net_proceeds_cents"] = net
    event["status"] = "COMPLETED"
    core.touch(event)
    return success_object(event)


# ---------------------------------------------------------------------------
# Auction lots
# ---------------------------------------------------------------------------

@bp.post("/auction-lots")
def create_lot():
    body = get_body()
    event_id = req_str(body, "event_id")
    title = req_str(body, "title")
    caller = authorized(COORDINATOR)
    require_ref("auction_events", event_id, "event_id")
    rec = core.new_record("auction_lots", {
        "event_id": event_id,
        "title": title,
        "status": "DRAFT",
        "minimum_bid_cents": 0,
        "hammer_price_cents": None,
        "created_by": caller.user_id,
        "finalized_by": None,
    })
    return success_object(rec, 201)


@bp.get("/auction-lots")
def list_lots():
    limit, offset = pagination_params()
    event_id = opt_query_str("event_id")
    status = opt_query_enum("status", core.LOT_STATUSES)
    authorized(STAFF_ROLES)
    recs = list(db["auction_lots"].values())
    if event_id is not None:
        recs = [r for r in recs if r["event_id"] == event_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/auction-lots/<lot_id>")
def get_lot(lot_id):
    authorized(STAFF_ROLES)
    rec = require_path("auction_lots", lot_id)
    return success_object(rec)


@bp.post("/auction-lots/<lot_id>/items")
def add_lot_item(lot_id):
    body = get_body()
    item_id = req_str(body, "item_id")
    expected_lot_version = req_int(body, "expected_lot_version")
    authorized(COORDINATOR)
    lot = require_path("auction_lots", lot_id)
    item = require_ref("items", item_id, "item_id")
    # Checks in order (PRD 3.8): stale version -> lot DRAFT -> item eligible ->
    # cross-program -> insurance cap.
    if expected_lot_version != lot["version"]:
        raise_error(ERR_STALE_LOT_VERSION,
                    "expected_lot_version does not match the lot's current version")
    if lot["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "items may only be added to a DRAFT lot")
    if item["status"] != "AUCTION_ELIGIBLE":
        raise_error(ERR_ITEM_NOT_AUCTION_ELIGIBLE,
                    "item is not AUCTION_ELIGIBLE")
    event = db["auction_events"].get(lot["event_id"])
    if event is not None and item["program_id"] != event["program_id"]:
        raise_error(ERR_CROSS_PROGRAM_REFERENCE,
                    "lotted item's program must equal the event's program")
    venue = db["venues"].get(event["venue_id"]) if event is not None else None
    floor_price = core.floor_price_of(item)
    if venue is not None and lot["minimum_bid_cents"] + floor_price > venue["insurance_cap_cents"]:
        raise_error(ERR_INSURANCE_CAP_EXCEEDED,
                    "addition would push the lot minimum bid above the venue insurance cap")
    rec = core.new_record("lot_items", {
        "lot_id": lot["id"],
        "item_id": item["id"],
        "floor_price_cents": floor_price,
    }, with_version=False)
    item["status"] = "LOTTED"
    core.touch(item)
    core.recompute_lot_minimum(lot)
    core.touch(lot)
    return success_object(rec, 201)


@bp.delete("/auction-lots/<lot_id>/items/<item_id>")
def remove_lot_item(lot_id, item_id):
    authorized(COORDINATOR)
    lot = require_path("auction_lots", lot_id)
    item = require_path("items", item_id)
    row = next(
        (li for li in core.lot_items_of(lot["id"]) if li["item_id"] == item["id"]),
        None,
    )
    if row is None:
        raise_error(ERR_NOT_FOUND, "item is not a member of this lot")
    if lot["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "items may only be removed from a DRAFT lot")
    del db["lot_items"][row["id"]]
    if item["status"] == "LOTTED":
        item["status"] = "AUCTION_ELIGIBLE"
        core.touch(item)
    core.recompute_lot_minimum(lot)
    core.touch(lot)
    return "", 204


@bp.get("/auction-lots/<lot_id>/items")
def list_lot_items(lot_id):
    limit, offset = pagination_params()
    authorized(STAFF_ROLES)
    require_path("auction_lots", lot_id)
    recs = core.lot_items_of(lot_id)
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/lot-items")
def list_all_lot_items():
    limit, offset = pagination_params()
    lot_id = opt_query_str("lot_id")
    item_id = opt_query_str("item_id")
    authorized(STAFF_ROLES)
    recs = list(db["lot_items"].values())
    if lot_id is not None:
        recs = [r for r in recs if r["lot_id"] == lot_id]
    if item_id is not None:
        recs = [r for r in recs if r["item_id"] == item_id]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/lot-items/<lot_item_id>")
def get_lot_item(lot_item_id):
    authorized(STAFF_ROLES)
    rec = require_path("lot_items", lot_item_id)
    return success_object(rec)


@bp.post("/auction-lots/<lot_id>/publish")
def publish_lot(lot_id):
    authorized(COORDINATOR)
    lot = require_path("auction_lots", lot_id)
    if lot["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT lot can be published")
    if len(core.lot_items_of(lot["id"])) < 1:
        raise_error(ERR_LOT_EMPTY, "publishing a lot requires at least one item")
    lot["status"] = "PUBLISHED"
    core.touch(lot)
    return success_object(lot)


@bp.post("/auction-lots/<lot_id>/finalize-sale")
def finalize_sale(lot_id):
    body = get_body()
    hammer_price_cents = req_int(body, "hammer_price_cents", minimum=0)
    caller = authorized(COORDINATOR)
    lot = require_path("auction_lots", lot_id)
    # Checks in order (PRD 3.8): PUBLISHED -> duty segregation -> minimum bid.
    if lot["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "only a PUBLISHED lot can be finalized")
    if caller.user_id == lot["created_by"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the lot's creator may not finalize its sale")
    if hammer_price_cents < lot["minimum_bid_cents"]:
        raise_error(ERR_BELOW_MINIMUM_BID,
                    "hammer price is below the lot's minimum bid")
    lot["hammer_price_cents"] = hammer_price_cents
    lot["finalized_by"] = caller.user_id
    lot["status"] = "SOLD"
    core.touch(lot)
    for li in core.lot_items_of(lot["id"]):
        item = db["items"].get(li["item_id"])
        if item is not None and item["status"] == "LOTTED":
            item["status"] = "SOLD"  # frees the storage slot (PRD 2.9)
            core.touch(item)
    return success_object(lot)


@bp.post("/auction-lots/<lot_id>/close-unsold")
def close_unsold(lot_id):
    authorized(COORDINATOR)
    lot = require_path("auction_lots", lot_id)
    if lot["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "only a PUBLISHED lot can be closed unsold")
    _release_lot_items(lot, bump_unsold=True)
    lot["status"] = "CLOSED_UNSOLD"
    core.touch(lot)
    return success_object(lot)
