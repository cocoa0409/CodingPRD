"""KioskQueueEntry routes (PRD §3.11). Entries are created automatically on
readiness (§3.4), not by an explicit client call — so there is no POST create.
"""
from flask import Blueprint, request

import db
import serialize
from errors import (
    err,
    ERR_QUEUE_ENTRY_NOT_WAITING,
    ERR_SESSION_NOT_READY,
    ERR_ROOM_CLINIC_MISMATCH,
    ERR_QUEUE_ENTRY_NOT_CALLED,
    ERR_QUEUE_ENTRY_NOT_IN_ROOM,
    ERR_QUEUE_ENTRY_NOT_ACTIVE,
)
from middleware import require_roles
from response import success, success_list
from services.common import touch, require_string
from services.lookups import get_queue_entry, get_exam_room
from services.pagination import paginate

bp = Blueprint("queue", __name__)


@bp.route("/queue-entries/<qid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_queue_entry_route(qid):
    entry = get_queue_entry(qid)
    return success(serialize.queue_entry(entry), status=200)


@bp.route("/queue-entries", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_queue_entries():
    records = list(db.queue_entries.values())
    for f in ("intake_session_id", "clinic_id", "exam_room_id", "status"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r.get(f) == val]
    items, limit, offset, total = paginate(records, serialize.queue_entry)
    return success_list(items, limit, offset, total)


@bp.route("/queue-entries/<qid>/call", methods=["POST"])
@require_roles("FrontDeskStaff")
def call_entry(qid):
    body = request.get_json(silent=True) or {}
    exam_room_id = require_string(body, "exam_room_id")
    entry = get_queue_entry(qid)
    room = get_exam_room(exam_room_id)
    with db.LOCK:
        if entry["status"] != "WAITING":
            raise err(ERR_QUEUE_ENTRY_NOT_WAITING, "queue entry not WAITING")
        session = db.intake_sessions[entry["intake_session_id"]]
        if session["workflow_status"] not in {"READY_FOR_VISIT", "CHECKED_IN"}:
            raise err(ERR_SESSION_NOT_READY, "session not READY_FOR_VISIT/CHECKED_IN")
        # Referenced room must belong to the same clinic as the session.
        if room["clinic_id"] != session["clinic_id"]:
            raise err(ERR_ROOM_CLINIC_MISMATCH, "room clinic mismatch")
        entry["status"] = "CALLED"
        entry["exam_room_id"] = exam_room_id
        touch(entry)
    return success(serialize.queue_entry(entry), status=200)


@bp.route("/queue-entries/<qid>/room-in", methods=["POST"])
@require_roles("FrontDeskStaff")
def room_in_entry(qid):
    entry = get_queue_entry(qid)
    with db.LOCK:
        if entry["status"] != "CALLED":
            raise err(ERR_QUEUE_ENTRY_NOT_CALLED, "queue entry not CALLED")
        entry["status"] = "IN_ROOM"
        touch(entry)
    return success(serialize.queue_entry(entry), status=200)


@bp.route("/queue-entries/<qid>/done", methods=["POST"])
@require_roles("FrontDeskStaff")
def done_entry(qid):
    entry = get_queue_entry(qid)
    with db.LOCK:
        if entry["status"] != "IN_ROOM":
            raise err(ERR_QUEUE_ENTRY_NOT_IN_ROOM, "queue entry not IN_ROOM")
        entry["status"] = "DONE"
        touch(entry)
        # Leaving the active set decrements the clinic counter (PRD §2.9, §3.11).
        clinic = db.clinics[entry["clinic_id"]]
        clinic["active_queue_count"] -= 1
        touch(clinic)
    return success(serialize.queue_entry(entry), status=200)


@bp.route("/queue-entries/<qid>/no-show", methods=["POST"])
@require_roles("FrontDeskStaff")
def no_show_entry(qid):
    entry = get_queue_entry(qid)
    with db.LOCK:
        if entry["status"] not in {"WAITING", "CALLED"}:
            raise err(ERR_QUEUE_ENTRY_NOT_ACTIVE, "queue entry not active")
        entry["status"] = "NO_SHOW"
        touch(entry)
        clinic = db.clinics[entry["clinic_id"]]
        clinic["active_queue_count"] -= 1
        touch(clinic)
    return success(serialize.queue_entry(entry), status=200)
