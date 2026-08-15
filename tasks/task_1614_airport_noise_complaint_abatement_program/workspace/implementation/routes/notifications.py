"""Operator notifications: draft/send/ack/respond/close/escalate (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_notification
import services
from services import touch
from util import now
from validate import validate, parse_pagination

bp = Blueprint("notifications", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

TERMINAL_COMPLAINT = {"CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED", "WITHDRAWN"}


def _get_notification(nid):
    n = db.notifications.get(nid)
    if n is None:
        raise err("ERR_NOT_FOUND", f"OperatorNotification {nid} not found")
    return n


def _check_rep_owner(caller, n):
    if caller.role == "OperatorRep" and n["operator_id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "An OperatorRep may act only on their own operator's notifications")


def _bump_operator_counters(operator, delta_sent=0, delta_open=0, delta_closed=0):
    if delta_sent:
        operator["notifications_sent_total"] += delta_sent
    if delta_open:
        operator["notifications_open"] += delta_open
    if delta_closed:
        operator["notifications_closed"] += delta_closed
    if delta_sent or delta_open or delta_closed:
        touch(operator)


@bp.post("/operator-notifications")
def create_notification():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("operator_id", "str", True),
        ("complaint_id", "str", False),
        ("noise_event_id", "str", False),
        ("severity", "enum", True, {"enum": ["ADVISORY", "FORMAL"]}),
        ("subject", "str", True),
        ("body", "str", True),
    ])
    require_role(caller, ["NoiseAnalyst"])
    operator = db.operators.get(data["operator_id"])
    if operator is None:
        raise err("ERR_OPERATOR_NOT_FOUND",
                  f"Operator {data['operator_id']} not found")
    complaint = None
    event = None
    if data.get("complaint_id") is not None:
        complaint = db.complaints.get(data["complaint_id"])
        if complaint is None:
            raise err("ERR_NOT_FOUND",
                      f"NoiseComplaint {data['complaint_id']} not found")
    if data.get("noise_event_id") is not None:
        event = db.events.get(data["noise_event_id"])
        if event is None:
            raise err("ERR_EVENT_NOT_FOUND",
                      f"NoiseEvent {data['noise_event_id']} not found")
    if complaint is None and event is None:
        raise err("ERR_NOTIFICATION_TARGET_REQUIRED",
                  "At least one of complaint_id or noise_event_id is required")
    t = now()
    n = {
        "id": new_id(),
        "operator_id": operator["id"],
        "complaint_id": complaint["id"] if complaint else None,
        "noise_event_id": event["id"] if event else None,
        "severity": data["severity"],
        "subject": data["subject"],
        "body": data["body"],
        "status": "DRAFT",
        "sent_at": None,
        "due_at": None,
        "acknowledged_at": None,
        "responded_at": None,
        "closed_at": None,
        "response_text": None,
        "escalation_reason": None,
        "closed_outcome": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.notifications[n["id"]] = n
    operator["notifications_draft"] += 1
    touch(operator)
    return success_object(ser_notification(n), status=201)


@bp.get("/operator-notifications")
def list_notifications():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    f_operator = request.args.get("operator_id")
    f_complaint = request.args.get("complaint_id")
    f_event = request.args.get("noise_event_id")
    f_status = request.args.get("status")
    items = sorted(db.notifications.values(), key=lambda n: n["created_at"])
    if f_operator is not None:
        items = [n for n in items if n["operator_id"] == f_operator]
    if f_complaint is not None:
        items = [n for n in items if n.get("complaint_id") == f_complaint]
    if f_event is not None:
        items = [n for n in items if n.get("noise_event_id") == f_event]
    if f_status is not None:
        items = [n for n in items if n["status"] == f_status]
    for n in items:
        services.sweep_notification_on_read(n)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_notification(n) for n in page], limit, offset, total)


@bp.get("/operator-notifications/<notificationId>")
def get_notification(notificationId):
    caller = get_caller()
    require_role(caller, STAFF + ["OperatorRep"])
    n = _get_notification(notificationId)
    _check_rep_owner(caller, n)
    services.sweep_notification_on_read(n)
    return success_object(ser_notification(n))


@bp.post("/operator-notifications/<notificationId>/send")
def send_notification(notificationId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseAnalyst"])
    n = _get_notification(notificationId)
    if n["status"] != "DRAFT":
        raise err("ERR_INVALID_NOTIFICATION_STATE", "send requires status DRAFT")
    t = now()
    n["status"] = "SENT"
    n["sent_at"] = t
    n["due_at"] = t + timedelta(days=10)
    operator = db.operators.get(n["operator_id"])
    if operator is not None:
        operator["notifications_draft"] -= 1
        _bump_operator_counters(operator, delta_sent=1, delta_open=1)
    touch(n)
    return success_object(ser_notification(n))


@bp.post("/operator-notifications/<notificationId>/acknowledge")
def acknowledge_notification(notificationId):
    caller = get_caller()
    get_body()
    require_role(caller, ["OperatorRep"])
    n = _get_notification(notificationId)
    _check_rep_owner(caller, n)
    if n["status"] != "SENT":
        raise err("ERR_INVALID_NOTIFICATION_STATE",
                  "acknowledge requires status SENT")
    n["status"] = "ACKNOWLEDGED"
    n["acknowledged_at"] = now()
    touch(n)
    return success_object(ser_notification(n))


@bp.post("/operator-notifications/<notificationId>/respond")
def respond_notification(notificationId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("response_text", "str", True)])
    require_role(caller, ["OperatorRep"])
    n = _get_notification(notificationId)
    _check_rep_owner(caller, n)
    if n["status"] != "ACKNOWLEDGED":
        raise err("ERR_INVALID_NOTIFICATION_STATE",
                  "respond requires status ACKNOWLEDGED")
    if len(data["response_text"]) < 20:
        raise err("ERR_RESPONSE_TOO_SHORT",
                  "response_text must be at least 20 characters")
    n["status"] = "RESPONSE_RECEIVED"
    n["responded_at"] = now()
    n["response_text"] = data["response_text"]
    touch(n)
    return success_object(ser_notification(n))


@bp.post("/operator-notifications/<notificationId>/close")
def close_notification(notificationId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("closed_outcome", "enum", False, {"enum": ["RESOLVED", "OVERRIDE"]}),
    ])
    require_role(caller, ["NoiseAnalyst"])
    n = _get_notification(notificationId)
    if n["status"] not in ("RESPONSE_RECEIVED", "ESCALATED"):
        raise err("ERR_INVALID_NOTIFICATION_STATE",
                  "close requires RESPONSE_RECEIVED or ESCALATED")
    # linked complaint must be terminal
    complaint = db.complaints.get(n.get("complaint_id") or "")
    if complaint is not None and complaint["status"] not in TERMINAL_COMPLAINT:
        raise err("ERR_LINKED_COMPLAINT_OPEN",
                  "The linked complaint is not in a terminal state")
    if n["status"] == "ESCALATED":
        if n.get("responded_at") is not None:
            n["closed_outcome"] = data.get("closed_outcome", "RESOLVED")
        else:
            if data.get("closed_outcome") != "OVERRIDE":
                raise err("ERR_INVALID_NOTIFICATION_STATE",
                          "Closing an escalated notification without a response "
                          "requires closed_outcome OVERRIDE")
            n["closed_outcome"] = "OVERRIDE"
    else:
        n["closed_outcome"] = "RESOLVED"
    n["closed_at"] = now()
    n["status"] = "CLOSED"
    operator = db.operators.get(n["operator_id"])
    if operator is not None:
        _bump_operator_counters(operator, delta_open=-1, delta_closed=1)
    touch(n)
    return success_object(ser_notification(n))


@bp.post("/operator-notifications/<notificationId>/escalate")
def escalate(notificationId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("escalation_reason", "str", True)])
    require_role(caller, ["NoiseOfficeAdmin"])
    n = _get_notification(notificationId)
    if n["status"] not in ("SENT", "ACKNOWLEDGED"):
        raise err("ERR_INVALID_NOTIFICATION_STATE",
                  "escalate requires status SENT or ACKNOWLEDGED")
    services.escalate_notification(n, data["escalation_reason"])
    return success_object(ser_notification(n))
