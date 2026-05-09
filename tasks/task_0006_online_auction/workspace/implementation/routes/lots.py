from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_LOT_NOT_FOUND,
    ERR_LOT_INVALID_STATE,
    ERR_LOT_DURATION_TOO_SHORT,
    ERR_LOT_START_IN_PAST,
    ERR_PHYSICAL_ITEM_TIME_OVERLAP,
    ERR_IDENTITY_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_FOUND,
)
from middleware import require_role
from response import success
from routes._helpers import (
    get_json_body,
    require_string,
    require_int,
    require_enum,
    require_datetime,
    parse_pagination,
    paginate,
)
from services.lot_service import (
    serialize_lot,
    serialize_invoice,
    bump,
    transition_to_defaulted,
    transition_reoffered_to_sold,
    transition_reoffered_to_unsold,
    _find_active_invoice,
)

bp = Blueprint("lots", __name__)

LOT_CATEGORIES = {"ART", "COLLECTIBLE", "ELECTRONICS", "JEWELRY", "REAL_ESTATE", "VEHICLE"}
LOT_CONDITIONS = {"NEW", "LIKE_NEW", "USED_GOOD", "USED_FAIR", "FOR_PARTS"}
LOT_STATUSES = {"DRAFT", "SCHEDULED", "LIVE", "SOLD", "UNSOLD", "REOFFERED", "DEFAULTED", "DISPUTED", "REFUNDED", "RELISTED", "CANCELLED"}


