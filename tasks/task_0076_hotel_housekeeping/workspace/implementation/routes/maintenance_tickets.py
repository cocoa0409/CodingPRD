"""Routes for /maintenance-tickets."""

from flask import Blueprint, request, g

from db import DB, LOCK
from errors import (
    raise_error,
    ERR_HOUSEKEEPER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ROOM_NOT_FOUND,
    ERR_ROOM_ALREADY_ISOLATED,
    ERR_TICKET_NOT_FOUND,
    ERR_TICKET_NOT_REPORTED,
    ERR_TICKET_NOT_DISPATCHED,
    ERR_TICKET_NOT_COMPLETED,
)
from middleware import auth_required
from response import success_response, list_response
from services.audit import append_audit
from services.cleaning_task_service import (
    build_cleaning_task,
    cancel_open_tasks_for_room,
    try_auto_dispatch,
)
from services.common import (
    bump,
    require_body_dict,
    require_enum,
    require_field,
    stamp_create,
)
from services.pagination import parse_pagination, paginate
from services.room_machine import transition_room
from services.serializers import serialize_maintenance_ticket
from services.time_util import utc_now_iso


bp = Blueprint("maintenance_tickets", __name__)


CATEGORIES = {"ELECTRICAL", "PLUMBING", "HVAC", "FURNITURE", "APPLIANCE", "OTHER"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ISOLATING = {"HIGH", "CRITICAL"}


def get_ticket_or_404(ticket_id):
    t = DB["maintenance_tickets"].get(ticket_id)
    if t is None:
        raise_error(ERR_TICKET_NOT_FOUND, "MaintenanceTicket not found")
    return t


@bp.route("/maintenance-tickets", methods=["POST"])
@auth_required(["Housekeeper", "Supervisor"])
def create_ticket():
    body = require_body_dict(request.get_json(silent=True))
    room_id = require_field(body, "room_id", str)
    reporter_id = require_field(body, "reporter_housekeeper_id", str)
    category = require_enum(body, "category", CATEGORIES)
    severity = require_enum(body, "severity", SEVERITIES)
    description = require_field(body, "description", str)

    with LOCK:
        if room_id not in DB["rooms"]:
            raise_error(ERR_ROOM_NOT_FOUND, "Room not found")
        if reporter_id not in DB["housekeepers"]:
            raise_error(ERR_HOUSEKEEPER_NOT_FOUND, "Reporter housekeeper not found")
        ticket = {
            "room_id": room_id,
            "reporter_housekeeper_id": reporter_id,
            "category": category,
            "severity": severity,
            "description": description,
            "isolates_room": severity in ISOLATING,
            "engineering_assignee": None,
            "completed_at": None,
            "verified_at": None,
            "re_clean_task_id": None,
            "status": "REPORTED",
        }
        stamp_create(ticket)
        DB["maintenance_tickets"][ticket["id"]] = ticket
    return success_response(serialize_maintenance_ticket(ticket), http_status=201)


@bp.route("/maintenance-tickets", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Engineer", "Housekeeper"])
def list_tickets():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    room_id = request.args.get("room_id")
    severity = request.args.get("severity")
    items = list(DB["maintenance_tickets"].values())
    if status:
        items = [t for t in items if t["status"] == status]
    if room_id:
        items = [t for t in items if t["room_id"] == room_id]
    if severity:
        items = [t for t in items if t["severity"] == severity]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_maintenance_ticket(t) for t in page], total, limit, offset
    )


