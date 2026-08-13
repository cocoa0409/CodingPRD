"""Cascade services: suspension, ban, waitlist promotion, strikes, exposure journal.

All cascades run synchronously within the triggering request (immediate
consistency, PRD section 2.5). Every mutated entity gets its own updated_at
refresh and version bump.
"""

from datetime import timedelta

import db
from db import _parse_iso, _format_iso
from util import stamp_new_append_only, touch


# ---------------------------------------------------------------------------
# Exposure journal
# ---------------------------------------------------------------------------

def write_exposure(participant_id, build_id, study_id, event_type):
    rec = {
        "participant_id": participant_id,
        "build_id": build_id,
        "study_id": study_id,
        "event_type": event_type,
        "recorded_at": _format_iso(db.clock.now()),
    }
    stamp_new_append_only(rec)
    db.exposure_records[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Access key revocation helper (cascade-driven)
# ---------------------------------------------------------------------------

def revoke_key_cascade(key):
    """Revoke an ISSUED or REDEEMED key as part of a cascade."""
    key["status"] = "REVOKED"
    touch(key)
    build = db.builds.get(key["build_id"])
    if build is not None:
        build["keys_active_count"] = max(0, build.get("keys_active_count", 0) - 1)
        touch(build)
    write_exposure(key["participant_id"], key["build_id"],
                   build["study_id"] if build else None, "KEY_REVOKED")


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------

def promote_waitlist(session):
    """Promote the earliest-created eligible waitlisted booking on a session.

    Eligible: status == WAITLISTED and owning participant still ACTIVE.
    Ranking: created_at ASC (ties impossible: server-stamped distinct).
    """
    candidates = [
        b for b in db.bookings.values()
        if b["session_id"] == session["id"] and b["status"] == "WAITLISTED"
    ]
    eligible = []
    for b in candidates:
        p = db.participants.get(b["participant_id"])
        if p is not None and p["status"] == "ACTIVE":
            eligible.append(b)
    if not eligible:
        return
    eligible.sort(key=lambda b: (b["_created_sort"], b["_seq"]))
    winner = eligible[0]
    winner["status"] = "PROMOTED"
    touch(winner)
    session["seats_taken"] = session.get("seats_taken", 0) + 1
    touch(session)


def cancel_booking_cascade(booking, promote=True):
    """Cascade-driven cancellation of a booking in BOOKED / PROMOTED / WAITLISTED.

    When `promote` is False (session-cancel cascade), no promotion occurs.
    """
    prev_status = booking["status"]
    booking["status"] = "CANCELLED"
    touch(booking)
    if prev_status in ("BOOKED", "PROMOTED"):
        session = db.sessions.get(booking["session_id"])
        if session is not None:
            session["seats_taken"] = max(0, session.get("seats_taken", 0) - 1)
            touch(session)
            if promote:
                promote_waitlist(session)


# ---------------------------------------------------------------------------
# No-show strikes
# ---------------------------------------------------------------------------

STRIKE_LIMIT = 3
STRIKE_WINDOW_DAYS = 90


def recompute_strikes(participant):
    """Recompute no_show_strikes over the rolling 90-day window (inclusive)."""
    now = db.clock.now()
    window_start = now - timedelta(days=STRIKE_WINDOW_DAYS)
    count = 0
    for b in db.bookings.values():
        if b["participant_id"] != participant["id"]:
            continue
        if b["status"] != "NO_SHOW":
            continue
        recorded = b.get("no_show_recorded_at")
        if recorded is None:
            continue
        if _parse_iso(recorded) >= window_start:
            count += 1
    participant["no_show_strikes"] = count
    touch(participant)
    if participant["status"] == "ACTIVE" and count >= STRIKE_LIMIT:
        suspend_participant_cascade(participant)


# ---------------------------------------------------------------------------
# Participant suspension / ban cascades
# ---------------------------------------------------------------------------

def _cancel_participant_bookings(participant_id, statuses):
    """Cancel this participant's bookings in the given statuses, promoting per rule."""
    mine = [
        b for b in db.bookings.values()
        if b["participant_id"] == participant_id and b["status"] in statuses
    ]
    # Deterministic order: by created_at asc
    mine.sort(key=lambda b: (b["_created_sort"], b["_seq"]))
    for b in mine:
        cancel_booking_cascade(b, promote=True)


def suspend_participant_cascade(participant):
    """ACTIVE -> SUSPENDED with the full suspension cascade (PRD 3.1)."""
    participant["status"] = "SUSPENDED"
    touch(participant)
    # Bookings in BOOKED / PROMOTED cancel (with promotion); WAITLISTED cancel (no promotion)
    _cancel_participant_bookings(participant["id"], ("BOOKED", "PROMOTED"))
    _cancel_participant_bookings(participant["id"], ("WAITLISTED",))
    # Access keys in ISSUED are revoked
    for key in list(db.access_keys.values()):
        if key["participant_id"] == participant["id"] and key["status"] == "ISSUED":
            revoke_key_cascade(key)


def ban_participant_cascade(participant):
    """ACTIVE|SUSPENDED -> BANNED with the full ban cascade (PRD 3.1)."""
    participant["status"] = "BANNED"
    touch(participant)

    # 1. Every booking in BOOKED / PROMOTED / WAITLISTED is cancelled
    #    (freed seats promote per the booking-cancel rule).
    _cancel_participant_bookings(participant["id"], ("BOOKED", "PROMOTED"))
    _cancel_participant_bookings(participant["id"], ("WAITLISTED",))

    # 2. Every access key in ISSUED or REDEEMED is revoked.
    for key in list(db.access_keys.values()):
        if key["participant_id"] == participant["id"] and key["status"] in ("ISSUED", "REDEEMED"):
            revoke_key_cascade(key)

    # 3. Every NDA signature in PENDING or SIGNED is voided; any ENROLLED
    #    application whose signature was voided reverts to APPROVED.
    for sig in list(db.nda_signatures.values()):
        if sig["participant_id"] == participant["id"] and sig["status"] in ("PENDING", "SIGNED"):
            was_signed = sig["status"] == "SIGNED"
            sig["status"] = "VOIDED"
            touch(sig)
            if was_signed:
                app = db.applications.get(sig["application_id"])
                if app is not None and app["status"] == "ENROLLED":
                    app["status"] = "APPROVED"
                    touch(app)
                    study = db.studies.get(app["study_id"])
                    if study is not None:
                        study["enrolled_count"] = max(0, study.get("enrolled_count", 0) - 1)
                        touch(study)

    # 4. Incentive payouts: DRAFT / PENDING_APPROVAL / REJECTED -> VOID outright;
    #    APPROVED -> VOID releasing the committed budget.
    for payout in list(db.payouts.values()):
        if payout["participant_id"] != participant["id"]:
            continue
        if payout["status"] in ("DRAFT", "PENDING_APPROVAL", "REJECTED"):
            payout["status"] = "VOID"
            touch(payout)
        elif payout["status"] == "APPROVED":
            study = db.studies.get(payout["study_id"])
            final = payout.get("amount_final_cents") or 0
            if study is not None:
                study["budget_committed_cents"] = max(
                    0, study.get("budget_committed_cents", 0) - final)
                touch(study)
            payout["status"] = "VOID"
            touch(payout)
