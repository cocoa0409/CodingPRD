"""Group classes, bookings, waitlist, check-in, cancel."""
from datetime import timedelta
from clock import now
from db import state, new_id, next_order, stamp_create, bump
from errors import raise_err
from . import wallet as wallet_svc


# ---------------- Class create ----------------

def create_class(class_code, instructor_trainer_id, starts_at, ends_at, capacity,
                 recurrence_series_id=None, deduction_cents=0):
    trainer = state["trainers"].get(instructor_trainer_id)
    if not trainer:
        raise_err("ERR_NOT_FOUND", "instructor not found")
    if capacity < 1:
        raise_err("ERR_VALIDATION", "capacity >= 1")
    if deduction_cents < 0:
        raise_err("ERR_VALIDATION", "deduction_cents >= 0")
    if ends_at <= starts_at:
        raise_err("ERR_VALIDATION", "ends_at must be after starts_at")
    # Overlap rule (priority 14): same instructor, status==SCHEDULED, 30-min buffer.
    # For any pair a, b ordered in time, b.starts_at - a.ends_at >= 30 minutes.
    BUFFER = timedelta(minutes=30)
    for c in state["group_classes"].values():
        if c["instructor_trainer_id"] != instructor_trainer_id:
            continue
        if c["status"] != "SCHEDULED":
            continue
        # If the new class starts after c (new.starts_at >= c.ends_at), need
        # new.starts_at - c.ends_at >= 30min.
        # If the new class ends before c (new.ends_at <= c.starts_at), need
        # c.starts_at - new.ends_at >= 30min.
        # Otherwise they overlap.
        if starts_at >= c["ends_at"]:
            if starts_at - c["ends_at"] < BUFFER:
                raise_err("ERR_CLASS_OVERLAP", "class within 30 min buffer")
        elif ends_at <= c["starts_at"]:
            if c["starts_at"] - ends_at < BUFFER:
                raise_err("ERR_CLASS_OVERLAP", "class within 30 min buffer")
        else:
            raise_err("ERR_CLASS_OVERLAP", "class overlaps existing")
    gc = {
        "id": new_id(),
        "class_code": class_code,
        "instructor_trainer_id": instructor_trainer_id,
        "substitute_trainer_id": None,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "recurrence_series_id": recurrence_series_id,
        "deduction_cents": deduction_cents,
        "status": "SCHEDULED",
    }
    stamp_create(gc)
    state["group_classes"][gc["id"]] = gc
    return gc


def patch_class(gc, body):
    # Capacity raise => promote waitlist heads
    capacity_changed = False
    if "capacity" in body and body["capacity"] is not None:
        if body["capacity"] < 1:
            raise_err("ERR_VALIDATION", "capacity >= 1")
        gc["capacity"] = body["capacity"]
        capacity_changed = True
    if "substitute_trainer_id" in body:
        sub_id = body["substitute_trainer_id"]
        if sub_id is not None and sub_id not in state["trainers"]:
            raise_err("ERR_NOT_FOUND", "substitute trainer not found")
        gc["substitute_trainer_id"] = sub_id
    bump(gc)
    if capacity_changed:
        _promote_waitlist_until_full(gc)
    return gc


def _confirmed_count(gc_id):
    return sum(
        1 for b in state["group_bookings"].values()
        if b["class_id"] == gc_id and b["status"] == "CONFIRMED"
    )


def _waitlisted_bookings_ordered(gc_id):
    rows = [b for b in state["group_bookings"].values()
            if b["class_id"] == gc_id and b["status"] == "WAITLISTED"]
    rows.sort(key=lambda x: (x.get("waitlist_position") or 99999))
    return rows


def _next_waitlist_position(gc_id):
    existing = _waitlisted_bookings_ordered(gc_id)
    return len(existing) + 1


