"""Derived state, conserved counters and the cascades (PRD 2.9, 2.10, 3.2-3.10)."""

import calc
import clock
import lookups
from db import db
from middleware import touch
from util import (
    iso_instant,
    midnight,
    parse_date,
    parse_instant,
    intervals_intersect,
    clears_buffered_window,
    shift_months,
)

LIVE_HOLD_STATES = ("ACTIVE", "CHALLENGED", "CONFIRMED")
COMMITTED_BOOKING_STATES = ("TENTATIVE", "DEFINITE", "IN_HOUSE", "CLOSED", "SETTLED")


# --------------------------------------------------------------------------
# order posture (PRD 2.10)
# --------------------------------------------------------------------------
def derive_order_posture(booking, client):
    if booking["status"] in ("RELEASED", "CANCELLED", "SETTLED"):
        return "LOCKED"
    if client is not None and client.get("booking_standing") == "HOLD_RESTRICTED":
        return "LOCKED"
    if booking["status"] == "CLOSED":
        return "RESTRICTED"
    return "OPEN"


def recompute_order_posture(booking):
    client = db.clients.get(booking["client_id"])
    posture = derive_order_posture(booking, client)
    if booking.get("order_posture") != posture:
        booking["order_posture"] = posture
        touch(booking)
    return posture


# --------------------------------------------------------------------------
# client standing (PRD 3.1 / calculations.client_booking_standing)
# --------------------------------------------------------------------------
def recompute_client_standing(client):
    outstanding = 0
    for booking in lookups.bookings_of_client(client["id"]):
        for settlement in lookups.settlements_of_booking(booking["id"]):
            if settlement["status"] == "FINAL":
                outstanding += settlement["grand_total_cents"]
    standing = calc.client_booking_standing(outstanding)
    changed = (
        client["outstanding_balance_cents"] != outstanding
        or client["booking_standing"] != standing
    )
    if changed:
        client["outstanding_balance_cents"] = outstanding
        client["booking_standing"] = standing
        touch(client)
        # a standing change re-derives the posture of every booking of the client
        for booking in lookups.bookings_of_client(client["id"]):
            recompute_order_posture(booking)
    return standing


# --------------------------------------------------------------------------
# conserved space-day counter (PRD 2.9)
# --------------------------------------------------------------------------
def adjust_committed_space_days(space_id, delta):
    """SpaceUnit.committed_space_days aggregates the space and its descendants,
    so a booking on a child also charges every ancestor."""
    if delta == 0:
        return
    for sid in lookups.self_and_ancestor_ids(space_id):
        space = db.spaces.get(sid)
        if space is None:
            continue
        space["committed_space_days"] = space["committed_space_days"] + delta
        touch(space)


# --------------------------------------------------------------------------
# hold hierarchy (PRD 3.3, calculations.hold_rank_assignment)
# --------------------------------------------------------------------------
def hold_space_id(hold):
    booking = db.bookings.get(hold["booking_id"])
    return booking["space_id"] if booking else None


def hold_interval(hold):
    return parse_date(hold["interval_start_date"]), parse_date(hold["interval_end_date"])


def hold_candidate_set(hold):
    """Every other live hold on a related space with an intersecting interval."""
    space_id = hold_space_id(hold)
    if space_id is None:
        return []
    related = lookups.related_space_ids(space_id)
    start, end = hold_interval(hold)
    out = []
    for other in db.holds.rows():
        if other["id"] == hold["id"]:
            continue
        if other["status"] not in LIVE_HOLD_STATES:
            continue
        other_space = hold_space_id(other)
        if other_space not in related:
            continue
        o_start, o_end = hold_interval(other)
        if intervals_intersect(start, end, o_start, o_end):
            out.append(other)
    return out


def assign_hold_rank_on_insert(hold):
    hold["hold_rank"] = 1 + len(hold_candidate_set(hold))
    return hold["hold_rank"]


def rerank_after_release(released_hold):
    """Re-rank the survivors of the released hold's competitor set."""
    survivors = hold_candidate_set(released_hold)
    survivors.sort(key=lambda h: (h["hold_rank"], h["created_at"], h["_seq"]))
    for index, survivor in enumerate(survivors, start=1):
        if survivor["hold_rank"] != index:
            survivor["hold_rank"] = index
            touch(survivor)


def release_hold(hold, booking_release_states=()):
    """Move a hold to RELEASED and run the declared knock-on effects.

    Returns the number of bookings that cascaded to RELEASED.
    """
    hold["status"] = "RELEASED"
    touch(hold)
    released_bookings = 0
    booking = db.bookings.get(hold["booking_id"])
    if booking is not None:
        booking["hold_count"] = max(0, booking["hold_count"] - 1)
        touch(booking)
    rerank_after_release(hold)
    if (
        booking is not None
        and booking["hold_count"] == 0
        and booking["status"] in booking_release_states
    ):
        release_booking(booking)
        released_bookings = 1
    return released_bookings


