"""Price tiers, on-sale, dynamic single-ticket pricing and subscriptions (PRD 3.6)."""

from flask import Blueprint

import calc
import derive
from envelope import array_response, object_response
from errors import ApiError
from helpers import auth, body, page, query_filter, req_bool, req_enum, req_int, req_str
from lookup import find_engagement, find_package, find_tier
from store import public, stamp, store, touch, touch_time_only

bp = Blueprint("ticketing", __name__)

CHANNELS = ("WEB", "PHONE", "WINDOW")


# ---------------------------------------------------------------------------
# Price tiers
# ---------------------------------------------------------------------------
@bp.post("/engagements/<engagement_id>/price-tiers")
def create_price_tier(engagement_id):
    auth("BoxOfficeManager")
    engagement = find_engagement(engagement_id)
    data = body()
    tier_name = req_str(data, "tier_name")
    seats_allocated = req_int(data, "seats_allocated", minimum=1)
    base_price = req_int(data, "base_price_cents", minimum=0)
    price_ceiling = req_int(data, "price_ceiling_cents", minimum=0)
    dynamic_enabled = req_bool(data, "dynamic_pricing_enabled")
    subscription_eligible = req_bool(data, "subscription_eligible")
    if price_ceiling < base_price:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'price_ceiling_cents' may not be lower than 'base_price_cents'.",
        )

    if engagement["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError(
            "ERR_ENGAGEMENT_NOT_DRAFT",
            "Price tiers may be drafted only while the booking is DRAFT or CONFIRMED.",
        )
    if engagement["engagement_type"] != "PRESENTED":
        raise ApiError(
            "ERR_ENGAGEMENT_TYPE_MISMATCH",
            "Ticketing applies to PRESENTED engagements only.",
        )

    existing = derive.engagement_tiers(engagement["id"])
    if any(t["tier_name"] == tier_name for t in existing):
        raise ApiError(
            "ERR_SEAT_ALLOCATION_EXCEEDS_CAPACITY",
            "Tier name '%s' already exists on this engagement." % tier_name,
        )
    space = store.spaces.get(engagement["space_id"])
    allocated = sum(t["seats_allocated"] for t in existing if t["status"] == "ACTIVE")
    if space is not None and allocated + seats_allocated > space["seat_capacity"]:
        raise ApiError("ERR_SEAT_ALLOCATION_EXCEEDS_CAPACITY")

    record = {
        "engagement_id": engagement["id"],
        "tier_name": tier_name,
        "seats_allocated": seats_allocated,
        "base_price_cents": base_price,
        "price_ceiling_cents": price_ceiling,
        "dynamic_pricing_enabled": dynamic_enabled,
        "subscription_eligible": subscription_eligible,
        "sold_qty": 0,
        "subscription_held_qty": 0,
        "available_qty": seats_allocated,
        "gross_cents": 0,
        "subscription_revenue_cents": 0,
        "status": "ACTIVE",
    }
    stamp(record)
    store.tiers[record["id"]] = record
    if engagement["ticketing_status"] == "TICKETING_UNSET":
        engagement["ticketing_status"] = "TIERS_DRAFT"
        touch_time_only(engagement)
    return object_response(public(record), 201)