def _renumber_waitlist(gc_id):
    """Renumber WAITLISTED rows to 1-based contiguous positions."""
    rows = [b for b in state["group_bookings"].values()
            if b["class_id"] == gc_id and b["status"] == "WAITLISTED"]
    rows.sort(key=lambda x: (x.get("waitlist_position") or 99999, x.get("waitlisted_at") or now()))
    for i, b in enumerate(rows, start=1):
        if b.get("waitlist_position") != i:
            b["waitlist_position"] = i
            bump(b)


def _consume_payment_for_booking(gc, booking):
    """Apply wallet debit OR card visit consumption for a booking that becomes CONFIRMED."""
    card_id = booking.get("card_id")
    if card_id:
        card = state["cards"].get(card_id)
        if not card:
            raise_err("ERR_NOT_FOUND", "card not found")
        # Family share rule
        if card["holder_member_id"] != booking["member_id"]:
            holder = state["members"].get(card["holder_member_id"])
            member = state["members"].get(booking["member_id"])
            fg_h = holder.get("family_group_id") if holder else None
            fg_m = member.get("family_group_id") if member else None
            if not fg_h or fg_h != fg_m:
                raise_err("ERR_FAMILY_SHARE_NOT_AUTHORIZED", "family group mismatch")
        # Visits remaining check
        from .card import visits_remaining, get_card_type
        vr = visits_remaining(card)
        if vr is not None and vr <= 0:
            raise_err("ERR_CARD_VISITS_EXHAUSTED", "card visits exhausted")
        # Don't increment yet — visits_consumed increments on check-in per §3.9
        # ("when a card_id was attached to the booking, increments that card's
        # visits_consumed by one"). But the scaffold state-machine ATTENDED side
        # effect also has Card.visits_consumed += 1. So we leave it for check-in.
    else:
        if gc.get("deduction_cents", 0) > 0:
            wallet_svc.debit(
                booking["member_id"], gc["deduction_cents"],
                service_type="GROUP_CLASS",
                ref_entity=f"GroupBooking:{booking['id']}",
            )


