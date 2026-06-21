"""Domain services: entity lookup, mutation, state machines, cascades.

All money in integer cents. Computed fields recomputed on read via serializers.
"""
from datetime import timedelta

from db import db
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_VENUE_NOT_OPEN,
    ERR_STALE_SLOT_VERSION,
    ERR_STALE_GROUP_VERSION,
    ERR_HEIGHT_REQUIREMENT,
    ERR_WAIVER_REQUIRED,
    ERR_CHECK_IN_WINDOW,
    ERR_NO_SHOW_WINDOW,
    ERR_PARTY_GROUP_EMPTY,
    ERR_CAPACITY_EXCEEDED,
    ERR_COMBO_PASS_INVALID,
    ERR_INSUFFICIENT_CARD_BALANCE,
    ERR_INVALID_REQUEST,
)
from util import now_iso, parse_iso, parse_date
import serializers as S
import calculations as C


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

def touch(entity):
    """Mark an entity mutated: refresh updated_at, bump version."""
    entity["updated_at"] = now_iso()
    if "version" in entity:
        entity["version"] = entity["version"] + 1


# ---------------------------------------------------------------------------
# Existence lookups (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def get_venue(venue_id):
    v = db.venues.get(venue_id)
    if v is None:
        raise err(ERR_NOT_FOUND, "Venue not found")
    return v


def get_attraction(attraction_id):
    a = db.attractions.get(attraction_id)
    if a is None:
        raise err(ERR_NOT_FOUND, "Attraction not found")
    return a


def get_pricing_plan(plan_id):
    p = db.pricing_plans.get(plan_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Pricing plan not found")
    return p


def get_heat(heat_id):
    h = db.heats.get(heat_id)
    if h is None:
        raise err(ERR_NOT_FOUND, "Heat not found")
    return h


def get_tee_session(tid):
    s = db.tee_sessions.get(tid)
    if s is None:
        raise err(ERR_NOT_FOUND, "Tee session not found")
    return s


def get_guest(guest_id):
    g = db.guests.get(guest_id)
    if g is None:
        raise err(ERR_NOT_FOUND, "Guest not found")
    return g


def get_waiver(waiver_id):
    w = db.waivers.get(waiver_id)
    if w is None:
        raise err(ERR_NOT_FOUND, "Waiver not found")
    return w


def get_wallet(wallet_id):
    w = db.wallets.get(wallet_id)
    if w is None:
        raise err(ERR_NOT_FOUND, "Wallet not found")
    return w


def get_combo_pass(cid):
    c = db.combo_passes.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "Combo pass not found")
    return c


def get_party_group(gid):
    pg = db.party_groups.get(gid)
    if pg is None:
        raise err(ERR_NOT_FOUND, "Party group not found")
    return pg


def get_booking(bid):
    b = db.bookings.get(bid)
    if b is None:
        raise err(ERR_NOT_FOUND, "Booking not found")
    return b


def wallet_for_guest(guest_id):
    for w in db.wallets.values():
        if w["guest_id"] == guest_id:
            return w
    return None


# ---------------------------------------------------------------------------
# Slot abstraction (Heat / TeeSession share confirm/cancel/promotion logic)
# ---------------------------------------------------------------------------

def slot_of_booking(b):
    if b["slot_kind"] == "HEAT":
        return db.heats.get(b["heat_id"]), "HEAT"
    else:
        return db.tee_sessions.get(b["tee_session_id"]), "TEE_SESSION"


def slot_available(slot, slot_kind):
    if slot_kind == "HEAT":
        return S.heat_available(slot)
    return S.tee_available(slot)


def attraction_of_slot(slot):
    return db.attractions.get(slot["attraction_id"])


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------

