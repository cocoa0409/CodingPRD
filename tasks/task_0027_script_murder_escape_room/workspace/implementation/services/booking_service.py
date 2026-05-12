"""Booking lifecycle, cancellation, refund, settlement reversal cascades, waitlist promotion."""
import math
from datetime import datetime, timezone

from db import (
    store, bump, make_common, parse_iso, now_dt, now_iso,
    FREE_CANCEL_LEAD_MINUTES, LATE_CANCEL_LEAD_MINUTES, LATE_CANCEL_PAID_REFUND_BPS,
    DEPOSIT_HOLD_TTL_MINUTES, NO_SHOW_BAN_THRESHOLD,
)
from errors import (
    ERR_SETTLEMENT_ALREADY_FINALIZED, raise_error,
)
from audit import write_audit


# ---- Refund computation per cancellation_initiator ----
def compute_refund(booking: dict, slot: dict, initiator: str, refund_amount_cents: int = 0) -> tuple[int, int]:
    """Returns (deposit_refund_cents, paid_refund_cents)."""
    if initiator == "PLAYER":
        starts_at = parse_iso(slot["starts_at"])
        lead_minutes = (starts_at - now_dt()).total_seconds() / 60.0
        if lead_minutes >= FREE_CANCEL_LEAD_MINUTES:
            return booking["deposit_held_cents"], booking["paid_amount_cents"]
        elif lead_minutes >= LATE_CANCEL_LEAD_MINUTES:
            paid = (booking["paid_amount_cents"] * LATE_CANCEL_PAID_REFUND_BPS) // 10000
            return booking["deposit_held_cents"], paid
        else:
            return 0, 0
    elif initiator in ("VENUE", "SYSTEM_MATCH_FAIL"):
        return booking["deposit_held_cents"], booking["paid_amount_cents"]
    elif initiator == "NO_SHOW":
        return 0, 0
    elif initiator == "POST_SETTLEMENT":
        # paid_refund supplied by caller; deposit refund 0 (already released)
        return 0, refund_amount_cents
    return 0, 0


def recompute_slot_aggregates(slot: dict):
    """Recompute confirmed_seat_count, gross_revenue_cents, net_revenue_cents."""
    bookings = [b for b in store.bookings.values() if b["slot_id"] == slot["id"]]
    confirmed = sum(b["seat_count"] for b in bookings if b["status"] == "CONFIRMED")
    slot["confirmed_seat_count"] = confirmed
    settled = [b for b in bookings if b["status"] in ("SETTLED", "REFUNDED")]
    gross = sum(b["paid_amount_cents"] for b in settled)
    refunds_total = sum(b["refund_total_cents"] for b in settled)
    # gross_revenue_cents is sum of paid across SETTLED & REFUNDED bookings (pinned at completion)
    # but during pre-completion phase remains as-is. Since this method is called from many places
    # we recompute for all phases in a deterministic way.
    if slot["schedule_status"] in ("COMPLETED",):
        slot["gross_revenue_cents"] = gross
        slot["net_revenue_cents"] = gross - refunds_total
    else:
        slot["gross_revenue_cents"] = gross
        slot["net_revenue_cents"] = gross - refunds_total


# ---- Match quorum cascade ----
def cascade_match_quorum_after_change(slot: dict):
    """After confirmed_seat_count changes, evaluate match_status."""
    if slot["schedule_status"] != "SCHEDULED":
        return
    n = slot["confirmed_seat_count"]
    R = slot["required_seats_for_launch"]
    deadline = parse_iso(slot["match_deadline_at"])
    now = now_dt()
    if now < deadline:
        if slot["match_status"] == "OPEN" and n >= R:
            slot["match_status"] = "MATCHED"
            bump(slot)
        elif slot["match_status"] == "MATCHED" and n < R:
            slot["match_status"] = "OPEN"
            bump(slot)
    # at/post deadline: do nothing here; handled by clock advance scan


