"""Drop-in ticket endpoints: intake, list, get, call-next, complete, leave."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, parse_iso_datetime, require_fields,
    stamp_new, touch,
)
from services.calculations import DROPIN_MAX_ACTIVE_TICKETS

bp = Blueprint("dropin", __name__)

ROLE_READ = ("AdvisingDirector", "Advisor", "FrontDeskStaff")


def ticket_public(t):
    return {
        "id": t["id"],
        "student_id": t["student_id"],
        "reason": t["reason"],
        "queue_date": t["queue_date"],
        "position": t["position"],
        "status": t["status"],
        "called_by_advisor_id": t["called_by_advisor_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _logical_date():
    now = parse_iso_datetime(db.get_logical_clock_iso())
    return now.strftime("%Y-%m-%d")


@bp.route("/advising/dropin-tickets", methods=["POST"])
def create_ticket():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["student_id", "reason"])
    require_role(role, ("FrontDeskStaff",))
    student = db.students.get(data["student_id"])
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {data['student_id']} not found", 404)

    queue_date = _logical_date()
    # one active ticket per student per queue_date
    for t in db.dropin_tickets.values():
        if (t["student_id"] == student["id"] and t["queue_date"] == queue_date
                and t["status"] in ("QUEUED", "CALLED")):
            raise ApiError(errors.ERR_STUDENT_ALREADY_HAS_ACTIVE_TICKET,
                           "Student already has an active ticket for this queue_date", 409)
    # day capacity: QUEUED+CALLED of the queue_date
    active_today = sum(1 for t in db.dropin_tickets.values()
                       if t["queue_date"] == queue_date and t["status"] in ("QUEUED", "CALLED"))
    if active_today >= DROPIN_MAX_ACTIVE_TICKETS:
        raise ApiError(errors.ERR_QUEUE_CAPACITY_REACHED,
                       "Queue capacity reached for this queue_date", 409)

    # position = 1 + count of pre-existing tickets with same queue_date (any status)
    existing_count = sum(1 for t in db.dropin_tickets.values() if t["queue_date"] == queue_date)
    ticket = stamp_new({
        "student_id": student["id"],
        "reason": data["reason"],
        "queue_date": queue_date,
        "position": existing_count + 1,
        "status": "QUEUED",
        "called_by_advisor_id": None,
    })
    db.dropin_tickets[ticket["id"]] = ticket
    return success_object(ticket_public(ticket), 201)


@bp.route("/advising/dropin-tickets", methods=["GET"])
def list_tickets():
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    limit, offset = get_pagination_params()
    items = list(db.dropin_tickets.values())
    student_id = request.args.get("student_id")
    called_by = request.args.get("called_by_advisor_id")
    status = request.args.get("status")
    queue_date = request.args.get("queue_date")
    if student_id is not None:
        items = [t for t in items if t["student_id"] == student_id]
    if called_by is not None:
        items = [t for t in items if t["called_by_advisor_id"] == called_by]
    if status is not None:
        if status not in ("QUEUED", "CALLED", "SERVED", "LEFT"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status}", 400)
        items = [t for t in items if t["status"] == status]
    if queue_date is not None:
        items = [t for t in items if t["queue_date"] == queue_date]
    page, total = paginate(items, limit, offset)
    return success_list([ticket_public(t) for t in page], limit, offset, total)


@bp.route("/advising/dropin-tickets/call-next", methods=["POST"])
def call_next():
    user_id, role = get_auth_context()
    require_role(role, ("Advisor",))
    queue_date = _logical_date()
    queued = [t for t in db.dropin_tickets.values()
              if t["queue_date"] == queue_date and t["status"] == "QUEUED"]
    if not queued:
        raise ApiError(errors.ERR_QUEUE_EMPTY, "No QUEUED ticket for the current logical date", 409)
    queued.sort(key=lambda t: t["position"])
    ticket = queued[0]
    ticket["status"] = "CALLED"
    ticket["called_by_advisor_id"] = user_id
    touch(ticket)
    return success_object(ticket_public(ticket))


@bp.route("/advising/dropin-tickets/<ticketId>", methods=["GET"])
def get_ticket(ticketId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    ticket = db.dropin_tickets.get(ticketId)
    if not ticket:
        raise ApiError(errors.ERR_TICKET_NOT_FOUND, f"Ticket {ticketId} not found", 404)
    return success_object(ticket_public(ticket))


@bp.route("/advising/dropin-tickets/<ticketId>/complete", methods=["POST"])
def complete_ticket(ticketId):
    user_id, role = get_auth_context()
    require_role(role, ("Advisor", "AdvisingDirector"))
    ticket = db.dropin_tickets.get(ticketId)
    if not ticket:
        raise ApiError(errors.ERR_TICKET_NOT_FOUND, f"Ticket {ticketId} not found", 404)
    if ticket["status"] != "CALLED":
        raise ApiError(errors.ERR_TICKET_INVALID_STATE,
                       "Ticket must be CALLED to complete", 409)
    ticket["status"] = "SERVED"
    touch(ticket)
    return success_object(ticket_public(ticket))


@bp.route("/advising/dropin-tickets/<ticketId>/leave", methods=["POST"])
def leave_ticket(ticketId):
    user_id, role = get_auth_context()
    require_role(role, ("FrontDeskStaff", "Advisor", "AdvisingDirector"))
    ticket = db.dropin_tickets.get(ticketId)
    if not ticket:
        raise ApiError(errors.ERR_TICKET_NOT_FOUND, f"Ticket {ticketId} not found", 404)
    if ticket["status"] not in ("QUEUED", "CALLED"):
        raise ApiError(errors.ERR_TICKET_INVALID_STATE,
                       "Ticket must be QUEUED or CALLED to leave", 409)
    ticket["status"] = "LEFT"
    touch(ticket)
    return success_object(ticket_public(ticket))
