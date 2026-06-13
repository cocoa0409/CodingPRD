"""Dispatch endpoints: read, list, cancel."""
from flask import Blueprint, request

from db import db, touch
from errors import err, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success, list_response
from services import common
from services.derive import serialize_dispatch

bp = Blueprint("dispatches", __name__)


@bp.route("/dispatches/<did>", methods=["GET"])
def get_dispatch(did):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    dispatch = common.lookup(db.dispatches, did)
    return success(serialize_dispatch(dispatch))


@bp.route("/dispatches", methods=["GET"])
def list_dispatches():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    limit, offset = common.parse_pagination()
    alarm_event_id = request.args.get("alarm_event_id")
    account_id = request.args.get("account_id")
    service = request.args.get("service")
    items = list(db.dispatches.values())
    if alarm_event_id is not None:
        items = [d for d in items if d["alarm_event_id"] == alarm_event_id]
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    if service is not None:
        items = [d for d in items if d["service"] == service]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_dispatch(d) for d in window], limit, offset, total)


@bp.route("/dispatches/<did>/cancel", methods=["POST"])
def cancel_dispatch(did):
    caller = authenticate()
    require_role(caller, {"MonitoringOperator"})
    dispatch = common.lookup(db.dispatches, did)
    if dispatch["status"] != "ORDERED":
        raise err(ERR_INVALID_STATE, "Dispatch is not ORDERED")
    dispatch["status"] = "CANCELLED"
    touch(dispatch)
    # Compensation: monitoring_balance_cents is derived; cancelled dispatches
    # contribute 0, so the fee is automatically reversed on the next read.
    return success(serialize_dispatch(dispatch))
