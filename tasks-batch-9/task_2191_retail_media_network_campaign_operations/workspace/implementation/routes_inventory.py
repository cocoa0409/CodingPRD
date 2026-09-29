"""Placement slots, line items and slot occupancy arbitration (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint

from core import (
    F, db, fail, insert, new_row, now, ok, overlaps, rows, touch,
)
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("inventory", __name__)

SLOT_READ = ("NetworkAdmin", "AccountManager", "AuctionService", "AdvertiserUser")
LI_WRITE = ("NetworkAdmin", "AccountManager", "AdvertiserUser")
LI_READ = ("NetworkAdmin", "AccountManager", "AuctionService",
           "MeasurementAnalyst", "BillingOps", "AdvertiserUser")

CHANNELS = ("ONSITE", "OFFSITE")
PAGE_TYPES = ("SEARCH_RESULTS", "CATEGORY_BROWSE", "PRODUCT_DETAIL",
              "HOMEPAGE", "OFFSITE_SOCIAL", "OFFSITE_DISPLAY")
SLOT_STATUSES = ("OPEN", "MAINTENANCE", "RETIRED")
PAUSE_REASONS = ("NONE", "OUT_OF_STOCK", "MANUAL", "BUDGET_EXHAUSTED",
                 "CATALOG_RESTRICTED")

SLOT_TRANSITIONS = {
    "OPEN": ("MAINTENANCE",),
    "MAINTENANCE": ("OPEN", "RETIRED"),
    "RETIRED": (),
}

LINE_ITEM_TRANSITIONS = {
    "submit": {"DRAFT": "PENDING_ELIGIBILITY"},
    "APPROVE": {"PENDING_ELIGIBILITY": "ELIGIBLE"},
    "REJECT": {"PENDING_ELIGIBILITY": "REJECTED"},
    "activate": {"ELIGIBLE": "SERVING"},
    "pause": {"SERVING": "MANUAL_PAUSED"},
    "resume": {"OOS_PAUSED": "SERVING", "MANUAL_PAUSED": "SERVING"},
    "end": {"ELIGIBLE": "ENDED", "SERVING": "ENDED", "OOS_PAUSED": "ENDED",
            "MANUAL_PAUSED": "ENDED"},
}

SLOT_FILTERS = (
    ("channel", "channel", "string"),
    ("page_type", "page_type", "string"),
    ("slot_status", "slot_status", "string"),
    ("slot_code", "slot_code", "string"),
)

LI_FILTERS = (
    ("campaign_id", "campaign_id", "string"),
    ("placement_slot_id", "placement_slot_id", "string"),
    ("line_item_status", "line_item_status", "string"),
    ("priority_tier", "priority_tier", "string"),
    ("category_code", "category_code", "string"),
)

CAMPAIGN_ELIGIBILITY_STATES = ("DRAFT", "PENDING_REVIEW", "SCHEDULED",
                               "DELIVERING")


# ---------------------------------------------------------------------------
# Placement slots
# ---------------------------------------------------------------------------
@bp.post("/rmn/placement-slots")
def create_slot():
    specs = (
        F("slot_code", "string", required=True),
        F("channel", "enum", required=True, enum=CHANNELS),
        F("page_type", "enum", required=True, enum=PAGE_TYPES),
        F("position_index", "integer", required=True, minimum=1),
        F("max_concurrent_line_items", "integer", required=True, minimum=1),
        F("floor_cpc_cents", "integer", required=True, minimum=1),
        F("relevance_weight", "number", minimum=0.5, maximum=2.0, default=1.0,
          has_default=True),
        F("exclusivity_category_code", "string", nullable=True),
        F("buffer_minutes", "integer", minimum=0, default=0, has_default=True),
    )
    ctx = guard(("NetworkAdmin",), body_specs=specs)
    data = ctx.data
    if any(s["slot_code"] == data["slot_code"]
           for s in db.placement_slots.values()):
        fail("ERR_DUPLICATE_RESOURCE_CODE", "slot_code is already in use.")
    row = new_row()
    row.update({
        "slot_code": data["slot_code"],
        "channel": data["channel"],
        "page_type": data["page_type"],
        "position_index": data["position_index"],
        "max_concurrent_line_items": data["max_concurrent_line_items"],
        "floor_cpc_cents": data["floor_cpc_cents"],
        "exclusivity_category_code": data.get("exclusivity_category_code"),
        "buffer_minutes": data["buffer_minutes"],
        "slot_status": "OPEN",
        "relevance_weight": data["relevance_weight"],
    })
    insert("placement_slot", row)
    return ok(D.ser_placement_slot(row), 201)


@bp.get("/rmn/placement-slots")
def list_slots():
    ctx = guard(SLOT_READ, paginated=True)
    return H.respond_list(ctx, "placement_slot", rows("placement_slot"),
                          SLOT_FILTERS)


@bp.get("/rmn/placement-slots/<sid>")
def read_slot(sid):
    ctx = guard(SLOT_READ, path_refs=(("placement_slot", sid),))
    return ok(D.ser_placement_slot(ctx.get("placement_slot")))


@bp.patch("/rmn/placement-slots/<sid>")
def patch_slot(sid):
    specs = (
        F("slot_status", "enum", enum=SLOT_STATUSES),
        F("max_concurrent_line_items", "integer", minimum=1),
        F("floor_cpc_cents", "integer", minimum=1),
        F("relevance_weight", "number", minimum=0.5, maximum=2.0),
        F("exclusivity_category_code", "string", nullable=True),
        F("buffer_minutes", "integer", minimum=0),
    )
    ctx = guard(("NetworkAdmin",), path_refs=(("placement_slot", sid),),
                body_specs=specs)
    slot = ctx.get("placement_slot")
    data = ctx.data
    target = data.get("slot_status")
    if target is not None and target != slot["slot_status"]:
        if target not in SLOT_TRANSITIONS.get(slot["slot_status"], ()):
            fail("ERR_SLOT_NOT_OPEN",
                 "A slot in %s may not move to %s."
                 % (slot["slot_status"], target))
        if target == "RETIRED" and D.slot_occupancy(slot) != 0:
            fail("ERR_SLOT_NOT_OPEN",
                 "A slot may only retire once its occupancy_count is 0.")
    elif slot["slot_status"] == "RETIRED":
        fail("ERR_SLOT_NOT_OPEN", "A RETIRED slot may not be amended.")

    if "max_concurrent_line_items" in data:
        slot["max_concurrent_line_items"] = data["max_concurrent_line_items"]
    if "floor_cpc_cents" in data:
        slot["floor_cpc_cents"] = data["floor_cpc_cents"]
    if "relevance_weight" in data:
        slot["relevance_weight"] = data["relevance_weight"]
    if "exclusivity_category_code" in data:
        slot["exclusivity_category_code"] = data["exclusivity_category_code"]
    if "buffer_minutes" in data:
        slot["buffer_minutes"] = data["buffer_minutes"]

    cascade = target == "MAINTENANCE" and slot["slot_status"] == "OPEN"
    if target is not None:
        slot["slot_status"] = target
    touch(slot)
    if cascade:
        touched_campaigns = []
        for li in D.line_items_of_slot(slot["id"]):
            if li["line_item_status"] == "SERVING":
                H.pause_line_item(li, "MANUAL")
                camp = D.campaign_of_line_item(li)
                if camp is not None and camp["id"] not in touched_campaigns:
                    touched_campaigns.append(camp["id"])
        for camp_id in touched_campaigns:
            H.campaign_rollup_pause(db.campaigns[camp_id])
    return ok(D.ser_placement_slot(slot))


# ---------------------------------------------------------------------------
# Occupancy arbitration (PRD 3.4 rules A, B and C)
# ---------------------------------------------------------------------------
def occupying_peers(slot, candidate):
    return [l for l in D.line_items_of_slot(slot["id"])
            if l["id"] != candidate["id"]
            and l["line_item_status"] in D.OCCUPYING_STATUSES]


def check_occupancy_rules(slot, li):
    peers = occupying_peers(slot, li)
    start, end = li["flight_start_at"], li["flight_end_at"]
    overlapping = [p for p in peers
                   if overlaps(start, end, p["flight_start_at"],
                               p["flight_end_at"])]
    # rule A -- aggregate capacity
    if len(overlapping) >= slot["max_concurrent_line_items"]:
        fail("ERR_SLOT_CAPACITY_EXCEEDED",
             "The slot already carries %d overlapping occupying line items."
             % len(overlapping))
    # rule B -- category exclusivity
    exclusive = slot["exclusivity_category_code"]
    if exclusive is not None and exclusive == li["category_code"]:
        if any(p["category_code"] == li["category_code"] for p in overlapping):
            fail("ERR_SLOT_CATEGORY_EXCLUSIVE",
                 "An overlapping line item already holds category %s on this "
                 "exclusivity slot." % li["category_code"])
    # rule C -- off-site adjacency buffer
    if slot["channel"] == "OFFSITE" and slot["buffer_minutes"] > 0:
        pad = timedelta(minutes=slot["buffer_minutes"])
        wide_start, wide_end = start - pad, end + pad
        for p in peers:
            if overlaps(wide_start, wide_end, p["flight_start_at"],
                        p["flight_end_at"]):
                fail("ERR_SLOT_BUFFER_CONFLICT",
                     "An occupying line item falls inside the %d minute "
                     "adjacency buffer." % slot["buffer_minutes"])


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------
@bp.post("/rmn/line-items")
def create_line_item():
    specs = (
        F("campaign_id", "string", required=True),
        F("placement_slot_id", "string", required=True),
        F("bid_cents", "integer", required=True, minimum=1),
        F("bid_type", "enum", enum=("CPC", "CPM"), default="CPC",
          has_default=True),
        F("flight_start_at", "datetime", required=True),
        F("flight_end_at", "datetime", required=True),
        F("daily_budget_cents", "integer", required=True, minimum=100),
        F("category_code", "string", required=True),
        F("keyword_match_terms", "array", required=True),
        F("expected_campaign_version", "integer", required=True),
    )
    ctx = guard(LI_WRITE, body_specs=specs,
                body_refs=(("campaign", "campaign_id"),
                           ("placement_slot", "placement_slot_id")),
                occ=("expected_campaign_version", "campaign",
                     "ERR_STALE_CAMPAIGN_VERSION"),
                mutating=True)
    data = ctx.data
    camp = ctx.get("campaign")
    slot = ctx.get("placement_slot")
    start, end = data["flight_start_at"], data["flight_end_at"]
    if start >= end or start < camp["flight_start_at"] or \
            end > camp["flight_end_at"]:
        fail("ERR_FLIGHT_WINDOW_OUTSIDE_CAMPAIGN",
             "The line item flight must lie inside the campaign flight.")
    if camp["channel_mix"] == "ONSITE_ONLY" and slot["channel"] == "OFFSITE":
        fail("ERR_OFFSITE_CHANNEL_MISMATCH",
             "An ONSITE_ONLY campaign may hold no off-site line item.")
    if camp["channel_mix"] == "OFFSITE_ONLY" and slot["channel"] == "ONSITE":
        fail("ERR_OFFSITE_CHANNEL_MISMATCH",
             "An OFFSITE_ONLY campaign may hold no on-site line item.")

    row = new_row()
    row.update({
        "campaign_id": data["campaign_id"],
        "placement_slot_id": data["placement_slot_id"],
        "line_item_status": "DRAFT",
        "bid_cents": data["bid_cents"],
        "bid_type": data["bid_type"],
        "flight_start_at": start,
        "flight_end_at": end,
        "daily_budget_cents": data["daily_budget_cents"],
        "category_code": data["category_code"],
        "keyword_match_terms": list(data["keyword_match_terms"]),
        "reserved_cents": 0,
        "relevance_score": 0.0,
        "quality_adjusted_score": 0.0,
        "priority_tier": D.priority_tier({"campaign_id": camp["id"]}),
        "pause_reason": "NONE",
        "last_pause_at": None,
        "eligibility_decided_by_user_id": None,
    })
    insert("line_item", row)
    touch(camp)
    return ok(D.ser_line_item(row), 201)


@bp.get("/rmn/line-items")
def list_line_items():
    ctx = guard(LI_READ, paginated=True)
    return H.respond_list(ctx, "line_item", rows("line_item"), LI_FILTERS,
                          owner_kind="line_item")


@bp.get("/rmn/line-items/<lid>")
def read_line_item(lid):
    ctx = guard(LI_READ, path_refs=(("line_item", lid),))
    return ok(D.ser_line_item(ctx.get("line_item")))


@bp.post("/rmn/line-items/<lid>/submit-eligibility")
def submit_eligibility(lid):
    specs = (F("submission_note", "string"),)
    ctx = guard(LI_WRITE, path_refs=(("line_item", lid),), body_specs=specs,
                mutating=True)
    li = ctx.get("line_item")
    camp = D.campaign_of_line_item(li)
    target = H.require_transition(li["line_item_status"],
                                  LINE_ITEM_TRANSITIONS["submit"],
                                  "ERR_LINE_ITEM_INVALID_STATE",
                                  "line_item_status")
    if camp["delivery_status"] not in CAMPAIGN_ELIGIBILITY_STATES:
        fail("ERR_INVALID_CAMPAIGN_TRANSITION",
             "The owning campaign is %s." % camp["delivery_status"])
    heroes = [a for a in D.assignments_of_line_item(li["id"])
              if a["assignment_status"] == "ACTIVE" and a["is_hero"]]
    if not heroes:
        fail("ERR_HERO_ASSIGNMENT_REQUIRED",
             "An active hero product assignment is required.")
    if D.eligible_product_count(li) < 1:
        fail("ERR_NO_ELIGIBLE_PRODUCTS",
             "At least one eligible product must be assigned.")
    li["line_item_status"] = target
    touch(li)
    return ok(D.ser_line_item(li))


@bp.post("/rmn/line-items/<lid>/eligibility-decision")
def eligibility_decision(lid):
    specs = (
        F("decision", "enum", required=True, enum=("APPROVE", "REJECT")),
        F("decision_note", "string"),
    )
    ctx = guard(("NetworkAdmin", "CatalogOps"),
                path_refs=(("line_item", lid),), body_specs=specs,
                mutating=True)
    li = ctx.get("line_item")
    slot = D.slot_of_line_item(li)
    decision = ctx.data["decision"]
    target = H.require_transition(li["line_item_status"],
                                  LINE_ITEM_TRANSITIONS[decision],
                                  "ERR_LINE_ITEM_INVALID_STATE",
                                  "line_item_status")
    if decision == "APPROVE":
        if slot["slot_status"] != "OPEN":
            fail("ERR_SLOT_NOT_OPEN",
                 "The placement slot is %s." % slot["slot_status"])
        for assignment in D.assignments_of_line_item(li["id"]):
            if assignment["assignment_status"] != "ACTIVE":
                continue
            product = db.catalog_products.get(assignment["catalog_product_id"])
            if product is None or product["eligibility_status"] != "ELIGIBLE":
                fail("ERR_PRODUCT_RESTRICTED",
                     "An assigned catalog product is not ELIGIBLE.")
        check_occupancy_rules(slot, li)

    li["eligibility_decided_by_user_id"] = ctx.user_id
    li["line_item_status"] = target
    if decision == "APPROVE":
        li["reserved_cents"] = D.line_item_reservation(li)
        li["priority_tier"] = D.priority_tier(li)
        touch(li)
        touch(slot)
    else:
        li["reserved_cents"] = 0
        touch(li)
        for assignment in D.assignments_of_line_item(li["id"]):
            if assignment["assignment_status"] != "REMOVED":
                assignment["assignment_status"] = "REMOVED"
                assignment["removed_at"] = now()
                assignment["relevance_contribution"] = 0.0
                touch(assignment)
    return ok(D.ser_line_item(li))


@bp.post("/rmn/line-items/<lid>/activate")
def activate_line_item(lid):
    ctx = guard(LI_WRITE, path_refs=(("line_item", lid),), mutating=True)
    li = ctx.get("line_item")
    camp = D.campaign_of_line_item(li)
    adv = ctx.get("advertiser")
    plan = D.plan_of_campaign(camp)
    if adv["onboarding_status"] != "ACTIVE":
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    if plan["plan_status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_FUNDABLE",
             "The funding plan is %s." % plan["plan_status"])
    if camp["delivery_status"] != "DELIVERING":
        fail("ERR_CAMPAIGN_NOT_DELIVERING",
             "The owning campaign is %s." % camp["delivery_status"])
    target = H.require_transition(li["line_item_status"],
                                  LINE_ITEM_TRANSITIONS["activate"],
                                  "ERR_LINE_ITEM_INVALID_STATE",
                                  "line_item_status")
    if not (li["flight_start_at"] <= now() < li["flight_end_at"]):
        fail("ERR_LINE_ITEM_INVALID_STATE",
             "The current logical time lies outside the line item flight.")
    if D.eligible_product_count(li) < 1:
        fail("ERR_NO_ELIGIBLE_PRODUCTS",
             "At least one eligible product must be assigned.")
    if D.plan_available(plan) < li["daily_budget_cents"]:
        fail("ERR_PLAN_BUDGET_INSUFFICIENT",
             "The plan's available_cents does not cover daily_budget_cents.")
    li["line_item_status"] = target
    li["pause_reason"] = "NONE"
    li["priority_tier"] = D.priority_tier(li)
    touch(li)
    return ok(D.ser_line_item(li))


@bp.post("/rmn/line-items/<lid>/pause")
def pause_line_item_endpoint(lid):
    specs = (F("pause_reason", "enum", required=True, enum=PAUSE_REASONS),)
    ctx = guard(LI_WRITE, path_refs=(("line_item", lid),), body_specs=specs,
                mutating=True)
    li = ctx.get("line_item")
    H.require_transition(li["line_item_status"],
                         LINE_ITEM_TRANSITIONS["pause"],
                         "ERR_LINE_ITEM_INVALID_STATE", "line_item_status")
    H.pause_line_item(li, ctx.data["pause_reason"])
    camp = D.campaign_of_line_item(li)
    if camp is not None:
        H.campaign_rollup_pause(camp)
    return ok(D.ser_line_item(li))


@bp.post("/rmn/line-items/<lid>/resume")
def resume_line_item(lid):
    specs = (F("resume_note", "string"),)
    ctx = guard(("NetworkAdmin", "AccountManager", "CatalogOps",
                 "AdvertiserUser"),
                path_refs=(("line_item", lid),), body_specs=specs,
                mutating=True)
    li = ctx.get("line_item")
    camp = D.campaign_of_line_item(li)
    plan = D.plan_of_campaign(camp)
    if camp["delivery_status"] != "DELIVERING":
        fail("ERR_CAMPAIGN_NOT_DELIVERING",
             "The owning campaign is %s." % camp["delivery_status"])
    target = H.require_transition(li["line_item_status"],
                                  LINE_ITEM_TRANSITIONS["resume"],
                                  "ERR_LINE_ITEM_INVALID_STATE",
                                  "line_item_status")
    if now() >= li["flight_end_at"]:
        fail("ERR_LINE_ITEM_INVALID_STATE",
             "The line item flight has already ended.")
    if D.eligible_product_count(li) < 1:
        fail("ERR_NO_ELIGIBLE_PRODUCTS",
             "At least one eligible product must be assigned.")
    if D.plan_available(plan) < li["daily_budget_cents"]:
        fail("ERR_PLAN_BUDGET_INSUFFICIENT",
             "The plan's available_cents does not cover daily_budget_cents.")
    li["line_item_status"] = target
    li["pause_reason"] = "NONE"
    li["priority_tier"] = D.priority_tier(li)
    touch(li)
    return ok(D.ser_line_item(li))


@bp.post("/rmn/line-items/<lid>/end")
def end_line_item_endpoint(lid):
    specs = (F("end_reason", "string"),)
    ctx = guard(LI_WRITE, path_refs=(("line_item", lid),), body_specs=specs,
                mutating=True)
    li = ctx.get("line_item")
    slot = D.slot_of_line_item(li)
    source = li["line_item_status"]
    H.require_transition(source, LINE_ITEM_TRANSITIONS["end"],
                         "ERR_LINE_ITEM_INVALID_STATE", "line_item_status")
    if source == "ELIGIBLE":
        if D.line_item_spend(li) != 0:
            fail("ERR_LINE_ITEM_INVALID_STATE",
                 "An eligible line item that already spent cannot end.")
    else:
        for auction in rows("auction_event"):
            if auction.get("winning_line_item_id") == li["id"] and \
                    auction["status"] in ("OPEN", "RANKED", "AWARDED"):
                fail("ERR_AUCTION_INVALID_STATE",
                     "An auction won by this line item is still %s."
                     % auction["status"])
    li["line_item_status"] = "ENDED"
    li["reserved_cents"] = 0
    touch(li)
    if slot is not None:
        touch(slot)
    return ok(D.ser_line_item(li))
