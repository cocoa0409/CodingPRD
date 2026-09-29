"""Lookup helpers and the cascade discipline of PRD 2.8.

Every derived counter in this system is recomputed from the child rows rather
than incremented blindly, except the three audit counters the PRD declares
never-decremented (FareRule.bookings_pinned_count and the two
released_cabins_total fields), which are explicitly raised by their transitions.
"""

import calcs
import store
from errors import ApiError

ACTIVE = calcs.ACTIVE_BOOKING_STATUSES
FENCING = calcs.FENCING_BLOCK_STATUSES


# --------------------------------------------------------------------------
# Lookups (validation tiers 5 and 6)
# --------------------------------------------------------------------------
def fetch(table, row_id, error_id):
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def sailing_or_404(sailing_id):
    return fetch(store.sailings, sailing_id, "ERR_SAILING_NOT_FOUND")


def category_or_404(category_id):
    return fetch(store.cabin_categories, category_id, "ERR_CABIN_CATEGORY_NOT_FOUND")


def inventory_or_404(inventory_id):
    return fetch(store.sailing_inventories, inventory_id, "ERR_SAILING_INVENTORY_NOT_FOUND")


def fare_rule_or_404(rule_id):
    return fetch(store.fare_rules, rule_id, "ERR_FARE_RULE_NOT_FOUND")


def promotion_or_404(promotion_id):
    return fetch(store.promotions, promotion_id, "ERR_PROMOTION_NOT_FOUND")


def block_or_404(block_id):
    return fetch(store.group_blocks, block_id, "ERR_GROUP_BLOCK_NOT_FOUND")


def guest_or_404(guest_id):
    return fetch(store.guests, guest_id, "ERR_GUEST_NOT_FOUND")


