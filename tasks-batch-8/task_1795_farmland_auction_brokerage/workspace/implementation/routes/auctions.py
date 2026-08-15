"""Auctions (schedule/open/award/no-sale) and bid placement/reads."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import serializers
from errors import (
    raise_err, ERR_INVALID_LISTING_STATE, ERR_INVALID_AUCTION_STATE,
    ERR_AUCTION_NOT_OPEN, ERR_STALE_AUCTION_VERSION, ERR_BUYER_NOT_QUALIFIED,
    ERR_AUCTION_WINDOW_INVALID, ERR_LISTING_AUCTION_OVERLAP,
    ERR_AUCTIONEER_SCHEDULE_CONFLICT, ERR_TRACT_SCOPE_INVALID,
    ERR_DUPLICATE_RECORD, ERR_BID_BELOW_INCREMENT, ERR_BID_BELOW_MINIMUM,
    ERR_PROOF_OF_FUNDS_INSUFFICIENT, ERR_RESERVE_NOT_MET, ERR_VALIDATION,
    ERR_NOT_FOUND,
)
from middleware import auth, require_roles, forbid
from response import (
    success_object, success_list, get_body, as_str, as_enum, as_decimal,
    as_int, as_datetime, as_list, new_common, touch, paginate, fmt_dt,
)
from services import sweeps
from services.bidding import (
    increment, placed_high_for_scope, scope_key, combo_threshold, select_winners,
)
from .clock import get_or_404, new_id

bp = Blueprint("auctions", __name__)

ALL_ROLES = {"Seller", "BrokerAgent", "Buyer", "PlatformAdmin"}
METHODS = ("LIVE", "ONLINE", "SEALED_BID")
ACTIVE = sweeps.ACTIVE_AUCTION_STATES


def _listing_of(auction):
    return get_or_404(db.listings, auction["listing_id"], "listing")


def _own_listing_or_forbid(listing, user_id):
    if listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")


# ---------------------------------------------------------------------------
# Auction scheduling
# ---------------------------------------------------------------------------

@bp.post("/api/auctions")
def create_auction():
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    body = get_body()
    listing_id = body.get("listing_id")
    if listing_id is None:
        raise_err(ERR_VALIDATION, "missing required field: listing_id")
    listing = get_or_404(db.listings, listing_id, "listing")
    _own_listing_or_forbid(listing, user_id)

    method = as_enum(body, "method", METHODS)
    start = as_datetime(body, "scheduled_start")
    end = as_datetime(body, "scheduled_end")
    soft_close = as_int(body, "soft_close_window_minutes", required=False, default=5)
    extension = as_int(body, "extension_minutes", required=False, default=5)

    if listing["status"] not in ("MARKETED", "AUCTION_SCHEDULED"):
        raise_err(ERR_INVALID_LISTING_STATE,
                  "auctions may be scheduled only for MARKETED or AUCTION_SCHEDULED listings")

    now = db.clock_now()
    # Window well-formedness: end > start, duration >= 60 min, start >= clock + 24h.
    if end <= start or (end - start) < timedelta(minutes=60) or start < now + timedelta(hours=24):
        raise_err(ERR_AUCTION_WINDOW_INVALID,
                  "window malformed (end <= start, duration < 60 min, or start < clock + 24h)")

    # Per-listing half-open overlap; adjacency permitted.
    for a in db.auctions.values():
        if a["listing_id"] != listing["id"] or a["status"] not in ACTIVE:
            continue
        if start < a["_scheduled_end_dt"] and end > a["_scheduled_start_dt"]:
            raise_err(ERR_LISTING_AUCTION_OVERLAP,
                      "window overlaps another active auction of this listing")

    # Auctioneer 2h buffer against OTHER listings sharing the same agent.
    two_h = timedelta(hours=2)
    for a in db.auctions.values():
        if a["listing_id"] == listing["id"] or a["status"] not in ACTIVE:
            continue
        if a["agent_id"] != listing["agent_id"]:
            continue
        if start < a["_scheduled_end_dt"] + two_h and end + two_h > a["_scheduled_start_dt"]:
            raise_err(ERR_AUCTIONEER_SCHEDULE_CONFLICT,
                      "window within 2h of another auction for the same agent")

    auction = new_common({
        "id": new_id(),
        "listing_id": listing["id"],
        "agent_id": listing["agent_id"],
        "method": method,
        "scheduled_start": fmt_dt(start),
        "scheduled_end": fmt_dt(end),
        "_scheduled_start_dt": start,
        "_scheduled_end_dt": end,
        "soft_close_window_minutes": soft_close,
        "extension_minutes": extension,
        "effective_end": fmt_dt(end),
        "_effective_end_dt": end,
        "extension_count": 0,
        "awarded_total": None,
        "status": "SCHEDULED",
    })
    db.auctions[auction["id"]] = auction
    if listing["status"] == "MARKETED":
        listing["status"] = "AUCTION_SCHEDULED"
    touch(listing)
    return success_object(serializers.auction(auction), status=201)


@bp.get("/api/auctions/<aid>")
def get_auction(aid):
    auth()
    a = get_or_404(db.auctions, aid, "auction")
    return success_object(serializers.auction(a))


@bp.get("/api/listings/<lid>/auctions")
def list_auctions(lid):
    auth()
    listing = get_or_404(db.listings, lid, "listing")
    items = [a for a in db.auctions.values() if a["listing_id"] == listing["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.auction(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Auction lifecycle
# ---------------------------------------------------------------------------

@bp.post("/api/auctions/<aid>/open")
def open_auction(aid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    auction = get_or_404(db.auctions, aid, "auction")
    listing = _listing_of(auction)
    _own_listing_or_forbid(listing, user_id)
    if auction["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_AUCTION_STATE, "only a SCHEDULED auction can be opened")
    now = db.clock_now()
    if not (auction["_scheduled_start_dt"] <= now < auction["_scheduled_end_dt"]):
        raise_err(ERR_AUCTION_WINDOW_INVALID, "logical clock is outside the scheduled window")

    # Rights DECLARED -> LOCKED on every tract of the listing.
    for t in sweeps.listing_tracts(listing["id"]):
        for r in db.rights.values():
            if r["tract_id"] == t["id"] and r["status"] == "DECLARED":
                r["status"] = "LOCKED"
                touch(r)
        # Tracts UNSOLD -> OFFERED (re-offer after a partial award).
        if t["status"] == "UNSOLD":
            t["status"] = "OFFERED"
            touch(t)
    auction["status"] = "OPEN"
    touch(auction)
    return success_object(serializers.auction(auction))


@bp.post("/api/auctions/<aid>/award")
def award_auction(aid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    auction = get_or_404(db.auctions, aid, "auction")
    listing = _listing_of(auction)
    _own_listing_or_forbid(listing, user_id)
    if auction["status"] != "CLOSED_PENDING_AWARD":
        raise_err(ERR_INVALID_AUCTION_STATE, "only a CLOSED_PENDING_AWARD auction can be awarded")

    winners, losers, awarded_total, assigned = select_winners(auction)
    if awarded_total < listing["reserve_price_total"]:
        raise_err(ERR_RESERVE_NOT_MET, "awarded total is below the listing reserve")

    now = db.clock_now()
    for b in winners:
        b["status"] = "CONFIRMED_WINNER"
        touch(b)
    for b in losers:
        b["status"] = "LOST"
        touch(b)
    auction["awarded_total"] = awarded_total
    auction["status"] = "AWARDED"

    # Tracts in winning scopes -> SOLD; remaining OFFERED tracts -> UNSOLD.
    for t in sweeps.listing_tracts(listing["id"]):
        if t["status"] != "OFFERED":
            continue
        if t["id"] in assigned:
            t["status"] = "SOLD"
        else:
            t["status"] = "UNSOLD"
        touch(t)

    # Listing -> UNDER_CONTRACT iff every tract is SOLD.
    tracts = sweeps.listing_tracts(listing["id"])
    if tracts and all(t["status"] == "SOLD" for t in tracts):
        listing["status"] = "UNDER_CONTRACT"
        touch(listing)

    # Earnest-money deposit per winning bid.
    for b in winners:
        amount_due = max(
            Decimal("10000"),
            (Decimal("0.03") * b["amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )
        due = now + timedelta(hours=48)
        dep = new_common({
            "id": new_id(),
            "bid_id": b["id"],
            "buyer_id": b["buyer_id"],
            "amount_due": amount_due,
            "amount_received": Decimal("0"),
            "due_at": fmt_dt(due),
            "_due_at_dt": due,
            "amount_refunded": Decimal("0"),
            "amount_forfeited": Decimal("0"),
            "amount_applied": Decimal("0"),
            "status": "PENDING",
        })
        db.deposits[dep["id"]] = dep

    touch(auction)
    return success_object(serializers.auction(auction))


@bp.post("/api/auctions/<aid>/no-sale")
def no_sale_auction(aid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    auction = get_or_404(db.auctions, aid, "auction")
    listing = _listing_of(auction)
    _own_listing_or_forbid(listing, user_id)
    if auction["status"] != "CLOSED_PENDING_AWARD":
        raise_err(ERR_INVALID_AUCTION_STATE,
                  "only a CLOSED_PENDING_AWARD auction can be declared no-sale")

    sweeps.void_bids(auction, ("PLACED", "REVEALED"))
    auction["status"] = "NO_SALE"
    listing = _listing_of(auction)
    sweeps.no_sale_fallout(auction)
    touch(auction)
    return success_object(serializers.auction(auction))


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------

@bp.post("/api/bids")
def place_bid():
    user_id, role = auth()
    require_roles(role, {"Buyer"})
    body = get_body()

    auction_id = body.get("auction_id")
    if auction_id is None:
        raise_err(ERR_VALIDATION, "missing required field: auction_id")
    auction = get_or_404(db.auctions, auction_id, "auction")
    buyer = get_or_404(db.buyers, user_id, "buyer")
    tract_ids_raw = body.get("tract_ids")
    if isinstance(tract_ids_raw, list):
        for tid in tract_ids_raw:
            get_or_404(db.tracts, tid, "tract")

    amount = as_decimal(body, "amount", gt=0)
    tract_ids = as_list(body, "tract_ids")
    for tid in tract_ids:
        if not isinstance(tid, str):
            raise_err(ERR_VALIDATION, "tract_ids elements must be strings")
    expected = as_int(body, "expected_auction_version")

    # State gate: auction must be OPEN or EXTENDED with clock < effective_end.
    now = db.clock_now()
    if auction["status"] not in ("OPEN", "EXTENDED") or now >= auction["_effective_end_dt"]:
        raise_err(ERR_AUCTION_NOT_OPEN, "auction is not accepting bids")

    # Optimistic concurrency on the auction version.
    if expected != auction["version"]:
        raise_err(ERR_STALE_AUCTION_VERSION, "expected_auction_version is stale")

    # Bidder compliance.
    exp = buyer.get("_qualification_expires_dt")
    if buyer["qualification_status"] != "QUALIFIED" or exp is None or not (now < exp):
        raise_err(ERR_BUYER_NOT_QUALIFIED, "buyer is not QUALIFIED or qualification expired")

    # Scope rules.
    scope = list(dict.fromkeys(tract_ids))
    if not scope:
        raise_err(ERR_TRACT_SCOPE_INVALID, "tract_ids must be non-empty")
    listing = get_or_404(db.listings, auction["listing_id"], "listing")
    listing_tracts = sweeps.listing_tracts(listing["id"])
    listing_tract_ids = {t["id"] for t in listing_tracts}
    for tid in scope:
        if tid not in listing_tract_ids:
            raise_err(ERR_TRACT_SCOPE_INVALID, "bid scope references a foreign tract")
    scope_tracts = [db.tracts[tid] for tid in scope]
    for t in scope_tracts:
        if t["status"] != "OFFERED":
            raise_err(ERR_TRACT_SCOPE_INVALID, "bid scope includes a non-OFFERED tract")
    strategy = listing["packaging_strategy"]
    if strategy == "WHOLE" and set(scope) != listing_tract_ids:
        raise_err(ERR_TRACT_SCOPE_INVALID, "WHOLE listings require a full-tract scope")
    if strategy == "SPLIT" and len(scope) != 1:
        raise_err(ERR_TRACT_SCOPE_INVALID, "SPLIT listings require a single-tract scope")

    # Sealed-bid uniqueness: at most one bid per buyer per sealed auction.
    if auction["method"] == "SEALED_BID":
        for b in db.bids.values():
            if b["auction_id"] == auction["id"] and b["buyer_id"] == buyer["id"]:
                raise_err(ERR_DUPLICATE_RECORD, "only one sealed bid per buyer per auction")

    # Price economics.
    scope_set = frozenset(scope)
    min_sum = sum((t["min_price"] for t in scope_tracts), Decimal("0"))
    is_whole_scope = strategy == "WHOLE" and scope_set == frozenset(listing_tract_ids)
    if auction["method"] == "SEALED_BID":
        if amount < min_sum:
            raise_err(ERR_BID_BELOW_MINIMUM, "sealed bid below the scope minimum")
    elif len(scope) == 1 or is_whole_scope:
        high = placed_high_for_scope(auction["id"], scope_set)
        if high > 0:
            if amount < high + increment(high):
                raise_err(ERR_BID_BELOW_INCREMENT,
                          "bid below current high plus the tiered increment")
        else:
            if amount < min_sum:
                raise_err(ERR_BID_BELOW_MINIMUM, "bid below the scope minimum")
    else:
        threshold = combo_threshold(auction["id"], scope, ("PLACED",)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount < max(threshold, min_sum):
            raise_err(ERR_BID_BELOW_MINIMUM,
                      "combination bid below the premium threshold")

    # Proof of funds.
    if amount > buyer["proof_of_funds_amount"]:
        raise_err(ERR_PROOF_OF_FUNDS_INSUFFICIENT, "bid exceeds proof_of_funds_amount")

    # Acceptance ripples: prior identical single-tract high -> OUTBID (LIVE/ONLINE).
    if auction["method"] in ("LIVE", "ONLINE") and len(scope) == 1:
        for b in db.bids.values():
            if (b["auction_id"] == auction["id"] and b["status"] == "PLACED"
                    and scope_key(b) == scope_set and b["amount"] < amount):
                b["status"] = "OUTBID"
                touch(b)

    bid_status = "SEALED" if auction["method"] == "SEALED_BID" else "PLACED"
    bid = new_common({
        "id": new_id(),
        "auction_id": auction["id"],
        "buyer_id": buyer["id"],
        "amount": amount,
        "_amount_hidden": auction["method"] == "SEALED_BID",
        "tract_ids": list(tract_ids),
        "status": bid_status,
    })
    db.bids[bid["id"]] = bid

    # ONLINE soft close: a bid inside the soft-close window extends effective_end.
    if auction["method"] == "ONLINE":
        window = timedelta(minutes=auction["soft_close_window_minutes"])
        if auction["_effective_end_dt"] - window <= now < auction["_effective_end_dt"]:
            auction["_effective_end_dt"] = auction["_effective_end_dt"] + timedelta(
                minutes=auction["extension_minutes"])
            auction["effective_end"] = fmt_dt(auction["_effective_end_dt"])
            auction["extension_count"] += 1
            auction["status"] = "EXTENDED"

    touch(auction)  # every accepted bid increments the auction version
    return success_object(serializers.bid(bid), status=201)


@bp.get("/api/bids/<bid>")
def get_bid(bid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent", "PlatformAdmin", "Buyer"})
    b = get_or_404(db.bids, bid, "bid")
    if role == "Buyer" and b["buyer_id"] != user_id:
        forbid("a Buyer may read only its own bids")
    return success_object(serializers.bid(b))


@bp.get("/api/bids")
def list_bids():
    _, role = auth()
    require_roles(role, {"BrokerAgent", "PlatformAdmin"})
    items = list(db.bids.values())
    auction_id = request.args.get("auction_id")
    buyer_id = request.args.get("buyer_id")
    status = request.args.get("status")
    if auction_id is not None:
        items = [b for b in items if b["auction_id"] == auction_id]
    if buyer_id is not None:
        items = [b for b in items if b["buyer_id"] == buyer_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.bid(b) for b in page], limit, offset, total)
