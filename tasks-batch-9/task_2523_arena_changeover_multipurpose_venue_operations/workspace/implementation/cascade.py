"""Shared state transitions and the transitive cascades of PRD 2.11."""

import calc
from store import db, now_logical, ordered, touch


def bump_venue(venue):
    """PRD 2.6: the enumerated operations advance the arena's version by one."""
    touch(venue)


def rows(collection):
    return ordered(list(collection.values()))


# --- equipment -------------------------------------------------------------
def return_issue(issue, damaged_units, reason):
    issue["status"] = "RETURNED"
    issue["damaged_units"] = damaged_units
    issue["returned_at_utc"] = now_logical()
    issue["return_reason"] = reason
    touch(issue)
    asset = db.assets.get(issue["asset_id"])
    if asset is not None:
        asset["units_out_of_service"] = int(asset["units_out_of_service"]) + int(damaged_units)
        asset["cycles_since_service"] = int(asset["cycles_since_service"]) + 1
        touch(asset)


# --- labor -----------------------------------------------------------------
def cancel_labor_call(call):
    call["cancellation_fee_cents"] = calc.labor_cancellation_fee_cents(call, now_logical())
    call["status"] = "CANCELLED"
    touch(call)


# --- changeover orders -----------------------------------------------------
def abandon_order(order, reason):
    """PLANNED/IN_PROGRESS/REWORK/READY_FOR_SIGNOFF -> ABANDONED (system only)."""
    order["status"] = "ABANDONED"
    order["abandon_reason"] = reason
    touch(order)
    for issue in rows(db.issues):
        if issue["changeover_order_id"] == order["id"] and issue["status"] == "ISSUED":
            return_issue(issue, 0, "ORDER_ABANDONED")
    for call in rows(db.labor_calls):
        if call["changeover_order_id"] == order["id"] and call["status"] == "CALLED":
            cancel_labor_call(call)


# --- booking departure cascade --------------------------------------------
def cascade_booking_gone(booking):
    booking_id = booking["id"]
    for reservation in rows(db.docks):
        if reservation["booking_id"] == booking_id and reservation["status"] == "RESERVED":
            reservation["status"] = "RELEASED"
            reservation["release_reason"] = "BOOKING_GONE"
            touch(reservation)
    for order in rows(db.orders):
        if order["status"] in calc.TERMINAL_ORDER_STATES:
            continue
        if order["from_booking_id"] == booking_id:
            abandon_order(order, "FROM_BOOKING_GONE")
        elif order["to_booking_id"] == booking_id:
            abandon_order(order, "TO_BOOKING_GONE")


def deny_open_challenges(booking):
    """Cascaded denial of every OPEN challenge against a departing booking."""
    for challenge in rows(db.challenges):
        if challenge["booking_id"] == booking["id"] and challenge["status"] == "OPEN":
            challenge["status"] = "DENIED"
            challenge["ruled_at"] = now_logical()
            touch(challenge)


def release_booking(booking, reason):
    """DRAFT/HELD/CHALLENGED/CONFIRMED -> RELEASED, with the full cascade.

    The caller is responsible for the single arena version increment.
    """
    if booking["status"] == "CHALLENGED":
        deny_open_challenges(booking)
    booking["status"] = "RELEASED"
    booking["release_reason"] = reason
    touch(booking)
    cascade_booking_gone(booking)


def displace_booking(booking, challenger_booking_id):
    """CHALLENGED -> DISPLACED, with the settlement waterfall and the cascade."""
    booking["displaced_by_booking_id"] = challenger_booking_id
    booking["displacement_penalty_cents"] = calc.displacement_settlement_cents(
        booking, now_logical())
    booking["release_reason"] = None
    booking["status"] = "DISPLACED"
    touch(booking)
    cascade_booking_gone(booking)


# --- ice -------------------------------------------------------------------
def cover_ice_sheet(sheet):
    """IN_SERVICE -> COVERED, plus the automatic melt-out beyond the cycle limit.

    The caller is responsible for the sheet's single version increment and for
    the arena's.
    """
    sheet["status"] = "COVERED"
    sheet["cover_installed_at_utc"] = now_logical()
    sheet["cover_cycles"] = int(sheet["cover_cycles"]) + 1
    sheet["condensation_risk_score"] = calc.condensation_risk_score(sheet)
    if int(sheet["cover_cycles"]) > calc.COVER_CYCLE_LIMIT:
        sheet["status"] = "MELTING"
