"""Reconciliation of derived/computed fields and cross-entity helpers.

A computed-field reconciliation is itself a mutation (PRD §2.4/§2.10): when a
field's reserved_headcount or an arena's pool/ledger figures change, that
resource's updated_at refreshes and its version increments. We funnel every
such recompute through db.touch so the discipline is uniform.
"""

import db
from calc import REFEREE_THRESHOLD, ADULT_AGE
from timeutil import parse_iso

LIVE_BOOKING_STATES = {"HELD", "CONFIRMED", "CHECKED_IN"}


# --- Arena equipment pool + deposit ledger -----------------------------------

def reconcile_arena(arena):
    """Recompute arena available counts and deposit ledger from live state.

    Bumps the arena's version (this is a mutation of the arena resource).
    """
    marker_avail = 0
    vest_avail = 0
    for unit in db.equipment_units.values():
        if unit["arena_id"] != arena["id"]:
            continue
        if unit["status"] == "AVAILABLE":
            if unit["unit_type"] == "MARKER":
                marker_avail += 1
            else:
                vest_avail += 1

    held = 0
    for rental in db.rentals.values():
        if rental["arena_id"] != arena["id"]:
            continue
        if rental["status"] in ("HELD", "CHECKED_OUT"):
            held += rental["deposit_hold_cents"]

    changed = (
        arena["marker_available_count"] != marker_avail
        or arena["vest_available_count"] != vest_avail
        or arena["deposit_held_cents"] != held
    )
    arena["marker_available_count"] = marker_avail
    arena["vest_available_count"] = vest_avail
    arena["deposit_held_cents"] = held
    if changed:
        db.touch(arena)


def add_refund(arena, refund_cents, forfeit_cents):
    """Accumulate settled refund/forfeit onto the arena ledger (a mutation)."""
    if refund_cents == 0 and forfeit_cents == 0:
        return
    arena["deposit_refunded_cents"] += refund_cents
    arena["deposit_forfeited_cents"] += forfeit_cents
    db.touch(arena)


# --- Field reserved headcount ------------------------------------------------

def reconcile_field_headcount(field):
    """Recompute reserved_headcount: sum of party_size over live bookings on
    this field whose window overlaps the arena's current time (PRD §3.1).

    This sets the derived value but does NOT itself bump the field version; the
    caller decides when a field version increment is owed (e.g. confirm bumps it
    exactly once per §3.3). reserved_headcount is recomputed as a read-through
    derived figure on every booking transition.
    """
    arena = db.arenas.get(field["arena_id"])
    now = parse_iso(arena["current_utc"]) if arena else None
    total = 0
    for booking in db.bookings.values():
        if booking["field_id"] != field["id"]:
            continue
        if booking["status"] not in LIVE_BOOKING_STATES:
            continue
        if now is not None:
            start = parse_iso(booking["window_start"])
            end = parse_iso(booking["window_end"])
            if start is not None and end is not None:
                # half-open [start, end)
                if not (start <= now < end):
                    continue
            else:
                continue
        total += booking["party_size"]
    field["reserved_headcount"] = total


# --- Booking computed flags --------------------------------------------------

def recompute_booking_flags(booking):
    """Recompute minors_present and referee_required (PRD §3.6)."""
    field = db.fields.get(booking["field_id"])
    minors_present = False
    for w in db.waiver_profiles.values():
        if w["booking_id"] != booking["id"]:
            continue
        if w["status"] == "SIGNED" and w["is_minor"]:
            minors_present = True
            break
    referee_required = (
        booking["party_size"] >= REFEREE_THRESHOLD
        or minors_present
        or (field is not None and field["game_mode"] == "PAINTBALL")
    )
    changed = (
        booking["minors_present"] != minors_present
        or booking["referee_required"] != referee_required
    )
    booking["minors_present"] = minors_present
    booking["referee_required"] = referee_required
    if changed:
        db.touch(booking)


def compute_age(dob_iso, ref_iso):
    """Full years between dob and ref; returns (age_years, is_minor)."""
    from timeutil import full_years_between
    dob = parse_iso(dob_iso)
    ref = parse_iso(ref_iso)
    if dob is None or ref is None:
        return 0, False
    age = full_years_between(dob, ref)
    return age, age < ADULT_AGE


# --- Overlap helpers ---------------------------------------------------------

def windows_overlap_half_open(a_start, a_end, b_start, b_end):
    """Two half-open intervals [s,e) overlap iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end
