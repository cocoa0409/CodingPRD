"""State-machine transitions and cascades (scaffold §1.2, PRD §3.5-§3.10).

Occupancy "holds" and "windows" are tracked implicitly: a seat/room is occupied
for a window exactly while a non-terminal reservation (or active visitor pass)
references it. Overlap and neighborhood-capacity checks query live state, so
"free the window" simply means moving the reservation to a terminal occupancy
state. Neighborhood occupancy is recomputed live; we still touch the neighborhood
on retire/seat changes to keep updated_at/version consistent (PRD §2.8).
"""
from __future__ import annotations

from typing import Dict, Optional

import db
from services import calculations as calc
from services.common import stamp_new, touch


# ---------------------------------------------------------------------------
# Strike ledger: append a NoShowEvent and reconcile the employee (PRD §3.6).
# ---------------------------------------------------------------------------

def append_no_show_event(employee: Dict, reservation_id: str, kind: str) -> Dict:
    delta = calc.STRIKE_WEIGHT if kind == "NO_SHOW" else -calc.GOOD_CREDIT
    ev = {
        "employee_id": employee["id"],
        "reservation_id": reservation_id,
        "kind": kind,
        "delta": delta,
    }
    stamp_new(ev, with_version=False)  # immutable audit row
    db.no_show_events[ev["id"]] = ev
    reconcile_employee(employee)
    return ev


def reconcile_employee(employee: Dict) -> None:
    """Recompute strike_score + booking_privilege; counts as a mutation."""
    score = calc.compute_strike_score(employee)
    privilege = calc.derive_privilege(score)
    employee["strike_score"] = score
    employee["booking_privilege"] = privilege
    touch(employee)


# ---------------------------------------------------------------------------
# Provisional chargeback reconciliation on a reservation (PRD §3.5).
# ---------------------------------------------------------------------------

def reconcile_provisional(reservation: Dict) -> None:
    reservation["provisional_chargeback_cents"] = calc.compute_provisional(reservation["id"])
    touch(reservation)


# ---------------------------------------------------------------------------
# Void cascade shared by cancel and no-show release (PRD §3.8).
# ---------------------------------------------------------------------------

def void_cascade(reservation: Dict) -> None:
    """Move REQUESTED/APPROVED amenity lines to CANCELLED; set billing VOID;
    zero provisional. Each cancelled line is its own mutation."""
    for a in db.amenity_requests.values():
        if a["reservation_id"] != reservation["id"]:
            continue
        if a["line_status"] in ("REQUESTED", "APPROVED"):
            a["line_status"] = "CANCELLED"
            touch(a)
    reservation["billing_status"] = "VOID"
    reservation["provisional_chargeback_cents"] = 0
    # touch happens in the caller's final touch of the reservation


# ---------------------------------------------------------------------------
# Reservation occupancy transitions.
# ---------------------------------------------------------------------------

def reservation_check_in(reservation: Dict, employee: Dict, clock_minute: int) -> None:
    """BOOKED -> CHECKED_IN. Caller has already validated preconditions."""
    reservation["occupancy_status"] = "CHECKED_IN"
    reservation["occupied_minutes"] = reservation["end_minute"] - reservation["start_minute"]
    touch(reservation)

    within_grace = clock_minute <= reservation["checkin_deadline_minute"]
    ci = {
        "reservation_id": reservation["id"],
        "checked_in_at_minute": clock_minute,
        "within_grace": within_grace,
    }
    stamp_new(ci, with_version=False)  # immutable audit row
    db.checkins[ci["id"]] = ci

    append_no_show_event(employee, reservation["id"], "GOOD_CHECKIN")


def reservation_complete(reservation: Dict) -> None:
    """CHECKED_IN -> COMPLETED. Freeze final chargeback if PROVISIONAL."""
    reservation["occupancy_status"] = "COMPLETED"
    reservation["occupied_minutes"] = reservation["end_minute"] - reservation["start_minute"]
    if reservation["billing_status"] == "PROVISIONAL":
        reservation["billing_status"] = "FINALIZED"
        reservation["final_chargeback_cents"] = calc.compute_final(reservation["id"])
    touch(reservation)


def reservation_cancel(reservation: Dict) -> None:
    """BOOKED|CHECKED_IN -> CANCELLED. Void cascade; reset occupied_minutes if
    cancelling from CHECKED_IN. No strike."""
    from_checked_in = reservation["occupancy_status"] == "CHECKED_IN"
    reservation["occupancy_status"] = "CANCELLED"
    if from_checked_in:
        reservation["occupied_minutes"] = 0
    void_cascade(reservation)
    touch(reservation)


def reservation_release(reservation: Dict, employee: Dict) -> None:
    """BOOKED -> NO_SHOW_RELEASED. Strike +10; void cascade. Depth-3 cascade."""
    reservation["occupancy_status"] = "NO_SHOW_RELEASED"
    void_cascade(reservation)
    touch(reservation)
    append_no_show_event(employee, reservation["id"], "NO_SHOW")
