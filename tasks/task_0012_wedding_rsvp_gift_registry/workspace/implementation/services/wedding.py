"""Wedding entity service: lookups, state transitions, archived/ownership guards."""
from __future__ import annotations

from typing import Optional

from flask import g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_WEDDING_ARCHIVED,
    ERR_INVALID_STATE,
)


# ---- lookup helpers --------------------------------------------------------

def get_wedding_or_404(wedding_id: str) -> dict:
    w = db.weddings.get(wedding_id)
    if w is None:
        raise APIError(ERR_NOT_FOUND, 404, f"Wedding {wedding_id} not found")
    return w


def get_meal_option_or_404(meal_option_id: str) -> dict:
    m = db.meal_options.get(meal_option_id)
    if m is None:
        raise APIError(ERR_NOT_FOUND, 404, f"MealOption {meal_option_id} not found")
    return m


def get_table_or_404(table_id: str) -> dict:
    t = db.tables.get(table_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, f"Table {table_id} not found")
    return t


def get_guest_or_404(guest_id: str) -> dict:
    gst = db.guests.get(guest_id)
    if gst is None:
        raise APIError(ERR_NOT_FOUND, 404, f"Guest {guest_id} not found")
    return gst


def get_plus_one_or_404(plus_one_id: str) -> dict:
    p = db.plus_ones.get(plus_one_id)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, f"PlusOne {plus_one_id} not found")
    return p


def get_seating_or_404(sa_id: str) -> dict:
    s = db.seating_assignments.get(sa_id)
    if s is None:
        raise APIError(ERR_NOT_FOUND, 404, f"SeatingAssignment {sa_id} not found")
    return s


def get_registry_item_or_404(ri_id: str) -> dict:
    r = db.registry_items.get(ri_id)
    if r is None:
        raise APIError(ERR_NOT_FOUND, 404, f"RegistryItem {ri_id} not found")
    return r


def get_purchase_or_404(p_id: str) -> dict:
    p = db.purchases.get(p_id)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, f"Purchase {p_id} not found")
    return p


def get_thank_you_or_404(t_id: str) -> dict:
    t = db.thank_you_notes.get(t_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, f"ThankYouNote {t_id} not found")
    return t


# ---- ownership / authorization helpers -------------------------------------

def assert_couple_owns(wedding: dict) -> None:
    """When the current caller is Couple, enforce that they own this wedding."""
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    if role == "Couple" and wedding.get("couple_user_id") != user_id:
        raise APIError(
            ERR_FORBIDDEN,
            403,
            "Couple X-User-ID does not match this wedding's couple_user_id",
        )


def assert_guest_self_binding(guest: dict) -> None:
    """When caller is GuestSelf, enforce X-User-ID == Guest.id and token match."""
    role = getattr(g, "user_role", None)
    if role != "GuestSelf":
        return
    user_id = getattr(g, "user_id", None)
    token = getattr(g, "invitation_token", None)
    if guest.get("id") != user_id:
        # The PRD treats this as an FK chain violation; per §2.1 the GuestSelf
        # token-bound identity must match the resource. We surface as forbidden.
        raise APIError(ERR_FORBIDDEN, 403, "GuestSelf identity does not match target Guest")
    if not token or token != guest.get("invitation_token"):
        # Missing or wrong invitation token is ERR_UNAUTHENTICATED per §2.1.
        from errors import ERR_UNAUTHENTICATED
        raise APIError(ERR_UNAUTHENTICATED, 401, "Invalid or missing X-Invitation-Token")


def assert_not_archived(wedding: dict) -> None:
    if wedding.get("status") == "ARCHIVED":
        raise APIError(ERR_WEDDING_ARCHIVED, 409, "Wedding is archived")


# ---- automatic close-on-deadline (PRD §3.1) --------------------------------

