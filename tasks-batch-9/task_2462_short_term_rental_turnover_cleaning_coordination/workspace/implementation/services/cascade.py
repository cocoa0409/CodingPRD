"""Declared cascades: revocation, voiding, holds and guest gates (PRD 2.10)."""

from db import db, now, ordered, touch
from services.pay import sync_cleaners

REVOCABLE_STATUSES = ("OFFERED", "ACCEPTED", "ACTIVE")


def _assignment_pay_lines(assignment_id):
    return [p for p in ordered(db.pay_lines.values())
            if p["assignment_id"] == assignment_id]


def revoke_assignment(assignment):
    assignment["status"] = "REVOKED"
    assignment["revoked_at"] = now()
    touch(assignment)


def void_provisional_pay_lines(assignment):
    """Voided lines keep their money fields readable (PRD 2.10)."""
    for pay_line in _assignment_pay_lines(assignment["id"]):
        if pay_line["status"] == "PROVISIONAL":
            pay_line["status"] = "VOIDED"
            touch(pay_line)


def supersede_outstanding_offer(turnover):
    """A fresh offer revokes the turnover's outstanding OFFERED assignment."""
    touched = []
    for assignment in ordered(db.assignments.values()):
        if assignment["turnover_id"] != turnover["id"]:
            continue
        if assignment["status"] != "OFFERED":
            continue
        revoke_assignment(assignment)
        # A mere offer never carried a pay line, so no ledger movement.
        touched.append(assignment["cleaner_id"])
    return touched


def void_turnover(turnover):
    """The outgoing-cancellation branch (PRD 3.10)."""
    turnover["status"] = "VOID"
    touch(turnover)
    affected = []
    for assignment in ordered(db.assignments.values()):
        if assignment["turnover_id"] != turnover["id"]:
            continue
        if assignment["status"] not in REVOCABLE_STATUSES:
            continue
        revoke_assignment(assignment)
        void_provisional_pay_lines(assignment)
        affected.append(assignment["cleaner_id"])
    for audit in ordered(db.quality_audits.values()):
        if audit["turnover_id"] == turnover["id"] and audit["status"] == "SAMPLED":
            audit["status"] = "VOIDED"
            touch(audit)
    sync_cleaners(affected)


def revoke_open_work(cleaner):
    """The suspend / offboard-from-active cascade (PRD 3.10)."""
    for assignment in ordered(db.assignments.values()):
        if assignment["cleaner_id"] != cleaner["id"]:
            continue
        if assignment["status"] not in ("OFFERED", "ACCEPTED"):
            continue
        revoke_assignment(assignment)
        turnover = db.turnovers.get(assignment["turnover_id"])
        if turnover is not None and turnover["status"] == "SCHEDULED":
            turnover["status"] = "PENDING_ASSIGNMENT"
            touch(turnover)
        void_provisional_pay_lines(assignment)


def holds_active_assignment(cleaner):
    for assignment in db.assignments.values():
        if assignment["cleaner_id"] == cleaner["id"] and assignment["status"] == "ACTIVE":
            return True
    return False


# --------------------------------------------------------------------------
# guest check-in gate
# --------------------------------------------------------------------------

def block_incoming_gate(turnover):
    booking_id = turnover.get("incoming_booking_id")
    if not booking_id:
        return
    booking = db.bookings.get(booking_id)
    if booking is None or booking["checkin_gate"] != "OPEN":
        return
    booking["checkin_gate"] = "BLOCKED"
    booking["guest_notice_code"] = "CHECKIN_DELAYED"
    touch(booking)


def release_incoming_gate(turnover):
    booking_id = turnover.get("incoming_booking_id")
    if not booking_id:
        return
    booking = db.bookings.get(booking_id)
    if booking is None or booking["checkin_gate"] != "BLOCKED":
        return
    booking["checkin_gate"] = "RELEASED"
    booking["guest_notice_code"] = "NONE"
    touch(booking)