@bp.post("/lots")
def create_lot():
    user_id, _ = require_role({"Seller"})
    body = get_json_body()
    seller_id = require_string(body, "seller_id", min_len=1, max_len=200)
    title = require_string(body, "title", min_len=1, max_len=200)
    category = require_enum(body, "category", LOT_CATEGORIES)
    condition = require_enum(body, "condition", LOT_CONDITIONS)
    physical_item_serial = require_string(body, "physical_item_serial", min_len=1, max_len=200)
    reserve_price_cents = require_int(body, "reserve_price_cents", min_val=1)
    starting_bid_cents = require_int(body, "starting_bid_cents", min_val=1)
    scheduled_start_at = require_datetime(body, "scheduled_start_at")
    scheduled_end_at = require_datetime(body, "scheduled_end_at")

    # ERR_INVALID_REQUEST out-of-range scalars
    if starting_bid_cents > reserve_price_cents:
        raise_err(ERR_INVALID_REQUEST, "starting_bid_cents must be <= reserve_price_cents")

    # Identity check
    if seller_id != user_id:
        raise_err(ERR_IDENTITY_MISMATCH)

    lot_id = db.gen_id()
    now = db.now()
    lot = {
        "id": lot_id,
        "seller_id": seller_id,
        "title": title,
        "category": category,
        "condition": condition,
        "physical_item_serial": physical_item_serial,
        "reserve_price_cents": reserve_price_cents,
        "starting_bid_cents": starting_bid_cents,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "effective_end_at": None,
        "extension_count": 0,
        "status": "DRAFT",
        "current_price_cents": starting_bid_cents - 1,
        "current_winner_bid_id": None,
        "current_winner_bidder_id": None,
        "bid_count": 0,
        "has_met_reserve": False,
        "hammer_price_cents": None,
        "winning_bidder_id": None,
        "runner_up_bid_id": None,
        "payment_deadline_at": None,
        "hammer_at": None,
        "delivered_at": None,
        "relisted_from_lot_id": None,
        "runner_up_acceptance_deadline_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.lots[lot_id] = lot
    return success(serialize_lot(lot), http_status=201)


@bp.get("/lots/<lot_id>")
def get_lot(lot_id):
    require_role({"PlatformAdmin", "Seller", "Bidder", "ArbitratorOps", "Anonymous"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    return success(serialize_lot(lot))


@bp.get("/lots")
def list_lots():
    require_role({"PlatformAdmin", "Seller", "Bidder", "ArbitratorOps", "Anonymous"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    category = request.args.get("category")
    seller_id = request.args.get("seller_id")
    if status is not None and status not in LOT_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
    if category is not None and category not in LOT_CATEGORIES:
        raise_err(ERR_INVALID_REQUEST, "Invalid category filter")
    items = list(db.lots.values())
    if status:
        items = [l for l in items if l["status"] == status]
    if category:
        items = [l for l in items if l["category"] == category]
    if seller_id:
        items = [l for l in items if l["seller_id"] == seller_id]
    items.sort(key=lambda l: l["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([serialize_lot(l) for l in page], pagination=pag)


@bp.post("/lots/<lot_id>/publish")
def publish_lot(lot_id):
    user_id, _ = require_role({"Seller"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    if lot["status"] != "DRAFT":
        raise_err(ERR_LOT_INVALID_STATE)
    if lot["seller_id"] != user_id:
        raise_err(ERR_IDENTITY_MISMATCH)
    # Temporal checks (priority 11)
    duration_seconds = (lot["scheduled_end_at"] - lot["scheduled_start_at"]).total_seconds()
    if duration_seconds < 3600:
        raise_err(ERR_LOT_DURATION_TOO_SHORT)
    now = db.now()
    if lot["scheduled_start_at"] <= now:
        raise_err(ERR_LOT_START_IN_PAST)
    # Physical-item overlap (priority 12)
    active_set = {"SCHEDULED", "LIVE", "SOLD", "REOFFERED", "DEFAULTED", "DISPUTED"}
    for other in db.lots.values():
        if other["id"] == lot["id"]:
            continue
        if other["physical_item_serial"] != lot["physical_item_serial"]:
            continue
        if other["status"] not in active_set:
            continue
        # Half-open interval overlap
        a_start = lot["scheduled_start_at"]
        a_end = lot["scheduled_end_at"]  # for self the eff_end == sched_end at publish
        b_start = other["scheduled_start_at"]
        b_end = other.get("effective_end_at") or other["scheduled_end_at"]
        if a_start < b_end and a_end > b_start:
            raise_err(ERR_PHYSICAL_ITEM_TIME_OVERLAP)
    lot["status"] = "SCHEDULED"
    lot["effective_end_at"] = lot["scheduled_end_at"]
    bump(lot)
    return success(serialize_lot(lot))


@bp.post("/lots/<lot_id>/cancel")
def cancel_lot(lot_id):
    user_id, _ = require_role({"Seller"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    if lot["status"] not in ("DRAFT", "SCHEDULED"):
        raise_err(ERR_LOT_INVALID_STATE)
    if lot["seller_id"] != user_id:
        raise_err(ERR_IDENTITY_MISMATCH)
    lot["status"] = "CANCELLED"
    bump(lot)
    return success(serialize_lot(lot))


@bp.post("/lots/<lot_id>/winner/default")
def winner_default(lot_id):
    require_role({"PlatformAdmin"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    if lot["status"] != "SOLD":
        raise_err(ERR_LOT_INVALID_STATE)
    inv = _find_active_invoice(lot["id"])
    if inv is not None and inv["status"] not in ("PENDING", "ISSUED"):
        raise_err(ERR_LOT_INVALID_STATE)
    transition_to_defaulted(lot)
    return success(serialize_lot(lot))


@bp.post("/lots/<lot_id>/runner-up/accept")
def runner_up_accept(lot_id):
    user_id, _ = require_role({"Bidder"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    if lot["status"] != "REOFFERED":
        raise_err(ERR_LOT_INVALID_STATE)
    bidder = db.bidders.get(user_id)
    if bidder is None:
        raise_err(ERR_IDENTITY_MISMATCH)
    if bidder["status"] in ("RESTRICTED", "SUSPENDED"):
        from errors import ERR_BIDDER_RESTRICTED
        raise_err(ERR_BIDDER_RESTRICTED)
    runner_up_bid_id = lot.get("runner_up_bid_id")
    if not runner_up_bid_id:
        raise_err(ERR_LOT_INVALID_STATE)
    rb = db.bids.get(runner_up_bid_id)
    if not rb or rb["bidder_id"] != user_id:
        raise_err(ERR_IDENTITY_MISMATCH)
    # Window check
    deadline = lot.get("runner_up_acceptance_deadline_at")
    now = db.now()
    if deadline is not None and now > deadline:
        from errors import ERR_RUNNER_UP_WINDOW_EXPIRED
        raise_err(ERR_RUNNER_UP_WINDOW_EXPIRED)
    transition_reoffered_to_sold(lot, user_id)
    return success(serialize_lot(lot))


@bp.post("/lots/<lot_id>/runner-up/decline")
def runner_up_decline(lot_id):
    user_id, _ = require_role({"Bidder"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    if lot["status"] != "REOFFERED":
        raise_err(ERR_LOT_INVALID_STATE)
    runner_up_bid_id = lot.get("runner_up_bid_id")
    if not runner_up_bid_id:
        raise_err(ERR_LOT_INVALID_STATE)
    rb = db.bids.get(runner_up_bid_id)
    if not rb or rb["bidder_id"] != user_id:
        raise_err(ERR_IDENTITY_MISMATCH)
    transition_reoffered_to_unsold(lot)
    return success(serialize_lot(lot))


@bp.get("/lots/<lot_id>/invoice")
def get_invoice(lot_id):
    require_role({"PlatformAdmin", "Seller", "Bidder", "ArbitratorOps"})
    lot = db.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND)
    invs = [i for i in db.invoices.values() if i["lot_id"] == lot_id]
    if not invs:
        raise_err(ERR_INVOICE_NOT_FOUND)
    # Active (non-REVERSED) invoices precede reversed ones; otherwise newest first.
    invs.sort(key=lambda i: (1 if i["status"] == "REVERSED" else 0, -i["created_at"].timestamp()))
    return success(serialize_invoice(invs[0]))