# --------------------------------------------------------------------------
# the release cascade (PRD 3.2)
# --------------------------------------------------------------------------
def release_booking(booking):
    booking["status"] = "RELEASED"
    touch(booking)

    # every live hold on the booking is released and the survivors re-ranked
    for hold in lookups.holds_of_booking(booking["id"]):
        if hold["status"] in LIVE_HOLD_STATES:
            hold["status"] = "RELEASED"
            touch(hold)
            booking["hold_count"] = max(0, booking["hold_count"] - 1)
            touch(booking)
            rerank_after_release(hold)

    # a DRAFT or ISSUED license is voided and its escrow returned
    for lic in lookups.licenses_of_booking(booking["id"]):
        if lic["status"] in ("DRAFT", "ISSUED"):
            void_license(lic, booking)

    # every live service order is cancelled and voided
    cancel_service_orders(booking)

    # the conserved space-day counter is reversed
    adjust_committed_space_days(booking["space_id"], -booking["space_days_committed"])

    recompute_order_posture(booking)
    return booking


def void_license(lic, booking):
    lic["status"] = "VOIDED"
    held = lic.get("deposit_held_cents") or 0
    if held:
        client = db.clients.get(booking["client_id"])
        if client is not None:
            client["credit_balance_cents"] = client["credit_balance_cents"] + held
            touch(client)
        lic["deposit_held_cents"] = 0
    touch(lic)
    return lic


def cancel_service_orders(booking):
    for order in lookups.service_orders_of_booking(booking["id"]):
        if order["approval_status"] in ("PENDING_APPROVAL", "APPROVED"):
            order["approval_status"] = "CANCELLED"
            if order["billing_status"] == "ESTIMATED":
                order["estimated_charge_cents"] = 0
            order["billing_status"] = "VOID"
            touch(order)


def cancel_booking(booking):
    booking["status"] = "CANCELLED"
    touch(booking)
    adjust_committed_space_days(booking["space_id"], -booking["space_days_committed"])
    recompute_order_posture(booking)
    return booking


# --------------------------------------------------------------------------
# the hold sweep (PRD 3.3)
# --------------------------------------------------------------------------
def run_hold_sweep():
    now = clock.now()
    expired_challenge_count = 0
    released_hold_count = 0
    promoted_hold_count = 0
    released_booking_count = 0

    for hold in db.holds.rows():
        if hold["status"] != "CHALLENGED":
            continue
        deadline = parse_instant(hold.get("challenge_deadline_utc"))
        if deadline is None or not now > deadline:
            continue
        challenger = db.holds.get(hold.get("challenged_by_hold_id") or "")
        expired_challenge_count += 1
        released_hold_count += 1
        released_booking_count += release_hold(hold, booking_release_states=("TENTATIVE",))
        if challenger is not None and challenger["status"] in LIVE_HOLD_STATES:
            promoted_hold_count += 1

    for hold in db.holds.rows():
        if hold["status"] != "ACTIVE":
            continue
        deadline = parse_instant(hold.get("release_deadline_utc"))
        if deadline is None or not now > deadline:
            continue
        released_hold_count += 1
        released_booking_count += release_hold(hold, booking_release_states=("TENTATIVE",))

    return {
        "expired_challenge_count": expired_challenge_count,
        "released_hold_count": released_hold_count,
        "promoted_hold_count": promoted_hold_count,
        "released_booking_count": released_booking_count,
    }


# --------------------------------------------------------------------------
# maintenance blackouts (PRD 3.10)
# --------------------------------------------------------------------------
def approved_blackouts_for_spaces(space_ids):
    return [
        b
        for b in db.blackouts.rows()
        if b["status"] == "APPROVED" and b["space_id"] in space_ids
    ]


def interval_clears_all_blackouts(space_id, start, end):
    """True when [start, end] clears every APPROVED blackout on a related space."""
    for blackout in approved_blackouts_for_spaces(lookups.related_space_ids(space_id)):
        if not clears_buffered_window(
            start,
            end,
            parse_date(blackout["window_start_date"]),
            parse_date(blackout["window_end_date"]),
            blackout["buffer_days"],
        ):
            return False
    return True


