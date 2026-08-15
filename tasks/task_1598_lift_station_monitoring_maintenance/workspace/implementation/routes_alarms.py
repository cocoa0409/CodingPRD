"""AlarmTicket routes: raise/list/get and the ack-dispatch-arrive-clear-cancel
workflow with callout selection and OCC (PRD 3.3, 2.6)."""
from flask import Blueprint, g, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
    ERR_STALE_VERSION,
    ERR_SSO_EVENT_OPEN,
)
from helpers import (
    body, bad, is_int, req_str, req_enum, req_instant, opt_bool, paginate,
    ALARM_CLASSES,
)
from middleware import require_roles
from routes_stations import get_station_or_404
from serializers import ser_alarm_ticket

bp = Blueprint("alarm_tickets", __name__)

ALARM_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "OnCallOperator", "Operator",
    "ComplianceOfficer",
)

# SSO states that permit clearing an SSO-flagged ticket (anything past OPEN).
NON_OPEN_SSO_STATES = (
    "CONTAINED", "REPORT_DRAFT", "REPORT_SUBMITTED", "REPORT_ACCEPTED", "CLOSED",
)


def get_ticket_or_404(tid):
    t = db.alarm_tickets.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Alarm ticket not found")
    return t


@bp.post("/stations/<sid>/alarm-tickets")
def create_alarm_ticket(sid):
    require_roles("ScadaWebhook", "OnCallOperator", "UtilityAdmin")
    st = get_station_or_404(sid)
    # posture gate; raising an alarm is an alarm action, allowed in EMERGENCY
    services.check_posture(st, allow_emergency=True)
    b = body()
    alarm_class = req_enum(b, "alarm_class", ALARM_CLASSES)
    code = req_str(b, "alarm_code")
    raised = req_instant(b, "raised_at")
    sso_related = opt_bool(b, "is_sso_related", False)
    t = {
        "id": db.new_id(),
        "station_id": sid,
        "alarm_class": alarm_class,
        "alarm_code": code,
        "raised_at": raised,
        "status": "OPEN",
        "assigned_operator_id": None,
        "acked_at": None,
        "dispatched_at": None,
        "cleared_at": None,
        "response_minutes": None,
        "is_sso_related": sso_related,
    }
    db.stamp(t)
    db.alarm_tickets[t["id"]] = t
    # Creating a ticket bumps the parent station version.
    services.sync_station(st, force_bump=True)
    return success(ser_alarm_ticket(t), 201)


@bp.get("/stations/<sid>/alarm-tickets")
def list_station_tickets(sid):
    require_roles(*ALARM_READ_ROLES)
    get_station_or_404(sid)
    items = [t for t in db.alarm_tickets.values() if t["station_id"] == sid]
    items = _filter_tickets(items)
    page, meta = paginate(items)
    return success([ser_alarm_ticket(t) for t in page], 200, meta)


@bp.get("/alarm-tickets")
def list_tickets():
    require_roles(*ALARM_READ_ROLES)
    items = list(db.alarm_tickets.values())
    stid = request.args.get("station_id")
    if stid is not None:
        items = [t for t in items if t["station_id"] == stid]
    op = request.args.get("assigned_operator_id")
    if op is not None:
        items = [t for t in items if t["assigned_operator_id"] == op]
    items = _filter_tickets(items)
    page, meta = paginate(items)
    return success([ser_alarm_ticket(t) for t in page], 200, meta)


def _filter_tickets(items):
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    klass = request.args.get("alarm_class")
    if klass is not None:
        items = [t for t in items if t["alarm_class"] == klass]
    return items


@bp.get("/alarm-tickets/<tid>")
def get_ticket(tid):
    require_roles(*ALARM_READ_ROLES)
    return success(ser_alarm_ticket(get_ticket_or_404(tid)))


# --------------------------------------------------------------------- workflow


@bp.post("/alarm-tickets/<tid>/ack")
def ack_ticket(tid):
    require_roles("OnCallOperator")
    t = get_ticket_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN ticket can be acknowledged")
    services.check_posture(st, allow_emergency=True)
    t["status"] = "ACKED"
    t["acked_at"] = db.now()
    db.touch(t)
    services.sync_station(st)
    return success(ser_alarm_ticket(t))


