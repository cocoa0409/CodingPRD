"""Cross-entity side effects: waitlist promotion, cascades, the time sweep."""
from datetime import timedelta

import db
import constants
from models import touch, waitlist_ordered, booked_count
from services import calc


# --------------------------------------------------------------------------
# Eligibility (PRD §3.5 waitlist promotion eligibility).
# --------------------------------------------------------------------------

def member_bookable(member):
    """ACTIVE membership and dues not SUSPENDED (PRD §3.5 / §2.8)."""
    return member["membership_status"] == "ACTIVE" and member["dues_status"] != "SUSPENDED"


def waitlist_eligible(member):
    """Eligible to be promoted: ACTIVE, not SUSPENDED, >=1 class credit."""
    return member_bookable(member) and member["class_credits_remaining"] >= 1


# --------------------------------------------------------------------------
# Waitlist promotion (PRD §3.5).
# --------------------------------------------------------------------------

def promote_waitlist(session):
    """Promote the lowest-position eligible WAITLISTED booking into a freed seat.

    Runs after a BOOKED seat frees. Skips ineligible waitlisted bookings.
    Returns True if a promotion occurred. Bumps the promoted booking's version
    and the session's version.
    """
    # Only promote if there is actually a free seat now.
    if booked_count(session["id"]) >= session["capacity"]:
        return False
    for b in waitlist_ordered(session["id"]):
        member = db.store.members.get(b["member_id"])
        if member is None or not waitlist_eligible(member):
            continue
        # Promote this booking.
        b["status"] = "BOOKED"
        b["booked_at"] = db.now()
        b["credit_charged"] = True
        member["class_credits_remaining"] -= 1
        touch(b)
        touch(member)
        touch(session)
        return True
    return False


# --------------------------------------------------------------------------
# Booking cancel core (used by direct cancel and cascades) (PRD §3.5).
# --------------------------------------------------------------------------

def cancel_booking_internal(booking, run_promotion=True):
    """Set a non-terminal booking to CANCELLED with credit-restore + promotion.

    Returns nothing; mutates in place. Bumps booking.version and session.version.
    """
    was_booked = booking["status"] == "BOOKED"
    booking["status"] = "CANCELLED"
    if booking["credit_charged"]:
        member = db.store.members.get(booking["member_id"])
        if member is not None:
            member["class_credits_remaining"] += 1
            touch(member)
        booking["credit_charged"] = False
    touch(booking)
    session = db.store.class_sessions.get(booking["session_id"])
    if session is not None:
        touch(session)
        if was_booked and run_promotion:
            promote_waitlist(session)


# --------------------------------------------------------------------------
# Member freeze cascade (PRD §3.3).
# --------------------------------------------------------------------------

def freeze_cascade(member):
    """Cancel future-dated BOOKED bookings on SCHEDULED sessions starting after now.

    Each cancellation runs waitlist promotion + restores a credit if charged.
    """
    now = db.now()
    targets = []
    for b in db.store.bookings.values():
        if b["member_id"] != member["id"]:
            continue
        if b["status"] != "BOOKED":
            continue
        session = db.store.class_sessions.get(b["session_id"])
        if session is None or session["status"] != "SCHEDULED":
            continue
        if session["starts_at"] > now:
            targets.append(b)
    # Stable order by created_at for determinism.
    targets.sort(key=lambda b: (b["created_at"], b["_seq"]))
    for b in targets:
        cancel_booking_internal(b, run_promotion=True)


# --------------------------------------------------------------------------
# Member cancel cascade (PRD §3.7).
# --------------------------------------------------------------------------

def cancel_member_cascade(member):
    """Cancel future BOOKED/WAITLISTED bookings; void ACTIVE PT packages."""
    now = db.now()
    # Bookings: future-dated BOOKED or WAITLISTED on SCHEDULED sessions.
    booking_targets = []
    for b in db.store.bookings.values():
        if b["member_id"] != member["id"]:
            continue
        if b["status"] not in ("BOOKED", "WAITLISTED"):
            continue
        session = db.store.class_sessions.get(b["session_id"])
        if session is None or session["status"] != "SCHEDULED":
            continue
        if session["starts_at"] > now:
            booking_targets.append(b)
    booking_targets.sort(key=lambda b: (b["created_at"], b["_seq"]))
    for b in booking_targets:
        cancel_booking_internal(b, run_promotion=True)

    # PT packages: ACTIVE packages -> VOID; their SCHEDULED sessions -> CANCELLED
    # (deduction reinstated on the session, but sessions_remaining frozen at the
    # voided value because the package is now VOID).
    for pkg in db.store.pt_packages.values():
        if pkg["member_id"] != member["id"]:
            continue
        if pkg["status"] != "ACTIVE":
            continue
        for s in db.store.pt_sessions.values():
            if s["package_id"] != pkg["id"]:
                continue
            if s["status"] == "SCHEDULED":
                s["status"] = "CANCELLED"
                s["deducted"] = False
                touch(s)
        pkg["status"] = "VOID"
        touch(pkg)


# --------------------------------------------------------------------------
# The time-driven sweep (PRD §3.4, §3.10; SCAFFOLD /_clock/advance_dues).
# --------------------------------------------------------------------------

def oldest_overdue_due_date(member_id, clock):
    """Due date of the oldest OPEN invoice whose due_date is strictly before clock."""
    overdue = [i for i in db.store.dues_invoices.values()
               if i["member_id"] == member_id and i["status"] == "OPEN" and i["due_date"] < clock]
    if not overdue:
        return None
    overdue.sort(key=lambda i: (i["due_date"], i["_seq"]))
    return overdue[0]["due_date"]


def run_sweep():
    clock = db.now()

    # 1. Delinquency ladder.
    for member in db.store.members.values():
        if member["dues_status"] == "CURRENT":
            due = oldest_overdue_due_date(member["id"], clock)
            if due is not None:
                member["dues_status"] = "PAST_DUE"
                member["past_due_since"] = due
                touch(member)
        if member["past_due_since"] is not None and member["dues_status"] != "CURRENT":
            elapsed = calc.whole_days(member["past_due_since"], clock)
            target = calc.delinquency_status(
                elapsed, constants.DELINQUENT_AFTER_DAYS, constants.SUSPENDED_AFTER_DAYS)
            if target != member["dues_status"]:
                member["dues_status"] = target
                touch(member)

    # 2. Contract progression.
    for member in db.store.members.values():
        if member["contract_status"] == "IN_COOLING_OFF" and clock > member["cooling_off_ends_at"]:
            member["contract_status"] = "IN_TERM"
            touch(member)
        if member["contract_status"] == "IN_TERM" and clock > member["term_ends_at"]:
            member["contract_status"] = "FULFILLED"
            touch(member)

    # 3. Guest-pass expiry.
    for gp in db.store.guest_passes.values():
        if gp["status"] == "ISSUED" and clock > gp["expires_at"]:
            gp["status"] = "EXPIRED"
            touch(gp)


def add_months(dt, months):
    """Advance dt by a number of calendar months, clamping the day."""
    import calendar
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