def book_group(member_id, class_id, card_id=None, accept_waitlist=None):
    gc = state["group_classes"].get(class_id)
    if not gc:
        raise_err("ERR_NOT_FOUND", "class not found")
    member = state["members"].get(member_id)
    if not member:
        raise_err("ERR_NOT_FOUND", "member not found")
    if gc["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "class not SCHEDULED")
    if card_id is not None and card_id not in state["cards"]:
        raise_err("ERR_NOT_FOUND", "card not found")
    if accept_waitlist is None:
        accept_waitlist = True
    confirmed_count = _confirmed_count(gc["id"])
    at_capacity = confirmed_count >= gc["capacity"]
    booking_id = new_id()
    if at_capacity:
        if accept_waitlist is False:
            raise_err("ERR_CAPACITY_REACHED", "class at capacity")
        booking = {
            "id": booking_id,
            "class_id": class_id,
            "member_id": member_id,
            "card_id": card_id,
            "status": "WAITLISTED",
            "waitlist_position": _next_waitlist_position(class_id),
            "waitlisted_at": now(),
        }
        stamp_create(booking)
        state["group_bookings"][booking_id] = booking
        return booking
    # Will be CONFIRMED — apply payment
    booking = {
        "id": booking_id,
        "class_id": class_id,
        "member_id": member_id,
        "card_id": card_id,
        "status": "CONFIRMED",
        "waitlist_position": None,
        "waitlisted_at": None,
    }
    stamp_create(booking)
    state["group_bookings"][booking_id] = booking
    try:
        _consume_payment_for_booking(gc, booking)
    except Exception:
        # Roll back booking
        del state["group_bookings"][booking_id]
        raise
    return booking


def _promote_waitlist_head(gc):
    """Promote one waitlist head if confirmed_count < capacity. Returns booking or None."""
    if _confirmed_count(gc["id"]) >= gc["capacity"]:
        return None
    wl = _waitlisted_bookings_ordered(gc["id"])
    if not wl:
        return None
    head = wl[0]
    # Apply payment first; if fails, leave head waitlisted? Spec doesn't say.
    # We'll attempt; on failure we propagate exception.
    head["status"] = "CONFIRMED"
    head["waitlist_position"] = None
    bump(head)
    _renumber_waitlist(gc["id"])
    try:
        _consume_payment_for_booking(gc, head)
    except Exception:
        # Revert
        head["status"] = "WAITLISTED"
        head["waitlist_position"] = 1
        bump(head)
        _renumber_waitlist(gc["id"])
        raise
    return head


def _promote_waitlist_until_full(gc):
    while True:
        b = None
        try:
            b = _promote_waitlist_head(gc)
        except Exception:
            break
        if b is None:
            break


def cancel_group_booking(booking):
    gc = state["group_classes"].get(booking["class_id"])
    if booking["status"] not in ("CONFIRMED", "WAITLISTED"):
        raise_err("ERR_INVALID_STATE", "booking not cancellable")
    if booking["status"] == "CONFIRMED":
        # 2h window
        if now() >= gc["starts_at"] - timedelta(hours=2):
            raise_err("ERR_CANCEL_WINDOW_EXPIRED", "less than 2h before start")
        booking["status"] = "CANCELED"
        bump(booking)
        # Refund deduction or card-visit return — PRD: cancel within window means
        # no penalty. We refund the deduction if it was paid.
        if booking.get("card_id"):
            # Visit was NOT yet consumed (consumed only on check-in per our model)
            pass
        elif gc and gc.get("deduction_cents", 0) > 0:
            wallet_svc.refund_credit(
                booking["member_id"], gc["deduction_cents"],
                ref_entity=f"GroupBooking:{booking['id']}",
            )
        # Promote waitlist head
        if gc:
            try:
                _promote_waitlist_head(gc)
            except Exception:
                pass
    else:
        # WAITLISTED cancel
        booking["status"] = "CANCELED"
        booking["waitlist_position"] = None
        bump(booking)
        if gc:
            _renumber_waitlist(gc["id"])
    return booking


def check_in(booking):
    if booking["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE", "booking not CONFIRMED")
    gc = state["group_classes"].get(booking["class_id"])
    if now() < gc["starts_at"]:
        raise_err("ERR_INVALID_STATE", "class has not started")
    booking["status"] = "ATTENDED"
    bump(booking)
    if booking.get("card_id"):
        card = state["cards"].get(booking["card_id"])
        if card:
            card["visits_consumed"] = card.get("visits_consumed", 0) + 1
            bump(card)
            # Check if visits exhausted -> EXPIRED
            from . import card as card_svc
            ct = state["card_types"].get(card["card_type_id"])
            if ct and ct.get("visit_quota", 0) > 0:
                if card["visits_consumed"] >= ct["visit_quota"]:
                    card_svc.expire_card(card)
    return booking


def cancel_class(gc):
    if gc["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "class not SCHEDULED")
    if now() >= gc["ends_at"]:
        raise_err("ERR_INVALID_STATE", "class already ended")
    # For each CONFIRMED booking: refund
    for b in list(state["group_bookings"].values()):
        if b["class_id"] != gc["id"]:
            continue
        if b["status"] == "CONFIRMED":
            if b.get("card_id"):
                # No card-visit was consumed (consumption is on check-in)
                pass
            elif gc.get("deduction_cents", 0) > 0:
                wallet_svc.refund_credit(
                    b["member_id"], gc["deduction_cents"],
                    ref_entity=f"GroupBooking:{b['id']}",
                )
            b["status"] = "CANCELED"
            bump(b)
        elif b["status"] == "WAITLISTED":
            b["status"] = "CANCELED"
            b["waitlist_position"] = None
            bump(b)
    gc["status"] = "CANCELED"
    bump(gc)
    return gc


def auto_complete_class_if_due(gc):
    if gc["status"] != "SCHEDULED":
        return
    if now() >= gc["ends_at"]:
        # Auto-no-show any still-CONFIRMED bookings
        for b in list(state["group_bookings"].values()):
            if b["class_id"] == gc["id"] and b["status"] == "CONFIRMED":
                b["status"] = "NO_SHOW"
                bump(b)
        gc["status"] = "COMPLETED"
        bump(gc)