def promote_waitlist(slot, slot_kind):
    """Promote the earliest-eligible WAITLISTED booking on this slot whose
    party_size still fits, if venue OPEN and slot OPEN. Only one promotion per
    capacity release (matches the single-booking release semantics)."""
    venue = db.venues.get(slot["venue_id"])
    if venue is None or venue["posture"] != "OPEN":
        return
    if slot["status"] != "OPEN":
        return

    waitlisted = []
    for b in db.bookings.values():
        if b["status"] != "WAITLISTED":
            continue
        if slot_kind == "HEAT" and b.get("heat_id") == slot["id"]:
            waitlisted.append(b)
        elif slot_kind == "TEE_SESSION" and b.get("tee_session_id") == slot["id"]:
            waitlisted.append(b)

    # order by created_at ASC, then waitlist_seq ASC
    waitlisted.sort(key=lambda b: (b["created_at"], b["_seq"], b["waitlist_seq"] or 0))

    avail = slot_available(slot, slot_kind)
    for b in waitlisted:
        if b["party_size"] <= avail:
            _do_promote(b, slot, slot_kind)
            return  # one promotion per release


def _do_promote(b, slot, slot_kind):
    plan = db.pricing_plans.get(b["pricing_plan_id"])
    combo = db.combo_passes.get(b["combo_pass_id"]) if b["combo_pass_id"] else None

    gross = C.booking_price(plan, slot["window"], b["units"], b["party_size"])
    credits_applied, cash_due = C.combo_credit_application(
        plan, combo, gross, b["units"], b["party_size"]
    )
    b["gross_price_cents"] = gross
    b["credits_applied"] = credits_applied
    b["cash_due_cents"] = cash_due
    b["status"] = "CONFIRMED"
    b["waitlist_seq"] = None
    touch(b)

    touch(slot)  # committed counter recomputed on read; version bumps

    if b["group_id"]:
        pg = db.party_groups.get(b["group_id"])
        if pg is not None:
            touch(pg)


# ---------------------------------------------------------------------------
# Capacity release shared by cancel / no-show
# ---------------------------------------------------------------------------

def release_confirmed_capacity(b):
    """Release a previously CONFIRMED/CHECKED_IN booking's slot capacity and
    promote the earliest-eligible waitlisted booking."""
    slot, slot_kind = slot_of_booking(b)
    if slot is not None:
        touch(slot)  # committed recomputed on read after status change; version +1
    if b["group_id"]:
        pg = db.party_groups.get(b["group_id"])
        if pg is not None:
            touch(pg)
    if slot is not None:
        promote_waitlist(slot, slot_kind)


# ---------------------------------------------------------------------------
# Booking lifecycle
# ---------------------------------------------------------------------------

def cancel_booking_internal(b):
    """Cancel a HOLD/CONFIRMED/WAITLISTED booking, running side effects.

    Caller has already validated the booking is in a cancellable state.
    """
    prev = b["status"]
    b["status"] = "CANCELLED"
    # combo credits applied at confirm but not redeemed are released simply by
    # not advancing credits_redeemed (already the case) — credits_applied stays
    # informational; ComboPass.credits_redeemed unchanged.
    if prev == "WAITLISTED":
        b["waitlist_seq"] = None
    touch(b)
    if prev in ("CONFIRMED", "CHECKED_IN"):
        release_confirmed_capacity(b)
    maybe_complete_group(b.get("group_id"))


def maybe_complete_group(group_id):
    """Bubble a PartyGroup to COMPLETED when all members terminal w/ >=1 COMPLETED."""
    if not group_id:
        return
    pg = db.party_groups.get(group_id)
    if pg is None:
        return
    if pg["status"] not in ("CONFIRMED", "CHECKED_IN"):
        return
    members = [b for b in db.bookings.values() if b.get("group_id") == group_id]
    if not members:
        return
    terminal = {"COMPLETED", "CANCELLED", "NO_SHOW"}
    if all(b["status"] in terminal for b in members) and \
            any(b["status"] == "COMPLETED" for b in members):
        pg["status"] = "COMPLETED"
        touch(pg)


# ---------------------------------------------------------------------------
# Slot state machines (Heat / TeeSession)
# ---------------------------------------------------------------------------

def open_slot(slot, slot_kind):
    venue = db.venues.get(slot["venue_id"])
    # posture gate (priority 5) before state check (priority 7)
    if venue is None or venue["posture"] != "OPEN":
        raise err(ERR_VENUE_NOT_OPEN, "Venue is not OPEN")
    if slot["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Slot is not SCHEDULED")
    slot["status"] = "OPEN"
    touch(slot)