@bp.get("/engagements/<engagement_id>/price-tiers")
def list_price_tiers(engagement_id):
    auth("BoxOfficeManager", "FinanceController", "ProgrammingDirector", "RentalManager")
    engagement = find_engagement(engagement_id)
    items = derive.engagement_tiers(engagement["id"])
    status = query_filter("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    window, meta = page(items)
    return array_response([public(t) for t in window], meta)


@bp.get("/price-tiers/<tier_id>")
def read_price_tier(tier_id):
    auth("BoxOfficeManager", "FinanceController", "ProgrammingDirector")
    return object_response(public(find_tier(tier_id)))


# ---------------------------------------------------------------------------
# On sale
# ---------------------------------------------------------------------------
@bp.post("/engagements/<engagement_id>/on-sale")
def go_on_sale(engagement_id):
    auth("BoxOfficeManager")
    engagement = find_engagement(engagement_id)
    if engagement["ticketing_status"] != "TIERS_DRAFT":
        raise ApiError("ERR_TICKETING_NOT_ON_SALE")
    if engagement["lifecycle_status"] != "CONFIRMED":
        raise ApiError("ERR_ENGAGEMENT_NOT_CONFIRMED")
    if engagement["engagement_type"] != "PRESENTED":
        raise ApiError(
            "ERR_ENGAGEMENT_TYPE_MISMATCH",
            "Ticketing applies to PRESENTED engagements only.",
        )
    active = [t for t in derive.engagement_tiers(engagement["id"]) if t["status"] == "ACTIVE"]
    if not active:
        raise ApiError(
            "ERR_SEAT_ALLOCATION_EXCEEDS_CAPACITY",
            "At least one ACTIVE price tier is required before going on sale.",
        )
    space = store.spaces.get(engagement["space_id"])
    if space is not None:
        if sum(t["seats_allocated"] for t in active) > space["seat_capacity"]:
            raise ApiError("ERR_SEAT_ALLOCATION_EXCEEDS_CAPACITY")

    engagement["ticketing_status"] = "ON_SALE"
    derive.recompute_projection(engagement)
    touch(engagement)
    return object_response(public(engagement))


# ---------------------------------------------------------------------------
# Single ticket sales
# ---------------------------------------------------------------------------
@bp.post("/price-tiers/<tier_id>/ticket-sales")
def sell_ticket(tier_id):
    auth("BoxOfficeManager")
    tier = find_tier(tier_id)
    data = body()
    qty = req_int(data, "qty", minimum=1)
    channel = req_enum(data, "channel", CHANNELS)

    if tier["status"] == "CLOSED":
        raise ApiError("ERR_TIER_CLOSED")
    engagement = store.engagements.get(tier["engagement_id"])
    if engagement is None or engagement["ticketing_status"] != "ON_SALE":
        raise ApiError("ERR_TICKETING_NOT_ON_SALE")
    if qty > tier["available_qty"]:
        raise ApiError("ERR_TIER_SOLD_OUT")

    (
        sell_through,
        multiplier,
        unit_price,
        gross,
        restoration,
    ) = calc.dynamic_price(tier, qty)
    record = {
        "price_tier_id": tier["id"],
        "qty": qty,
        "channel": channel,
        "sell_through_pct_at_sale": float(sell_through),
        "dynamic_multiplier_applied": float(multiplier),
        "unit_price_cents": unit_price,
        "gross_cents": gross,
        "restoration_fee_cents": restoration,
        "status": "SOLD",
    }
    stamp(record)
    store.sales[record["id"]] = record
    derive.recompute_tier_counters(tier)
    derive.recompute_realized_gross(engagement)
    return object_response(public(record), 201)


@bp.get("/price-tiers/<tier_id>/ticket-sales")
def list_ticket_sales(tier_id):
    auth("BoxOfficeManager", "FinanceController")
    tier = find_tier(tier_id)
    items = derive.tier_sales(tier["id"])
    status = query_filter("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, meta = page(items)
    return array_response([public(s) for s in window], meta)


# ---------------------------------------------------------------------------
# Subscription packages
# ---------------------------------------------------------------------------
@bp.post("/subscription-packages")
def create_package():
    auth("BoxOfficeManager")
    data = body()

    raw_ids = data.get("included_engagement_ids")
    members = []
    if isinstance(raw_ids, list):
        for element in raw_ids:
            members.append(find_engagement(element))

    name = req_str(data, "name")
    package_price = req_int(data, "package_price_cents", minimum=1)
    if not isinstance(raw_ids, list) or len(raw_ids) < 2:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'included_engagement_ids' must hold at least two engagement ids.",
        )
    subscription_tier_name = req_str(data, "subscription_tier_name")
    seats_per_order = req_int(data, "seats_per_order", minimum=1)

    for engagement in members:
        if engagement["engagement_type"] != "PRESENTED":
            raise ApiError(
                "ERR_ENGAGEMENT_TYPE_MISMATCH",
                "Subscription packages span PRESENTED engagements only.",
            )
    for engagement in members:
        if engagement["ticketing_status"] != "ON_SALE":
            raise ApiError(
                "ERR_TICKETING_NOT_ON_SALE",
                "Every included engagement must already be ON_SALE.",
            )

    pairs = []
    for engagement in members:
        tier = None
        for candidate in derive.engagement_tiers(engagement["id"]):
            if (
                candidate["tier_name"] == subscription_tier_name
                and candidate["subscription_eligible"] is True
                and candidate["status"] == "ACTIVE"
            ):
                tier = candidate
                break
        if tier is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Engagement %s has no ACTIVE subscription-eligible tier named '%s'."
                % (engagement["id"], subscription_tier_name),
            )
        pairs.append((engagement, tier))

    pairs.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["_performance_start"]))
    allocations = calc.subscription_allocation(pairs, package_price, seats_per_order)
    allocation_map = {}
    for (engagement, _tier), allocation in zip(pairs, allocations):
        allocation_map[engagement["id"]] = allocation

    record = {
        "name": name,
        "package_price_cents": package_price,
        "included_engagement_ids": list(raw_ids),
        "subscription_tier_name": subscription_tier_name,
        "seats_per_order": seats_per_order,
        "sold_count": 0,
        "allocation_map": allocation_map,
        "_pairs": [(engagement["id"], tier["id"]) for engagement, tier in pairs],
    }
    stamp(record)
    store.packages[record["id"]] = record
    return object_response(public(record), 201)


@bp.post("/subscription-packages/<package_id>/sell")
def sell_subscriptions(package_id):
    auth("BoxOfficeManager")
    package = find_package(package_id)
    data = body()
    order_qty = req_int(data, "order_qty", minimum=1)

    seats = package["seats_per_order"] * order_qty
    targets = []
    for engagement_id, tier_id in package["_pairs"]:
        engagement = store.engagements.get(engagement_id)
        tier = store.tiers.get(tier_id)
        if tier is None or tier["available_qty"] < seats:
            raise ApiError("ERR_TIER_SOLD_OUT")
        targets.append((engagement, tier))

    package["sold_count"] += order_qty
    for engagement, tier in targets:
        tier["subscription_held_qty"] += seats
        tier["available_qty"] = (
            tier["seats_allocated"] - tier["sold_qty"] - tier["subscription_held_qty"]
        )
        tier["subscription_revenue_cents"] += (
            package["allocation_map"].get(engagement["id"], 0) * order_qty
        )
        touch(tier)
        if engagement is not None:
            derive.recompute_realized_gross(engagement)
    touch(package)
    return object_response(public(package))
