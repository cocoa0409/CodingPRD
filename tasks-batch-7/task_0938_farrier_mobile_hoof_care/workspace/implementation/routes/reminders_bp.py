"""Reminders: delivery, suppression and acknowledgement (PRD 3.8)."""

from flask import Blueprint

from core.auth import authenticate
from core.constants import DELIVERY_OUTCOMES
from core.errors import ApiError
from core.store import db
from core.timeutil import clock
from core.validate import bad, body, enum
from domain.gates import ELIGIBLE, gate5_appointment
from domain.lookup import guard_reminder, must
from domain.scheduling import reminder_is_suppressed

from ._common import listing, single

bp = Blueprint("reminders", __name__)

READ_ROLES = ("PlatformAdmin", "Dispatcher", "ClientUser")


@bp.get("/reminders")
def list_reminders():
    return listing(
        "reminders", {"appointment_id": "appointment_id", "status": "status"}, READ_ROLES
    )


@bp.get("/reminders/<reminder_id>")
def read_reminder(reminder_id):
    authenticate(READ_ROLES)
    reminder = must("reminders", reminder_id)
    guard_reminder(reminder)
    return single(reminder)


@bp.post("/reminders/<reminder_id>/send")
def send_reminder(reminder_id):
    authenticate(("Dispatcher",))
    reminder = must("reminders", reminder_id)
    data = body()
    outcome = data.get("delivery_outcome")
    if not isinstance(outcome, str) or not outcome:
        bad("Field delivery_outcome is required.")
    enum(outcome, DELIVERY_OUTCOMES, "delivery_outcome")

    appointment = db.get("appointments", reminder["appointment_id"])
    # Adjudication of friction 11: the GATE stays authoritative.  An ineligible
    # appointment status reports ERR_APPOINTMENT_NOT_ELIGIBLE at rung 33, and
    # ERR_REMINDER_SUPPRESSED (rung 48) is reserved for the recently-sent
    # sibling alone.  The ladder is explicit that the lowest-numbered rung wins,
    # and both codes stay reachable under this reading.
    gate5_appointment(appointment, ELIGIBLE["reminder_send"])
    if reminder["status"] not in ("PENDING", "FAILED"):
        raise ApiError("ERR_INVALID_STATE")

    if outcome == "DELIVERED":
        if reminder_is_suppressed(reminder):
            raise ApiError("ERR_REMINDER_SUPPRESSED")
        reminder["status"] = "SENT"
        reminder["sent_on"] = clock.today_iso
    else:
        reminder["status"] = "FAILED"
        reminder["sent_on"] = None
    db.touch(reminder)
    return single(reminder)


@bp.post("/reminders/<reminder_id>/acknowledge")
def acknowledge_reminder(reminder_id):
    authenticate(("ClientUser",))
    reminder = must("reminders", reminder_id)
    guard_reminder(reminder)
    appointment = db.get("appointments", reminder["appointment_id"])
    gate5_appointment(appointment, ELIGIBLE["reminder_acknowledge"])
    if reminder["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE")
    reminder["status"] = "ACKNOWLEDGED"
    db.touch(reminder)
    if appointment["status"] == "SCHEDULED":
        appointment["status"] = "CONFIRMED"
        db.touch(appointment)
    return single(reminder)