def booking_or_404(booking_id):
    return fetch(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")


def bid_or_404(bid_id):
    return fetch(store.upgrade_bids, bid_id, "ERR_UPGRADE_BID_NOT_FOUND")


def change_or_404(change_id):
    return fetch(store.itinerary_changes, change_id, "ERR_ITINERARY_CHANGE_NOT_FOUND")


# --------------------------------------------------------------------------
# Collection walks
# --------------------------------------------------------------------------
def inventory_for(sailing_id, cabin_category_id):
    for inv in store.sailing_inventories.values():
        if inv["sailing_id"] == sailing_id and inv["cabin_category_id"] == cabin_category_id:
            return inv
    return None


def inventories_of(sailing_id):
    return [inv for inv in store.sailing_inventories.values()
            if inv["sailing_id"] == sailing_id]


def fare_rules_of(sailing_id, cabin_category_id):
    return [r for r in store.fare_rules.values()
            if r["sailing_id"] == sailing_id and r["cabin_category_id"] == cabin_category_id]


def rule_for_window(sailing_id, cabin_category_id, days_to_sail):
    for rule in fare_rules_of(sailing_id, cabin_category_id):
        if calcs.fare_window_contains(rule, days_to_sail):
            return rule
    return None


def blocks_of(sailing_id, cabin_category_id=None):
    rows = []
    for block in store.group_blocks.values():
        if block["sailing_id"] != sailing_id:
            continue
        if cabin_category_id is not None and block["cabin_category_id"] != cabin_category_id:
            continue
        rows.append(block)
    return rows


def bookings_of_sailing(sailing_id):
    return [b for b in store.bookings.values() if b["sailing_id"] == sailing_id]


def bookings_of_guest(guest_id):
    return [b for b in store.bookings.values() if b["guest_id"] == guest_id]


def events_of(booking_id):
    return [e for e in store.payment_events.values() if e["booking_id"] == booking_id]


def bids_of(booking_id):
    return [b for b in store.upgrade_bids.values() if b["booking_id"] == booking_id]


def promotions_of(sailing_id):
    return [p for p in store.promotions.values() if p["sailing_id"] == sailing_id]


# --------------------------------------------------------------------------
# Group block: picked_up_cabins
# --------------------------------------------------------------------------
def recompute_block(block, bump=True):
    picked = 0
    for booking in store.bookings.values():
        if booking.get("group_block_id") == block["id"] and booking["booking_status"] in ACTIVE:
            picked += 1
    return store.apply_changes(block, {"picked_up_cabins": picked}, bump=bump)


# --------------------------------------------------------------------------
# The inventory chain (PRD 2.7 / 2.8)
# --------------------------------------------------------------------------
def group_fence(sailing_id, cabin_category_id):
    total = 0
    for block in blocks_of(sailing_id, cabin_category_id):
        if block["status"] in FENCING:
            total += max(0, block["cabins_held"] - block["picked_up_cabins"])
    return total


def recompute_inventory(inv, bump=True):
    """group_held_cabins, booked_cabins, waitlisted_bookings_count,
    effective_oversell_cabins and available_cabins, from current child state."""
    sailing_id = inv["sailing_id"]
    category_id = inv["cabin_category_id"]

    for block in blocks_of(sailing_id, category_id):
        recompute_block(block, bump=bump)

    booked = 0
    waitlisted = 0
    for booking in store.bookings.values():
        if booking["sailing_id"] != sailing_id:
            continue
        if booking["booking_status"] in ACTIVE:
            if booking.get("assigned_cabin_category_id") == category_id:
                booked += 1
        elif booking["booking_status"] == "WAITLISTED":
            if booking["cabin_category_id"] == category_id:
                waitlisted += 1

    category = store.cabin_categories.get(category_id)
    is_guarantee = bool(category and category["is_guarantee"])
    held = group_fence(sailing_id, category_id)
    effective = calcs.effective_oversell(
        inv["physical_cabins"], inv["oversell_allowance"], is_guarantee)
    available = calcs.availability(inv["physical_cabins"], effective, booked, held)

    return store.apply_changes(inv, {
        "group_held_cabins": held,
        "booked_cabins": booked,
        "waitlisted_bookings_count": waitlisted,
        "effective_oversell_cabins": effective,
        "available_cabins": available,
    }, bump=bump)


def recompute_inventories_of(sailing_id, bump=True):
    for inv in inventories_of(sailing_id):
        recompute_inventory(inv, bump=bump)


# --------------------------------------------------------------------------
# The occupancy and revenue chains (PRD 2.8 / 3.9)
# --------------------------------------------------------------------------
def recompute_sailing(sailing, bump=True):
    lower = third = fourth = 0
    gross_ticket = 0
    onboard = 0
    liability = 0
    confirmed = 0
    paid_in_full = 0

    for booking in bookings_of_sailing(sailing["id"]):
        status = booking["booking_status"]
        if status == "CONFIRMED":
            confirmed += 1
        if status in ACTIVE:
            lower += booking["occupancy_adults"]
            third += booking["third_berth_guests"]
            fourth += booking["fourth_berth_guests"]
            gross_ticket += booking["net_ticket_cents"] + booking["upgrade_charge_cents"]
            onboard += booking["projected_onboard_net_cents"]
            liability += (booking["itinerary_compensation_obc_cents"]
                          + booking["itinerary_refund_cents"])
            if booking["payment_status"] == "PAID_IN_FULL":
                paid_in_full += 1

    total_lower_berths = sailing["total_lower_berths"]
    nights = sailing["nights"]

    held_lower_berths = 0
    for inv in inventories_of(sailing["id"]):
        category = store.cabin_categories.get(inv["cabin_category_id"])
        berths = category["lower_berths"] if category else 0
        held_lower_berths += inv["group_held_cabins"] * berths

    albd_gross = total_lower_berths * nights
    albd_net = max(1, total_lower_berths - held_lower_berths) * nights

    total_revenue = gross_ticket + onboard - liability
    ralbd_gross = calcs.ralbd(total_revenue, albd_gross)
    ralbd_net = calcs.ralbd(total_revenue, albd_net)

    pct = calcs.occupancy_pct(lower, total_lower_berths)

    return store.apply_changes(sailing, {
        "lower_berths_sold": lower,
        "third_berths_sold": third,
        "fourth_berths_sold": fourth,
        "occupancy_pct": pct,
        "inventory_posture": calcs.posture(pct),
        "confirmed_bookings_count": confirmed,
        "paid_in_full_bookings_count": paid_in_full,
        "final_payment_risk_flag": calcs.final_payment_risk(confirmed, paid_in_full),
        "gross_ticket_revenue_cents": gross_ticket,
        "projected_onboard_revenue_cents": onboard,
        "compensation_liability_cents": liability,
        "available_lower_berth_days_gross": albd_gross,
        "available_lower_berth_days_net": albd_net,
        "ralbd_gross_cents": ralbd_gross,
        "ralbd_net_cents": ralbd_net,
        "revenue_alert": calcs.revenue_alert(ralbd_net),
    }, bump=bump)


# --------------------------------------------------------------------------
# Guest counters
# --------------------------------------------------------------------------
def recompute_guest(guest, bump=True):
    count = 0
    for booking in bookings_of_guest(guest["id"]):
        if booking["booking_status"] != "CANCELLED":
            count += 1
    return store.apply_changes(guest, {"bookings_count": count}, bump=bump)


def apply_loyalty(guest, bump=True):
    tier, pct = calcs.loyalty(guest["prior_sailings_count"])
    return store.apply_changes(
        guest, {"loyalty_tier": tier, "repeat_guest_offer_pct": pct}, bump=bump)


# --------------------------------------------------------------------------
# Booking money and onboard projection
# --------------------------------------------------------------------------
def paid_total(booking_id):
    total = 0
    for event in events_of(booking_id):
        if event["kind"] == "REFUND":
            total -= event["amount_cents"]
        else:
            total += event["amount_cents"]
    return total


def recompute_booking_money(booking):
    """amount_paid_cents from the ledger, then balance_due_cents. No version bump:
    every caller is already writing the booking row."""
    paid = paid_total(booking["id"])
    booking["amount_paid_cents"] = paid
    booking["balance_due_cents"] = (
        booking["net_ticket_cents"]
        + booking["upgrade_charge_cents"]
        - booking["itinerary_refund_cents"]
        - paid
    )
    return booking


def recompute_onboard(booking, sailing):
    category_id = booking.get("assigned_cabin_category_id") or booking["cabin_category_id"]
    category = store.cabin_categories.get(category_id)
    if category is None:
        return booking
    gross, net = calcs.onboard_projection(
        sailing["nights"], category, booking["occupancy_adults"],
        booking["third_berth_guests"], booking["fourth_berth_guests"],
        booking["itinerary_compensation_obc_cents"],
    )
    booking["projected_onboard_gross_cents"] = gross
    booking["projected_onboard_net_cents"] = net
    return booking


def append_payment_event(booking, kind, amount_cents, resulting_payment_status, note=None):
    """Append-only ledger row: id and created_at only, no updated_at, no version."""
    event = {
        "booking_id": booking["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "posted_at": store.now_iso(),
        "resulting_payment_status": resulting_payment_status,
        "note": note,
    }
    store.stamp_new(event, versioned=False)
    store.payment_events[event["id"]] = event
    return event


# --------------------------------------------------------------------------
# Promotion redemption bookkeeping
# --------------------------------------------------------------------------
def redeem_promotion(promotion):
    """Raise redemption_count and exhaust the campaign when the cap is reached."""
    changes = {"redemption_count": promotion["redemption_count"] + 1}
    if changes["redemption_count"] >= promotion["max_redemptions"]:
        changes["status"] = "EXHAUSTED"
    store.apply_changes(promotion, changes, bump=True)


def release_redemption(promotion):
    """A cancellation frees a redemption slot but never resurrects the campaign."""
    store.apply_changes(
        promotion,
        {"redemption_count": max(0, promotion["redemption_count"] - 1)},
        bump=True,
    )


# --------------------------------------------------------------------------
# The waitlist promotion loop (calc 10)
# --------------------------------------------------------------------------
def promote_waitlist(sailing, inv):
    """While available_cabins >= 1, promote the head of the ordered eligible pool."""
    if sailing["status"] not in ("OPEN_FOR_SALE", "SALES_SUSPENDED"):
        return 0
    promoted = 0
    while True:
        recompute_inventory(inv, bump=True)
        if inv["available_cabins"] < 1:
            return promoted
        pool = [b for b in store.bookings.values()
                if b["booking_status"] == "WAITLISTED"
                and b["sailing_id"] == sailing["id"]
                and b["cabin_category_id"] == inv["cabin_category_id"]]
        if not pool:
            return promoted
        head = calcs.waitlist_order(pool)[0]
        head["booking_status"] = "OPTION"
        head["deposit_due_date"] = store.iso(store.add_days(
            store.now_dt(), sailing["deposit_due_days_after_booking"]))
        store.touch(head)
        promoted += 1


# --------------------------------------------------------------------------
# Shared cancellation machinery (client cancel, close-inventory, ops-run)
# --------------------------------------------------------------------------
def cancel_booking(booking, sailing, reason, provisional_cents=None,
                   final_cents=None, assess_payment=True):
    """Move a booking to CANCELLED. Callers supply the already-evaluated penalties."""
    was_waitlisted = booking["booking_status"] == "WAITLISTED"
    prior_payment = booking["payment_status"]

    booking["booking_status"] = "CANCELLED"
    booking["cancelled_at"] = store.now_iso()
    booking["cancel_reason"] = reason
    if provisional_cents is not None:
        booking["provisional_penalty_cents"] = provisional_cents
    if final_cents is not None:
        booking["cancellation_penalty_cents"] = final_cents
    if assess_payment and not was_waitlisted and prior_payment in (
            "AWAITING_DEPOSIT", "DEPOSIT_PAID", "PAID_IN_FULL", "DELINQUENT"):
        booking["payment_status"] = "PENALTY_ASSESSED"
    recompute_booking_money(booking)
    store.touch(booking)

    promotion_id = booking.get("promotion_id")
    if promotion_id:
        promotion = store.promotions.get(promotion_id)
        if promotion is not None:
            release_redemption(promotion)

    block_id = booking.get("group_block_id")
    if block_id:
        block = store.group_blocks.get(block_id)
        if block is not None:
            recompute_block(block, bump=True)

    guest = store.guests.get(booking["guest_id"])
    if guest is not None:
        recompute_guest(guest, bump=True)

    return booking
