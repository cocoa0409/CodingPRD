"""Upgrade bidding: submission, the bounded counter cycle, award and decline."""

from flask import Blueprint

import calcs
import cascade
import shape
import store
from auth import actor, require_booking_owner
from envelope import created, list_response, object_response
from errors import ApiError

bp = Blueprint("bids", __name__)

READ_ROLES = ("RevenueManager", "ReservationAgent", "Guest")
ADJUDICATION_STATUSES = ("OPEN_FOR_SALE", "SALES_SUSPENDED", "INVENTORY_CLOSED")


def _days(sailing):
    return store.days_to_sail(store.parse_iso(sailing["embark_date"]), store.now_dt())


def _reachable(source_category_id, target_category_id):
    """The target must sit one or more upgrade_to_category_id hops above the source."""
    current = store.cabin_categories.get(source_category_id)
    seen = set()
    while current is not None:
        next_id = current.get("upgrade_to_category_id")
        if next_id is None or next_id in seen:
            return False
        if next_id == target_category_id:
            return True
        seen.add(next_id)
        current = store.cabin_categories.get(next_id)
    return False


def _floor_for(booking, sailing, target_category):
    """Tier 15 then the floor derivation, both re-evaluated at the current instant."""
    days = _days(sailing)
    source_id = booking["assigned_cabin_category_id"]
    source_rule = cascade.rule_for_window(sailing["id"], source_id, days)
    target_rule = cascade.rule_for_window(sailing["id"], target_category["id"], days)
    if source_rule is None or target_rule is None:
        raise ApiError("ERR_NO_FARE_RULE_FOR_WINDOW")
    # Tier 16: bidding is only open inside the declared day window.
    if not calcs.bid_window_open(days):
        raise ApiError("ERR_BID_WINDOW_CLOSED")
    source_category = store.cabin_categories.get(source_id)
    return days, calcs.bid_floor(
        source_rule, target_rule, source_category, target_category,
        sailing["nights"], booking["guest_count"])


def _bid_context(bid):
    booking = store.bookings.get(bid["booking_id"])
    sailing = store.sailings.get(booking["sailing_id"]) if booking else None
    target = store.cabin_categories.get(bid["target_cabin_category_id"])
    return booking, sailing, target


@bp.post("/bookings/<booking_id>/upgrade-bids")
def submit_bid(booking_id):
    user_id, role = actor("Guest", "ReservationAgent")
    data = shape.body()
    target_id = shape.req_str(data, "target_cabin_category_id")
    amount = shape.req_int(data, "bid_amount_per_guest_cents", minimum=1)

    booking = cascade.booking_or_404(booking_id)
    # Tier 6.
    target = cascade.category_or_404(target_id)
    # Tier 7.
    require_booking_owner(role, user_id, booking)

    # Tier 11: the booking must be commercially alive.
    if booking["booking_status"] not in ("OPTION", "CONFIRMED"):
        raise ApiError("ERR_BOOKING_NOT_ACTIVE")

    sailing = store.sailings.get(booking["sailing_id"])
    # Tiers 15 and 16.
    days, floor = _floor_for(booking, sailing, target)

    # Tier 17: the target must sit on the booking's upgrade chain.
    if not _reachable(booking["assigned_cabin_category_id"], target["id"]):
        raise ApiError("ERR_UPGRADE_PATH_INVALID")

    # Tier 20.
    if amount < floor:
        raise ApiError("ERR_BID_BELOW_FLOOR")

    row = store.stamp_new({})
    row.update({
        "booking_id": booking["id"],
        "target_cabin_category_id": target["id"],
        "bid_amount_per_guest_cents": amount,
        "guest_count": booking["guest_count"],
        "min_acceptable_per_guest_cents": floor,
        "countered_min_per_guest_cents": None,
        "counter_rounds": 0,
        "award_amount_cents": None,
        "submitted_days_to_sail": days,
        "status": "SUBMITTED",
        "decline_reason": None,
    })
    store.upgrade_bids[row["id"]] = row
    return created(row)


@bp.get("/upgrade-bids/<bid_id>")
def read_bid(bid_id):
    user_id, role = actor(*READ_ROLES)
    bid = cascade.bid_or_404(bid_id)
    # Tier 7 runs through the bid's booking to that booking's guest_id.
    booking = store.bookings.get(bid["booking_id"])
    if booking is not None:
        require_booking_owner(role, user_id, booking)
    return object_response(bid)


@bp.get("/upgrade-bids")
def list_bids():
    actor("RevenueManager", "ReservationAgent")
    limit, offset = shape.pagination()
    booking_id = shape.filter_str("booking_id")
    target_id = shape.filter_str("target_cabin_category_id")
    status = shape.filter_str("status")

    rows = []
    for row in store.upgrade_bids.values():
        if booking_id is not None and row["booking_id"] != booking_id:
            continue
        if target_id is not None and row["target_cabin_category_id"] != target_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


