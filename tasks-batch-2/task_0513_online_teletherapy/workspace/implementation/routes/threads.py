"""Thread & message routes."""
from flask import Blueprint, request

from db import db, common_create_fields, light_create_fields, touch
from errors import err, ERR_THREAD_NOT_OPEN
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner, check_therapist_owner, paginate
from validate import require_body, require_string
import serialize
from response import success, list_success

bp = Blueprint("threads", __name__)


def _match_for_thread(thread):
    return db.matches.get(thread["match_id"])


@bp.route("/threads/<tid>", methods=["GET"])
def get_thread(tid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    thread = get_or_404(db.threads, tid)
    match = _match_for_thread(thread)
    if match:
        check_client_owner(role, user_id, match["client_id"])
        check_therapist_owner(role, user_id, match["therapist_id"])
    return success(serialize.thread_out(thread))


@bp.route("/threads/<tid>/messages", methods=["POST"])
def post_message(tid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist"})
    thread = get_or_404(db.threads, tid)
    match = _match_for_thread(thread)
    if match:
        check_client_owner(role, user_id, match["client_id"])
        check_therapist_owner(role, user_id, match["therapist_id"])
    data = require_body(request.get_json(silent=True))
    body = require_string(data, "body", max_len=4000)
    if thread["status"] != "OPEN":
        raise err(ERR_THREAD_NOT_OPEN, "Thread is not OPEN")
    sender_role = "CLIENT" if role == "Client" else "THERAPIST"
    message = {
        **light_create_fields(),
        "thread_id": tid,
        "sender_role": sender_role,
        "body": body,
    }
    db.messages[message["id"]] = message
    if sender_role == "CLIENT":
        thread["unread_for_therapist"] = thread.get("unread_for_therapist", 0) + 1
        touch(thread)
    return success(serialize.message_out(message), status=201)


@bp.route("/threads/<tid>/messages", methods=["GET"])
def list_messages(tid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin"})
    thread = get_or_404(db.threads, tid)
    match = _match_for_thread(thread)
    if match:
        check_client_owner(role, user_id, match["client_id"])
        check_therapist_owner(role, user_id, match["therapist_id"])
    items = [m for m in db.messages.values() if m["thread_id"] == tid]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.message_out(m) for m in page], lim, off, total)