@bp.route("/maintenance-tickets/<ticket_id>", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Engineer", "Housekeeper"])
def get_ticket(ticket_id):
    t = get_ticket_or_404(ticket_id)
    return success_response(serialize_maintenance_ticket(t))


@bp.route("/maintenance-tickets/<ticket_id>/dispatch", methods=["POST"])
@auth_required(["Supervisor"])
def dispatch_ticket(ticket_id):
    body = require_body_dict(request.get_json(silent=True))
    engineering_assignee = require_field(body, "engineering_assignee", str)

    with LOCK:
        t = get_ticket_or_404(ticket_id)
        if t["status"] != "REPORTED":
            raise_error(ERR_TICKET_NOT_REPORTED,
                        "Ticket is not in REPORTED state")
        room = DB["rooms"].get(t["room_id"])
        if room is None:
            raise_error(ERR_ROOM_NOT_FOUND, "Room not found")

        if t["isolates_room"]:
            if room.get("out_of_order_ticket_id") and \
                    room.get("out_of_order_ticket_id") != t["id"]:
                raise_error(ERR_ROOM_ALREADY_ISOLATED,
                            "Room is already isolated by another ticket")
            # Cascade: room → OUT_OF_ORDER, open tasks → CANCELLED
            room["out_of_order_ticket_id"] = t["id"]
            transition_room(
                room, "OUT_OF_ORDER",
                change_reason="MAINTENANCE_ISOLATE",
                actor_id=g.user_id,
                write_audit=True,
            )
            cancel_open_tasks_for_room(room["id"])

        t["status"] = "DISPATCHED"
        t["engineering_assignee"] = engineering_assignee
        bump(t)
        append_audit(
            actor_id=g.user_id,
            actor_role=g.user_role,
            action_type="ROOM_STATUS_CHANGE",
            subject_entity="MaintenanceTicket",
            subject_id=t["id"],
            detail={"dispatched_to": engineering_assignee,
                    "isolated_room": t["isolates_room"]},
        )
    return success_response(serialize_maintenance_ticket(t))


@bp.route("/maintenance-tickets/<ticket_id>/verify", methods=["POST"])
@auth_required(["Supervisor"])
def verify_ticket(ticket_id):
    with LOCK:
        t = get_ticket_or_404(ticket_id)
        if t["status"] != "REPAIR_COMPLETED":
            raise_error(ERR_TICKET_NOT_COMPLETED,
                        "Ticket is not in REPAIR_COMPLETED state")
        room = DB["rooms"].get(t["room_id"])
        t["status"] = "VERIFIED"
        t["verified_at"] = utc_now_iso()
        bump(t)

        if t["isolates_room"] and room is not None:
            room["out_of_order_ticket_id"] = None
            transition_room(
                room, "VACANT_DIRTY",
                change_reason="MAINTENANCE_VERIFY",
                actor_id=g.user_id,
                write_audit=True,
            )
            # Auto-create a re-clean SCHEDULED expedited task
            new_task = build_cleaning_task(
                room=room,
                task_source="SCHEDULED",
                expedite_flag=True,
                early_check_in_at=None,
                parent_task_id=None,
            )
            try_auto_dispatch(new_task, room)
            t["re_clean_task_id"] = new_task["id"]
            bump(t)
        append_audit(
            actor_id=g.user_id,
            actor_role=g.user_role,
            action_type="ROOM_STATUS_CHANGE",
            subject_entity="MaintenanceTicket",
            subject_id=t["id"],
            detail={"verified": True},
        )
    return success_response(serialize_maintenance_ticket(t))


@bp.route("/maintenance-tickets/<ticket_id>/reject", methods=["POST"])
@auth_required(["Supervisor"])
def reject_ticket(ticket_id):
    with LOCK:
        t = get_ticket_or_404(ticket_id)
        if t["status"] != "REPORTED":
            raise_error(ERR_TICKET_NOT_REPORTED,
                        "Ticket is not in REPORTED state")
        t["status"] = "REJECTED"
        bump(t)
        append_audit(
            actor_id=g.user_id,
            actor_role=g.user_role,
            action_type="ROOM_STATUS_CHANGE",
            subject_entity="MaintenanceTicket",
            subject_id=t["id"],
            detail={"rejected": True},
        )
    return success_response(serialize_maintenance_ticket(t))
