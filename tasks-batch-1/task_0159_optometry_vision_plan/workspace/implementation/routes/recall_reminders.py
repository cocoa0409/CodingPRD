"""RecallReminder lifecycle: schedule, get, list, send, cancel."""
from flask import Blueprint, request

import errors
import helpers
import response
import serialize
from db import db, new_id, stamp_create, touch
from middleware import require_roles

bp = Blueprint("recall_reminders", __name__)

CHANNELS = {"EMAIL", "SMS", "MAIL"}


@bp.post("/recall-reminders")
@require_roles("FrontDesk")
def create_reminder():
    body = helpers.get_json_body()
    patient_id = helpers.require_str(body, "patient_id")

    # body FK existence (priority 4)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise errors.reference_not_found("patient_id references no Patient")

    channel = helpers.require_enum(body, "channel", CHANNELS)

    # due_date copied from Patient.recall_due_date at generation time
    due_date = serialize._recall_due_date(patient)

    record = {
        "id": new_id(),
        "patient_id": patient_id,
        "due_date": due_date,
        "channel": channel,
        "status": "SCHEDULED",
    }
    stamp_create(record)
    db.recall_reminders[record["id"]] = record
    return response.object_response(serialize.recall_reminder(record), 201)


@bp.get("/recall-reminders/<reminder_id>")
@require_roles("FrontDesk")
def get_reminder(reminder_id):
    record = db.recall_reminders.get(reminder_id)
    if record is None:
        raise errors.not_found("RecallReminder not found")
    return response.object_response(serialize.recall_reminder(record), 200)


@bp.get("/recall-reminders")
@require_roles("FrontDesk")
def list_reminders():
    limit, offset = helpers.parse_pagination()
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    records = list(db.recall_reminders.values())
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.recall_reminder(r) for r in page], limit, offset, total, 200)


@bp.post("/recall-reminders/<reminder_id>/send")
@require_roles("FrontDesk")
def send_reminder(reminder_id):
    record = db.recall_reminders.get(reminder_id)
    if record is None:
        raise errors.not_found("RecallReminder not found")
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Reminder must be SCHEDULED to send")
    record["status"] = "SENT"
    touch(record)
    return response.object_response(serialize.recall_reminder(record), 200)


@bp.post("/recall-reminders/<reminder_id>/cancel")
@require_roles("FrontDesk")
def cancel_reminder(reminder_id):
    record = db.recall_reminders.get(reminder_id)
    if record is None:
        raise errors.not_found("RecallReminder not found")
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Reminder must be SCHEDULED to cancel")
    record["status"] = "CANCELLED"
    touch(record)
    return response.object_response(serialize.recall_reminder(record), 200)
