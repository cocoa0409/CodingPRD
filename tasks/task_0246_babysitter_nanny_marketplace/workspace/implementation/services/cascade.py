"""Cross-entity cascade helpers (PRD §2.9, §3.2, §3.5).

Each secondary entity touched by a cascade gets its own updated_at refresh
and version bump (PRD §2.9).
"""

from db import store
from services.common import touch
from services.ledger import recompute_escrow_available


def cancel_confirmed_booking_escrow_release(booking, family):
    """Exact reversal of a CONFIRMED booking's escrow reservation."""
    family["escrow_reserved_cents"] -= booking["estimated_pay_cents"]
    if family["escrow_reserved_cents"] < 0:
        family["escrow_reserved_cents"] = 0
    recompute_escrow_available(family)
    touch(family)


def cancel_scheduled_sessions(booking):
    """Cascade every still-SCHEDULED child session to CANCELLED."""
    for s in store.sessions.values():
        if s["booking_id"] == booking["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)


def flag_caregiver_cascade(caregiver):
    """FLAGGED adjudication cascade (PRD §3.2):
      - caregiver.availability_status := SUSPENDED
      - every booking of this caregiver in {OFFERED, COUNTERED, CONFIRMED}
        -> CANCELLED, each CONFIRMED one releasing its family escrow.
    """
    caregiver["availability_status"] = "SUSPENDED"
    touch(caregiver)

    for bk in store.bookings.values():
        if bk["caregiver_id"] != caregiver["id"]:
            continue
        if bk["status"] not in {"OFFERED", "COUNTERED", "CONFIRMED"}:
            continue
        was_confirmed = bk["status"] == "CONFIRMED"
        bk["status"] = "CANCELLED"
        touch(bk)
        if was_confirmed:
            family = store.families.get(bk["family_id"])
            if family is not None:
                cancel_confirmed_booking_escrow_release(bk, family)
            # Reopen the posting and cancel scheduled sessions, mirroring a
            # normal cancel of a confirmed booking.
            cancel_scheduled_sessions(bk)
            posting = store.job_postings.get(bk["job_posting_id"])
            if posting is not None:
                posting["status"] = "OPEN"
                touch(posting)
