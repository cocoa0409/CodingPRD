"""CallEvent audit-trail read endpoints."""
from flask import Blueprint, request

from db import store
from errors import err_not_found
from middleware import auth, require_fleet_ownership
from response import success
from serializers import serialize_call_event
from util import parse_pagination, paginate

bp = Blueprint("call_events", __name__)

ROLES = ["OpsAdmin", "Dispatcher", "FleetManager", "BillingClerk"]


@bp.route("/roadside/call-events/<callEventId>", methods=["GET"])
def get_event(callEventId):
    uid, role = auth(ROLES)
    rec = store.call_events.get(callEventId)
    if rec is None:
        raise err_not_found("CallEvent not found")
    if role == "FleetManager":
        call = store.service_calls.get(rec["service_call_id"])
        require_fleet_ownership(
            uid, call.get("fleet_account_id") if call else None)
    return success(serialize_call_event(rec))


@bp.route("/roadside/call-events", methods=["GET"])
def list_events():
    uid, role = auth(ROLES)
    limit, offset = parse_pagination(request.args)
    call_f = request.args.get("service_call_id")
    etype_f = request.args.get("event_type")
    items = sorted(store.call_events.values(), key=lambda r: r["_seq"])
    if role == "FleetManager":
        items = [e for e in items
                 if (store.service_calls.get(e["service_call_id"]) or {})
                 .get("fleet_account_id") == uid]
    if call_f is not None:
        items = [e for e in items if e["service_call_id"] == call_f]
    if etype_f is not None:
        items = [e for e in items if e["event_type"] == etype_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize_call_event(e) for e in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})
