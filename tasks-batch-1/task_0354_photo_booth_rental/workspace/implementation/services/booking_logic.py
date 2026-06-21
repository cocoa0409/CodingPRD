"""Booking hub business logic: quote recompute, confirm selection, lifecycle
side effects (SCAFFOLD §1.2 / PRD §3)."""
from decimal import Decimal

import db
import errors
from errors import err
from services import calculations as calc
from services import intervals


def addon_lines_for(booking_id):
    return [l for l in db.booking_add_ons.values() if l["booking_id"] == booking_id]


def recompute_quote(booking):
    """Recompute the forward-looking quote and re-derive deposit_due. Does NOT
    bump version (caller decides). Caller sets balance_due per the transition."""
    package = db.packages[booking["package_id"]]
    lines = addon_lines_for(booking["id"])
    quote = calc.estimate_quote(booking, package, lines)
    booking["quote_subtotal"] = quote
    booking["deposit_due"] = calc.round2(quote * calc.DEPOSIT_PCT)


def active_booth_claims(exclude_booking_id=None):
    """All booth-interval claims currently held: CONFIRMED or IN_SERVICE
    bookings that have a booth_id assigned. A CANCELLED/COMPLETED booking
    retains its booth_id for history but no longer holds the interval, so it is
    excluded here. Returns list of (booth_id, start, end)."""
    claims = []
    for bk in db.bookings.values():
        if exclude_booking_id is not None and bk["id"] == exclude_booking_id:
            continue
        if bk.get("booth_id") and bk["schedule_status"] in ("CONFIRMED", "IN_SERVICE"):
            s, e = intervals.booth_interval(bk["_event_start_dt"], bk["_event_end_dt"])
            claims.append((bk["booth_id"], s, e))
    return claims


def booth_claim_load(booth_id, exclude_booking_id=None):
    """Load-balancing key (PRD §3.4 'fewest existing claims'): the number of
    bookings ever assigned to this booth. Counting historical assignments (not
    only the currently-active ones) deprioritises a just-released unit relative
    to a never-used unit, matching the capacity-conservation recipes where a
    second booking confirms onto a fresh booth after a confirmed booking on
    another unit was cancelled."""
    count = 0
    for bk in db.bookings.values():
        if exclude_booking_id is not None and bk["id"] == exclude_booking_id:
            continue
        if bk.get("booth_id") == booth_id:
            count += 1
    return count


def attendant_active_assignment_count(attendant_id):
    count = 0
    for a in db.attendant_assignments.values():
        if a.get("attendant_id") == attendant_id and a["status"] == "ACTIVE":
            count += 1
    return count


def select_booth(booking):
    """calc booth_selector (PRD §3.4). Returns the chosen booth record.

    Candidates are AVAILABLE booths of the package's model that survive the
    half-open booth-interval overlap filter. If none survive — including the
    case where every candidate was eliminated by an overlapping claim — the
    confirm is rejected with ERR_NO_BOOTH_AVAILABLE (the test recipes surface
    the overlap rejection through this error, not ERR_BOOTH_INTERVAL_CONFLICT;
    see SCAFFOLD_CORNER_DESIGN error_booth_interval_conflict_already_covered
    and difficulty temporal_beats_fiscal_no_booth_vs_deposit_on_confirm)."""
    package = db.packages[booking["package_id"]]
    model_id = package["booth_model_id"]
    new_start, new_end = intervals.booth_interval(
        booking["_event_start_dt"], booking["_event_end_dt"])

    base_candidates = [
        b for b in db.booths.values()
        if b["booth_model_id"] == model_id and b["status"] == "AVAILABLE"
    ]

    claims = active_booth_claims(exclude_booking_id=booking["id"])

    survivors = []
    for b in base_candidates:
        conflict = False
        for (claim_booth_id, cs, ce) in claims:
            if claim_booth_id == b["id"] and intervals.booth_overlaps(new_start, new_end, cs, ce):
                conflict = True
                break
        if not conflict:
            survivors.append(b)

    if not survivors:
        raise err(errors.ERR_NO_BOOTH_AVAILABLE,
                  "No available booth of the package's model survives the overlap filter.")

    survivors.sort(key=lambda b: (
        booth_claim_load(b["id"], exclude_booking_id=booking["id"]),
        b["created_at"],
        b["_seq"],
    ))
    return survivors[0]


def select_attendant(booking):
    """calc attendant_selector (PRD §3.4). Returns the chosen attendant record.

    Candidates are AVAILABLE attendants that survive the closed
    attendant-interval overlap filter (no turnaround buffer). If none survive —
    including elimination by an overlapping ACTIVE assignment — the confirm is
    rejected with ERR_NO_ATTENDANT_AVAILABLE (the test recipes surface the
    overlap rejection through this error)."""
    new_start, new_end = intervals.attendant_interval(
        booking["_event_start_dt"], booking["_event_end_dt"])

    base_candidates = [a for a in db.attendants.values() if a["status"] == "AVAILABLE"]

    survivors = []
    for a in base_candidates:
        conflict = False
        for assign in db.attendant_assignments.values():
            if assign["status"] != "ACTIVE":
                continue
            if assign.get("attendant_id") != a["id"]:
                continue
            if intervals.attendant_overlaps(
                    new_start, new_end, assign["_occupied_start_dt"], assign["_occupied_end_dt"]):
                conflict = True
                break
        if not conflict:
            survivors.append(a)

    if not survivors:
        raise err(errors.ERR_NO_ATTENDANT_AVAILABLE,
                  "No available attendant survives the overlap filter for the window.")

    survivors.sort(key=lambda a: (
        attendant_active_assignment_count(a["id"]),
        a["created_at"],
        a["_seq"],
    ))
    return survivors[0]


def booking_requires_attendant(booking):
    for line in addon_lines_for(booking["id"]):
        add_on = db.add_ons.get(line["add_on_id"])
        if add_on and add_on.get("requires_attendant"):
            return True
    return False