@bp.post("/upgrade-bids/<bid_id>/counter")
def counter_bid(bid_id):
    actor("RevenueManager")
    shape.body()
    bid = cascade.bid_or_404(bid_id)

    # Tier 10.
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_NOT_PENDING")

    booking, sailing, target = _bid_context(bid)
    # Adjudication continues after inventory closes, but not before sale opens.
    if sailing is None or sailing["status"] not in ADJUDICATION_STATUSES:
        raise ApiError("ERR_SAILING_NOT_OPEN")

    # Tiers 15 and 16.
    _days_to_sail, floor = _floor_for(booking, sailing, target)

    # Tier 19: the negotiation cycle is bounded.
    if bid["counter_rounds"] >= calcs.MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_MAX_COUNTER_ROUNDS_EXCEEDED")

    bid["counter_rounds"] = bid["counter_rounds"] + 1
    bid["countered_min_per_guest_cents"] = floor
    bid["status"] = "COUNTERED"
    store.touch(bid)
    return object_response(bid)


@bp.post("/upgrade-bids/<bid_id>/rebid")
def rebid(bid_id):
    user_id, role = actor("Guest")
    data = shape.body()
    amount = shape.req_int(data, "bid_amount_per_guest_cents", minimum=1)
    bid = cascade.bid_or_404(bid_id)

    booking, sailing, target = _bid_context(bid)
    # Tier 7.
    if booking is not None:
        require_booking_owner(role, user_id, booking)

    # Tier 10.
    if bid["status"] != "COUNTERED":
        raise ApiError("ERR_BID_NOT_COUNTERED")

    # Tiers 15 and 16.
    _days_to_sail, _floor = _floor_for(booking, sailing, target)

    # Tier 20: the published counter floor is the one that binds.
    countered = bid["countered_min_per_guest_cents"]
    if countered is not None and amount < countered:
        raise ApiError("ERR_BID_BELOW_FLOOR")

    bid["bid_amount_per_guest_cents"] = amount
    if countered is not None:
        # The published floor is promoted to binding.
        bid["min_acceptable_per_guest_cents"] = countered
    bid["status"] = "SUBMITTED"
    store.touch(bid)
    return object_response(bid)


@bp.post("/upgrade-bids/<bid_id>/accept")
def accept_bid(bid_id):
    actor("RevenueManager")
    shape.body()
    bid = cascade.bid_or_404(bid_id)

    # Tier 10.
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_NOT_PENDING")

    booking, sailing, target = _bid_context(bid)

    # Tier 12: the party must still fit the richer cabin.
    if target is None or booking["guest_count"] > target["max_occupancy"]:
        raise ApiError("ERR_MAX_OCCUPANCY_EXCEEDED")

    # Tiers 15 and 16.
    _days_to_sail, _floor = _floor_for(booking, sailing, target)

    # Tier 19: the target allotment must have a cabin to give.
    target_inv = cascade.inventory_for(sailing["id"], target["id"])
    if target_inv is None or target_inv["available_cabins"] < 1:
        raise ApiError("ERR_TARGET_CATEGORY_UNAVAILABLE")

    # Tier 20: the binding floor.
    if bid["bid_amount_per_guest_cents"] < bid["min_acceptable_per_guest_cents"]:
        raise ApiError("ERR_BID_BELOW_FLOOR")

    award = bid["bid_amount_per_guest_cents"] * bid["guest_count"]
    source_id = booking["assigned_cabin_category_id"]

    bid["award_amount_cents"] = award
    bid["status"] = "ACCEPTED"
    store.touch(bid)

    booking["assigned_cabin_category_id"] = target["id"]
    booking["upgrade_charge_cents"] = booking["upgrade_charge_cents"] + award
    # Charged and collected in the same movement, so the balance does not move.
    cascade.append_payment_event(
        booking, "UPGRADE_CHARGE", award, booking["payment_status"],
        note="UPGRADE_AWARD")
    cascade.recompute_onboard(booking, sailing)
    cascade.recompute_booking_money(booking)
    store.touch(booking)

    # Every sibling bid still in play is superseded.
    for other in cascade.bids_of(booking["id"]):
        if other["id"] != bid["id"] and other["status"] in ("SUBMITTED", "COUNTERED"):
            other["status"] = "DECLINED"
            other["decline_reason"] = "SUPERSEDED_BY_AWARD"
            store.touch(other)

    source_inv = cascade.inventory_for(sailing["id"], source_id)
    if source_inv is not None:
        cascade.recompute_inventory(source_inv, bump=True)
    cascade.recompute_inventory(target_inv, bump=True)
    cascade.recompute_sailing(sailing, bump=True)
    return object_response(bid)


@bp.post("/upgrade-bids/<bid_id>/decline")
def decline_bid(bid_id):
    actor("RevenueManager")
    data = shape.body()
    reason = shape.req_str(data, "reason")
    bid = cascade.bid_or_404(bid_id)

    # Tier 10: a decline is available from either live state.
    if bid["status"] not in ("SUBMITTED", "COUNTERED"):
        raise ApiError("ERR_BID_NOT_PENDING")

    bid["status"] = "DECLINED"
    bid["decline_reason"] = reason
    store.touch(bid)
    return object_response(bid)
