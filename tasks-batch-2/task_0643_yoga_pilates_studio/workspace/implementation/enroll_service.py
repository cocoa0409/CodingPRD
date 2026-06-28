"""Workshop/enrollment count + posture helpers and waitlist promotion (PRD §3.9)."""
from db import store
from models import touch


def recompute_workshop_count(workshop):
    wid = workshop["id"]
    count = sum(1 for e in store.enrollments.values()
                if e["workshop_id"] == wid and e["status"] == "CONFIRMED")
    workshop["confirmed_seat_count"] = count


def recompute_workshop_posture(workshop):
    """OPEN <-> FULL based on confirmed_seat_count vs seat_capacity."""
    if workshop["status"] not in ("OPEN", "FULL"):
        return
    recompute_workshop_count(workshop)
    if workshop["confirmed_seat_count"] >= workshop["seat_capacity"]:
        if workshop["status"] != "FULL":
            workshop["status"] = "FULL"
            touch(workshop)
    else:
        if workshop["status"] == "FULL":
            workshop["status"] = "OPEN"
            touch(workshop)


def capture_deposit(enrollment, workshop):
    enrollment["deposit_paid_cents"] = workshop["deposit_cents"]
    enrollment["balance_due_cents"] = workshop["price_cents"] - workshop["deposit_cents"]


def promote_earliest_waitlisted(workshop):
    """Promote the earliest-created WAITLISTED enrollment to CONFIRMED if a seat
    is confirmable. Captures its deposit and bumps confirmed_seat_count.

    Returns the promoted enrollment or None.
    """
    recompute_workshop_count(workshop)
    if workshop["confirmed_seat_count"] >= workshop["seat_capacity"]:
        return None
    waitlisted = [e for e in store.enrollments.values()
                  if e["workshop_id"] == workshop["id"] and e["status"] == "WAITLISTED"]
    if not waitlisted:
        return None
    waitlisted.sort(key=lambda e: e["_seq"])  # earliest created
    promote = waitlisted[0]
    promote["status"] = "CONFIRMED"
    capture_deposit(promote, workshop)
    touch(promote)
    recompute_workshop_count(workshop)
    return promote