@bp.post("/alarm-tickets/<tid>/dispatch")
def dispatch_ticket(tid):
    require_roles("OnCallOperator")
    t = get_ticket_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] != "ACKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACKED ticket can be dispatched")
    services.check_posture(st, allow_emergency=True)
    # OCC guard (PRD 2.6)
    b = body()
    expected = b.get("expected_ticket_version")
    if expected is None or not is_int(expected):
        bad("expected_ticket_version is required and must be an integer")
    if expected != t["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_ticket_version does not match the ticket's current version",
        )
    winner = services.select_callout_operator(st, t["alarm_class"])
    t["assigned_operator_id"] = winner["id"]
    t["dispatched_at"] = db.now()
    t["status"] = "DISPATCHED"
    db.touch(t)
    winner["_dispatch_times"].append(db.now())
    db.touch(winner)
    services.sync_station(st)
    return success(ser_alarm_ticket(t))


@bp.post("/alarm-tickets/<tid>/arrive")
def arrive_ticket(tid):
    require_roles("Operator")
    t = get_ticket_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DISPATCHED ticket can arrive on scene")
    services.check_posture(st, allow_emergency=True)
    if g.user_id != t["assigned_operator_id"]:
        raise ApiError(
            ERR_UNAUTHORIZED, 403,
            "Only the assigned operator may arrive on scene",
        )
    t["status"] = "ON_SCENE"
    db.touch(t)
    services.sync_station(st)
    return success(ser_alarm_ticket(t))


@bp.post("/alarm-tickets/<tid>/clear")
def clear_ticket(tid):
    require_roles("Operator")
    t = get_ticket_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] != "ON_SCENE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ON_SCENE ticket can be cleared")
    services.check_posture(st, allow_emergency=True)
    if g.user_id != t["assigned_operator_id"]:
        raise ApiError(
            ERR_UNAUTHORIZED, 403,
            "Only the assigned operator may clear the ticket",
        )
    # referential (priority 22): SSO-flagged tickets need a non-OPEN SSO event
    if t["is_sso_related"]:
        ok = any(
            e["station_id"] == st["id"] and e["status"] in NON_OPEN_SSO_STATES
            for e in db.sso_events.values()
        )
        if not ok:
            raise ApiError(
                ERR_SSO_EVENT_OPEN, 422,
                "Station still has an OPEN SSO event for this SSO-related ticket",
            )
    t["status"] = "CLEARED"
    t["cleared_at"] = db.now()
    if t["dispatched_at"] is not None:
        delta = (t["dispatched_at"] - t["raised_at"]).total_seconds()
        t["response_minutes"] = int(delta // 60)
    db.touch(t)
    op = db.operators.get(t["assigned_operator_id"])
    if op is not None:
        db.touch(op)
    services.sync_station(st)
    return success(ser_alarm_ticket(t))


@bp.post("/alarm-tickets/<tid>/cancel")
def cancel_ticket(tid):
    require_roles("OnCallOperator", "OperationsSupervisor")
    t = get_ticket_or_404(tid)
    st = db.stations[t["station_id"]]
    # OPEN -> CANCELLED is the OnCallOperator path; ON_SCENE -> CANCELLED is
    # the OperationsSupervisor override.
    if t["status"] == "OPEN":
        if g.user_role != "OnCallOperator":
            raise ApiError(
                ERR_UNAUTHORIZED, 403,
                "Only an OnCallOperator may cancel an OPEN ticket",
            )
    elif t["status"] == "ON_SCENE":
        if g.user_role != "OperationsSupervisor":
            raise ApiError(
                ERR_UNAUTHORIZED, 403,
                "Only an OperationsSupervisor may cancel an ON_SCENE ticket",
            )
    else:
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Ticket in %s cannot be cancelled" % t["status"],
        )
    services.check_posture(st, allow_emergency=True)
    if t["alarm_class"] == "CRITICAL":
        raise ApiError(ERR_INVALID_STATE, 409, "CRITICAL alarms may never be cancelled")
    op = db.operators.get(t["assigned_operator_id"]) if t["assigned_operator_id"] else None
    t["assigned_operator_id"] = None
    t["status"] = "CANCELLED"
    db.touch(t)
    if op is not None:
        db.touch(op)
    services.sync_station(st)
    return success(ser_alarm_ticket(t))