# ---- Cancel a booking with optional cascade-driven trigger ----
def cancel_booking(booking: dict, initiator: str, actor_user_id: str, actor_role: str,
                   sweep_waitlist: bool = True, refund_amount_cents: int = 0):
    """Move booking to CANCELLED with refund logic. Also handles cascades."""
    if booking["status"] in ("CANCELLED", "REFUNDED", "SETTLED"):
        # Already finalized — skip
        return booking

    pre_status = booking["status"]
    slot = store.session_slots[booking["slot_id"]]

    deposit_refund, paid_refund = compute_refund(booking, slot, initiator)
    booking["refund_total_cents"] = booking.get("refund_total_cents", 0) + deposit_refund + paid_refund
    booking["cancellation_initiator"] = initiator
    booking["status"] = "CANCELLED"
    bump(booking)

    # Slot aggregates: confirmed_seat_count decrement if was CONFIRMED
    if pre_status == "CONFIRMED":
        slot["confirmed_seat_count"] = max(0, slot["confirmed_seat_count"] - booking["seat_count"])
        bump(slot)
        # If match was MATCHED and now n < R, demote (only pre-deadline)
        if slot["match_status"] == "MATCHED" and slot["confirmed_seat_count"] < slot["required_seats_for_launch"]:
            deadline = parse_iso(slot["match_deadline_at"])
            if now_dt() < deadline:
                slot["match_status"] = "OPEN"
                bump(slot)
            # else: post-deadline; MATCHED is sticky

    # Audit log entry: BOOKING_CANCELLED for general cancels; NO_SHOW special action recorded separately
    if initiator == "NO_SHOW":
        write_audit(actor_user_id, actor_role, "Booking", booking["id"],
                    "BOOKING_NO_SHOW_MARKED", booking)
        # Increment no_show_strikes on lead player
        player = store.players.get(booking["lead_player_id"])
        if player:
            player["no_show_strikes"] = int(player.get("no_show_strikes", 0)) + 1
            bump(player)
    else:
        write_audit(actor_user_id, actor_role, "Booking", booking["id"],
                    "BOOKING_CANCELLED", booking)

    # Waitlist promotion sweep — only if there's freed seat capacity (not for NO_SHOW since slot is already completing)
    if sweep_waitlist and pre_status == "CONFIRMED":
        promote_waitlist(slot, actor_user_id, actor_role)

    return booking


def promote_waitlist(slot: dict, actor_user_id: str, actor_role: str):
    """Iterate waitlist promotion sweep until no eligible entry."""
    # Get theme for max_players cap
    theme = store.themes.get(slot["theme_id"])
    max_players = theme["max_players"] if theme else 9999
    # Track remaining capacity locally; promoted bookings tentatively occupy the seats
    # until confirm-deposit (or auto-cancel), per PRD §3.7.
    pending_promoted_seats = sum(
        b["seat_count"] for b in store.bookings.values()
        if b["slot_id"] == slot["id"] and b["status"] == "PENDING_DEPOSIT" and b.get("promoted_at")
    )
    remaining_capacity = max_players - slot["confirmed_seat_count"] - pending_promoted_seats
    while remaining_capacity > 0:
        # Find QUEUED entries
        candidates = [e for e in store.waitlist_entries.values()
                      if e["slot_id"] == slot["id"] and e["status"] == "QUEUED"]
        eligible = [e for e in candidates if e["requested_seat_count"] <= remaining_capacity]
        if not eligible:
            return
        # Sort: VIP first, then enqueued_at ASC, then id ASC
        eligible.sort(key=lambda e: (
            0 if e["priority_class"] == "VIP" else 1,
            e["enqueued_at"],
            e["id"],
        ))
        winner = eligible[0]
        winner["status"] = "PROMOTED"
        bump(winner)

        # Create new Booking in PENDING_DEPOSIT
        venue = store.venues[slot["venue_id"]]
        seat_count = winner["requested_seat_count"]
        new_booking = make_common({
            "slot_id": slot["id"],
            "lead_player_id": winner["lead_player_id"],
            "team_player_ids": [winner["lead_player_id"]] * seat_count,
            "seat_count": seat_count,
            "paid_amount_cents": seat_count * slot["price_cents"],
            "deposit_held_cents": seat_count * venue["deposit_policy_cents"],
            "refund_total_cents": 0,
            "cancellation_initiator": None,
            "status": "PENDING_DEPOSIT",
            "promoted_at": now_iso(),
            "from_waitlist_entry_id": winner["id"],
        })
        store.bookings[new_booking["id"]] = new_booking
        remaining_capacity -= seat_count


