"""Read-only audit streams: BOL events and credit hold log entries."""
from flask import Blueprint, request

from db import db
from errors import not_found
from helpers import list_query, ser_bol_event, ser_credit_log
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("audit", __name__)

_BOL_ROLES = ["PlatformAdmin", "TerminalOperator", "BillingClerk"]
_LOG_ROLES = ["PlatformAdmin", "CreditAnalyst"]


@bp.get("/rack/bol-events/<eventId>")
def get_bol_event(eventId):
    require_roles(_BOL_ROLES)
    e = db.bol_events.get(eventId)
    if e is None:
        raise not_found("BolEvent {} does not exist".format(eventId))
    return success_object(ser_bol_event(e))


@bp.get("/rack/bol-events")
def list_bol_events():
    require_roles(_BOL_ROLES)
    page, total, limit, offset = list_query(
        db.bol_events.values(), request.args, ["lifting_ticket_id", "event_type"]
    )
    return success_list([ser_bol_event(e) for e in page], total, limit, offset)


@bp.get("/rack/credit-hold-logs/<logId>")
def get_credit_hold_log(logId):
    require_roles(_LOG_ROLES)
    e = db.credit_hold_logs.get(logId)
    if e is None:
        raise not_found("CreditHoldLog {} does not exist".format(logId))
    return success_object(ser_credit_log(e))


@bp.get("/rack/credit-hold-logs")
def list_credit_hold_logs():
    require_roles(_LOG_ROLES)
    page, total, limit, offset = list_query(
        db.credit_hold_logs.values(), request.args, ["customer_id", "event_type"]
    )
    return success_list([ser_credit_log(e) for e in page], total, limit, offset)
