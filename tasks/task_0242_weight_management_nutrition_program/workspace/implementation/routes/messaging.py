"""MessageThread + Message endpoints (PRD 3.8)."""
from flask import Blueprint, g, request

from common import (as_str, get_body, init_common, init_event, parse_pagination,
                    require, sort_by_creation, touch)
from db import db
from errors import (ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_THREAD_NOT_OPEN,
                    raise_error)
from lookups import get_assignment, get_message, get_thread
from middleware import require_roles
from response import paginated, success
from serializers import serialize

bp = Blueprint("messaging", __name__)

ALL_READ = ("ProgramAdmin", "Clinician", "Coach", "Member")


# --- threads ---
@bp.route("/wm/message-threads", methods=["POST"])
@require_roles("ProgramAdmin", "Coach", "Member")
def create_thread():
    body = get_body()
    assignment_id = as_str(require(body, "coach_assignment_id"), "coach_assignment_id")
    subject = as_str(require(body, "subject"), "subject")

    assignment = get_assignment(assignment_id)

    thread = {
        "coach_assignment_id": assignment_id,
        "enrollment_id": assignment["enrollment_id"],
        "subject": subject,
        "message_count": 0,
        "status": "OPEN",
    }
    init_common(thread)
    db.message_threads[thread["id"]] = thread
    return success(serialize(thread), 201)


@bp.route("/wm/message-threads", methods=["GET"])
@require_roles(*ALL_READ)
def list_threads():
    limit, offset = parse_pagination()
    items = list(db.message_threads.values())
    assignment_id = request.args.get("coach_assignment_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if assignment_id is not None:
        items = [t for t in items if t["coach_assignment_id"] == assignment_id]
    if enrollment_id is not None:
        items = [t for t in items if t["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(t) for t in page], limit, offset, total)


@bp.route("/wm/message-threads/<thread_id>", methods=["GET"])
@require_roles(*ALL_READ)
def get_one_thread(thread_id):
    return success(serialize(get_thread(thread_id)), 200)


@bp.route("/wm/message-threads/<thread_id>/archive", methods=["POST"])
@require_roles("ProgramAdmin", "Coach")
def archive_thread(thread_id):
    thread = get_thread(thread_id)
    if thread["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "Archive requires OPEN thread")
    thread["status"] = "ARCHIVED"
    touch(thread)
    return success(serialize(thread), 200)


# --- messages ---
@bp.route("/wm/message-threads/<thread_id>/messages", methods=["POST"])
@require_roles("Coach", "Member")
def post_message(thread_id):
    thread = get_thread(thread_id)
    body_payload = get_body()
    text = require(body_payload, "body")
    if not isinstance(text, str) or len(text) < 1 or len(text) > 4000:
        raise_error(ERR_INVALID_REQUEST, "body must be 1..4000 chars")

    # owning assignment must be ACTIVE and thread OPEN (priority 21)
    assignment = db.coach_assignments.get(thread["coach_assignment_id"])
    if thread["status"] != "OPEN" or assignment is None or assignment["status"] != "ACTIVE":
        raise_error(ERR_THREAD_NOT_OPEN, "Thread not OPEN or assignment not ACTIVE")

    program = db.programs.get(
        db.enrollments[thread["enrollment_id"]]["program_id"]
    )

    sender_role = "MEMBER" if g.user_role == "Member" else "COACH"

    message = {
        "message_thread_id": thread_id,
        "sender_role": sender_role,
        "sender_user_id": g.user_id,
        "body": text,
        "posted_utc": program["current_utc"],
    }
    init_event(message)
    db.messages[message["id"]] = message

    thread["message_count"] += 1
    touch(thread)
    return success(serialize(message), 201)


@bp.route("/wm/messages", methods=["GET"])
@require_roles(*ALL_READ)
def list_messages():
    limit, offset = parse_pagination()
    items = list(db.messages.values())
    thread_id = request.args.get("message_thread_id")
    if thread_id is not None:
        items = [m for m in items if m["message_thread_id"] == thread_id]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(m) for m in page], limit, offset, total)


@bp.route("/wm/messages/<message_id>", methods=["GET"])
@require_roles(*ALL_READ)
def get_one_message(message_id):
    return success(serialize(get_message(message_id)), 200)
