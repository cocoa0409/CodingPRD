"""MessageThread endpoints with after-hours escalation (PRD §3.12)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from clock import clock
from middleware import authenticate, require_roles
from routes.helpers import get_or_404, require_member_owns
from services import domain

bp = Blueprint("message_threads", __name__)


@bp.route("/members/<mid>/message-threads", methods=["POST"])
def open_thread(mid):
    caller = authenticate()
    require_roles(caller, {"Member"})
    member = get_or_404("member", mid)
    require_member_owns(caller, mid)
    data = validate.body()
    validate.require(data, "body", str)

    now = clock.now()
    priority, deadline = domain.compute_thread_sla(now)

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["member_id"] = mid
    e["provider_id"] = member.get("assigned_provider_id")
    e["priority"] = priority
    e["thread_status"] = "OPEN"
    e["response_deadline"] = deadline
    db.message_threads[e["id"]] = e
    return response.object_response(serialize.message_thread(e), 201)


@bp.route("/message-threads/<tid>", methods=["GET"])
def get_thread(tid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    e = get_or_404("message_thread", tid)
    _read_ownership(caller, e)
    return response.object_response(serialize.message_thread(e), 200)


@bp.route("/message-threads", methods=["GET"])
def list_threads():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    limit, offset = validate.pagination()
    member_id = request.args.get("member_id")
    provider_id = request.args.get("provider_id")
    thread_status = request.args.get("thread_status")

    rows = list(db.message_threads.values())
    if caller.role == "Member":
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    elif caller.role == "Provider":
        rows = [r for r in rows if r.get("provider_id") == caller.user_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if provider_id is not None:
        rows = [r for r in rows if r.get("provider_id") == provider_id]
    if thread_status is not None:
        rows = [r for r in rows if r["thread_status"] == thread_status]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.message_thread(r) for r in page], limit, offset, total, 200
    )


@bp.route("/message-threads/<tid>/reply", methods=["POST"])
def reply_thread(tid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("message_thread", tid)
    if caller.role == "Provider" and e.get("provider_id") != caller.user_id:
        raise errors.forbidden("Provider does not own this thread.")
    data = validate.body()
    validate.require(data, "body", str)

    status = e["thread_status"]
    if status == "OPEN":
        # Reply allowed only before the deadline (PRD §3.12).
        if clock.now() >= e["response_deadline"]:
            raise errors.invalid_state("Response deadline has passed.")
    elif status == "ESCALATED":
        pass  # allowed without deadline restriction
    else:
        raise errors.invalid_state("Thread cannot be replied to from %s." % status)

    e["thread_status"] = "ANSWERED"
    db.touch(e)
    return response.object_response(serialize.message_thread(e), 200)


@bp.route("/message-threads/<tid>/close", methods=["POST"])
def close_thread(tid):
    caller = authenticate()
    require_roles(caller, {"Member"})
    e = get_or_404("message_thread", tid)
    require_member_owns(caller, e["member_id"])

    if e["thread_status"] != "ANSWERED":
        raise errors.invalid_state("Only an ANSWERED thread can be closed.")
    e["thread_status"] = "CLOSED"
    db.touch(e)
    return response.object_response(serialize.message_thread(e), 200)


def _read_ownership(caller, thread):
    if caller.role == "Member" and caller.user_id != thread["member_id"]:
        raise errors.forbidden("Member does not own this thread.")
    if caller.role == "Provider" and caller.user_id != thread.get("provider_id"):
        raise errors.forbidden("Provider does not own this thread.")