# ---- Confirm deposit ----
def confirm_booking_deposit(booking: dict, actor_user_id: str, actor_role: str,
                            idempotency_key: str | None):
    from errors import (
        ERR_SESSION_NOT_OPEN_FOR_CONFIRM, ERR_SLOT_FULL, ERR_PLAYER_BANNED,
    )
    # Idempotency: if a key supplied for this booking previously, return current state
    if idempotency_key:
        ikey = (booking["id"], idempotency_key)
        if ikey in store.payment_idempotency:
            # Already processed — return current state (no duplicate audit)
            return booking
    if booking["status"] == "CONFIRMED":
        # Already confirmed; treat as idempotent if no key OR record key
        if idempotency_key:
            store.payment_idempotency[(booking["id"], idempotency_key)] = booking["id"]
        return booking
    if booking["status"] != "PENDING_DEPOSIT":
        raise_error(ERR_SESSION_NOT_OPEN_FOR_CONFIRM,
                    f"Booking status is {booking['status']}, not PENDING_DEPOSIT")

    slot = store.session_slots[booking["slot_id"]]
    # State check: slot must be SCHEDULED
    if slot["schedule_status"] != "SCHEDULED":
        raise_error(ERR_SESSION_NOT_OPEN_FOR_CONFIRM,
                    f"slot schedule_status is {slot['schedule_status']}")

    # Player ban check
    player = store.players.get(booking["lead_player_id"])
    if player:
        if player.get("status") == "BANNED" or int(player.get("no_show_strikes", 0)) >= NO_SHOW_BAN_THRESHOLD:
            raise_error(ERR_PLAYER_BANNED, "player banned or struck-out")

    # Capacity check (atomic)
    theme = store.themes[slot["theme_id"]]
    if slot["confirmed_seat_count"] + booking["seat_count"] > theme["max_players"]:
        raise_error(ERR_SLOT_FULL, "slot would exceed max_players")

    booking["status"] = "CONFIRMED"
    bump(booking)
    slot["confirmed_seat_count"] = slot["confirmed_seat_count"] + booking["seat_count"]
    bump(slot)

    # Audit on first entry to CONFIRMED
    write_audit(actor_user_id, actor_role, "Booking", booking["id"],
                "BOOKING_CREATED", booking)

    # Match quorum cascade
    cascade_match_quorum_after_change(slot)

    if idempotency_key:
        store.payment_idempotency[(booking["id"], idempotency_key)] = booking["id"]

    return booking


# ---- Refund post-completion ----
def refund_booking(booking: dict, refund_amount_cents: int, actor_user_id: str, actor_role: str):
    from errors import (
        ERR_REFUND_REQUIRES_COMPLETED_SESSION, ERR_REFUND_EXCEEDS_PAID,
    )
    slot = store.session_slots[booking["slot_id"]]
    # Slot must be COMPLETED
    if slot["schedule_status"] != "COMPLETED" or booking["status"] != "SETTLED":
        raise_error(ERR_REFUND_REQUIRES_COMPLETED_SESSION,
                    "refund requires SETTLED booking on COMPLETED slot")
    # Refund cap
    available = booking["paid_amount_cents"] - booking["refund_total_cents"]
    if refund_amount_cents > available:
        raise_error(ERR_REFUND_EXCEEDS_PAID, "refund exceeds available paid amount")

    booking["refund_total_cents"] = booking["refund_total_cents"] + refund_amount_cents
    booking["status"] = "REFUNDED"
    bump(booking)
    # Update slot net_revenue
    slot["net_revenue_cents"] = slot["net_revenue_cents"] - refund_amount_cents
    bump(slot)

    write_audit(actor_user_id, actor_role, "Booking", booking["id"],
                "BOOKING_REFUNDED", booking)

    # Cascade to settlement run if any FINALIZED run covers this slot
    from services.settlement_service import reverse_run_if_covers_slot
    reverse_run_if_covers_slot(slot["id"], actor_user_id, actor_role)

    return booking
