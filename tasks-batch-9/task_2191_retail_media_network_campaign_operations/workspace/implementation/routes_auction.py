"""The sponsored placement auction, its bid ledger and engagement ingestion
(PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint

from core import (
    F, ceil_int, db, dec, fail, insert, new_row, now, ok, rhu, rows,
    sort_rows, touch, trunc_int,
)
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("auction", __name__)

AUCTION_WRITE = ("NetworkAdmin", "AuctionService")
AUCTION_READ = ("NetworkAdmin", "AuctionService", "MeasurementAnalyst",
                "BillingOps", "AccountManager")
BID_READ = ("NetworkAdmin", "AuctionService", "MeasurementAnalyst",
            "AccountManager")
SETTLE_ROLES = ("NetworkAdmin", "AuctionService", "BillingOps")
ENGAGEMENT_READ = ("NetworkAdmin", "AuctionService", "MeasurementAnalyst",
                   "BillingOps", "AccountManager", "AdvertiserUser")
ENGAGEMENT_ONE_READ = ("NetworkAdmin", "AuctionService", "MeasurementAnalyst",
                       "BillingOps", "AccountManager")

SEGMENTS = ("NEW", "RETURNING", "LOYALTY")
EVENT_TYPES = ("IMPRESSION", "CLICK", "OFFSITE_VIEW")

AUCTION_FILTERS = (
    ("placement_slot_id", "placement_slot_id", "string"),
    ("winning_line_item_id", "winning_line_item_id", "string"),
    ("status", "status", "string"),
    ("shopper_segment", "shopper_segment", "string"),
)
BID_FILTERS = (
    ("auction_event_id", "auction_event_id", "string"),
    ("line_item_id", "line_item_id", "string"),
    ("outcome", "outcome", "string"),
    ("filter_reason", "filter_reason", "string"),
)
ENGAGEMENT_FILTERS = (
    ("line_item_id", "line_item_id", "string"),
    ("auction_event_id", "auction_event_id", "string"),
    ("catalog_product_id", "catalog_product_id", "string"),
    ("event_type", "event_type", "string"),
    ("channel", "channel", "string"),
)


# ---------------------------------------------------------------------------
# Auction events
# ---------------------------------------------------------------------------
@bp.post("/rmn/auction-events")
def open_auction():
    specs = (
        F("placement_slot_id", "string", required=True),
        F("request_context_query", "string", required=True),
        F("shopper_segment", "enum", required=True, enum=SEGMENTS),
        F("requested_at", "datetime", required=True),
    )
    ctx = guard(AUCTION_WRITE, body_specs=specs,
                body_refs=(("placement_slot", "placement_slot_id"),))
    data = ctx.data
    slot = ctx.get("placement_slot")
    if slot["slot_status"] != "OPEN":
        fail("ERR_SLOT_NOT_OPEN",
             "The placement slot is %s." % slot["slot_status"])
    row = new_row()
    row.update({
        "placement_slot_id": data["placement_slot_id"],
        "winning_line_item_id": None,
        "status": "OPEN",
        "request_context_query": data["request_context_query"],
        "shopper_segment": data["shopper_segment"],
        "requested_at": data["requested_at"],
        "candidate_count": 0,
        "winner_score": None,
        "second_best_score": None,
        "clearing_price_cents": None,
        "settled_spend_cents": 0,
        "no_fill_reason": "NONE",
    })
    insert("auction_event", row)
    return ok(D.ser_auction_event(row), 201)


@bp.get("/rmn/auction-events")
def list_auctions():
    ctx = guard(AUCTION_READ, paginated=True)
    return H.respond_list(ctx, "auction_event", rows("auction_event"),
                          AUCTION_FILTERS)


@bp.get("/rmn/auction-events/<aid>")
def read_auction(aid):
    ctx = guard(AUCTION_READ, path_refs=(("auction_event", aid),))
    return ok(D.ser_auction_event(ctx.get("auction_event")))


# --- the ordered five-clause filter chain -----------------------------------
def _filter_reason(li, auction, slot, relevance, headroom, qas):
    camp = D.campaign_of_line_item(li)
    adv = D.advertiser_of_campaign(camp)
    plan = D.plan_of_campaign(camp)
    requested_at = auction["requested_at"]
    if (li["line_item_status"] != "SERVING"
            or camp is None or camp["delivery_status"] != "DELIVERING"
            or adv is None or adv["onboarding_status"] != "ACTIVE"
            or plan is None or plan["plan_status"] != "ACTIVE"
            or requested_at < li["flight_start_at"]
            or requested_at >= li["flight_end_at"]):
        return "NOT_SERVING"
    if D.eligible_product_count(li) == 0:
        return "NO_ELIGIBLE_PRODUCTS"
    if relevance == Decimal("0.0000"):
        return "ZERO_TERM_OVERLAP"
    if headroom <= 0:
        return "DAILY_BUDGET_EXHAUSTED"
    if qas < dec(slot["floor_cpc_cents"]):
        return "BELOW_FLOOR"
    return "NONE"


@bp.post("/rmn/auction-events/<aid>/rank")
def rank_auction(aid):
    ctx = guard(AUCTION_WRITE, path_refs=(("auction_event", aid),))
    auction = ctx.get("auction_event")
    slot = db.placement_slots[auction["placement_slot_id"]]
    if slot["slot_status"] != "OPEN":
        fail("ERR_SLOT_NOT_OPEN",
             "The placement slot is %s." % slot["slot_status"])
    if auction["status"] != "OPEN":
        fail("ERR_AUCTION_INVALID_STATE",
             "Ranking requires an OPEN auction; this one is %s."
             % auction["status"])

    candidates = sort_rows(D.line_items_of_slot(slot["id"]))
    computed = []
    for li in candidates:
        relevance = D.relevance_for(li, auction)
        tier = D.priority_tier(li)
        headroom = D.daily_headroom(li)
        effective_bid = min(li["bid_cents"], headroom)
        qas = D.quality_adjusted(effective_bid, relevance,
                                 slot["relevance_weight"], tier)
        reason = _filter_reason(li, auction, slot, relevance, headroom, qas)
        computed.append({
            "li": li, "relevance": relevance, "tier": tier,
            "effective_bid": effective_bid, "qas": qas, "reason": reason,
        })

    survivors = [c for c in computed if c["reason"] == "NONE"]
    survivors.sort(key=lambda c: (-c["qas"], -c["effective_bid"],
                                  D.TIER_ORDER[c["tier"]],
                                  c["li"]["created_at"], c["li"]["_seq"]))
    ranks = {}
    for index, c in enumerate(survivors):
        ranks[c["li"]["id"]] = index + 1

    for c in computed:
        li = c["li"]
        bid = new_row(versioned=False)
        reason = c["reason"]
        if reason == "NONE":
            outcome = "RANKED"
        elif reason == "BELOW_FLOOR":
            outcome = "FILTERED_BELOW_FLOOR"
        else:
            outcome = "FILTERED_INELIGIBLE"
        bid.update({
            "auction_event_id": auction["id"],
            "line_item_id": li["id"],
            "raw_bid_cents": li["bid_cents"],
            "relevance_score": float(c["relevance"]),
            "quality_adjusted_score": float(c["qas"]),
            "rank": ranks.get(li["id"]),
            "outcome": outcome,
            "filter_reason": reason,
            "_effective_bid": c["effective_bid"],
            "_tier": c["tier"],
        })
        insert("auction_bid", bid)
        li["relevance_score"] = float(c["relevance"])
        li["quality_adjusted_score"] = float(c["qas"])
        li["priority_tier"] = c["tier"]
        touch(li)

    auction["candidate_count"] = len(computed)
    auction["winner_score"] = (float(survivors[0]["qas"]) if survivors else None)
    auction["second_best_score"] = (float(survivors[1]["qas"])
                                    if len(survivors) > 1 else None)
    auction["status"] = "RANKED"
    touch(auction)
    return ok(D.ser_auction_event(auction))


def _clearing_price(auction, slot, winner_bid):
    """Calculation 4: second-price clearing."""
    relevance = dec(winner_bid["relevance_score"])
    weight = dec(slot["relevance_weight"])
    multiplier = ((relevance ** weight) if relevance > 0 else Decimal("0")) \
        * Decimal(D.TIER_MULTIPLIER[winner_bid["_tier"]])
    if auction["second_best_score"] is None or multiplier == 0:
        raw = dec(slot["floor_cpc_cents"])
    else:
        raw = dec(auction["second_best_score"]) / multiplier + Decimal("1")
    rounded = ceil_int(raw)
    effective_bid = winner_bid["_effective_bid"]
    return max(slot["floor_cpc_cents"], min(effective_bid, rounded))


@bp.post("/rmn/auction-events/<aid>/award")
def award_auction(aid):
    ctx = guard(AUCTION_WRITE, path_refs=(("auction_event", aid),))
    auction = ctx.get("auction_event")
    slot = db.placement_slots[auction["placement_slot_id"]]
    if auction["status"] != "RANKED":
        fail("ERR_AUCTION_INVALID_STATE",
             "Awarding requires a RANKED auction; this one is %s."
             % auction["status"])
    bids = D.bids_of_auction(auction["id"])
    survivors = [b for b in bids
                 if b["outcome"] not in ("FILTERED_INELIGIBLE",
                                         "FILTERED_BELOW_FLOOR")]
    if survivors:
        survivors.sort(key=lambda b: b["rank"])
        winner = survivors[0]
        winner["outcome"] = "WON"
        for other in survivors[1:]:
            other["outcome"] = "LOST"
        auction["winning_line_item_id"] = winner["line_item_id"]
        auction["no_fill_reason"] = "NONE"
        auction["clearing_price_cents"] = _clearing_price(auction, slot, winner)
        auction["status"] = "AWARDED"
    else:
        auction["winning_line_item_id"] = None
        auction["clearing_price_cents"] = None
        auction["settled_spend_cents"] = 0
        if auction["candidate_count"] == 0 or all(
                b["outcome"] == "FILTERED_INELIGIBLE" for b in bids):
            auction["no_fill_reason"] = "NO_ELIGIBLE_CANDIDATES"
        else:
            auction["no_fill_reason"] = "ALL_BELOW_FLOOR"
        auction["status"] = "NO_FILL"
    touch(auction)
    return ok(D.ser_auction_event(auction))


def _distribute_cpm(auction, clearing, billable):
    """Calculation 5: the CPM remainder waterfall."""
    count = len(billable)
    total = rhu(dec(clearing) * dec(count) / dec(1000))
    base = trunc_int(dec(clearing) / dec(1000))
    for event in billable:
        event["billable_cents"] = base
    remainder = total - base * count
    ordered = sorted(billable, key=lambda e: (e["occurred_at"],
                                              e["created_at"], e["_seq"]))
    index = 0
    while remainder > 0 and ordered:
        ordered[index % len(ordered)]["billable_cents"] += 1
        remainder -= 1
        index += 1
    return total


@bp.post("/rmn/auction-events/<aid>/settle")
def settle_auction(aid):
    ctx = guard(SETTLE_ROLES, path_refs=(("auction_event", aid),))
    auction = ctx.get("auction_event")
    if auction["status"] not in ("AWARDED", "NO_FILL"):
        fail("ERR_AUCTION_INVALID_STATE",
             "Settlement requires an AWARDED or NO_FILL auction; this one is "
             "%s." % auction["status"])
    if auction["status"] == "NO_FILL":
        auction["settled_spend_cents"] = 0
        auction["status"] = "SETTLED"
        touch(auction)
        return ok(D.ser_auction_event(auction))

    li = db.line_items[auction["winning_line_item_id"]]
    camp = D.campaign_of_line_item(li)
    plan = D.plan_of_campaign(camp)
    events = D.events_of_auction(auction["id"])
    if not any(e["event_type"] == "IMPRESSION" for e in events):
        fail("ERR_AUCTION_INVALID_STATE",
             "An awarded auction settles only once an impression is recorded.")
    if plan is None or plan["plan_status"] not in ("ACTIVE", "EXHAUSTED"):
        fail("ERR_PLAN_NOT_FUNDABLE",
             "The winning line item's plan is not ACTIVE or EXHAUSTED.")

    clearing = auction["clearing_price_cents"] or 0
    if li["bid_type"] == "CPC":
        clicks = [e for e in events if e["event_type"] == "CLICK"]
        for event in events:
            event["billable_cents"] = clearing if event in clicks else 0
        total = clearing * len(clicks)
    else:
        billable = [e for e in events
                    if e["event_type"] in ("IMPRESSION", "OFFSITE_VIEW")]
        for event in events:
            if event not in billable:
                event["billable_cents"] = 0
        total = _distribute_cpm(auction, clearing, billable) if billable else 0
    auction["settled_spend_cents"] = total
    auction["status"] = "SETTLED"
    touch(auction)

    # level one and two of the exhaustion cascade
    touch(li)
    touch(camp)
    D.recompute_pacing(camp)
    H.exhaust_plan_if_drained(plan)
    return ok(D.ser_auction_event(auction))


# ---------------------------------------------------------------------------
# The bid ledger
# ---------------------------------------------------------------------------
@bp.get("/rmn/auction-bids")
def list_bids():
    ctx = guard(BID_READ, paginated=True)
    return H.respond_list(ctx, "auction_bid", rows("auction_bid"), BID_FILTERS)


@bp.get("/rmn/auction-bids/<bid_id>")
def read_bid(bid_id):
    ctx = guard(BID_READ)
    row = db.auction_bids.get(bid_id)
    if row is None:
        fail("ERR_AUCTION_EVENT_NOT_FOUND", "Auction bid does not exist.")
    return ok(D.ser_auction_bid(row))


# ---------------------------------------------------------------------------
# Engagement events
# ---------------------------------------------------------------------------
@bp.post("/rmn/engagement-events")
def record_engagement():
    specs = (
        F("line_item_id", "string", required=True),
        F("auction_event_id", "string", required=True),
        F("catalog_product_id", "string", required=True),
        F("event_type", "enum", required=True, enum=EVENT_TYPES),
        F("occurred_at", "datetime", required=True),
        F("shopper_hash", "string", required=True),
        F("channel", "enum", required=True, enum=("ONSITE", "OFFSITE")),
    )
    ctx = guard(AUCTION_WRITE, body_specs=specs,
                body_refs=(("line_item", "line_item_id"),
                           ("catalog_product", "catalog_product_id"),
                           ("auction_event", "auction_event_id")))
    data = ctx.data
    auction = ctx.get("auction_event")
    li = ctx.get("line_item")
    slot = db.placement_slots[auction["placement_slot_id"]]
    if auction["status"] not in ("AWARDED", "SETTLED"):
        fail("ERR_AUCTION_INVALID_STATE",
             "The auction is %s." % auction["status"])
    channel = slot["channel"]
    occurred = data["occurred_at"]
    win_li = db.line_items.get(auction["winning_line_item_id"]) or li
    # 49 -- the engagement window, measured against the winning line item
    if not (win_li["flight_start_at"] <= occurred < win_li["flight_end_at"]) or \
            occurred < auction["requested_at"]:
        fail("ERR_ENGAGEMENT_OUTSIDE_FLIGHT",
             "occurred_at must lie inside the line item flight and at or "
             "after the auction request.")
    # 69 -- the engagement must agree with the auction it belongs to
    if auction["winning_line_item_id"] != li["id"]:
        fail("ERR_ENGAGEMENT_AUCTION_MISMATCH",
             "The line item did not win this auction.")
    assigned = [a for a in D.assignments_of_line_item(li["id"])
                if a["catalog_product_id"] == data["catalog_product_id"]
                and a["assignment_status"] == "ACTIVE"]
    if not assigned:
        fail("ERR_ENGAGEMENT_AUCTION_MISMATCH",
             "The product is not actively assigned to the line item.")
    if data["event_type"] in ("IMPRESSION", "CLICK") and channel != "ONSITE":
        fail("ERR_ENGAGEMENT_AUCTION_MISMATCH",
             "%s may only be recorded on an on-site slot."
             % data["event_type"])
    if data["event_type"] == "OFFSITE_VIEW" and channel != "OFFSITE":
        fail("ERR_ENGAGEMENT_AUCTION_MISMATCH",
             "OFFSITE_VIEW may only be recorded on an off-site slot.")

    row = new_row(versioned=False)
    row.update({
        "line_item_id": li["id"],
        "auction_event_id": auction["id"],
        "catalog_product_id": data["catalog_product_id"],
        "event_type": data["event_type"],
        "occurred_at": occurred,
        "shopper_hash": data["shopper_hash"],
        "channel": channel,
        "billable_cents": 0,
    })
    insert("engagement_event", row)
    return ok(D.ser_engagement_event(row), 201)


@bp.get("/rmn/engagement-events")
def list_engagements():
    ctx = guard(ENGAGEMENT_READ, paginated=True)
    return H.respond_list(ctx, "engagement_event", rows("engagement_event"),
                          ENGAGEMENT_FILTERS, owner_kind="engagement_event")


@bp.get("/rmn/engagement-events/<eid>")
def read_engagement(eid):
    ctx = guard(ENGAGEMENT_ONE_READ, path_refs=(("engagement_event", eid),))
    return ok(D.ser_engagement_event(ctx.get("engagement_event")))
