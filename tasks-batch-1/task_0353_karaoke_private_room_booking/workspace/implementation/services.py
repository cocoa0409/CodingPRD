"""Business logic: reservation lifecycle, cascades, payments, ops sweep.

Implements the PRD §3 workflows and the scaffold §1.2 state machines.
Mutations bump updated_at + version per PRD §2.4/§2.5 (including cascades).
"""

from datetime import timedelta

import calculations
import db
import helpers


# --- Common mutation helper --------------------------------------------------

def touch(record):
    """Bump updated_at and version by exactly 1 (PRD §2.4/§2.5)."""
    record["updated_at"] = db.now_iso()
    record["version"] = record["version"] + 1


# --- Lookups (return None if absent) -----------------------------------------

def get_group_package(reservation):
    gid = reservation.get("group_package_id")
    if gid is None:
        return None
    return db.group_packages.get(gid)


def get_room_type_for_reservation(reservation):
    return db.room_types.get(reservation["room_type_id"])


def get_venue(reservation):
    return db.venues.get(reservation["venue_id"])


# --- Reservation preview recompute (HELD/CONFIRMED forward-looking) ----------

def recompute_quote_preview(reservation):
    """Recompute quoted_room_subtotal_cents and deposit_cents (PRD §3.3)."""
    venue = get_venue(reservation)
    room_type = get_room_type_for_reservation(reservation)
    pkg = get_group_package(reservation)
    quoted = calculations.quoted_room_subtotal(reservation, venue, room_type, pkg)
    reservation["quoted_room_subtotal_cents"] = quoted
    deposit = calculations.round_half_up(
        calculations.Decimal(quoted) * calculations.Decimal(str(venue["deposit_pct"]))
    )
    reservation["deposit_cents"] = deposit


def recompute_fb_preview(reservation):
    """Recompute fb_consumed_cents and fb_shortfall_cents previews (PRD §3.8)."""
    room_type = get_room_type_for_reservation(reservation)
    pkg = get_group_package(reservation)
    reservation["fb_consumed_cents"] = calculations.fb_consumed_cents(reservation["id"])
    reservation["fb_shortfall_cents"] = calculations.fb_shortfall_cents(
        reservation, room_type, pkg
    )


# --- Payment ledger ----------------------------------------------------------

def append_payment(reservation_id, kind, amount_cents):
    """Append an immutable Payment ledger event (PRD §3.8)."""
    pid = db.new_id()
    payment = {
        "id": pid,
        "reservation_id": reservation_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "created_at": db.now_iso(),
    }
    db.payments[pid] = payment
    return payment


# --- Cascades ----------------------------------------------------------------

def cascade_pending_queue(reservation_id, target_status):
    """Force-terminate all PENDING queue entries to target_status, each bumping
    its own updated_at/version (PRD §2.5, §3.6)."""
    affected = [
        qe for qe in db.queue_entries.values()
        if qe["reservation_id"] == reservation_id and qe["status"] == "PENDING"
    ]
    for qe in affected:
        qe["status"] = target_status
        touch(qe)
    calculations.recompute_play_order(reservation_id)


def occupy_room(room):
    room["status"] = "OCCUPIED"
    touch(room)


def free_room(room):
    room["status"] = "AVAILABLE"
    touch(room)


# --- Ops sweep (PRD §3.7) ----------------------------------------------------

def run_ops_sweep(venue_id):
    """Expire stale HELDs and NO_SHOW overdue CONFIRMEDs for a venue."""
    venue = db.venues[venue_id]
    now = helpers.current_utc(venue_id)
    grace = timedelta(minutes=venue["grace_minutes"])

    # Process deterministically by created_at (the documented tie-break key).
    targets = [
        r for r in db.reservations.values() if r["venue_id"] == venue_id
    ]
    targets.sort(key=lambda r: (r["created_at"], r["id"]))

    for r in targets:
        slot_start = helpers.parse_stored_dt(r["slot_start_utc"])
        if r["status"] == "HELD" and now > slot_start:
            # HELD past slot_start, never confirmed -> EXPIRED.
            r["status"] = "EXPIRED"
            cascade_pending_queue(r["id"], "CANCELLED")
            touch(r)
        elif r["status"] == "CONFIRMED" and now > slot_start + grace:
            # CONFIRMED past grace, never checked in -> NO_SHOW.
            r["status"] = "NO_SHOW"
            append_payment(r["id"], "FORFEIT", r["deposit_cents"])
            customer = db.customers.get(r["customer_id"])
            if customer is not None:
                customer["no_show_strikes"] = customer["no_show_strikes"] + 1
                touch(customer)
            cascade_pending_queue(r["id"], "CANCELLED")
            touch(r)


# --- Overlap detection (PRD §3.3, §3.5) --------------------------------------

ACTIVE_STATUSES = {"HELD", "CONFIRMED", "CHECKED_IN"}


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start,end) overlap; adjacency (end==start) is allowed."""
    return a_start < b_end and b_start < a_end


def has_room_conflict(room_id, start_utc, end_utc, exclude_reservation_id=None):
    """True if [start,end) overlaps any active reservation on the room (PRD §3.3)."""
    for r in db.reservations.values():
        if r["room_id"] != room_id:
            continue
        if exclude_reservation_id is not None and r["id"] == exclude_reservation_id:
            continue
        if r["status"] not in ACTIVE_STATUSES:
            continue
        r_start = helpers.parse_stored_dt(r["slot_start_utc"])
        r_end = helpers.parse_stored_dt(r["slot_end_utc"])
        if intervals_overlap(start_utc, end_utc, r_start, r_end):
            return True
    return False