def maybe_auto_close_rsvp(wedding: dict) -> None:
    """Automatically transition RSVP_OPEN -> RSVP_CLOSED when the server clock
    has crossed rsvp_deadline_at. Triggered before mutations of the wedding
    or its children.
    """
    if wedding.get("status") != "RSVP_OPEN":
        return
    cur = db.parse_iso(db.get_current_utc())
    deadline = db.parse_iso(wedding.get("rsvp_deadline_at"))
    if cur is None or deadline is None:
        return
    if cur >= deadline:
        _do_close_rsvp(wedding)


def _do_close_rsvp(wedding: dict) -> None:
    """Apply RSVP_OPEN -> RSVP_CLOSED cascade. Used both for explicit close
    and the automatic deadline-crossing trigger.
    """
    wedding_id = wedding["id"]
    # All guests in INVITED auto-DECLINE; their plus-ones auto-DECLINE too.
    for g_row in list(db.guests.values()):
        if g_row.get("wedding_id") != wedding_id:
            continue
        if g_row.get("rsvp_status") == "INVITED":
            g_row["rsvp_status"] = "DECLINED"
            g_row["meal_option_id"] = None
            db.bump(g_row)
            # Cascade: every PlusOne under this guest auto-DECLINES.
            for po in list(db.plus_ones.values()):
                if po.get("guest_id") != g_row["id"]:
                    continue
                if po.get("rsvp_status") == "ATTENDING":
                    po["rsvp_status"] = "DECLINED"
                    po["meal_option_id"] = None
                    db.bump(po)
                    # Remove any seating assignment for the plus-one.
                    _remove_plus_one_seatings(po["id"])
    # Wedding posture flips.
    wedding["status"] = "RSVP_CLOSED"
    # Recompute seating_dirty against ATTENDING.
    wedding["seating_dirty"] = _compute_seating_dirty(wedding_id)
    db.bump(wedding)


def _remove_guest_seatings(guest_id: str) -> int:
    n = 0
    for sa_id, sa in list(db.seating_assignments.items()):
        if sa.get("assignee_type") == "GUEST" and sa.get("assignee_id") == guest_id:
            del db.seating_assignments[sa_id]
            n += 1
    return n


def _remove_plus_one_seatings(plus_one_id: str) -> int:
    n = 0
    for sa_id, sa in list(db.seating_assignments.items()):
        if sa.get("assignee_type") == "PLUS_ONE" and sa.get("assignee_id") == plus_one_id:
            del db.seating_assignments[sa_id]
            n += 1
    return n


def _compute_seating_dirty(wedding_id: str) -> bool:
    """seating_dirty is true when the current set of ATTENDING attendees does
    not exactly match the set of existing SeatingAssignment rows for this
    wedding. The flag is meaningful only after a finalize; we recompute it
    against the current ATTENDING set for the close-rsvp cascade.

    On a freshly-built wedding (no assignments yet, RSVP_CLOSED via the close
    cascade), seating_dirty stays false if no ATTENDING attendee is unseated.
    Empirically: if there are no SeatingAssignment rows AND no ATTENDING
    attendees -> not dirty; otherwise dirty unless every ATTENDING is exactly
    once in the assignment set.
    """
    attendees = set()
    for guest in db.guests.values():
        if guest.get("wedding_id") == wedding_id and guest.get("rsvp_status") == "ATTENDING":
            attendees.add(("GUEST", guest["id"]))
    for po in db.plus_ones.values():
        if po.get("wedding_id") == wedding_id and po.get("rsvp_status") == "ATTENDING":
            attendees.add(("PLUS_ONE", po["id"]))
    assigned = set()
    for sa in db.seating_assignments.values():
        if sa.get("wedding_id") == wedding_id:
            assigned.add((sa["assignee_type"], sa["assignee_id"]))
    # If there are no assignments and no ATTENDING attendees, clean.
    if not assigned and not attendees:
        return False
    # If the sets diverge in any direction, dirty.
    return assigned != attendees


def recompute_total_capacity(wedding_id: str) -> int:
    total = 0
    for t in db.tables.values():
        if t.get("wedding_id") == wedding_id:
            total += int(t.get("capacity", 0))
    return total