def close_slot(slot, slot_kind):
    if slot["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Slot is not OPEN")
    slot["status"] = "CLOSED"
    # manual close: CONFIRMED + CHECKED_IN -> COMPLETED; WAITLISTED -> CANCELLED
    members = _bookings_on_slot(slot, slot_kind)
    for b in members:
        if b["status"] in ("CONFIRMED", "CHECKED_IN"):
            b["status"] = "COMPLETED"
            touch(b)
            maybe_complete_group(b.get("group_id"))
        elif b["status"] == "WAITLISTED":
            b["status"] = "CANCELLED"
            b["waitlist_seq"] = None
            touch(b)
            maybe_complete_group(b.get("group_id"))
    touch(slot)


def cancel_slot(slot, slot_kind):
    if slot["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Slot is not SCHEDULED")
    _cancel_scheduled_slot(slot, slot_kind)


def _cancel_scheduled_slot(slot, slot_kind):
    """SCHEDULED -> CANCELLED; non-terminal (HOLD, WAITLISTED) bookings -> CANCELLED."""
    slot["status"] = "CANCELLED"
    members = _bookings_on_slot(slot, slot_kind)
    for b in members:
        if b["status"] in ("HOLD", "WAITLISTED"):
            prev = b["status"]
            b["status"] = "CANCELLED"
            if prev == "WAITLISTED":
                b["waitlist_seq"] = None
            touch(b)
            maybe_complete_group(b.get("group_id"))
    touch(slot)


def _bookings_on_slot(slot, slot_kind):
    out = []
    for b in db.bookings.values():
        if slot_kind == "HEAT" and b.get("heat_id") == slot["id"]:
            out.append(b)
        elif slot_kind == "TEE_SESSION" and b.get("tee_session_id") == slot["id"]:
            out.append(b)
    return out


# ---------------------------------------------------------------------------
# Venue posture state machine + cascades
# ---------------------------------------------------------------------------

def venue_has_open_slot(venue_id):
    return S.open_slot_count(venue_id) > 0


def weather_hold(venue, reason):
    # state check (posture must be OPEN)
    if venue["posture"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Venue is not OPEN")
    venue["posture"] = "WEATHER_HOLD"
    venue["weather_hold_reason"] = reason
    # cascade: OPEN slots -> CLOSED; WAITLISTED on them -> CANCELLED;
    # CONFIRMED/CHECKED_IN stay (NOT completed).
    for slot, slot_kind in _all_slots(venue["id"]):
        if slot["status"] == "OPEN":
            slot["status"] = "CLOSED"
            for b in _bookings_on_slot(slot, slot_kind):
                if b["status"] == "WAITLISTED":
                    b["status"] = "CANCELLED"
                    b["waitlist_seq"] = None
                    touch(b)
                    maybe_complete_group(b.get("group_id"))
            touch(slot)
    touch(venue)


def resume(venue):
    if venue["posture"] != "WEATHER_HOLD":
        raise err(ERR_INVALID_STATE, "Venue is not in WEATHER_HOLD")
    venue["posture"] = "OPEN"
    venue["weather_hold_reason"] = None
    touch(venue)


def close_venue(venue):
    if venue["posture"] not in ("OPEN", "WEATHER_HOLD"):
        raise err(ERR_INVALID_STATE, "Venue cannot be closed from its current posture")
    # precondition: no OPEN slot on the venue
    if venue_has_open_slot(venue["id"]):
        raise err(ERR_INVALID_STATE, "Cannot close venue while a slot is OPEN")
    venue["posture"] = "CLOSED"
    # cascade: all SCHEDULED slots -> CANCELLED (cascading their bookings)
    for slot, slot_kind in _all_slots(venue["id"]):
        if slot["status"] == "SCHEDULED":
            _cancel_scheduled_slot(slot, slot_kind)
    touch(venue)


def _all_slots(venue_id):
    out = []
    for h in db.heats.values():
        if h["venue_id"] == venue_id:
            out.append((h, "HEAT"))
    for s in db.tee_sessions.values():
        if s["venue_id"] == venue_id:
            out.append((s, "TEE_SESSION"))
    return out