def approve_blackout(blackout):
    blackout["status"] = "APPROVED"
    touch(blackout)

    space = db.spaces.get(blackout["space_id"])
    if space is not None:
        space["active_blackout_count"] = space["active_blackout_count"] + 1
        touch(space)

    win_start = parse_date(blackout["window_start_date"])
    win_end = parse_date(blackout["window_end_date"])
    buffer_days = blackout["buffer_days"]
    affected_spaces = lookups.self_and_descendant_ids(blackout["space_id"])

    for hold in db.holds.rows():
        if hold["status"] not in LIVE_HOLD_STATES:
            continue
        if hold_space_id(hold) not in affected_spaces:
            continue
        start, end = hold_interval(hold)
        if clears_buffered_window(start, end, win_start, win_end, buffer_days):
            continue
        release_hold(hold, booking_release_states=("TENTATIVE", "DEFINITE"))
    return blackout


def blackout_conflicts_with_committed_booking(blackout):
    """Approval guard: no DEFINITE or IN_HOUSE booking on a related space may fail
    to clear the buffered window."""
    win_start = parse_date(blackout["window_start_date"])
    win_end = parse_date(blackout["window_end_date"])
    related = lookups.related_space_ids(blackout["space_id"])
    for booking in db.bookings.rows():
        if booking["status"] not in ("DEFINITE", "IN_HOUSE"):
            continue
        if booking["space_id"] not in related:
            continue
        if not clears_buffered_window(
            parse_date(booking["move_in_start_date"]),
            parse_date(booking["move_out_end_date"]),
            win_start,
            win_end,
            blackout["buffer_days"],
        ):
            return True
    return False


# --------------------------------------------------------------------------
# union crew capacity (PRD 3.6)
# --------------------------------------------------------------------------
def recompute_committed_crew_hours(jurisdiction):
    total = 0.0
    for call in lookups.labor_calls_of_jurisdiction(jurisdiction["id"]):
        if call["status"] in ("SCHEDULED", "DISPATCHED", "ACTUALIZED"):
            total += call["billed_hours"]
    total = calc.one_decimal(total)
    if jurisdiction["committed_crew_hours"] != total:
        jurisdiction["committed_crew_hours"] = total
        touch(jurisdiction)
    return total


def crew_hours_on_date(jurisdiction_id, work_date, exclude_call_id=None):
    total = 0.0
    for call in lookups.labor_calls_of_jurisdiction(jurisdiction_id):
        if call["id"] == exclude_call_id:
            continue
        if call["work_date"] != work_date:
            continue
        if call["status"] in ("SCHEDULED", "DISPATCHED", "ACTUALIZED"):
            total += call["billed_hours"]
    return calc.one_decimal(total)


# --------------------------------------------------------------------------
# settlement totalling and finalization (PRD 3.9)
# --------------------------------------------------------------------------
def rental_basis_for(settlement):
    booking = db.bookings.get(settlement["booking_id"])
    space = db.spaces.get(booking["space_id"])
    window = db.policy_windows.get(booking.get("policy_window_id") or "")
    if window is None:
        window = lookups.policy_window_for_class(booking["event_class"])
    usage = lookups.usage_records_of_booking(booking["id"])
    return calc.settlement_rental_basis(settlement, booking, space, window, usage)


def recompute_settlement_totals(settlement):
    lines = lookups.line_items_of_settlement(settlement["id"])
    settlement["line_subtotal_cents"] = calc.settlement_line_extension(lines)
    settlement["facility_service_fee_cents"] = calc.facility_service_fee(
        settlement["line_subtotal_cents"]
    )
    settlement["grand_total_cents"] = (
        settlement["line_subtotal_cents"]
        + settlement["facility_service_fee_cents"]
        - settlement["deposit_applied_cents"]
    )
    return settlement


def finalize_settlement(settlement, actor_id):
    booking = db.bookings.get(settlement["booking_id"])
    lic = lookups.deposit_license_of_booking(settlement["booking_id"])
    held = (lic.get("deposit_held_cents") or 0) if lic is not None else 0
    settlement["deposit_applied_cents"] = held
    if lic is not None and held:
        lic["deposit_held_cents"] = 0
        touch(lic)
    settlement["grand_total_cents"] = (
        settlement["line_subtotal_cents"]
        + settlement["facility_service_fee_cents"]
        - settlement["deposit_applied_cents"]
    )
    settlement["finalized_by_user_id"] = actor_id
    settlement["status"] = "FINAL"
    touch(settlement)

    if booking is not None and booking["status"] == "CLOSED":
        booking["status"] = "SETTLED"
        touch(booking)
        client = db.clients.get(booking["client_id"])
        if client is not None:
            recompute_client_standing(client)
        recompute_order_posture(booking)
    return settlement


# --------------------------------------------------------------------------
# hold creation helpers
# --------------------------------------------------------------------------
def release_deadline_for(show_start_date):
    """Midnight UTC of show_start_date less RELEASE_LEAD_MONTHS whole months."""
    target = shift_months(show_start_date, -calc.RELEASE_LEAD_MONTHS)
    return iso_instant(midnight(target))
